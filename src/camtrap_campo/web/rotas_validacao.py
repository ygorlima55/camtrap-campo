"""Validação por espécie (conferência em bloco), planilha das espécies e relatório fotográfico."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import select

from camtrap_campo.db import Camera, Campanha, Especie
from camtrap_campo.exportacao import especies as planilha_especies
from camtrap_campo.ia import validacao
from camtrap_campo.web.estilo import css_relatorio

AQUI = Path(__file__).parent
RESULTADOS = ("especie", "pessoa", "veiculo", "vazio", "indeterminado")


def registrar(app: FastAPI, fabrica, pagina, tpl) -> None:
    def _filtros(s, campanha: int | None, camera: int | None) -> dict:
        cmp = s.get(Campanha, campanha) if campanha else None
        cam = s.get(Camera, camera) if camera else None
        partes = [f"campanha {cmp.nome}" if cmp else "todas as campanhas",
                  f"câmera {cam.etiqueta}" if cam else "todas as câmeras"]
        return {"campanha_sel": cmp, "camera_sel": cam, "descricao": " · ".join(partes)}

    @app.get("/validacao", response_class=HTMLResponse)
    def tela_validacao(request: Request, campanha: int | None = None, camera: int | None = None):
        with fabrica() as s:
            dados = validacao.montar(s, campanha, camera)
            lista = s.scalars(select(Especie).where(Especie.ativa).order_by(Especie.nome_popular)).all()
            return pagina(request, "validacao.html", dados=dados, especies=lista, alta=validacao.CONFIANCA_ALTA,
                          campanhas=s.scalars(select(Campanha).order_by(Campanha.id.desc())).all(),
                          cameras=s.scalars(select(Camera).order_by(Camera.etiqueta)).all(),
                          campanha=campanha, camera=camera, **_filtros(s, campanha, camera))

    @app.post("/validacao")
    def salvar_validacao(corpo: dict = Body(...)):
        resultado = corpo.get("resultado")
        if resultado not in RESULTADOS:
            raise HTTPException(400, "resultado inválido")
        itens = corpo.get("itens") or []
        if not itens:
            raise HTTPException(400, "nenhuma sequência selecionada")
        with fabrica() as s:
            try:
                n = validacao.validar(s, itens, resultado, corpo.get("especie_id") if resultado == "especie" else None)
            except (ValueError, KeyError, TypeError) as exc:
                raise HTTPException(400, str(exc)) from exc
        return JSONResponse({"ok": True, "salvos": n})

    @app.get("/validacao/planilha")
    def baixar_planilha(campanha: int | None = None, camera: int | None = None):
        with fabrica() as s:
            regs = validacao.registros_validados(s, campanha, camera)
            filtros = _filtros(s, campanha, camera)
            conteudo = planilha_especies.planilha(validacao.resumo_especies(regs), regs, filtros["descricao"])
        nome = f"especies_validadas_{dt.datetime.now():%Y%m%d_%H%M}.xlsx"
        return Response(conteudo, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{nome}"'})

    @app.get("/validacao/relatorio", response_class=HTMLResponse)
    def relatorio_fotografico(request: Request, campanha: int | None = None, camera: int | None = None):
        with fabrica() as s:
            regs = validacao.registros_validados(s, campanha, camera)
            pendentes = validacao.montar(s, campanha, camera)["pendentes"]
            ctx = {"resumo": validacao.resumo_especies(regs), "total": len(regs), "pendentes": pendentes,
                   "gerado": dt.datetime.now(), "css": css_relatorio(),
                   **_filtros(s, campanha, camera)}
            return tpl.TemplateResponse(request, "relatorio_fotografico.html", ctx)
