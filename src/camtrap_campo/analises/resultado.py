"""Reúne todas as análises de uma campanha num único objeto (usado pela tela, relatório e exportações)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from camtrap_campo.analises import atividade
from camtrap_campo.analises.acumulacao import acumulacao
from camtrap_campo.analises.basicas import Esforco, esforco, independentes, taxa_captura
from camtrap_campo.analises.dados import Conjunto, Registro, carregar


@dataclass
class Analise:
    conjunto: Conjunto
    intervalo_min: int
    independentes: list[Registro]
    esforco: list[Esforco]
    taxas: dict
    horas_solares: dict[str, list[float]]
    curvas: dict[str, dict | None]
    periodos: dict[str, str]
    sobreposicoes: list[dict]
    acumulacao: dict
    pontos: list[dict]
    avisos: list[str] = field(default_factory=list)


def analisar(sessao, campanha_id: int, intervalo_min: int = 30) -> Analise:
    c = carregar(sessao, campanha_id)
    indep = independentes(c.registros, intervalo_min)
    esf = esforco(c.estacoes)
    coords = {e.ponto: (e.latitude, e.longitude) for e in c.estacoes}
    horas: dict[str, list[float]] = defaultdict(list)
    for r in indep:
        lat, lon = coords.get(r.ponto, (None, None))
        horas[r.especie].append(atividade.hora_solar(r.data, lat, lon))
    curvas = {e: atividade.curva(h) for e, h in horas.items()}
    periodos = {e: atividade.classificar_periodo(h) for e, h in horas.items()}
    elegiveis = sorted(e for e, h in horas.items() if len(h) >= atividade.AMOSTRA_MINIMA)
    sobre = []
    for a, b in combinations(elegiveis, 2):
        sobre.append({"a": a, "b": b, "na": len(horas[a]), "nb": len(horas[b]),
                      **atividade.sobreposicao(atividade.para_radianos(horas[a]), atividade.para_radianos(horas[b]))})
    por_ponto: dict[str, dict] = {}
    dias_ponto = taxa_captura(indep, esf)["dias_por_ponto"]
    for e in c.estacoes:
        por_ponto.setdefault(e.ponto, {"ponto": e.ponto, "latitude": e.latitude, "longitude": e.longitude,
                                    "registros": 0, "especies": set(), "camaras_dia": dias_ponto.get(e.ponto, 0)})
    for r in indep:
        por_ponto[r.ponto]["registros"] += 1
        por_ponto[r.ponto]["especies"].add(r.especie)
    pontos = [{**p, "riqueza": len(p["especies"]), "especies": sorted(p["especies"])} for p in por_ponto.values()]

    avisos = []
    if c.ignorados_relogio:
        avisos.append(f"{c.ignorados_relogio} identificação(ões) ignorada(s): relógio resetado sem correção de horário.")
    sem_coord = sorted(p["ponto"] for p in pontos if p["latitude"] is None or p["longitude"] is None)
    if sem_coord:
        avisos.append("Pontos sem coordenadas (atividade em hora do relógio e fora do mapa): " + ", ".join(sem_coord))
    sem_periodo = [f"{e.ponto}/{e.camera}" for e in esf if not e.camaras_dia]
    if sem_periodo:
        avisos.append("Estações sem período de operação conhecido (sem esforço): " + ", ".join(sem_periodo))
    if any(e.fonte_periodo != "eventos" for e in esf):
        avisos.append("Algumas estações sem eventos de instalação/retirada: o período usa a primeira e a última mídia, "
                      "o que pode subestimar o esforço. Registre os eventos na página de cada câmera.")
    return Analise(c, intervalo_min, indep, esf, taxa_captura(indep, esf), dict(horas), curvas, periodos, sobre,
                   acumulacao(indep, esf), pontos, avisos)
