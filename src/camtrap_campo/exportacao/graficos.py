"""Gráficos do relatório (matplotlib, sem janela) e mapa dos pontos em SVG (sem mapa de fundo: nada sai da máquina).

Estilo da identidade v2 em traço fino (hairline): linhas de 0,6–1 px, eixos só embaixo e à esquerda, ocre como único
destaque, mata nas curvas e preenchimentos bem leves.
"""

from __future__ import annotations

import base64
import html
import math
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from camtrap_campo.analises.resultado import Analise  # noqa: E402

OCRE = "#BD8A3A"  # paleta da identidade v2 (mesma do identidade.css)
MATA = "#183326"
CARVAO = "#202820"
TEXTO_2 = "#626E61"
LINHA = "#D3D8CE"
NOITE = "#EEF0E8"
SUPERFICIE = "#FFFDF8"

ESTILO = {
    "font.family": ["Segoe UI", "Arial", "DejaVu Sans"], "font.size": 9, "text.color": CARVAO,
    "axes.edgecolor": LINHA, "axes.linewidth": 0.6, "axes.labelcolor": TEXTO_2, "axes.titlecolor": CARVAO,
    "axes.spines.top": False, "axes.spines.right": False, "axes.facecolor": SUPERFICIE, "figure.facecolor": SUPERFICIE,
    "xtick.color": TEXTO_2, "ytick.color": TEXTO_2, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "xtick.major.size": 3, "ytick.major.size": 3, "axes.grid": True, "axes.grid.axis": "y", "grid.color": LINHA,
    "grid.linewidth": 0.5, "grid.linestyle": (0, (2, 3)), "lines.linewidth": 1.0, "legend.frameon": False,
}


def _png(fig) -> str:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def atividade(an: Analise, nomes: dict[str, str]) -> str | None:
    especies = [e for e, c in an.curvas.items() if c]
    if not especies:
        return None
    colunas = min(3, len(especies))
    linhas = math.ceil(len(especies) / colunas)
    with plt.rc_context(ESTILO):
        fig, eixos = plt.subplots(linhas, colunas, figsize=(4.2 * colunas, 2.8 * linhas), squeeze=False, layout="constrained")
        for ax, esp in zip(eixos.flat, sorted(especies), strict=False):
            c = an.curvas[esp]
            ax.fill_between(c["horas"], c["densidade"], color=MATA, alpha=0.06, linewidth=0)
            ax.plot(c["horas"], c["densidade"], color=MATA)
            h = an.horas_solares[esp]
            ax.plot(h, [0] * len(h), "|", color=OCRE, markersize=7, markeredgewidth=0.8)  # registros (tapete)
            ax.axvspan(0, 6, color=NOITE, zorder=0, linewidth=0)
            ax.axvspan(18, 24, color=NOITE, zorder=0, linewidth=0)
            ax.set_xlim(0, 24)
            ax.set_xticks([0, 6, 12, 18, 24])
            ax.set_title(f"{nomes.get(esp, esp)} (n={c['n']})", fontsize=9, style="italic", loc="left")
            ax.set_yticks([])
            ax.grid(False)
        for ax in list(eixos.flat)[len(especies):]:
            ax.axis("off")
        fig.supxlabel("hora solar (6 = nascer do sol, 18 = pôr do sol; faixa clara = noite)", fontsize=8.5, color=TEXTO_2)
        return _png(fig)


def acumulacao(an: Analise) -> str | None:
    a = an.acumulacao
    if not a["dias"]:
        return None
    with plt.rc_context(ESTILO):
        fig, ax = plt.subplots(figsize=(6, 3.2))
        sup = [m + d for m, d in zip(a["media"], a["desvio"], strict=True)]
        inf = [max(0, m - d) for m, d in zip(a["media"], a["desvio"], strict=True)]
        ax.fill_between(a["dias"], inf, sup, color=OCRE, alpha=0.12, linewidth=0, label="± 1 desvio-padrão")
        ax.plot(a["dias"], sup, color=OCRE, linewidth=0.6)
        ax.plot(a["dias"], inf, color=OCRE, linewidth=0.6)
        ax.plot(a["dias"], a["media"], color=MATA, label="média de ordens aleatórias")
        ax.set_xlabel("dias de amostragem")
        ax.set_ylabel("espécies")
        ax.legend(fontsize=8, loc="lower right")
        return _png(fig)


def mapa_svg(pontos: list[dict], largura: int = 640, altura: int = 420) -> str | None:
    """Pontos em projeção equiretangular; círculo ∝ √registros; número = riqueza. Sem mapa de fundo."""
    com = [p for p in pontos if p["latitude"] is not None and p["longitude"] is not None]
    if not com:
        return None
    lats, lons = [p["latitude"] for p in com], [p["longitude"] for p in com]
    margem = 0.1 * max(max(lats) - min(lats), max(lons) - min(lons), 0.005)
    la0, la1, lo0, lo1 = min(lats) - margem, max(lats) + margem, min(lons) - margem, max(lons) + margem
    escala_lon = math.cos(math.radians((la0 + la1) / 2))
    w, h = (lo1 - lo0) * escala_lon, la1 - la0
    fator = min((largura - 40) / w, (altura - 40) / h)
    maior = max(p["registros"] for p in com) or 1
    grade = "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{altura}"/>' for x in range(0, largura + 1, 80)) + "".join(
        f'<line x1="0" y1="{y}" x2="{largura}" y2="{y}"/>' for y in range(0, altura + 1, 80))
    elementos = [f'<g stroke="{LINHA}" stroke-width="0.6" stroke-dasharray="2 3">{grade}</g>']
    for p in com:
        x = 20 + (p["longitude"] - lo0) * escala_lon * fator
        y = altura - 20 - (p["latitude"] - la0) * fator
        r = 6 + 22 * math.sqrt(p["registros"] / maior)
        nome = html.escape(p["ponto"])
        elementos.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{OCRE}" fill-opacity="0.1" stroke="{MATA}"'
            f' stroke-width="1"><title>{nome}: {p["registros"]} registros, {p["riqueza"]} espécies</title></circle>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 3:.1f}" fill="none" stroke="{OCRE}" stroke-width="0.6"/>'
            f'<text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="middle" font-size="12" font-weight="600"'
            f' fill="{CARVAO}">{p["riqueza"]}</text>'
            f'<text x="{x + r + 6:.1f}" y="{y + 4:.1f}" font-size="11" fill="{CARVAO}">{nome}</text>')
    km = 111.32 * (lo1 - lo0) * escala_lon
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largura} {altura}" width="100%" '
            f'style="max-width:{largura}px;background:{SUPERFICIE};border:1px solid {LINHA};border-radius:8px">'
            + "".join(elementos)
            + f'<text x="8" y="{altura - 6}" font-size="10" fill="{TEXTO_2}">largura ≈ {km:.1f} km · círculo ∝ registros · '
              f'número = riqueza · sem mapa de fundo (funciona sem internet)</text></svg>')
