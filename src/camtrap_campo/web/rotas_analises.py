"""Rotas do Módulo 3: análises por campanha, relatório HTML e exportações (ZIP)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select

from camtrap_campo.analises.resultado import analisar
from camtrap_campo.db import Campanha, Especie
from camtrap_campo.exportacao import graficos
from camtrap_campo.exportacao.pacote import exportar_tudo

AQUI = Path(__file__).parent


def registrar(app: FastAPI, fabrica, pagina, tpl) -> None:
    def _contexto(s, cmp_id: int, intervalo: int) -> dict:
        try:
            an = analisar(s, cmp_id, intervalo)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        nomes = {e.nome_cientifico: e.nome_popular for e in s.scalars(select(Especie))}
        return {"an": an, "campanha": an.conjunto.campanha, "nomes": nomes,
                "grafico_atividade": graficos.atividade(an, nomes), "grafico_acumulacao": graficos.acumulacao(an),
                "mapa": graficos.mapa_svg(an.pontos)}

    @app.get("/analises", response_class=HTMLResponse)
    def analises(request: Request, campanha: int | None = None, intervalo: int = 30):
        if intervalo < 1:
            raise HTTPException(400, "intervalo deve ser de pelo menos 1 minuto")
        with fabrica() as s:
            campanhas = s.scalars(select(Campanha).order_by(Campanha.id.desc())).all()
            ctx = _contexto(s, campanha, intervalo) if campanha else {}
        return pagina(request, "analises.html", campanhas=campanhas, campanha_id=campanha, intervalo=intervalo, **ctx)

    @app.get("/analises/{cmp_id}/relatorio", response_class=HTMLResponse)
    def relatorio(request: Request, cmp_id: int, intervalo: int = 30):
        with fabrica() as s:
            ctx = _contexto(s, cmp_id, intervalo)
        css = (AQUI / "static" / "estilo.css").read_text("utf-8")
        return tpl.TemplateResponse(request, "relatorio.html", {**ctx, "css": css})

    @app.get("/analises/{cmp_id}/exportar")
    def exportar(request: Request, cmp_id: int, intervalo: int = 30, autor: str = ""):
        with fabrica() as s:
            ctx = _contexto(s, cmp_id, intervalo)
            html = tpl.get_template("relatorio.html").render(
                {**ctx, "css": (AQUI / "static" / "estilo.css").read_text("utf-8"), "request": request})
            arquivo = exportar_tudo(s, ctx["an"], html, autor)
        return FileResponse(arquivo, filename=arquivo.name, media_type="application/zip")
