"""Faixa impressa no rodapé das fotos (data, hora, temperatura, nome da câmera) lida por OCR (Tesseract).

A fase da lua costuma ser um ÍCONE: o OCR não a lê, e o resultado diz isso em vez de inventar.
Datas ambíguas (10/11/2025 = 10 nov ou 11 out?) são resolvidas pela data do EXIF quando houver.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from PIL import Image, ImageOps

from camtrap_campo.config import localizar_ferramenta

ALTURA_FAIXA = 0.08  # fração inferior da imagem

_RE_DATA = re.compile(r"(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{2,4})")
_RE_HORA = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?")
_RE_TEMP = re.compile(r"(-?\d{1,3})\s*[°ºo*]?\s*([CF])\b")


def _candidatas(a: int, b: int, c: int) -> list[dt.date]:
    datas = []
    if a > 31:  # AAAA-MM-DD
        tentativas = [(a, b, c)]
    else:
        ano = c + 2000 if c < 100 else c
        tentativas = [(ano, b, a), (ano, a, b)]  # DD/MM/AAAA e MM/DD/AAAA
    for ano, mes, dia in tentativas:
        try:
            d = dt.date(ano, mes, dia)
            if d not in datas:
                datas.append(d)
        except ValueError:
            continue
    return datas


def interpretar_texto(texto: str, referencia: dt.datetime | None = None) -> dict:
    """Extrai campos da faixa a partir do texto do OCR."""
    resultado: dict = {"texto": texto.strip(), "fase_lua": "ícone (não lido pelo OCR)"}
    hora = None
    if m := _RE_HORA.search(texto):
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        if m.group(4):
            h = h % 12 + (12 if m.group(4).lower() == "pm" else 0)
        if h < 24 and mi < 60 and s < 60:
            hora = dt.time(h, mi, s)
    data = None
    if m := _RE_DATA.search(texto):
        candidatas = _candidatas(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if len(candidatas) > 1:
            resultado["data_ambigua"] = [d.isoformat() for d in candidatas]
            if referencia:
                candidatas.sort(key=lambda d: abs((d - referencia.date()).days))
        data = candidatas[0] if candidatas else None
    if data and hora:
        resultado["data"] = dt.datetime.combine(data, hora).isoformat()
    if m := _RE_TEMP.search(texto):
        valor, escala = int(m.group(1)), m.group(2).upper()
        resultado["temperatura_c"] = round((valor - 32) * 5 / 9, 1) if escala == "F" else float(valor)
        resultado["temperatura_original"] = f"{valor}{escala}"
    resto = _RE_TEMP.sub(" ", _RE_HORA.sub(" ", _RE_DATA.sub(" ", texto)))
    palavras = [p for p in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{1,19}", resto) if p.upper() not in {"AM", "PM"}]
    if palavras:
        resultado["nome_camera"] = palavras[-1]  # heurística: Bushnell imprime o nome no fim da faixa
    return resultado


def ler_rodape(caminho: Path, referencia: dt.datetime | None = None) -> dict:
    exe = localizar_ferramenta("tesseract")
    if not exe:
        return {"disponivel": False, "motivo": "Tesseract não instalado"}
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = exe
    with Image.open(caminho) as im:
        largura, altura = im.size
        faixa = im.crop((0, int(altura * (1 - ALTURA_FAIXA)), largura, altura)).convert("L")
    faixa = ImageOps.autocontrast(faixa)
    if faixa.height < 60:
        fator = 60 / faixa.height
        faixa = faixa.resize((int(faixa.width * fator), 60))
    textos = []
    for imagem in (faixa, ImageOps.invert(faixa)):  # texto claro em fundo escuro ou o contrário
        textos.append(pytesseract.image_to_string(imagem, config="--psm 7"))
    melhor = max(textos, key=lambda t: len(_RE_DATA.findall(t)) * 3 + len(_RE_HORA.findall(t)) * 2 + len(t.strip()) / 100)
    resultado = interpretar_texto(melhor, referencia)
    resultado["disponivel"] = True
    return resultado
