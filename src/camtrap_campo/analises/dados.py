"""Carrega estações (campanha × ponto × câmera) e registros revisados de uma campanha.

Regras:
- Só entram identificações confirmadas por uma pessoa (Revisao com resultado "especie").
- A hora de um registro é a do início da sequência (hora corrigida, se houver correção de relógio).
- Registros com relógio resetado e sem correção ficam de fora (e são contados para o aviso).
- Período da estação: instalação → retirada (eventos de campo); na falta, primeira → última mídia com data válida.
- Falhas: eventos "falha" com início e fim descontam dias do esforço.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select

from camtrap_campo import config
from camtrap_campo.db import Arquivo, Camera, Campanha, EventoCamera, Importacao, Ponto, Revisao


@dataclass
class Estacao:
    campanha: str
    ponto: str
    camera: str
    modelo: str | None
    latitude: float | None
    longitude: float | None
    inicio: dt.datetime | None
    fim: dt.datetime | None
    fonte_periodo: str  # eventos | midias | misto
    falhas: list[tuple[dt.datetime, dt.datetime]] = field(default_factory=list)
    importacoes: list[int] = field(default_factory=list)

    @property
    def chave(self) -> tuple[str, str]:
        return self.ponto, self.camera


@dataclass
class Registro:
    especie: str  # nome científico
    nome_popular: str
    ponto: str
    camera: str
    data: dt.datetime
    quantidade: int | None
    comportamento: str | None
    divulgacao: bool
    arquivos: list[int]
    revisao_id: int
    importacao_id: int


@dataclass
class Conjunto:
    campanha: Campanha
    estacoes: list[Estacao]
    registros: list[Registro]
    ignorados_relogio: int = 0
    outros_resultados: dict = field(default_factory=dict)  # vazio/pessoa/veiculo/indeterminado → contagem


def _datas_validas(arquivos) -> list[dt.datetime]:
    out = []
    for a in arquivos:
        d = a.data_corrigida or a.data_original
        if d is None or a.fonte_data == "arquivo" or (a.data_corrigida is None and d.year < config.ANO_MINIMO_VALIDO):
            continue
        out.append(d)
    return out


def carregar(sessao, campanha_id: int) -> Conjunto:
    cmp = sessao.get(Campanha, campanha_id)
    if cmp is None:
        raise ValueError("campanha não encontrada")
    imps = sessao.scalars(select(Importacao).where(Importacao.campanha_id == campanha_id)).all()
    por_estacao: dict[tuple[int, int], list[Importacao]] = {}
    for imp in imps:
        por_estacao.setdefault((imp.ponto_id, imp.camera_id), []).append(imp)

    estacoes, mapa_imp = [], {}
    for (ponto_id, camera_id), lista in por_estacao.items():
        pto, cam = sessao.get(Ponto, ponto_id), sessao.get(Camera, camera_id)
        arquivos = sessao.scalars(select(Arquivo).where(
            Arquivo.importacao_id.in_([i.id for i in lista]), Arquivo.estado == "copiado",
            Arquivo.tipo.in_(("foto", "video")))).all()
        datas = _datas_validas(arquivos)
        eventos = sessao.scalars(select(EventoCamera).where(
            EventoCamera.camera_id == camera_id, EventoCamera.campanha_id == campanha_id)).all()
        inst = min((e.data for e in eventos if e.tipo == "instalacao" and e.ponto_id in (ponto_id, None)), default=None)
        ret = max((e.data for e in eventos if e.tipo == "retirada" and e.ponto_id in (ponto_id, None)), default=None)
        inicio = inst or (min(datas) if datas else None)
        fim = ret or (max(datas) if datas else None)
        fonte = "eventos" if inst and ret else ("midias" if not inst and not ret else "misto")
        falhas = [(e.data, e.fim) for e in eventos if e.tipo == "falha" and e.fim and e.fim > e.data]
        est = Estacao(cmp.nome, pto.nome, cam.etiqueta, cam.modelo, pto.latitude, pto.longitude, inicio, fim, fonte,
                      falhas, [i.id for i in lista])
        estacoes.append(est)
        for i in lista:
            mapa_imp[i.id] = est

    registros, ignorados, outros = [], 0, {}
    for rev in sessao.scalars(select(Revisao).where(Revisao.importacao_id.in_(list(mapa_imp)))):
        if rev.resultado != "especie":
            outros[rev.resultado] = outros.get(rev.resultado, 0) + 1
            continue
        arquivos = sessao.scalars(select(Arquivo).where(Arquivo.id.in_(rev.arquivos))).all()
        datas = _datas_validas(arquivos)
        if not datas:
            ignorados += 1
            continue
        est = mapa_imp[rev.importacao_id]
        registros.append(Registro(rev.especie.nome_cientifico, rev.especie.nome_popular, est.ponto, est.camera,
                                  min(datas), rev.quantidade, rev.comportamento, rev.divulgacao, rev.arquivos, rev.id,
                                  rev.importacao_id))
    registros.sort(key=lambda r: (r.ponto, r.data))
    return Conjunto(cmp, sorted(estacoes, key=lambda e: e.chave), registros, ignorados, outros)
