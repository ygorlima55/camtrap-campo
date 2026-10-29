"""Rotas do Módulo 4: identificação ao conectar, teste de câmera sem tela, histórico, roteiros e checklist."""

from __future__ import annotations

import datetime as dt
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from PIL import Image
from sqlalchemy import func, select

from camtrap_campo import config
from camtrap_campo.db import Camera, Campanha, EventoCamera, Importacao, PassoRoteiro, Ponto, TesteSemTela
from camtrap_campo.diagnostico import historico, sem_tela
from camtrap_campo.diagnostico.identificar import identificar
from camtrap_campo.importacao.copiar import obter_ou_criar, sanitizar
from camtrap_campo.importacao.detectar import detectar_cartoes

ITENS_CHECKLIST = [
    "Pilhas NOVAS, todas da mesma marca e tipo (anotar marca/tipo)",
    "Cartão SD copiado no computador ANTES de formatar",
    "Cartão formatado NA CÂMERA (não no computador)",
    "Data e hora ajustadas na câmera (ou roteiro às cegas aplicado)",
    "Foto do relógio do celular tirada pela câmera ao instalar (referência de horário)",
    "Teste de disparo: passar à frente da câmera e conferir o LED/registro",
    "Chave em ON (não SETUP/TEST) ao sair",
    "Câmera fixa, nivelada, altura e direção anotadas; vegetação que balança afastada do sensor",
    "Tampa fechada, vedação limpa, cadeado/cinta",
    "Coordenadas do ponto conferidas",
    "Nunca abrir o cartão num Mac (gera arquivos '._' e já causou perda de fotos)",
]


def registrar(app: FastAPI, fabrica, pagina, extras_cartoes: list[str]) -> None:
    def _raizes_permitidas() -> list[Path]:
        return [Path(c.raiz).resolve() for c in detectar_cartoes(extras_cartoes)]

    def _dentro_de_cartao(caminho: Path) -> bool:
        caminho = caminho.resolve()
        return any(caminho == r or r in caminho.parents for r in _raizes_permitidas())

    @app.get("/diagnostico", response_class=HTMLResponse)
    def diagnostico(request: Request, origem: str):
        if not Path(origem).is_dir():
            raise HTTPException(404, "Cartão/câmera não encontrado")
        with fabrica() as s:
            ident = identificar(s, origem)
            cameras = s.scalars(select(Camera).order_by(Camera.etiqueta)).all()
            testes = s.scalars(select(TesteSemTela).where(TesteSemTela.raiz == origem)
                               .order_by(TesteSemTela.id.desc()).limit(5)).all()
        return pagina(request, "diagnostico.html", ident=ident, cameras=cameras, testes=testes)

    @app.get("/cartao/miniatura")
    def miniatura_cartao(caminho: str, tamanho: int = 480):
        p = Path(caminho)
        if not p.is_file() or p.suffix.lower() not in config.EXT_FOTO or not _dentro_de_cartao(p):
            raise HTTPException(404)
        with Image.open(p) as im:  # leitura apenas
            im.thumbnail((tamanho, tamanho))
            buf = BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=80)
        return Response(buf.getvalue(), media_type="image/jpeg")

    @app.post("/sem-tela/iniciar")
    def iniciar_sem_tela(origem: str = Form(...), camera: str = Form("")):
        with fabrica() as s:
            cam = obter_ou_criar(s, Camera, camera.strip()) if camera.strip() else None
            try:
                teste = sem_tela.iniciar(s, origem, cam.id if cam else None)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/sem-tela/{teste.id}", status_code=303)

    @app.get("/sem-tela/{teste_id}", response_class=HTMLResponse)
    def ver_sem_tela(request: Request, teste_id: int):
        with fabrica() as s:
            teste = s.get(TesteSemTela, teste_id)
            if teste is None:
                raise HTTPException(404)
            _ = teste.camera
        return pagina(request, "sem_tela.html", teste=teste, conclusoes=sem_tela.CONCLUSOES)

    @app.post("/sem-tela/{teste_id}/verificar")
    def verificar_sem_tela(teste_id: int):
        with fabrica() as s:
            teste = sem_tela.verificar(s, teste_id)
            if teste.camera_id and teste.resultado in ("gravacao_ok", "sem_novos"):
                s.add(EventoCamera(camera_id=teste.camera_id, tipo="falha" if teste.resultado == "sem_novos" else "observacao",
                                   data=teste.verificado_em, descricao="Teste sem tela: " + sem_tela.CONCLUSOES[teste.resultado]))
                s.commit()
        return RedirectResponse(f"/sem-tela/{teste_id}", status_code=303)

    @app.get("/cameras", response_class=HTMLResponse)
    def cameras(request: Request):
        with fabrica() as s:
            lista = s.scalars(select(Camera).order_by(Camera.etiqueta)).all()
            resumo = {c.id: historico.atividade(s, c.id) for c in lista}
            n_imp = dict(s.execute(select(Importacao.camera_id, func.count()).group_by(Importacao.camera_id)).all())
        return pagina(request, "cameras.html", cameras=lista, resumo=resumo, n_imp=n_imp)

    @app.get("/cameras/{cam_id}", response_class=HTMLResponse)
    def camera(request: Request, cam_id: int):
        with fabrica() as s:
            cam = s.get(Camera, cam_id)
            if cam is None:
                raise HTTPException(404)
            imps = s.scalars(select(Importacao).where(Importacao.camera_id == cam_id).order_by(Importacao.id.desc())).all()
            for i in imps:
                _ = i.ponto, i.campanha
            return pagina(request, "camera.html", cam=cam, ativ=historico.atividade(s, cam_id),
                          eventos=historico.eventos(s, cam_id), importacoes=imps, tipos=historico.TIPOS_EVENTO,
                          pontos=s.scalars(select(Ponto).order_by(Ponto.nome)).all(),
                          campanhas=s.scalars(select(Campanha).order_by(Campanha.id.desc())).all(),
                          agora=dt.datetime.now().strftime("%Y-%m-%dT%H:%M"))

    @app.post("/cameras/{cam_id}/eventos")
    async def novo_evento(cam_id: int, tipo: str = Form(...), data: str = Form(...), ponto: str = Form(""),
                          campanha: str = Form(""), pilhas_marca: str = Form(""), pilhas_tipo: str = Form(""),
                          descricao: str = Form(""), fim: str = Form(""), fotos: list[UploadFile] = File(default=[])):
        if tipo not in historico.TIPOS_EVENTO:
            raise HTTPException(400, "tipo de evento inválido")
        with fabrica() as s:
            cam = s.get(Camera, cam_id)
            if cam is None:
                raise HTTPException(404)
            pto = obter_ou_criar(s, Ponto, ponto.strip()) if ponto.strip() else None
            cmp = obter_ou_criar(s, Campanha, campanha.strip()) if campanha.strip() else None
            quando = dt.datetime.fromisoformat(data)
            salvas = []
            pasta = config.pasta_dados() / "_eventos_cameras" / sanitizar(cam.etiqueta)
            for i, up in enumerate(fotos):
                if not up.filename:
                    continue
                pasta.mkdir(parents=True, exist_ok=True)
                destino = pasta / f"{quando:%Y%m%d_%H%M%S}_{tipo}_{i + 1}{Path(up.filename).suffix.lower() or '.jpg'}"
                destino.write_bytes(await up.read())
                salvas.append(destino.relative_to(config.pasta_dados()).as_posix())
            ate = dt.datetime.fromisoformat(fim) if fim else None
            if ate and ate < quando:
                raise HTTPException(400, "o fim da falha não pode ser antes do início")
            s.add(EventoCamera(camera_id=cam_id, tipo=tipo, data=quando, fim=ate, ponto_id=pto.id if pto else None,
                               campanha_id=cmp.id if cmp else None, pilhas_marca=pilhas_marca or None,
                               pilhas_tipo=pilhas_tipo or None, descricao=descricao or None, fotos=salvas or None))
            s.commit()
        return RedirectResponse(f"/cameras/{cam_id}", status_code=303)

    @app.get("/dados/{caminho:path}")
    def arquivo_dados(caminho: str):
        base = config.pasta_dados().resolve()
        alvo = (base / caminho).resolve()
        if base not in alvo.parents or not alvo.is_file() or "_eventos_cameras" not in alvo.parts:
            raise HTTPException(404)
        return Response(alvo.read_bytes(), media_type="image/jpeg" if alvo.suffix.lower() in (".jpg", ".jpeg") else
                        "application/octet-stream")

    @app.get("/roteiros", response_class=HTMLResponse)
    def roteiros(request: Request, modelo: str = ""):
        with fabrica() as s:
            modelos = [m for (m,) in s.execute(select(PassoRoteiro.modelo).distinct().order_by(PassoRoteiro.modelo))]
            modelos_cameras = sorted({c.modelo for c in s.scalars(select(Camera)) if c.modelo})
            passos = s.scalars(select(PassoRoteiro).where(PassoRoteiro.modelo == modelo)
                               .order_by(PassoRoteiro.ordem, PassoRoteiro.id)).all() if modelo else []
        return pagina(request, "roteiros.html", modelos=modelos, sugestoes=sorted(set(modelos) | set(modelos_cameras)),
                      modelo=modelo, passos=passos)

    @app.post("/roteiros")
    def novo_passo(modelo: str = Form(...), ordem: int = Form(...), ajuste: str = Form(...), botoes: str = Form(...),
                   observacao: str = Form(""), confirmado: str = Form("")):
        with fabrica() as s:
            s.add(PassoRoteiro(modelo=modelo.strip(), ordem=ordem, ajuste=ajuste.strip(), botoes=botoes.strip(),
                               observacao=observacao or None, confirmado_em_campo=bool(confirmado)))
            s.commit()
        return RedirectResponse(f"/roteiros?modelo={modelo.strip()}", status_code=303)

    @app.post("/roteiros/{passo_id}/remover")
    def remover_passo(passo_id: int):
        with fabrica() as s:
            passo = s.get(PassoRoteiro, passo_id)
            if passo is None:
                raise HTTPException(404)
            modelo = passo.modelo
            s.delete(passo)  # apaga só a linha do roteiro (dado do programa), nunca arquivos de câmera
            s.commit()
        return RedirectResponse(f"/roteiros?modelo={modelo}", status_code=303)

    @app.get("/roteiros/imprimir", response_class=HTMLResponse)
    def imprimir_roteiro(request: Request, modelo: str):
        with fabrica() as s:
            passos = s.scalars(select(PassoRoteiro).where(PassoRoteiro.modelo == modelo)
                               .order_by(PassoRoteiro.ordem, PassoRoteiro.id)).all()
        return pagina(request, "roteiro_impressao.html", modelo=modelo, passos=passos)

    @app.get("/campanhas/{cmp_id}/checklist", response_class=HTMLResponse)
    def checklist(request: Request, cmp_id: int):
        with fabrica() as s:
            cmp = s.get(Campanha, cmp_id)
            if cmp is None:
                raise HTTPException(404)
            linhas = s.execute(select(Camera.etiqueta, Ponto.nome, Ponto.latitude, Ponto.longitude)
                               .join(Importacao, Importacao.camera_id == Camera.id).join(Ponto, Importacao.ponto_id == Ponto.id)
                               .where(Importacao.campanha_id == cmp_id).distinct().order_by(Ponto.nome)).all()
        return pagina(request, "checklist.html", campanha=cmp, itens=ITENS_CHECKLIST, linhas=linhas)
