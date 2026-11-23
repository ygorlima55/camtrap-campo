"""Compara a caracterização de um vestígio com o guia de referência e devolve as espécies mais compatíveis.

Não é IA de imagem: o programa não mede nada na foto. A pessoa informa medidas e características (com a régua ou
outra escala na foto) e cada espécie do guia recebe uma nota de compatibilidade (0–1, média geométrica ponderada das
características informadas). A "porcentagem" mostrada é a participação de cada espécie no total das notas
(elevadas à 4ª potência): diz quão mais compatível uma é em relação às outras do guia, não a probabilidade de acerto.
"""

from __future__ import annotations

import math

from sqlalchemy import select

from camtrap_campo.db import Especie, GuiaVestigio
from camtrap_campo.vestigios import guia_base as gb

TIPOS = {"pegada": "Pegada", "fezes": "Fezes", "sinal": "Outro sinal (arranhado, toca, foçado...)"}
# característica → (rótulo, peso)
CAMPOS = {
    "pegada": {"comprimento": ("comprimento", 2.0), "largura": ("largura", 1.5), "dedos": ("dedos visíveis", 1.5),
               "garras": ("garras", 1.5), "forma": ("forma", 2.0)},
    "fezes": {"diametro": ("diâmetro", 2.0), "forma": ("forma", 1.5), "conteudo": ("conteúdo", 2.0), "local": ("local", 1.0)},
    "sinal": {"sinal": ("tipo de sinal", 3.0), "altura": ("altura", 1.0), "diametro": ("diâmetro", 1.5)},
}
MINIMO_PORCENTAGEM = 1  # não mostra candidatas abaixo de 1%
AJUSTE_FRACO = 0.5  # se nem a melhor passa disso, avisa que nenhuma espécie do guia combina bem
NITIDEZ = 4  # expoente da nota ao dividir as porcentagens: quem se encaixa bem se destaca dos que mal combinam


def semear(sessao) -> int:
    """Insere as referências iniciais que faltarem (não altera as já editadas)."""
    existentes = {(t, n) for t, n in sessao.execute(select(GuiaVestigio.tipo, GuiaVestigio.nome_cientifico))}
    novas = [GuiaVestigio(tipo=t, nome_cientifico=c, nome_popular=p, dados=d, descricao=desc)
             for t, c, p, d, desc in gb.INICIAIS if (t, c) not in existentes]
    sessao.add_all(novas)
    sessao.commit()
    return len(novas)


def _cm(v) -> str:
    return f"{v:g}".replace(".", ",")


def _numero(valor, faixa, unidade="cm") -> tuple[float, str, bool]:
    lo, hi = faixa
    tol = max(0.4, 0.15 * (lo + hi) / 2)
    dist = 0.0 if lo <= valor <= hi else min(abs(valor - lo), abs(valor - hi))
    nota = max(0.02, math.exp(-0.5 * (dist / tol) ** 2))
    return nota, f"{_cm(valor)} {unidade} (guia {_cm(lo)}–{_cm(hi)} {unidade})", dist == 0


def _lista(usuario: list, guia: list, base: float, nomes: dict) -> tuple[float, str, bool]:
    comuns = [u for u in usuario if u in guia]
    nota = base + (1 - base) * len(comuns) / len(usuario)
    faltam = [nomes.get(u, u) for u in usuario if u not in guia]
    texto = ", ".join(nomes.get(u, u) for u in usuario) + (f" (não esperado: {', '.join(faltam)})" if faltam else "")
    return nota, texto, not faltam


def _nota_campo(tipo: str, campo: str, valor, dados: dict) -> tuple[float, str, bool] | None:
    """Nota de 0 a 1 de uma característica; None se o guia não tem a informação (o campo não pesa)."""
    ref = dados.get(campo)
    if ref is None:
        return None
    if campo in ("comprimento", "largura", "diametro", "altura"):
        return _numero(float(valor), ref)
    if campo == "dedos":
        ok = int(valor) in ref
        return (1.0 if ok else 0.1), f"{valor} (guia {'/'.join(map(str, ref))})", ok
    if campo == "garras":
        if ref == "as_vezes":
            return 0.8, f"{gb.GARRAS[valor]} (guia: às vezes)", True
        return (1.0 if ref == valor else 0.15), f"{gb.GARRAS[valor]} (guia: {gb.GARRAS[ref]})", ref == valor
    if campo == "forma":
        refs = ref if isinstance(ref, list) else [ref]
        nomes = gb.FORMAS_FEZES if tipo == "fezes" else gb.FORMAS_PEGADA
        ok = valor in refs
        return (1.0 if ok else 0.05), nomes.get(valor, valor) + ("" if ok else " (guia: outra forma)"), ok
    if campo == "conteudo":
        return _lista(valor, ref, 0.15, gb.CONTEUDOS)
    if campo == "local":
        return _lista(valor, ref, 0.4, gb.LOCAIS)
    if campo == "sinal":
        ok = valor in ref
        return (1.0 if ok else 0.05), gb.SINAIS.get(valor, valor) + ("" if ok else " (não citado no guia)"), ok
    return None


def limpar(tipo: str, bruto: dict) -> dict:
    """Converte o formulário em características válidas (ignora o que veio vazio ou fora das opções)."""
    if tipo not in CAMPOS:
        raise ValueError("Escolha o tipo de vestígio: pegada, fezes ou outro sinal")
    c: dict = {}
    for campo in CAMPOS[tipo]:
        v = bruto.get(campo)
        if v in (None, "", []):
            continue
        if campo in ("comprimento", "largura", "diametro", "altura"):
            n = float(str(v).replace(",", "."))
            if not 0 < n < 1000:
                raise ValueError(f"Medida fora do esperado: {campo} = {v}")
            c[campo] = n
        elif campo == "dedos":
            n = int(v)
            if not 1 <= n <= 5:
                raise ValueError("Dedos visíveis: de 1 a 5")
            c[campo] = n
        elif campo == "garras" and v in gb.GARRAS and v != "as_vezes":
            c[campo] = v
        elif campo == "forma" and v in (gb.FORMAS_FEZES if tipo == "fezes" else gb.FORMAS_PEGADA):
            c[campo] = v
        elif campo in ("conteudo", "local"):
            opcoes = gb.CONTEUDOS if campo == "conteudo" else gb.LOCAIS
            itens = [x for x in (v if isinstance(v, list) else [v]) if x in opcoes]
            if itens:
                c[campo] = itens
        elif campo == "sinal" and v in gb.SINAIS:
            c[campo] = v
    return c


def comparar(sessao, tipo: str, caracteristicas: dict, limite: int = 6) -> list[dict]:
    """Espécies do guia mais compatíveis, com nota (0–1), porcentagem relativa e o porquê de cada característica."""
    if not caracteristicas or tipo not in CAMPOS:
        return []
    refs = sessao.scalars(select(GuiaVestigio).where(GuiaVestigio.tipo == tipo, GuiaVestigio.ativa)).all()
    especies = {e.nome_cientifico: e.id for e in sessao.scalars(select(Especie))}
    candidatas = []
    for g in refs:
        soma_peso = soma_log = 0.0
        motivos = []
        for campo, valor in caracteristicas.items():
            r = _nota_campo(tipo, campo, valor, g.dados or {})
            if r is None:
                continue
            nota, texto, ok = r
            peso = CAMPOS[tipo][campo][1]
            soma_peso += peso
            soma_log += peso * math.log(nota)
            motivos.append({"campo": CAMPOS[tipo][campo][0], "texto": texto, "ok": ok})
        if not soma_peso:
            continue
        candidatas.append({"guia_id": g.id, "nome_cientifico": g.nome_cientifico, "nome_popular": g.nome_popular,
                           "especie_id": especies.get(g.nome_cientifico), "nota": round(math.exp(soma_log / soma_peso), 4),
                           "motivos": motivos, "descricao": g.descricao})
    total = sum(c["nota"] ** NITIDEZ for c in candidatas)
    for c in candidatas:
        c["porcentagem"] = round(100 * c["nota"] ** NITIDEZ / total) if total else 0
    candidatas.sort(key=lambda c: -c["nota"])
    return [c for c in candidatas if c["porcentagem"] >= MINIMO_PORCENTAGEM][:limite]


def ajuste_fraco(sugestoes: list[dict]) -> bool:
    return bool(sugestoes) and sugestoes[0]["nota"] < AJUSTE_FRACO
