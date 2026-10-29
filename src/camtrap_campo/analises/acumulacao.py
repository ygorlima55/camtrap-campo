"""Curva de acumulação de espécies por dia de amostragem (ordem aleatória dos dias, média ± desvio)."""

from __future__ import annotations

import datetime as dt
import random
import statistics

from camtrap_campo.analises.basicas import Esforco
from camtrap_campo.analises.dados import Registro


def acumulacao(indep: list[Registro], esf: list[Esforco], permutacoes: int = 200, semente: int = 42) -> dict:
    """Cada dia com ao menos uma câmera operando é uma unidade amostral (estações somadas no dia)."""
    dias = set()
    for e in esf:
        if e.inicio and e.fim:
            dias |= {e.inicio + dt.timedelta(days=i) for i in range((e.fim - e.inicio).days + 1)}
    especies_dia: dict[dt.date, set[str]] = {d: set() for d in dias}
    for r in indep:
        especies_dia.setdefault(r.data.date(), set()).add(r.especie)
    unidades = list(especies_dia.values())
    if not unidades:
        return {"dias": [], "media": [], "desvio": [], "observada": 0}
    gerador = random.Random(semente)
    curvas = []
    for _ in range(permutacoes):
        ordem = unidades[:]
        gerador.shuffle(ordem)
        vistas, linha = set(), []
        for u in ordem:
            vistas |= u
            linha.append(len(vistas))
        curvas.append(linha)
    colunas = list(zip(*curvas, strict=True))
    return {"dias": list(range(1, len(unidades) + 1)), "media": [round(statistics.fmean(c), 3) for c in colunas],
            "desvio": [round(statistics.pstdev(c), 3) for c in colunas],
            "observada": len(set().union(*unidades)), "permutacoes": permutacoes}
