"""Cartões SINTÉTICOS para testes e demonstração. Nenhuma imagem real; EXIF e faixa de rodapé desenhados.

Cenários: Bushnell (DCIM/100EK113, nomes MMDD+contador, faixa no rodapé), genérica (DSCF), relógio resetado,
foto + '._' de Mac, '._' de Mac SEM a foto (perdida), arquivo oculto, vídeo AVI.
"""

from __future__ import annotations

import datetime as dt
import struct
from io import BytesIO
from pathlib import Path

from PIL import ExifTags, Image, ImageDraw, ImageFont


def foto(data: dt.datetime | None, make: str = "SINTETICA", model: str = "TESTE", software: str = "0000",
         rodape: str | None = None, tamanho=(640, 360)) -> bytes:
    im = Image.new("RGB", tamanho, (70, 90, 60))
    d = ImageDraw.Draw(im)
    d.ellipse((260, 120, 380, 220), fill=(140, 110, 80))  # "animal" desenhado: não é usado para IA
    if rodape:
        altura = int(tamanho[1] * 0.08)
        d.rectangle((0, tamanho[1] - altura, tamanho[0], tamanho[1]), fill=(0, 0, 0))
        try:
            fonte = ImageFont.truetype("arial.ttf", int(altura * 0.7))
        except OSError:
            fonte = ImageFont.load_default()
        d.text((8, tamanho[1] - altura + 2), rodape, fill=(255, 255, 255), font=fonte)
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = make
    exif[ExifTags.Base.Model] = model
    exif[ExifTags.Base.Software] = software
    if data:
        texto = data.strftime("%Y:%m:%d %H:%M:%S")
        exif[ExifTags.Base.DateTime] = texto
        exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = texto
    buf = BytesIO()
    im.save(buf, "JPEG", exif=exif.tobytes(), quality=80)
    return buf.getvalue()


def avi(quadros: int = 300, us: int = 33333) -> bytes:
    avih = b"avih" + struct.pack("<I", 56) + struct.pack("<10I", us, 0, 0, 0, quadros, 0, 1, 0, 1920, 1080) + b"\x00" * 16
    hdrl = b"LIST" + struct.pack("<I", 4 + len(avih)) + b"hdrl" + avih
    movi = b"LIST" + struct.pack("<I", 4 + 8 + 16) + b"movi" + b"00dc" + struct.pack("<I", 16) + b"\x10" * 16
    idx = b"idx1" + struct.pack("<I", 16) + b"00dc" + struct.pack("<III", 0x10, 4, 16)
    corpo = b"AVI " + hdrl + movi + idx
    return b"RIFF" + struct.pack("<I", len(corpo)) + corpo


def _rodape_bushnell(d: dt.datetime, nome: str) -> str:
    return f"{d:%m/%d/%Y} {d:%I:%M %p}  25C  {nome}"


def cartao_bushnell(raiz: Path, inicio=dt.datetime(2026, 10, 20, 5, 42, 10), nome_camera="P7") -> Path:
    pasta = Path(raiz) / "DCIM" / "100EK113"
    pasta.mkdir(parents=True, exist_ok=True)
    for n, horas in enumerate((0, 0.01, 30, 30.02, 100), start=7):  # há uma lacuna longa (30 h → 100 h)
        d = inicio + dt.timedelta(hours=horas)
        nome = f"{d:%m%d}{n:04d}.JPG"
        (pasta / nome).write_bytes(foto(d, "Bushnell", "119837", "BS598BWNx05232", _rodape_bushnell(d, nome_camera)))
    d = inicio + dt.timedelta(hours=101)
    (pasta / f"{d:%m%d}0012.AVI").write_bytes(avi())
    return Path(raiz)


def cartao_problemas(raiz: Path) -> Path:
    """Genérica (DSCF) com relógio resetado, '._' de Mac com e sem a foto e arquivo oculto."""
    pasta = Path(raiz) / "DCIM" / "100MEDIA"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "DSCF0001.JPG").write_bytes(foto(dt.datetime(2000, 1, 1, 0, 0, 12), software="MINI400 24466"))
    (pasta / "DSCF0002.JPG").write_bytes(foto(dt.datetime(2000, 1, 1, 0, 1, 40), software="MINI400 24466"))
    (pasta / "._DSCF0002.JPG").write_bytes(b"\x00\x05\x16\x07" + b"\x00" * 4092)  # Mac com a foto presente
    (pasta / "._DSCF0003.JPG").write_bytes(b"\x00\x05\x16\x07" + b"\x00" * 4092)  # foto PERDIDA
    (Path(raiz) / "SDFS_CFG.BIN").write_bytes(b"\x00" * 16 + b"\x09" + b"\x00" * 495)
    return Path(raiz)
