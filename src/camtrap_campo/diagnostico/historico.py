"""Histórico por câmera: eventos de campo + dias ativos calculados pelas mídias importadas."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select

from camtrap_campo import config
from camtrap_campo.db import Arquivo, EventoCamera, Importacao

TIPOS_EVENTO = {
    "instalacao": "Instalação", "retirada": "Retirada", "pilhas": "Troca de pilhas", "cartao": "Troca/formatação de cartão",
    "falha": "Falha", "manutencao": "Manutenção", "observacao": "Observação",
}


@dataclass
class Atividade:
    dias_com_registro: int = 0
    primeiro: dt.date | None = None
    ultimo: dt.date | None = None
    dias_no_periodo: int = 0
    lacunas: list[tuple[dt.date, dt.date, int]] = field(default_factory=list)  # (de, até, dias sem registro)
    midias_consideradas: int = 0
    midias_ignoradas: int = 0  # sem data interna ou com relógio resetado


def atividade(sessao, camera_id: int, lacuna_minima_dias: int = 2) -> Atividade:
    """Dias com pelo menos um registro (fotos/vídeos de time-lapse inclusive), com data interna válida."""
    linhas = sessao.execute(
        select(Arquivo.data_corrigida, Arquivo.data_original, Arquivo.fonte_data)
        .join(Importacao, Arquivo.importacao_id == Importacao.id)
        .where(Importacao.camera_id == camera_id, Arquivo.estado == "copiado", Arquivo.tipo.in_(("foto", "video")))
    ).all()
    a = Atividade()
    dias = set()
    for corrigida, original, fonte in linhas:
        data = corrigida or original
        if data is None or fonte == "arquivo" or (corrigida is None and data.year < config.ANO_MINIMO_VALIDO):
            a.midias_ignoradas += 1
            continue
        a.midias_consideradas += 1
        dias.add(data.date())
    if not dias:
        return a
    ordenados = sorted(dias)
    a.dias_com_registro, a.primeiro, a.ultimo = len(ordenados), ordenados[0], ordenados[-1]
    a.dias_no_periodo = (a.ultimo - a.primeiro).days + 1
    for d1, d2 in zip(ordenados, ordenados[1:], strict=False):
        sem = (d2 - d1).days - 1
        if sem >= lacuna_minima_dias:
            a.lacunas.append((d1 + dt.timedelta(days=1), d2 - dt.timedelta(days=1), sem))
    return a


def eventos(sessao, camera_id: int) -> list[EventoCamera]:
    lista = sessao.scalars(select(EventoCamera).where(EventoCamera.camera_id == camera_id)
                           .order_by(EventoCamera.data.desc())).all()
    for e in lista:
        _ = e.ponto, e.campanha
    return list(lista)
