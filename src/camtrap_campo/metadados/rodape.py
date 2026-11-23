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

# Tentativas em ordem (fração inferior da imagem, binarizar). Medido em fotos reais (Moultrie, MINI400) e nas
# sintéticas (Bushnell): faixa de 6% ampliada para 90 px lê quase todas; as outras cobrem faixas mais altas.
TENTATIVAS = ((0.06, False), (0.08, True), (0.06, True), (0.08, False), (0.11, True))
ALTURA_OCR = 90  # px: o Tesseract erra muito com letras pequenas ou grandes demais
MESES = {"JAN": 1, "FEB": 2, "FEV": 2, "MAR": 3, "APR": 4, "ABR": 4, "MAY": 5, "MAI": 5, "JUN": 6, "JUL": 7, "AUG": 8,
         "AGO": 8, "SEP": 9, "SET": 9, "OCT": 10, "OUT": 10, "NOV": 11, "DEC": 12, "DEZ": 12}
MARCAS = {"MOULTRIE", "BUSHNELL", "BROWNING", "STEALTH", "REVEAL", "WILDGAME", "SPYPOINT", "RECONYX", "CUDDEBACK", "CAM"}

_RE_DATA = re.compile(r"(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{2,4})")
_RE_HORA = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?")
_RE_DATA_MES = re.compile(r"(?<!\d)(\d{1,2})[\s\-.|]*(" + "|".join(MESES) + r")[\s\-.|]*(\d{4})(?!\d)", re.IGNORECASE)
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
    if m := _RE_DATA_MES.search(texto):  # Moultrie e outras: "04 JAN 2021 02:36AM"
        try:
            data = dt.date(int(m.group(3)), MESES[m.group(2).upper()], int(m.group(1)))
        except ValueError:
            data = None
    elif m := _RE_DATA.search(texto):
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
    resto = _RE_TEMP.sub(" ", _RE_HORA.sub(" ", _RE_DATA.sub(" ", _RE_DATA_MES.sub(" ", texto))))
    ignorar = {"AM", "PM", *MESES, *MARCAS}
    palavras = [p for p in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{1,19}", resto) if p.upper() not in ignorar]
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
        im.load()
        cinza = im.convert("L")
    largura, altura = cinza.size
    melhor, nota_melhor = None, -1.0
    for fracao, binarizar in TENTATIVAS:
        faixa = ImageOps.autocontrast(cinza.crop((0, int(altura * (1 - fracao)), largura, altura)))
        faixa = faixa.resize((max(1, int(faixa.width * ALTURA_OCR / faixa.height)), ALTURA_OCR), Image.LANCZOS)
        if binarizar:
            faixa = faixa.point(lambda v: 255 if v > 160 else 0)
        for imagem in (faixa, ImageOps.invert(faixa)):  # texto claro em fundo escuro ou o contrário
            r = interpretar_texto(pytesseract.image_to_string(imagem, config="--psm 7"), referencia)
            nota = 10 * ("data" in r) + 3 * bool(_RE_HORA.search(r["texto"])) + ("temperatura_c" in r) + len(r["texto"]) / 1000
            if nota > nota_melhor:
                melhor, nota_melhor = r, nota
        if "data" in melhor and "temperatura_c" in melhor:
            break  # já leu o essencial; poupa tempo
    melhor["disponivel"] = True
    return melhor
