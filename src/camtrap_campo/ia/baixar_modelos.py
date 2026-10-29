"""Baixa (uma vez) e testa os modelos da IA: carrega o SpeciesNet e roda numa imagem sintética.

Uso: ``uv run --group ia python -m camtrap_campo.ia.baixar_modelos``
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from camtrap_campo import amostras
from camtrap_campo.ia.motor import MotorIndisponivel, MotorSpeciesNet, dispositivo


def main() -> int:
    inicio = time.time()
    try:
        motor = MotorSpeciesNet()
    except MotorIndisponivel as exc:
        print(f"ERRO: {exc}")
        return 1
    print(f"Modelo carregado: {motor.nome} | processador: {dispositivo()} | {time.time() - inicio:.0f} s")
    with tempfile.TemporaryDirectory() as tmp:
        teste = Path(tmp) / "teste.jpg"
        teste.write_bytes(amostras.foto(None, tamanho=(1280, 720)))
        t0 = time.time()
        r = motor.analisar([teste])[0]
    print(f"Teste numa imagem sintética: {len(r.deteccoes)} detecção(ões) em {time.time() - t0:.1f} s"
          f"{' — erro: ' + r.erro if r.erro else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
