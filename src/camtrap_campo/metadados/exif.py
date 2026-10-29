"""EXIF via ExifTool (quando instalado) ou Pillow (sempre disponível)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from PIL import ExifTags, Image

from camtrap_campo.config import localizar_ferramenta

CAMPOS = ("Make", "Model", "Software", "DateTimeOriginal", "CreateDate", "ModifyDate", "ImageDescription",
          "ExposureTime", "ISO", "Flash", "ImageWidth", "ImageHeight", "SerialNumber", "AmbientTemperature")


def interpretar_data(texto: str | None) -> dt.datetime | None:
    if not texto:
        return None
    texto = str(texto).strip("\x00 ")
    for formato in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M"):
        try:
            return dt.datetime.strptime(texto[:19], formato)
        except ValueError:
            continue
    return None


def _limpo(v):
    if isinstance(v, bytes):
        return None
    if isinstance(v, str):
        return v.strip("\x00 ") or None
    try:
        return float(v) if not isinstance(v, int) else v
    except (TypeError, ValueError):
        return str(v)


def _pillow(caminho: Path) -> dict:
    with Image.open(caminho) as im:
        ex = im.getexif()
        sub = ex.get_ifd(ExifTags.IFD.Exif)
        dados = {"fonte": "pillow", "ImageWidth": im.size[0], "ImageHeight": im.size[1]}
    for tag, valor in list(ex.items()) + list(sub.items()):
        nome = ExifTags.TAGS.get(tag)
        if nome in ("Make", "Model", "Software", "DateTimeOriginal", "ImageDescription", "ExposureTime", "Flash"):
            dados[nome] = _limpo(valor)
        elif nome == "DateTime":
            dados["ModifyDate"] = _limpo(valor)
        elif nome == "DateTimeDigitized":
            dados["CreateDate"] = _limpo(valor)
        elif nome == "ISOSpeedRatings":
            dados["ISO"] = _limpo(valor)
    return dados


def _exiftool(caminho: Path, exe: str) -> dict:
    import exiftool

    with exiftool.ExifToolHelper(executable=exe) as et:
        bruto = et.get_metadata(str(caminho))[0]
    dados = {"fonte": "exiftool"}
    for chave, valor in bruto.items():
        nome = chave.split(":")[-1]
        if nome in CAMPOS and nome not in dados:
            dados[nome] = _limpo(valor)
    return dados


def ler_exif(caminho: Path) -> dict:
    """Devolve campos EXIF úteis e 'data' (datetime) quando houver data de captura."""
    exe = localizar_ferramenta("exiftool")
    try:
        dados = _exiftool(caminho, exe) if exe else _pillow(caminho)
    except Exception as exc:  # noqa: BLE001 — EXIF ilegível não pode parar a importação
        try:
            dados = _pillow(caminho)
            dados["aviso"] = f"ExifTool falhou ({exc}); lido com Pillow"
        except Exception as exc2:  # noqa: BLE001
            return {"fonte": None, "erro": str(exc2)}
    data = interpretar_data(dados.get("DateTimeOriginal") or dados.get("CreateDate") or dados.get("ModifyDate"))
    dados["data"] = data.isoformat() if data else None
    return dados
