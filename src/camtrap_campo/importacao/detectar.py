"""Detecção de cartões SD e câmeras montadas como unidade removível (com pasta DCIM) e resumo de pastas
comuns escolhidas pelo usuário (cópias de cartões, registros de teste). Somente leitura."""

from __future__ import annotations

import datetime as dt
import os
import platform
import shutil
import string
import time
from dataclasses import dataclass, field
from pathlib import Path

from camtrap_campo.config import EXT_FOTO, EXT_VIDEO

DRIVE_REMOVABLE = 2
PASTAS_DE_SISTEMA = {"system volume information", "$recycle.bin", ".spotlight-v100", ".fseventsd", ".trashes"}
CACHE_PASTAS_S = 30  # pastas grandes não são relidas a cada atualização do painel
_cache: dict[str, tuple[float, Cartao]] = {}


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
    tipo: str = "cartao"  # cartao | pasta

    @property
    def nome(self) -> str:
        return Path(self.raiz).name or self.raiz


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
    if c.tem_dcim:
        c.pastas_dcim = sorted(p.name for p in dcim.iterdir() if p.is_dir())
    else:  # pasta comum: conta tudo o que está dentro, como a importação fará
        c.tipo = "pasta"
    base = dcim if c.tem_dcim else raiz
    ultima = None
    for pasta, subpastas, nomes in os.walk(base):
        subpastas[:] = [d for d in subpastas if d.lower() not in PASTAS_DE_SISTEMA]
        for nome in nomes:
            p = Path(pasta) / nome
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
            if (Path(raiz) / "DCIM").is_dir():  # pen drive sem DCIM não é varrido inteiro a cada atualização
                vistos.append(resumir(raiz))
        except OSError:
            continue
    return vistos


def resumir_pastas(caminhos: list[str]) -> list[Cartao]:
    """Resumo das pastas escolhidas pelo usuário (com cache curto); pastas que sumiram ficam de fora."""
    agora = time.monotonic()
    resumos = []
    for caminho in caminhos:
        guardado = _cache.get(caminho)
        if guardado and agora - guardado[0] < CACHE_PASTAS_S:
            resumos.append(guardado[1])
            continue
        try:
            if not Path(caminho).is_dir():
                continue
            c = resumir(caminho)
        except OSError:
            continue
        c.tipo = "pasta"
        _cache[caminho] = (agora, c)
        resumos.append(c)
    return resumos
