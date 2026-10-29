"""Detecta o padrão de nomes da câmera a partir dos próprios arquivos (não supõe o modelo).

Exemplos observados: Bushnell E3 "10200007.JPG" (MMDD + contador), genéricas "DSCF0001.JPG",
Moultrie "MFDC0001.JPG", outras "IMAG0001", "PICT0001", "SUNP0001".
"""

from __future__ import annotations

import re
from collections import Counter

_MMDD = re.compile(r"^(?P<mm>0[1-9]|1[0-2])(?P<dd>0[1-9]|[12]\d|3[01])(?P<n>\d{4})$")
_PREFIXO = re.compile(r"^(?P<prefixo>[A-Za-z_]{2,6})(?P<n>\d{3,6})$")
_SO_NUMERO = re.compile(r"^(?P<n>\d{3,8})$")


def classificar(nome_sem_ext: str) -> tuple[str, int | None, str | None]:
    """(padrão, contador, prefixo) de um nome sem extensão."""
    if m := _MMDD.match(nome_sem_ext):
        return "MMDD+contador", int(m.group("n")), None
    if m := _PREFIXO.match(nome_sem_ext):
        return "prefixo+contador", int(m.group("n")), m.group("prefixo").upper()
    if m := _SO_NUMERO.match(nome_sem_ext):
        return "numerico", int(m.group("n")), None
    return "desconhecido", None, None


def detectar_padrao(nomes: list[str]) -> dict:
    """Padrão predominante entre os nomes de mídia (sem extensão)."""
    padroes, prefixos = Counter(), Counter()
    for nome in nomes:
        padrao, _, prefixo = classificar(nome)
        padroes[padrao] += 1
        if prefixo:
            prefixos[prefixo] += 1
    if not padroes:
        return {"padrao": None, "descricao": "sem arquivos de mídia"}
    padrao, n = padroes.most_common(1)[0]
    descricao = padrao
    if padrao == "prefixo+contador" and prefixos:
        descricao = f"{prefixos.most_common(1)[0][0]}NNNN"
    elif padrao == "MMDD+contador":
        descricao = "MMDDNNNN (mês, dia, contador — padrão Bushnell)"
    return {"padrao": padrao, "descricao": descricao, "proporcao": round(n / sum(padroes.values()), 3),
            "contagem": dict(padroes), "prefixos": dict(prefixos)}


def sugerir_modelo(pastas_dcim: list[str], exif: dict | None) -> str | None:
    """Pista de modelo pelos arquivos. Só afirma o que o EXIF declara; o resto é marcado como provável."""
    exif = exif or {}
    partes = [str(exif.get(k)).strip() for k in ("Make", "Model") if exif.get(k)]
    if partes:
        return " ".join(partes) + (f" (firmware {exif['Software']})" if exif.get("Software") else "")
    if exif.get("Software"):
        return f"firmware declarado: {exif['Software']}"
    if any(p.upper().endswith("EK113") for p in pastas_dcim):
        return "provável Bushnell (pasta 100EK113)"
    return None
