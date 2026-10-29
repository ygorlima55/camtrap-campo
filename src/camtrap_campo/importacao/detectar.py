"""Detecção de cartões SD e câmeras montadas como unidade removível (com pasta DCIM). Somente leitura."""

from __future__ import annotations

import datetime as dt
import platform
import shutil
import string
from dataclasses import dataclass, field
from pathlib import Path

from camtrap_campo.config import EXT_FOTO, EXT_VIDEO

DRIVE_REMOVABLE = 2


@dataclass
class Cartao:
    raiz: str
    rotulo: str | None
    total_bytes: int | None
    livre_bytes: int | None
    tem_dcim: bool
    pastas_dcim: list[str] = field(default_factory=list)
    fotos: int = 0
    videos: int = 0
    appledouble: int = 0
    ultima_midia: str | None = None
    ultima_data: str | None = None


def _rotulo(raiz: str) -> str | None:
    if platform.system() != "Windows":
        return None
    import ctypes

    nome = ctypes.create_unicode_buffer(261)
    if ctypes.windll.kernel32.GetVolumeInformationW(raiz, nome, 261, None, None, None, None, 0):
        return nome.value or None
    return None


def unidades_removiveis() -> list[str]:
    if platform.system() != "Windows":
        return []
    import ctypes

    mascara = ctypes.windll.kernel32.GetLogicalDrives()
    raizes = []
    for i, letra in enumerate(string.ascii_uppercase):
        if mascara >> i & 1:
            raiz = f"{letra}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(raiz) == DRIVE_REMOVABLE:
                raizes.append(raiz)
    return raizes


def resumir(raiz: str | Path) -> Cartao:
    raiz = Path(raiz)
    try:
        uso = shutil.disk_usage(raiz)
        total, livre = uso.total, uso.free
    except OSError:
        total = livre = None
    dcim = raiz / "DCIM"
    c = Cartao(str(raiz), _rotulo(str(raiz)), total, livre, dcim.is_dir())
    if not c.tem_dcim:
        return c
    c.pastas_dcim = sorted(p.name for p in dcim.iterdir() if p.is_dir())
    ultima = None
    for p in dcim.rglob("*"):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if p.name.startswith("._"):
            c.appledouble += 1
        elif ext in EXT_FOTO or ext in EXT_VIDEO:
            if ext in EXT_FOTO:
                c.fotos += 1
            else:
                c.videos += 1
            chave = (p.stat().st_mtime, p.name)  # empate de horário: o nome (contador) decide
            if ultima is None or chave > ultima[:2]:
                ultima = (*chave, p)
    if ultima:
        c.ultima_midia = str(ultima[2].relative_to(raiz))
        c.ultima_data = dt.datetime.fromtimestamp(ultima[0]).isoformat(timespec="seconds")
    return c


def detectar_cartoes(extras: list[str] | None = None) -> list[Cartao]:
    """Unidades removíveis com DCIM (e pastas extras, usadas em testes ou cópias já salvas)."""
    vistos = []
    for raiz in unidades_removiveis() + list(extras or []):
        try:
            cartao = resumir(raiz)
        except OSError:
            continue
        if cartao.tem_dcim:
            vistos.append(cartao)
    return vistos
