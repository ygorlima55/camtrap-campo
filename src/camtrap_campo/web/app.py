"""Rotas da interface. Toda a lógica fica nos módulos de importação/metadados; aqui só há apresentação."""

from __future__ import annotations

import datetime as dt
import os
import threading
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from sqlalchemy import select

from camtrap_campo import __version__, config
from camtrap_campo.db import Arquivo, Camera, Campanha, Importacao, Ponto, conectar
from camtrap_campo.importacao import horario
from camtrap_campo.importacao.copiar import importar, obter_ou_criar
from camtrap_campo.importacao.detectar import detectar_cartoes, resumir
from camtrap_campo.web import rotas_gestao

AQUI = Path(__file__).parent


def _data(texto: str | None) -> dt.date | None:
    return dt.date.fromisoformat(texto) if texto else None


def _numero(texto: str | None) -> float | None:
    return float(texto.replace(",", ".")) if texto and texto.strip() else None


def criar_app(fabrica=None, sincrono: bool = False, extras_cartoes: list[str] | None = None) -> FastAPI:
    """``sincrono`` roda a importação na própria requisição (testes); ``extras_cartoes`` simula cartões."""
    fabrica = fabrica or conectar(config.caminho_banco())
    if extras_cartoes is None:  # CAMTRAP_CARTOES_EXTRAS="C:\pasta1;C:\pasta2" — cópias de cartões ou demonstração
        extras_cartoes = [p for p in os.environ.get("CAMTRAP_CARTOES_EXTRAS", "").split(";") if p.strip()]
    app = FastAPI(title="CamTrap Campo", version=__version__)
    app.mount("/static", StaticFiles(directory=AQUI / "static"), name="static")
    tpl = Jinja2Templates(directory=AQUI / "templates")
    tpl.env.globals.update(versao=__version__, descrever_deslocamento=horario.descrever)
    tpl.env.filters["dh"] = lambda d: d.strftime("%d/%m/%Y %H:%M:%S") if d else "—"

    def pagina(request: Request, nome: str, **ctx):
        return tpl.TemplateResponse(request, nome, ctx)

    @app.get("/", response_class=HTMLResponse)
    def inicio(request: Request):
        with fabrica() as s:
            recentes = s.scalars(select(Importacao).order_by(Importacao.id.desc()).limit(10)).all()
            for imp in recentes:
                _ = imp.camera, imp.ponto, imp.campanha
        return pagina(request, "inicio.html", cartoes=detectar_cartoes(extras_cartoes), recentes=recentes)

    @app.get("/cartoes", response_class=HTMLResponse)
    def cartoes(request: Request):
        return pagina(request, "_cartoes.html", cartoes=detectar_cartoes(extras_cartoes))

    @app.get("/importar", response_class=HTMLResponse)
    def form_importar(request: Request, origem: str):
        if not Path(origem).is_dir():
            raise HTTPException(404, "Origem não encontrada")
        with fabrica() as s:
            cameras = s.scalars(select(Camera).order_by(Camera.etiqueta)).all()
            pontos = s.scalars(select(Ponto).order_by(Ponto.nome)).all()
            campanhas = s.scalars(select(Campanha).order_by(Campanha.id.desc())).all()
            nomes_p = {p.id: p.nome for p in pontos}
            nomes_c = {c.id: c.nome for c in campanhas}
            ultimas = {c.etiqueta: {"ponto": nomes_p.get(c.ultimo_ponto_id, ""),
                                    "campanha": nomes_c.get(c.ultima_campanha_id, "")} for c in cameras}
        return pagina(request, "importar.html", cartao=resumir(origem), cameras=cameras, pontos=pontos,
                      campanhas=campanhas, ultimas=ultimas)

    @app.post("/importar")
    def executar_importacao(origem: str = Form(...), camera: str = Form(...), ponto: str = Form(...),
                            campanha: str = Form(...)):
        camera, ponto, campanha = camera.strip(), ponto.strip(), campanha.strip()
        if not (camera and ponto and campanha):
            raise HTTPException(400, "Informe câmera, ponto e campanha")
        if not (Path(origem) / "DCIM").is_dir():
            raise HTTPException(400, "A origem não tem pasta DCIM")
        with fabrica() as s:
            cam = obter_ou_criar(s, Camera, camera)
            pto = obter_ou_criar(s, Ponto, ponto)
            cmp = obter_ou_criar(s, Campanha, campanha)
            imp = Importacao(camera_id=cam.id, ponto_id=pto.id, campanha_id=cmp.id, origem=origem)
            s.add(imp)
            s.commit()
            imp_id = imp.id
        args = (fabrica, Path(origem), camera, ponto, campanha)
        if sincrono:
            importar(*args, importacao_id=imp_id)
        else:
            threading.Thread(target=importar, args=args, kwargs={"importacao_id": imp_id}, daemon=True).start()
        return RedirectResponse(f"/importacoes/{imp_id}", status_code=303)

    def _carregar(s, imp_id: int) -> Importacao:
        imp = s.get(Importacao, imp_id)
        if imp is None:
            raise HTTPException(404, "Importação não encontrada")
        _ = imp.camera, imp.ponto, imp.campanha, imp.alertas, imp.arquivos
        return imp

    @app.get("/importacoes/{imp_id}", response_class=HTMLResponse)
    def ver_importacao(request: Request, imp_id: int):
        with fabrica() as s:
            imp = _carregar(s, imp_id)
            fotos = [a for a in imp.arquivos if a.tipo == "foto" and a.estado == "copiado" and a.data_original]
        return pagina(request, "importacao.html", imp=imp, fotos=fotos, arquivos=imp.arquivos[:500])

    @app.get("/importacoes/{imp_id}/progresso", response_class=HTMLResponse)
    def progresso(request: Request, imp_id: int):
        with fabrica() as s:
            imp = _carregar(s, imp_id)
        resposta = pagina(request, "_progresso.html", imp=imp)
        if imp.estado != "em_andamento":
            resposta.headers["HX-Refresh"] = "true"  # recarrega a página para mostrar alertas e arquivos
        return resposta

    @app.post("/importacoes/{imp_id}/horario")
    def corrigir_horario(imp_id: int, arquivo_id: int = Form(...), hora_real: str = Form(...)):
        with fabrica() as s:
            try:
                horario.aplicar_correcao(s, imp_id, arquivo_id, dt.datetime.fromisoformat(hora_real))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/importacoes/{imp_id}", status_code=303)

    @app.get("/arquivos/{arq_id}/miniatura")
    def miniatura(arq_id: int, tamanho: int = 360):
        with fabrica() as s:
            arq = s.get(Arquivo, arq_id)
            if arq is None or arq.tipo != "foto" or not arq.caminho_final:
                raise HTTPException(404)
            caminho = config.pasta_dados() / arq.caminho_final
        with Image.open(caminho) as im:
            im.thumbnail((tamanho, tamanho))
            buf = BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=80)
        return Response(buf.getvalue(), media_type="image/jpeg")

    @app.get("/cadastros", response_class=HTMLResponse)
    def cadastros(request: Request):
        with fabrica() as s:
            return pagina(request, "cadastros.html",
                          campanhas=s.scalars(select(Campanha).order_by(Campanha.id.desc())).all(),
                          pontos=s.scalars(select(Ponto).order_by(Ponto.nome)).all(),
                          cameras=s.scalars(select(Camera).order_by(Camera.etiqueta)).all())

    @app.post("/cadastros/campanha")
    def nova_campanha(nome: str = Form(...), inicio: str = Form(""), fim: str = Form("")):
        with fabrica() as s:
            c = obter_ou_criar(s, Campanha, nome.strip())
            c.inicio, c.fim = _data(inicio), _data(fim)
            s.commit()
        return RedirectResponse("/cadastros", status_code=303)

    @app.post("/cadastros/ponto")
    def novo_ponto(nome: str = Form(...), latitude: str = Form(""), longitude: str = Form(""), observacoes: str = Form("")):
        with fabrica() as s:
            p = obter_ou_criar(s, Ponto, nome.strip())
            p.latitude, p.longitude, p.observacoes = _numero(latitude), _numero(longitude), observacoes or None
            s.commit()
        return RedirectResponse("/cadastros", status_code=303)

    @app.post("/cadastros/camera")
    def nova_camera(etiqueta: str = Form(...), modelo: str = Form(""), numero_serie: str = Form(""), firmware: str = Form("")):
        with fabrica() as s:
            c = obter_ou_criar(s, Camera, etiqueta.strip())
            c.modelo, c.numero_serie, c.firmware = modelo or None, numero_serie or None, firmware or None
            s.commit()
        return RedirectResponse("/cadastros", status_code=303)

    rotas_gestao.registrar(app, fabrica, pagina, extras_cartoes)
    return app
