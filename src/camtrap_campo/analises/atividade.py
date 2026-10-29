"""Padrão de atividade diária: hora solar, densidade de kernel circular e sobreposição entre espécies.

Métodos (Ridout & Linkie 2009; pacote R ``overlap``):
- Hora solar por "dupla ancoragem": nascer do sol → 6 h solares, pôr do sol → 18 h; entre eles, escala linear
  (o mesmo princípio de ``overlap::sunTime``). Nascer/pôr calculados localmente com ``astral`` pelas coordenadas.
- Densidade: soma de kernels de von Mises; concentração pela regra de Taylor (2008) a partir do κ estimado
  (aproximação de Best & Fisher para A1⁻¹), multiplicada por ``ajuste`` (padrão 1).
- Sobreposição Δ: Δ̂1 (integral numérica de min(f, g)) para amostras pequenas; Δ̂4 (média nos pontos observados)
  quando ambas têm ≥ 75 registros, como recomendado por Ridout & Linkie.
Pendente: intervalos de confiança por bootstrap e conferência numérica com o pacote R.
"""

from __future__ import annotations

import datetime as dt
import math
from zoneinfo import ZoneInfo

import numpy as np

from camtrap_campo import config

DOIS_PI = 2 * math.pi
AMOSTRA_MINIMA = 10  # abaixo disso a curva não é estimada
LIMITE_DELTA4 = 75


def bessel_i(n: int, x: float, termos: int = 300) -> float:
    """Função de Bessel modificada de 1ª espécie Iₙ(x), por série (suficiente para x ≤ ~600)."""
    soma, termo = 0.0, (x / 2) ** n / math.factorial(n)
    for k in range(termos):
        soma += termo
        termo *= (x / 2) ** 2 / ((k + 1) * (k + 1 + n))
        if termo < soma * 1e-16:
            break
    return soma


def kappa_estimado(radianos: np.ndarray) -> float:
    r = math.hypot(np.cos(radianos).mean(), np.sin(radianos).mean())
    if r < 0.53:
        return 2 * r + r**3 + 5 * r**5 / 6
    if r < 0.85:
        return -0.4 + 1.39 * r + 0.43 / (1 - r)
    return 1 / (r**3 - 4 * r**2 + 3 * r)


def largura_banda(radianos: np.ndarray) -> float:
    """Regra de Taylor (2008): ν = [3 n κ² I₂(2κ) / (4 √π I₀(κ)²)]^(2/5)."""
    n, k = len(radianos), min(kappa_estimado(radianos), 300.0)
    return (3 * n * k**2 * bessel_i(2, 2 * k) / (4 * math.sqrt(math.pi) * bessel_i(0, k) ** 2)) ** 0.4


def densidade(radianos: np.ndarray, grade: np.ndarray, ajuste: float = 1.0) -> np.ndarray:
    nu = min(largura_banda(radianos) * ajuste, 600.0)
    # exp(ν(cos−1)) / (2π I₀(ν) e^{−ν}) evita estouro numérico
    i0_escalado = bessel_i(0, nu) * math.exp(-nu)
    kern = np.exp(nu * (np.cos(grade[:, None] - radianos[None, :]) - 1)) / (DOIS_PI * i0_escalado)
    return kern.mean(axis=1)


def sobreposicao(a: np.ndarray, b: np.ndarray, ajuste: float = 1.0) -> dict:
    """Coeficiente de sobreposição Δ entre duas amostras de horários (radianos)."""
    if min(len(a), len(b)) < AMOSTRA_MINIMA:
        return {"delta": None, "estimador": None, "motivo": f"menos de {AMOSTRA_MINIMA} registros numa das espécies"}
    if min(len(a), len(b)) >= LIMITE_DELTA4:
        fa_a, fb_a = densidade(a, a, ajuste), densidade(b, a, ajuste)
        fa_b, fb_b = densidade(a, b, ajuste), densidade(b, b, ajuste)
        d = 0.5 * (np.minimum(1, fb_a / fa_a).mean() + np.minimum(1, fa_b / fb_b).mean())
        return {"delta": float(round(d, 3)), "estimador": "Δ̂4"}
    grade = np.linspace(0, DOIS_PI, 512, endpoint=False)
    d = np.minimum(densidade(a, grade, ajuste), densidade(b, grade, ajuste)).sum() * DOIS_PI / len(grade)
    return {"delta": float(round(d, 3)), "estimador": "Δ̂1"}


def nascer_por(data: dt.date, lat: float, lon: float, fuso: str = config.FUSO) -> tuple[dt.datetime, dt.datetime] | None:
    from astral import Observer
    from astral.sun import sunrise, sunset

    tz = ZoneInfo(fuso)
    try:
        obs = Observer(latitude=lat, longitude=lon)
        return (sunrise(obs, data, tzinfo=tz).replace(tzinfo=None), sunset(obs, data, tzinfo=tz).replace(tzinfo=None))
    except ValueError:  # sol não nasce/põe (não ocorre no Brasil)
        return None


def hora_solar(momento: dt.datetime, lat: float | None, lon: float | None) -> float:
    """Horas solares 0–24 (nascer = 6, pôr = 18). Sem coordenadas, devolve a hora do relógio."""
    hora_relogio = momento.hour + momento.minute / 60 + momento.second / 3600
    if lat is None or lon is None:
        return hora_relogio
    np_hoje = nascer_por(momento.date(), lat, lon)
    if np_hoje is None:
        return hora_relogio
    nascer, por = np_hoje
    if nascer <= momento <= por:
        return 6 + 12 * (momento - nascer) / (por - nascer)
    if momento > por:
        seguinte = nascer_por(momento.date() + dt.timedelta(days=1), lat, lon)
        nascer2 = seguinte[0] if seguinte else nascer + dt.timedelta(days=1)
        return (18 + 12 * (momento - por) / (nascer2 - por)) % 24
    anterior = nascer_por(momento.date() - dt.timedelta(days=1), lat, lon)
    por0 = anterior[1] if anterior else por - dt.timedelta(days=1)
    return (18 + 12 * (momento - por0) / (nascer - por0)) % 24


def para_radianos(horas: list[float]) -> np.ndarray:
    return np.array(horas, dtype=float) % 24 * DOIS_PI / 24


def curva(horas: list[float], pontos: int = 289) -> dict | None:
    """Curva de densidade de atividade em horas (0–24); integral = 1 em radianos."""
    if len(horas) < AMOSTRA_MINIMA:
        return None
    rad = para_radianos(horas)
    grade = np.linspace(0, DOIS_PI, pontos)
    return {"horas": (grade * 24 / DOIS_PI).tolist(), "densidade": densidade(rad, grade).tolist(), "n": len(horas)}


def classificar_periodo(horas_solares: list[float]) -> str:
    """Rótulo descritivo pela proporção de registros (horas solares: dia 6–18). Não é um teste estatístico."""
    if not horas_solares:
        return "sem registros"
    dia = sum(1 for h in horas_solares if 6 <= h < 18) / len(horas_solares)
    crepusculo = sum(1 for h in horas_solares if 5 <= h < 7 or 17 <= h < 19) / len(horas_solares)
    if crepusculo >= 0.5:
        return "crepuscular"
    if dia >= 0.8:
        return "diurno"
    if dia <= 0.2:
        return "noturno"
    return "catemeral"
