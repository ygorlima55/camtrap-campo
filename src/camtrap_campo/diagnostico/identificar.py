"""Ao conectar: modelo provável, câmera provável, última foto e quantas mídias são novas. Somente leitura.

Rápido de propósito (sem hash): "já importada" = mesmo caminho no cartão e mesmo tamanho de um arquivo copiado antes.
A câmera provável é a que mais teve arquivos iguais importados — é uma pista, não uma prova.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from camtrap_campo.db import Arquivo, Camera, Importacao
from camtrap_campo.importacao.copiar import listar_cartao, tipo_de
from camtrap_campo.importacao.padroes import detectar_padrao, sugerir_modelo
from camtrap_campo.metadados.exif import ler_exif


@dataclass
class Identificacao:
    raiz: str
    padrao: str | None = None
    modelo: str | None = None
    exif_ultima: dict = field(default_factory=dict)
    camera_provavel: str | None = None
    votos_camera: dict = field(default_factory=dict)
    total_midias: int = 0
    novas: int = 0
    ja_importadas: int = 0
    appledouble_orfaos: int = 0
    ultima_midia: str | None = None
    ultima_data: str | None = None  # data interna (EXIF) quando houver; senão data do arquivo
    fonte_ultima_data: str | None = None
    dias_desde_ultima: int | None = None


def identificar(sessao, raiz: str | Path, hoje: dt.datetime | None = None) -> Identificacao:
    raiz = Path(raiz)
    hoje = hoje or dt.datetime.now()
    ident = Identificacao(str(raiz))
    arquivos = listar_cartao(raiz)
    midias = [p for p in arquivos if tipo_de(p) in ("foto", "video")]
    nomes = {p.relative_to(raiz).as_posix().lower() for p in arquivos}
    ident.appledouble_orfaos = sum(
        1 for p in arquivos if p.name.startswith("._")
        and (p.parent / p.name[2:]).relative_to(raiz).as_posix().lower() not in nomes)
    ident.total_midias = len(midias)
    ident.padrao = detectar_padrao([p.stem for p in midias]).get("descricao")
    dcim = raiz / "DCIM"  # pastas da câmera contam mesmo vazias (ex.: só restaram arquivos '._' de Mac)
    pastas = sorted(p.name for p in dcim.iterdir() if p.is_dir()) if dcim.is_dir() else []

    vistos = {(a, t): cam for a, t, cam in sessao.execute(
        select(Arquivo.caminho_cartao, Arquivo.tamanho, Camera.etiqueta)
        .join(Importacao, Arquivo.importacao_id == Importacao.id).join(Camera, Importacao.camera_id == Camera.id)
        .where(Arquivo.estado.in_(("copiado", "duplicado"))))}
    votos = Counter()
    for p in midias:
        chave = (p.relative_to(raiz).as_posix(), p.stat().st_size)
        if chave in vistos:
            ident.ja_importadas += 1
            votos[vistos[chave]] += 1
    ident.novas = ident.total_midias - ident.ja_importadas
    ident.votos_camera = dict(votos)
    if votos:
        ident.camera_provavel = votos.most_common(1)[0][0]

    if midias:
        ultima = max(midias, key=lambda p: (p.stat().st_mtime, p.name))
        ident.ultima_midia = ultima.relative_to(raiz).as_posix()
        data = None
        if tipo_de(ultima) == "foto":
            ident.exif_ultima = ler_exif(ultima)
            if ident.exif_ultima.get("data"):
                data, ident.fonte_ultima_data = dt.datetime.fromisoformat(ident.exif_ultima["data"]), "exif"
        if data is None:
            data, ident.fonte_ultima_data = dt.datetime.fromtimestamp(ultima.stat().st_mtime), "arquivo"
        ident.ultima_data = data.isoformat(timespec="seconds")
        ident.dias_desde_ultima = (hoje.date() - data.date()).days
    ident.modelo = sugerir_modelo(pastas, ident.exif_ultima or None)
    return ident
