"""CSS embutido nos relatórios autônomos (estilo base + identidade visual v2)."""

from pathlib import Path

AQUI = Path(__file__).parent


def css_relatorio() -> str:
    return "\n".join((AQUI / "static" / n).read_text("utf-8") for n in ("estilo.css", "identidade.css"))
