"""Exportação no padrão Camtrap DP 1.0 (TDWG): datapackage.json + deployments.csv + media.csv + observations.csv.

- Observações em nível de EVENTO (uma por sequência revisada), classificadas por pessoa ("human").
- Horários com fuso (padrão America/Sao_Paulo); arquivos referenciados pelo caminho relativo à pasta Dados.
- Não validado com o validador oficial (frictionless) — ele baixa os esquemas da internet. A estrutura e os
  campos obrigatórios seguem a especificação 1.0 e são conferidos nos testes.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from camtrap_campo import __version__, config
from camtrap_campo.analises.resultado import Analise
from camtrap_campo.db import Arquivo, Revisao
from camtrap_campo.exportacao.tabelas import escrever_csv

PERFIL = "https://raw.githubusercontent.com/tdwg/camtrap-dp/1.0/camtrap-dp-profile.json"
ESQUEMA = "https://raw.githubusercontent.com/tdwg/camtrap-dp/1.0/{}-table-schema.json"
TIPO_OBS = {"especie": "animal", "vazio": "blank", "pessoa": "human", "veiculo": "vehicle", "indeterminado": "unknown"}
MIDIA = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".avi": "video/x-msvideo", ".mp4": "video/mp4",
         ".mov": "video/quicktime", ".3gp": "video/3gpp"}


def _iso(d: dt.datetime | None, tz: ZoneInfo) -> str:
    return d.replace(tzinfo=tz).isoformat() if d else ""


def _id_deployment(ponto: str, camera: str) -> str:
    return f"{ponto}_{camera}".replace(" ", "-")


def exportar(sessao, an: Analise, destino: Path, autor: str = "") -> Path:
    tz = ZoneInfo(config.FUSO)
    destino.mkdir(parents=True, exist_ok=True)
    estacoes = {i: e for e in an.conjunto.estacoes for i in e.importacoes}

    deployments = [{
        "deploymentID": _id_deployment(e.ponto, e.camera), "locationID": e.ponto, "locationName": e.ponto,
        "latitude": e.latitude, "longitude": e.longitude, "deploymentStart": _iso(e.inicio, tz),
        "deploymentEnd": _iso(e.fim, tz), "cameraID": e.camera, "cameraModel": e.modelo or "",
        "deploymentComments": f"período por {e.fonte_periodo}",
    } for e in an.conjunto.estacoes]

    arquivos = sessao.scalars(select(Arquivo).where(Arquivo.importacao_id.in_(list(estacoes)), Arquivo.estado == "copiado",
                                                    Arquivo.tipo.in_(("foto", "video")))).all()
    media = [{
        "mediaID": str(a.id), "deploymentID": _id_deployment(estacoes[a.importacao_id].ponto, estacoes[a.importacao_id].camera),
        "captureMethod": "activityDetection", "timestamp": _iso(a.data, tz), "filePath": a.caminho_final,
        "filePublic": "false", "fileName": Path(a.caminho_final).name,
        "fileMediatype": MIDIA.get(Path(a.caminho_final).suffix.lower(), "application/octet-stream"),
        "mediaComments": f"nome original no cartão: {a.nome_original}",
    } for a in arquivos if a.data]
    por_id = {a.id: a for a in arquivos}

    observacoes = []
    for rev in sessao.scalars(select(Revisao).where(Revisao.importacao_id.in_(list(estacoes))).order_by(Revisao.id)):
        datas = [por_id[i].data for i in rev.arquivos if i in por_id and por_id[i].data]
        if not datas:
            continue
        e = estacoes[rev.importacao_id]
        observacoes.append({
            "observationID": f"obs{rev.id}", "deploymentID": _id_deployment(e.ponto, e.camera), "mediaID": "",
            "eventID": f"seq{rev.chave_sequencia}", "eventStart": _iso(min(datas), tz), "eventEnd": _iso(max(datas), tz),
            "observationLevel": "event", "observationType": TIPO_OBS.get(rev.resultado, "unknown"),
            "scientificName": rev.especie.nome_cientifico if rev.especie else "", "count": rev.quantidade or "",
            "behavior": rev.comportamento or "", "classificationMethod": "human", "classifiedBy": autor,
            "classificationTimestamp": _iso(rev.revisado_em, tz),
            "observationComments": ("boa para divulgação; " if rev.divulgacao else "") + (rev.observacao or ""),
        })

    escrever_csv(destino / "deployments.csv", deployments)
    escrever_csv(destino / "media.csv", media)
    escrever_csv(destino / "observations.csv", observacoes)
    for nome in ("deployments.csv", "media.csv", "observations.csv"):  # Camtrap DP pede UTF-8 sem BOM
        texto = (destino / nome).read_text(encoding="utf-8-sig")
        (destino / nome).write_text(texto, encoding="utf-8")

    inicios = [e.inicio for e in an.conjunto.estacoes if e.inicio]
    fins = [e.fim for e in an.conjunto.estacoes if e.fim]
    lats = [e.latitude for e in an.conjunto.estacoes if e.latitude is not None]
    lons = [e.longitude for e in an.conjunto.estacoes if e.longitude is not None]
    pacote = {
        "profile": PERFIL, "name": an.conjunto.campanha.nome.lower().replace(" ", "-"),
        "created": dt.datetime.now(tz).isoformat(timespec="seconds"),
        "title": f"Armadilhas fotográficas — {an.conjunto.campanha.nome}",
        "contributors": [{"title": autor or "Equipe do projeto", "role": "contact"}],
        "project": {"title": an.conjunto.campanha.nome, "samplingDesign": "opportunistic",
                    "captureMethod": ["activityDetection"], "individualAnimals": False, "observationLevel": ["event"]},
        "spatial": ({"type": "Polygon", "bbox": [min(lons), min(lats), max(lons), max(lats)],
                     "coordinates": [[[min(lons), min(lats)], [max(lons), min(lats)], [max(lons), max(lats)],
                                      [min(lons), max(lats)], [min(lons), min(lats)]]]} if lats and lons else None),
        "temporal": {"start": min(inicios).date().isoformat() if inicios else None,
                     "end": max(fins).date().isoformat() if fins else None},
        "taxonomic": [{"scientificName": t["especie"], "vernacularNames": {"por": t["nome_popular"]}}
                      for t in an.taxas["especies"]],
        "sources": [{"title": f"CamTrap Campo {__version__}"}],
        "resources": [{"name": n, "path": f"{n}.csv", "profile": "tabular-data-resource", "format": "csv",
                       "mediatype": "text/csv", "encoding": "UTF-8", "schema": ESQUEMA.format(n)}
                      for n in ("deployments", "media", "observations")],
    }
    (destino / "datapackage.json").write_text(json.dumps(pacote, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino
