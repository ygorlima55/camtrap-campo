"""Vestígios: importar fotos, ficha de caracterização, quadro com as espécies compatíveis, validação e guia."""

from __future__ import annotations

import datetime as dt
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from openpyxl import Workbook
from openpyxl.styles import Font
from PIL import Image, ImageOps
from sqlalchemy import select

from camtrap_campo import config
from camtrap_campo.db import Campanha, Especie, GuiaVestigio, Ponto, Vestigio
from camtrap_campo.ia import especies as lista_especies
from camtrap_campo.importacao import pastas
from camtrap_campo.vestigios import comparar, registro
from camtrap_campo.vestigios import guia_base as gb

OPCOES = {"formas_pegada": gb.FORMAS_PEGADA, "formas_fezes": gb.FORMAS_FEZES, "conteudos": gb.CONTEUDOS,
          "locais": gb.LOCAIS, "sinais": gb.SINAIS, "garras": {"sim": "marca garras", "nao": "sem garras"},
          "tipos": comparar.TIPOS}


def miniatura(caminho: Path, tamanho: int) -> Response:
    if not caminho.is_file():
        raise HTTPException(404)
    with Image.open(caminho) as im:
        im = ImageOps.exif_transpose(im)  # fotos de celular vêm deitadas sem isso
        im.thumbnail((tamanho, tamanho))
        buf = BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=82)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


def registrar(app: FastAPI, fabrica, pagina) -> None:
    def _semear(s) -> None:
        lista_especies.semear(s)
        comparar.semear(s)

    def _vest(s, vid: int) -> Vestigio:
        v = s.get(Vestigio, vid)
        if v is None:
            raise HTTPException(404, "Vestígio não encontrado")
        _ = v.campanha, v.ponto, v.especie
        return v

    @app.get("/vestigios", response_class=HTMLResponse)
    def tela_vestigios(request: Request, campanha: int | None = None, tipo: str = "", estado: str = "",
                       novos: int | None = None, duplicados: int = 0, erros: int = 0):
        with fabrica() as s:
            _semear(s)
            dados = registro.quadro(s, campanha, tipo or None, estado or None)
            return pagina(request, "vestigios.html", dados=dados, campanha=campanha, tipo=tipo, estado=estado,
                          campanhas=s.scalars(select(Campanha).order_by(Campanha.id.desc())).all(), opcoes=OPCOES,
                          novos=novos, duplicados=duplicados, erros=erros)

    @app.get("/vestigios/importar", response_class=HTMLResponse)
    def form_importar(request: Request, origem: str = "", erro: str = ""):
        fotos = []
        if origem:
            try:
                fotos = registro.listar_fotos(pastas.validar(origem))
            except ValueError as exc:
                erro, origem = str(exc), ""
        with fabrica() as s:
            return pagina(request, "vestigios_importar.html", origem=origem, fotos=len(fotos), erro=erro,
                          exemplos=[f.name for f in fotos[:5]], opcoes=OPCOES,
                          campanhas=s.scalars(select(Campanha).order_by(Campanha.id.desc())).all(),
                          pontos=s.scalars(select(Ponto).order_by(Ponto.nome)).all(),
                          salvas=pastas.listar(s))

    @app.post("/vestigios/escolher")
    def escolher():
        escolhida = pastas.escolher_no_windows("Escolha a pasta com as fotos de pegadas, fezes e outros vestígios")
        return RedirectResponse(f"/vestigios/importar?{urlencode({'origem': escolhida or ''})}", status_code=303)

    @app.post("/vestigios/importar")
    def importar(origem: str = Form(...), campanha: str = Form(...), ponto: str = Form(""), tipo: str = Form("")):
        campanha, ponto = campanha.strip(), ponto.strip()
        if not campanha:
            raise HTTPException(400, "Informe a campanha")
        try:
            raiz = pastas.validar(origem)
            with fabrica() as s:
                res = registro.importar_pasta(s, raiz, campanha, ponto, tipo or None)
                cmp_id = s.scalar(select(Campanha.id).where(Campanha.nome == campanha))
        except ValueError as exc:
            return RedirectResponse(f"/vestigios/importar?{urlencode({'origem': origem, 'erro': str(exc)})}", status_code=303)
        q = {"campanha": cmp_id, "novos": res["novos"], "duplicados": res["duplicados"], "erros": len(res["erros"])}
        return RedirectResponse(f"/vestigios?{urlencode(q)}", status_code=303)

    @app.get("/vestigios/guia", response_class=HTMLResponse)
    def tela_guia(request: Request, tipo: str = "pegada"):
        with fabrica() as s:
            _semear(s)
            refs = s.scalars(select(GuiaVestigio).where(GuiaVestigio.tipo == tipo)
                             .order_by(GuiaVestigio.nome_popular)).all()
            return pagina(request, "vestigios_guia.html", refs=refs, tipo=tipo, opcoes=OPCOES)

    @app.post("/vestigios/guia/{gid}")
    async def editar_guia(request: Request, gid: int):
        form = await request.form()
        with fabrica() as s:
            g = s.get(GuiaVestigio, gid)
            if g is None:
                raise HTTPException(404)
            dados = dict(g.dados or {})
            try:
                for campo in ("comprimento", "largura", "diametro", "altura"):
                    lo, hi = form.get(f"{campo}_min", ""), form.get(f"{campo}_max", "")
                    if lo.strip() and hi.strip():
                        a, b = sorted((float(lo.replace(",", ".")), float(hi.replace(",", "."))))
                        dados[campo] = [a, b]
                    elif f"{campo}_min" in form:
                        dados.pop(campo, None)
                if "dedos" in form:
                    dados["dedos"] = sorted({int(x) for x in form["dedos"].replace(",", " ").replace("/", " ").split()})
            except ValueError as exc:
                raise HTTPException(400, f"Número inválido: {exc}") from exc
            for campo in ("forma", "conteudo", "local", "sinal"):
                if f"_{campo}" in form:  # campo presente no formulário (lista de marcados, mesmo vazia)
                    marcados = form.getlist(campo)
                    dados[campo] = marcados[0] if campo == "forma" and g.tipo == "pegada" and marcados else marcados
            if form.get("garras") in gb.GARRAS:
                dados["garras"] = form["garras"]
            g.dados, g.editada = dados, True
            g.descricao = (form.get("descricao") or "").strip() or None
            g.ativa = form.get("ativa") == "on"
            s.commit()
            tipo = g.tipo
        return RedirectResponse(f"/vestigios/guia?tipo={tipo}#g{gid}", status_code=303)

    @app.get("/vestigios/planilha")
    def planilha(campanha: int | None = None):
        with fabrica() as s:
            dados = registro.quadro(s, campanha)
            wb = Workbook()
            ws = wb.active
            ws.title = "Vestígios"
            ws.append(["ID", "Campanha", "Ponto", "Data", "Latitude", "Longitude", "Tipo", "Características",
                       "1ª sugestão do guia", "%", "2ª sugestão", "%", "3ª sugestão", "%", "Validado como",
                       "Nome científico", "Guia acertou", "Observação", "Arquivo"])
            for v in dados["itens"]:
                sug = (v.sugestoes or [])[:3]
                cels = []
                for i in range(3):
                    cels += [sug[i]["nome_popular"], sug[i]["porcentagem"]] if i < len(sug) else ["", ""]
                validado = (v.especie.nome_popular if v.especie else "indeterminado") if v.resultado else "não validado"
                ws.append([v.id, v.campanha.nome, v.ponto.nome if v.ponto else "", v.data, v.latitude, v.longitude,
                           comparar.TIPOS.get(v.tipo, "") if v.tipo else "", _texto_ficha(v), *cels, validado,
                           v.especie.nome_cientifico if v.especie else "",
                           {True: "sim", False: "não"}.get(v.sugestao_aceita, ""), v.observacao or "", v.caminho_final])
            r = wb.create_sheet("Espécies (validadas)")
            r.append(["Espécie", "Nome científico", "Pegadas", "Fezes", "Outros sinais", "Total", "Pontos"])
            for e in dados["especies"]:
                r.append([e["especie"].nome_popular, e["especie"].nome_cientifico, e["pegada"], e["fezes"], e["sinal"],
                          e["total"], ", ".join(sorted(e["pontos"]))])
            sobre = wb.create_sheet("Sobre")
            for linha in ("Sugestões = comparação das características informadas com o guia de referência do programa "
                          "(não é IA de imagem). A % é relativa entre as espécies do guia, não probabilidade de acerto.",
                          "Só a coluna 'Validado como' é identificação confirmada por uma pessoa.",
                          f"Gerado em {dt.datetime.now():%d/%m/%Y %H:%M}."):
                sobre.append([linha])
            for aba in (ws, r):
                for c in aba[1]:
                    c.font = Font(bold=True)
            buf = BytesIO()
            wb.save(buf)
        nome = f"vestigios_{dt.datetime.now():%Y%m%d_%H%M}.xlsx"
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{nome}"'})

    def _texto_ficha(v: Vestigio) -> str:
        c = v.caracteristicas or {}
        partes = []
        for campo, valor in c.items():
            rotulo = comparar.CAMPOS.get(v.tipo, {}).get(campo, (campo,))[0]
            if isinstance(valor, list):
                nomes = {**gb.CONTEUDOS, **gb.LOCAIS}
                valor = ", ".join(nomes.get(x, x) for x in valor)
            elif campo == "forma":
                valor = {**gb.FORMAS_PEGADA, **gb.FORMAS_FEZES}.get(valor, valor)
            elif campo == "sinal":
                valor = gb.SINAIS.get(valor, valor)
            elif campo == "garras":
                valor = gb.GARRAS.get(valor, valor)
            elif isinstance(valor, float):
                valor = f"{valor:g} cm".replace(".", ",")
            partes.append(f"{rotulo}: {valor}")
        return "; ".join(partes)

    @app.get("/vestigios/{vid}", response_class=HTMLResponse)
    def ficha(request: Request, vid: int, salvo: str = ""):
        with fabrica() as s:
            _semear(s)
            v = _vest(s, vid)
            ids = s.scalars(select(Vestigio.id).where(Vestigio.campanha_id == v.campanha_id)
                            .order_by(Vestigio.data, Vestigio.id)).all()
            pos = ids.index(v.id)
            lista = s.scalars(select(Especie).where(Especie.ativa).order_by(Especie.nome_popular)).all()
            return pagina(request, "vestigio.html", v=v, opcoes=OPCOES, especies=lista, salvo=salvo,
                          anterior=ids[pos - 1] if pos else None, proximo=ids[pos + 1] if pos + 1 < len(ids) else None,
                          posicao=pos + 1, total=len(ids), fraco=comparar.ajuste_fraco(v.sugestoes or []),
                          texto_ficha=_texto_ficha(v))

    @app.post("/vestigios/{vid}/ficha")
    async def salvar_ficha(request: Request, vid: int):
        form = await request.form()
        bruto = {k: (form.getlist(k) if k in ("conteudo", "local") else form.get(k)) for k in form}
        with fabrica() as s:
            v = _vest(s, vid)
            try:
                registro.caracterizar(s, v, form.get("tipo", ""), bruto, form.get("observacao"))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/vestigios/{vid}?salvo=ficha#sugestoes", status_code=303)

    @app.post("/vestigios/{vid}/validar")
    def validar(vid: int, resultado: str = Form(...), especie_id: str = Form(""), guia_nome: str = Form(""),
                guia_popular: str = Form(""), seguir: str = Form("")):
        with fabrica() as s:
            v = _vest(s, vid)
            try:
                eid = int(especie_id) if especie_id.strip() else None
                if resultado == "especie" and eid is None and guia_nome:
                    eid = registro.especie_do_guia(s, guia_nome, guia_popular or guia_nome)
                registro.validar(s, v, resultado, eid)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            proximo = None
            if seguir:
                proximo = s.scalar(select(Vestigio.id).where(Vestigio.campanha_id == v.campanha_id,
                                                             Vestigio.resultado.is_(None), Vestigio.id != vid)
                                   .order_by(Vestigio.data, Vestigio.id))
        return RedirectResponse(f"/vestigios/{proximo}" if proximo else f"/vestigios/{vid}?salvo=validado",
                                status_code=303)

    @app.get("/vestigios/{vid}/foto")
    def foto(vid: int, tamanho: int = 480):
        with fabrica() as s:
            v = _vest(s, vid)
            caminho = config.pasta_dados() / v.caminho_final
        return miniatura(caminho, max(120, min(tamanho, 2400)))
