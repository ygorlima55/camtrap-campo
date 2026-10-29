"""Registros independentes, esforço amostral (câmeras-dia) e taxa de captura."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

from camtrap_campo.analises.dados import Estacao, Registro

INTERVALO_INDEPENDENCIA_MIN = 30


def independentes(registros: list[Registro], intervalo_min: int = INTERVALO_INDEPENDENCIA_MIN,
                  comparar_com: str = "ultimo_independente") -> list[Registro]:
    """Mesma espécie no mesmo ponto só conta de novo depois de ``intervalo_min`` minutos.

    ``comparar_com``: "ultimo_independente" (padrão, como deltaTimeComparedTo="lastIndependentRecord" no camtrapR)
    ou "ultimo_registro" (cada registro reinicia a janela).
    """
    if comparar_com not in ("ultimo_independente", "ultimo_registro"):
        raise ValueError("comparar_com inválido")
    janela = dt.timedelta(minutes=intervalo_min)
    grupos: dict[tuple[str, str], list[Registro]] = defaultdict(list)
    for r in registros:
        grupos[(r.ponto, r.especie)].append(r)
    out = []
    for lista in grupos.values():
        lista.sort(key=lambda r: r.data)
        referencia = None
        for r in lista:
            if referencia is None or r.data - referencia >= janela:
                out.append(r)
                referencia = r.data
            elif comparar_com == "ultimo_registro":
                referencia = r.data
    return sorted(out, key=lambda r: (r.ponto, r.data))


@dataclass
class Esforco:
    ponto: str
    camera: str
    inicio: dt.date | None
    fim: dt.date | None
    dias_totais: int
    dias_falha: int
    camaras_dia: int
    fonte_periodo: str


def _dias(inicio: dt.datetime, fim: dt.datetime) -> set[dt.date]:
    return {inicio.date() + dt.timedelta(days=i) for i in range((fim.date() - inicio.date()).days + 1)}


def esforco(estacoes: list[Estacao]) -> list[Esforco]:
    """Dias de operação (inclusive) menos dias inteiros cobertos por falhas registradas."""
    out = []
    for e in estacoes:
        if not (e.inicio and e.fim) or e.fim < e.inicio:
            out.append(Esforco(e.ponto, e.camera, None, None, 0, 0, 0, e.fonte_periodo))
            continue
        operando = _dias(e.inicio, e.fim)
        parados = set()
        for ini, fim in e.falhas:
            parados |= _dias(max(ini, e.inicio), min(fim, e.fim)) if fim >= e.inicio and ini <= e.fim else set()
        parados &= operando
        out.append(Esforco(e.ponto, e.camera, e.inicio.date(), e.fim.date(), len(operando), len(parados),
                           len(operando - parados), e.fonte_periodo))
    return out


def taxa_captura(indep: list[Registro], esf: list[Esforco]) -> dict:
    """Registros independentes por 100 câmeras-dia, por espécie (total e por ponto)."""
    dias_ponto: dict[str, int] = defaultdict(int)
    for e in esf:
        dias_ponto[e.ponto] += e.camaras_dia
    total_dias = sum(dias_ponto.values())
    por_especie: dict[str, dict] = {}
    for r in indep:
        d = por_especie.setdefault(r.especie, {"nome_popular": r.nome_popular, "registros": 0, "por_ponto": defaultdict(int)})
        d["registros"] += 1
        d["por_ponto"][r.ponto] += 1
    tabela = []
    for especie, d in sorted(por_especie.items(), key=lambda x: -x[1]["registros"]):
        tabela.append({
            "especie": especie, "nome_popular": d["nome_popular"], "registros": d["registros"],
            "taxa": round(100 * d["registros"] / total_dias, 2) if total_dias else None,
            "pontos_com_registro": len(d["por_ponto"]),
            "por_ponto": {p: {"registros": n, "taxa": round(100 * n / dias_ponto[p], 2) if dias_ponto.get(p) else None}
                          for p, n in sorted(d["por_ponto"].items())},
        })
    return {"camaras_dia": total_dias, "dias_por_ponto": dict(dias_ponto), "especies": tabela}
