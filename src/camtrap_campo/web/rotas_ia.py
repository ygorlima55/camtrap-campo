"""Rotas do Módulo 2: tarefas de IA/áudio, revisão com atalhos, lista de espécies e limiar."""

from __future__ import annotations

from io import BytesIO

from fastapi import Body, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from PIL import Image
from sqlalchemy import select

from camtrap_campo import config
from camtrap_campo.db import Arquivo, Deteccao, Especie, Importacao, Inferencia, Tarefa
from camtrap_campo.ia import especies as lista_especies
from camtrap_campo.ia import fila, motor, revisao


def registrar(app: FastAPI, fabrica, pagina, sincrono: bool) -> None:
    with fabrica() as s:
        lista_especies.semear(s)
    trabalhador = None
    if not sincrono:
        trabalhador = fila.Trabalhador(fabrica)
        trabalhador.iniciar()

    def _disparar(tarefa_id: int) -> None:
        if sincrono:
            fila.executar(fabrica, tarefa_id)
        elif trabalhador:
            trabalhador.acordar()

    @app.post("/importacoes/{imp_id}/tarefa")
    def nova_tarefa(imp_id: int, tipo: str = Form(...)):
        with fabrica() as s:
            try:
                t = fila.criar_tarefa(s, tipo, imp_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            tarefa_id = t.id
        _disparar(tarefa_id)
        return RedirectResponse("/tarefas", status_code=303)

    @app.get("/tarefas", response_class=HTMLResponse)
    def tarefas(request: Request):
        ok, situacao = motor.disponivel()
        return pagina(request, "tarefas.html", motor_ok=ok, motor_situacao=situacao, dispositivo=motor.dispositivo(),
                      ffmpeg=bool(config.localizar_ferramenta("ffmpeg")), **_lista_tarefas())

    def _lista_tarefas() -> dict:
        with fabrica() as s:
            lista = s.scalars(select(Tarefa).order_by(Tarefa.id.desc()).limit(30)).all()
            for t in lista:
                if t.importacao:
                    _ = t.importacao.camera, t.importacao.ponto, t.importacao.campanha
        return {"tarefas": lista, "ativas": any(t.estado in ("pendente", "executando") for t in lista)}

    @app.get("/tarefas/lista", response_class=HTMLResponse)
    def tarefas_lista(request: Request):
        return pagina(request, "_tarefas.html", **_lista_tarefas())

    @app.post("/tarefas/{tarefa_id}/{acao}")
    def controlar(tarefa_id: int, acao: str):
        with fabrica() as s:
            if acao == "pausar":
                fila.pausar(s, tarefa_id)
            elif acao == "retomar":
                fila.retomar(s, tarefa_id)
            else:
                raise HTTPException(400, "ação inválida")
        if acao == "retomar":
            _disparar(tarefa_id)
        return RedirectResponse("/tarefas", status_code=303)

    @app.get("/revisao/{imp_id}", response_class=HTMLResponse)
    def tela_revisao(request: Request, imp_id: int, pendentes: int = 0):
        with fabrica() as s:
            imp = s.get(Importacao, imp_id)
            if imp is None:
                raise HTTPException(404)
            _ = imp.camera, imp.ponto, imp.campanha
            dados = revisao.montar(s, imp_id, somente_pendentes=bool(pendentes))
            lista = s.scalars(select(Especie).where(Especie.ativa).order_by(Especie.nome_popular)).all()
            seqs = [_seq_json(sq) for sq in dados["sequencias"]]
        especies_json = [{"id": e.id, "c": e.nome_cientifico, "p": e.nome_popular} for e in lista]
        return pagina(request, "revisao.html", imp=imp, dados=dados, seqs=seqs, especies=especies_json,
                      comportamentos=lista_especies.COMPORTAMENTOS)

    def _seq_json(sq: dict) -> dict:
        imagens = []
        for a in sq["arquivos"]:
            dets = sq["deteccoes"].get(a.id, [])
            if a.tipo == "foto":
                imagens.append({"url": f"/arquivos/{a.id}/miniatura?tamanho=1280", "nome": a.nome_original,
                                "data": a.data.strftime("%d/%m/%Y %H:%M:%S") if a.data else "",
                                "caixas": [_caixa(d) for d in dets]})
            else:
                por_quadro: dict = {}
                for d in dets:
                    por_quadro.setdefault((d.quadro_s, d.id if not d.quadro_caminho else d.quadro_caminho), []).append(d)
                for (seg, _), ds in sorted(por_quadro.items(), key=lambda x: x[0][0] or 0):
                    imagens.append({"url": f"/deteccoes/{ds[0].id}/imagem", "nome": f"{a.nome_original} @ {seg:.0f} s",
                                    "data": a.data.strftime("%d/%m/%Y %H:%M:%S") if a.data else "",
                                    "caixas": [_caixa(d) for d in ds]})
        rev = sq["revisao"]
        sug = sq["sugestao"] or {}
        return {"chave": sq["chave"], "arquivos": [a.id for a in sq["arquivos"]], "imagens": imagens,
                "inicio": sq["inicio"].strftime("%d/%m/%Y %H:%M:%S") if sq["inicio"] else "",
                "categorias": sq["categorias"], "max_individuos": sq["max_individuos"], "sugestao": sug,
                "especie_sugerida": sq["especie_sugerida"].id if sq["especie_sugerida"] else None,
                "revisao": None if not rev else {
                    "resultado": rev.resultado, "especie_id": rev.especie_id, "quantidade": rev.quantidade,
                    "comportamento": rev.comportamento, "divulgacao": rev.divulgacao, "observacao": rev.observacao}}

    def _caixa(d: Deteccao) -> dict:
        c = d.classificacao or {}
        nome = c.get("nome_cientifico") or c.get("nome_popular_en")
        return {"bbox": d.bbox, "categoria": d.categoria, "confianca": round(d.confianca, 2), "simulado": d.simulado,
                "especie": f"{nome} {round(c.get('confianca', 0) * 100)}%" if nome and d.categoria == "animal" else ""}

    @app.get("/deteccoes/{det_id}/imagem")
    def imagem_deteccao(det_id: int, tamanho: int = 1280):
        with fabrica() as s:
            d = s.get(Deteccao, det_id)
            if d is None:
                raise HTTPException(404)
            arq = s.get(Arquivo, d.arquivo_id)
            relativo = d.quadro_caminho or (arq.caminho_final if arq.tipo == "foto" else None)
        if not relativo:
            raise HTTPException(404)
        with Image.open(config.pasta_dados() / relativo) as im:
            im.thumbnail((tamanho, tamanho))
            buf = BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=85)
        return Response(buf.getvalue(), media_type="image/jpeg")

    @app.post("/revisao/{imp_id}")
    def salvar_revisao(imp_id: int, corpo: dict = Body(...)):
        with fabrica() as s:
            arquivos = [int(x) for x in corpo.get("arquivos", [])]
            validos = set(s.scalars(select(Arquivo.id).where(Arquivo.importacao_id == imp_id, Arquivo.id.in_(arquivos))))
            if not arquivos or set(arquivos) != validos or int(corpo.get("chave", 0)) != min(arquivos):
                raise HTTPException(400, "sequência inválida para esta importação")
            sug = (s.scalars(select(Inferencia.classificacao).where(Inferencia.arquivo_id.in_(arquivos),
                                                                     Inferencia.classificacao.is_not(None))).first())
            try:
                rev = revisao.salvar(s, imp_id, min(arquivos), arquivos, corpo.get("resultado", ""),
                                     corpo.get("especie_id"), corpo.get("quantidade"), corpo.get("comportamento"),
                                     bool(corpo.get("divulgacao")), corpo.get("observacao"), sug)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            return JSONResponse({"ok": True, "id": rev.id})

    @app.get("/especies", response_class=HTMLResponse)
    def especies(request: Request):
        with fabrica() as s:
            lista = s.scalars(select(Especie).order_by(Especie.grupo, Especie.nome_popular)).all()
            corte = revisao.limiar(s)
        return pagina(request, "especies.html", especies=lista, limiar=corte)

    @app.post("/especies")
    def salvar_especie(nome_cientifico: str = Form(...), nome_popular: str = Form(...), grupo: str = Form(""),
                       biomas: str = Form("")):
        with fabrica() as s:
            nome = " ".join(nome_cientifico.split())
            e = s.scalar(select(Especie).where(Especie.nome_cientifico == nome)) or Especie(nome_cientifico=nome)
            e.nome_popular, e.grupo, e.biomas, e.ativa = nome_popular.strip(), grupo or None, biomas or None, True
            s.add(e)
            s.commit()
        return RedirectResponse("/especies", status_code=303)

    @app.post("/especies/{esp_id}/alternar")
    def alternar_especie(esp_id: int):
        with fabrica() as s:
            e = s.get(Especie, esp_id)
            if e is None:
                raise HTTPException(404)
            e.ativa = not e.ativa
            s.commit()
        return RedirectResponse("/especies", status_code=303)

    @app.post("/configuracao/limiar")
    def salvar_limiar(limiar: str = Form(...)):
        with fabrica() as s:
            try:
                revisao.definir_limiar(s, float(limiar.replace(",", ".")))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        return RedirectResponse("/especies", status_code=303)
