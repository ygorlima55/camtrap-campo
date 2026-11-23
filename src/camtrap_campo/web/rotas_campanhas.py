"""Campanhas: quantas fotos e vídeos, em que pasta estão e pré-visualização por câmera/ponto."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from camtrap_campo import config
from camtrap_campo.db import Arquivo, Camera, Campanha, Importacao, Ponto, Vestigio

POR_PAGINA = 60


def abrir_no_explorer(caminho: Path) -> None:  # substituído nos testes
    os.startfile(caminho)  # noqa: S606 — só pastas dentro de Dados, neste computador


def _midias(campanha_id: int):
    return (select(Arquivo, Importacao, Camera.etiqueta, Ponto.nome)
            .join(Importacao, Arquivo.importacao_id == Importacao.id)
            .join(Camera, Importacao.camera_id == Camera.id).join(Ponto, Importacao.ponto_id == Ponto.id)
            .where(Importacao.campanha_id == campanha_id, Arquivo.estado == "copiado", Arquivo.tipo.in_(("foto", "video"))))


def resumo_campanha(s, campanha_id: int) -> dict:
    """Totais e um bloco por câmera/ponto, com a pasta onde as mídias estão (relativa a Dados)."""
    blocos: dict[tuple, dict] = {}
    for arq, imp, cam, pto in s.execute(_midias(campanha_id)):
        b = blocos.setdefault((pto, cam), {"ponto": pto, "camera": cam, "camera_id": imp.camera_id, "ponto_id": imp.ponto_id,
                                           "fotos": 0, "videos": 0, "primeira": None, "ultima": None,
                                           "pastas": Counter(), "importacoes": set(), "capa": None})
        b["fotos" if arq.tipo == "foto" else "videos"] += 1
        b["importacoes"].add(imp.id)
        if arq.caminho_final:
            b["pastas"][str(PurePosixPath(arq.caminho_final).parent)] += 1
        if arq.tipo == "foto" and b["capa"] is None:
            b["capa"] = arq.id
        if arq.data:
            b["primeira"] = min(filter(None, (b["primeira"], arq.data)))
            b["ultima"] = max(filter(None, (b["ultima"], arq.data)))
    lista = sorted(blocos.values(), key=lambda b: (b["ponto"], b["camera"]))
    for b in lista:
        b["pasta"] = b["pastas"].most_common(1)[0][0] if b["pastas"] else None
        b["outras_pastas"] = len(b["pastas"]) - 1
    vest = s.execute(select(Vestigio.caminho_final).where(Vestigio.campanha_id == campanha_id)).scalars().all()
    return {"blocos": lista, "fotos": sum(b["fotos"] for b in lista), "videos": sum(b["videos"] for b in lista),
            "cameras": len({b["camera"] for b in lista}), "pontos": len({b["ponto"] for b in lista}),
            "vestigios": len(vest),
            "pasta_vestigios": str(PurePosixPath(vest[0]).parent.parent) if vest else None}


def registrar(app: FastAPI, fabrica, pagina) -> None:
    @app.get("/campanhas", response_class=HTMLResponse)
    def lista(request: Request):
        with fabrica() as s:
            campanhas = s.scalars(select(Campanha).order_by(Campanha.id.desc())).all()
            itens = []
            for c in campanhas:
                r = resumo_campanha(s, c.id)
                capas = [b["capa"] for b in r["blocos"] if b["capa"]][:4]
                itens.append({"c": c, "r": r, "capas": capas})
            return pagina(request, "campanhas.html", itens=itens, pasta_dados=str(config.pasta_dados()))

    @app.get("/campanhas/{cid}", response_class=HTMLResponse)
    def ver(request: Request, cid: int, camera: int | None = None, ponto: int | None = None, tipo: str = "foto",
            pagina_n: int = 1, aberta: str = ""):
        with fabrica() as s:
            c = s.get(Campanha, cid)
            if c is None:
                raise HTTPException(404, "Campanha não encontrada")
            r = resumo_campanha(s, cid)
            consulta = _midias(cid)
            if camera:
                consulta = consulta.where(Importacao.camera_id == camera)
            if ponto:
                consulta = consulta.where(Importacao.ponto_id == ponto)
            if tipo in ("foto", "video"):
                consulta = consulta.where(Arquivo.tipo == tipo)
            total = s.scalar(select(func.count()).select_from(consulta.subquery()))
            paginas = max(1, -(-total // POR_PAGINA))
            pagina_n = min(max(1, pagina_n), paginas)
            ordem = consulta.order_by(func.coalesce(Arquivo.data_corrigida, Arquivo.data_original), Arquivo.id)
            midias = [{"a": a, "camera": cam, "ponto": pto}
                      for a, _, cam, pto in s.execute(ordem.offset((pagina_n - 1) * POR_PAGINA).limit(POR_PAGINA))]
            vestigios = s.scalars(select(Vestigio).where(Vestigio.campanha_id == cid).order_by(Vestigio.data).limit(24)).all()
            return pagina(request, "campanha.html", c=c, r=r, midias=midias, total=total, paginas=paginas,
                          pagina_n=pagina_n, camera=camera, ponto=ponto, tipo=tipo, vestigios=vestigios,
                          pasta_dados=str(config.pasta_dados()), aberta=aberta)

    @app.post("/campanhas/{cid}/abrir")
    def abrir(cid: int, pasta: str = Form(...)):
        dados = config.pasta_dados().resolve()
        alvo = (dados / pasta).resolve()
        if not alvo.is_dir() or (alvo != dados and dados not in alvo.parents):
            raise HTTPException(400, "Só dá para abrir pastas dentro da pasta de dados do programa")
        abrir_no_explorer(alvo)
        return RedirectResponse(f"/campanhas/{cid}?aberta=1", status_code=303)
