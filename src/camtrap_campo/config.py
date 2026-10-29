"""Caminhos e parâmetros do programa. Tudo pode ser trocado por variável de ambiente (usado nos testes)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

RAIZ = Path(os.environ.get("CAMTRAP_CAMPO_RAIZ", Path(__file__).resolve().parents[2]))
FUSO = os.environ.get("CAMTRAP_FUSO", "America/Sao_Paulo")

# Alertas
INTERVALO_SEM_FOTOS_H = 48  # buraco entre registros que merece atenção
ANO_MINIMO_VALIDO = 2012  # datas anteriores = relógio resetado (Bushnell volta para 2000/2010)
DIVERGENCIA_RODAPE_MIN = 2  # diferença EXIF × rodapé (minutos) que gera alerta

EXT_FOTO = {".jpg", ".jpeg"}
EXT_VIDEO = {".avi", ".mp4", ".mov", ".3gp"}


def pasta_dados() -> Path:
    return Path(os.environ.get("CAMTRAP_DADOS", RAIZ / "Dados"))


def caminho_banco() -> Path:
    return Path(os.environ.get("CAMTRAP_BANCO", RAIZ / "camtrap.sqlite3"))


def pasta_ferramentas() -> Path:
    return RAIZ / "ferramentas"


def localizar_ferramenta(nome: str) -> str | None:
    """Procura um executável em ferramentas/ (instalado pelo install.bat) e depois no PATH."""
    base = pasta_ferramentas()
    if base.is_dir():
        for candidato in base.rglob(f"{nome}.exe"):
            return str(candidato)
        for candidato in base.rglob(nome):
            if candidato.is_file():
                return str(candidato)
    if encontrado := shutil.which(nome):
        return encontrado
    for pasta in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("LOCALAPPDATA", "")):
        if pasta:  # instaladores comuns (ex.: Tesseract UB Mannheim) nem sempre põem no PATH
            for sub in ("Tesseract-OCR", "ExifTool", "ffmpeg\\bin", "Programs\\Tesseract-OCR"):
                candidato = Path(pasta) / sub / f"{nome}.exe"
                if candidato.is_file():
                    return str(candidato)
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget.is_dir():  # winget põe no PATH, mas janelas abertas antes da instalação ainda não enxergam
        for candidato in sorted(winget.glob(f"*/*/bin/{nome}.exe")) + sorted(winget.glob(f"*/{nome}.exe")):
            return str(candidato)
    return None
