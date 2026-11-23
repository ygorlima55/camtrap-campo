"""Monta o pacote de instalação (zip) a partir do que está commitado no Git.

Uso (na pasta do projeto):  uv run --no-sync python scripts/montar_instalador.py
Saída: dist/CamTrap-Campo-<versão>-instalador.zip

Só entra o que está no commit atual (git archive): nada de Dados/, banco, prévias ou arquivos locais.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PROGRAMA = ["src", "pyproject.toml", "uv.lock", "README.md"]
BOM = b"\xef\xbb\xbf"


def main() -> Path:
    versao = tomllib.loads((RAIZ / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    sujos = subprocess.run(["git", "status", "--porcelain", "--", *PROGRAMA, "instalador"], cwd=RAIZ,
                           capture_output=True, text=True, check=True).stdout.strip()
    if sujos:
        raise SystemExit(f"Há mudanças não commitadas que ficariam fora do pacote:\n{sujos}")
    base = f"CamTrap-Campo-{versao}"
    destino = RAIZ / "dist" / f"{base}-instalador.zip"
    destino.parent.mkdir(exist_ok=True)
    tar = subprocess.run(["git", "archive", "--format=tar", "HEAD", "--", *PROGRAMA, "instalador"], cwd=RAIZ,
                         capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t, zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for membro in t.getmembers():
            if not membro.isfile() or "__pycache__" in membro.name:
                continue
            dados = t.extractfile(membro).read()
            nome = membro.name
            if nome.startswith("instalador/"):
                arquivo = nome.removeprefix("instalador/")
                if arquivo in ("Instalar CamTrap Campo.cmd", "LEIA-ME.txt"):
                    nome = arquivo  # na raiz do zip, à vista
                if nome.endswith(".cmd"):
                    dados = dados.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")  # cmd.exe quer CRLF
                if nome.endswith(".ps1") and not dados.startswith(BOM):
                    dados = BOM + dados  # PowerShell 5.1 só lê acentos em UTF-8 com BOM
            else:
                nome = f"programa/{nome}"
            z.writestr(f"{base}/{nome}", dados)
    print(f"{destino}  ({destino.stat().st_size / 1024:.0f} KB)")
    return destino


if __name__ == "__main__":
    main()
