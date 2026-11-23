"""Monta as sequências a revisar (só as com detecção acima do limiar) e grava a identificação confirmada."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select

from camtrap_campo.db import Arquivo, Configuracao, Deteccao, Especie, Inferencia, Revisao, agora
from camtrap_campo.ia import especies as lista_especies
from camtrap_campo.ia.sequencias import agrupar

LIMIAR_PADRAO = 0.2  # recomendação usual para MegaDetector v5
RESULTADOS = ("especie", "vazio", "pessoa", "veiculo", "indeterminado")


def limiar(sessao) -> float:
    c = sessao.get(Configuracao, "limiar_deteccao")
    return float(c.valor) if c else LIMIAR_PADRAO


def definir_limiar(sessao, valor: float) -> None:
    if not 0 < valor < 1:
        raise ValueError("o limiar deve estar entre 0 e 1")
    c = sessao.get(Configuracao, "limiar_deteccao") or Configuracao(chave="limiar_deteccao")
    c.valor = valor
    sessao.merge(c)
    sessao.commit()


def montar(sessao, importacao_id: int, somente_pendentes: bool = False) -> dict:
    corte = limiar(sessao)
    arquivos = list(sessao.scalars(select(Arquivo).where(
        Arquivo.importacao_id == importacao_id, Arquivo.estado == "copiado", Arquivo.tipo.in_(("foto", "video")))))
    ids = [a.id for a in arquivos]
    dets: dict[int, list[Deteccao]] = {}
    for d in sessao.scalars(select(Deteccao).where(Deteccao.arquivo_id.in_(ids), Deteccao.confianca >= corte)):
        dets.setdefault(d.arquivo_id, []).append(d)
    infs = {i.arquivo_id: i for i in sessao.scalars(select(Inferencia).where(Inferencia.arquivo_id.in_(ids),
                                                                              Inferencia.etapa == "ia"))}
    revisoes = {r.chave_sequencia: r for r in sessao.scalars(select(Revisao).where(Revisao.importacao_id == importacao_id))}
    especies = {e.nome_cientifico.lower(): e for e in sessao.scalars(select(Especie))}

    sequencias, vazias, nao_analisadas, simulado = [], 0, 0, False
    for grupo in agrupar(arquivos):
        if any(a.id not in infs for a in grupo):
            nao_analisadas += 1
            continue
        com_det = [a for a in grupo if a.id in dets]
        if not com_det:
            vazias += 1
            continue
        sugestoes = [infs[a.id].classificacao for a in grupo if infs[a.id].classificacao]
        sugestao = max(sugestoes, key=lambda c: c.get("confianca", 0)) if sugestoes else None
        especie_sugerida = None
        if sugestao and sugestao.get("nome_cientifico"):
            especie_sugerida = lista_especies.procurar(especies, sugestao["nome_cientifico"])
        categorias = Counter(d.categoria for a in com_det for d in dets[a.id])
        simulado = simulado or any(infs[a.id].simulado for a in grupo)
        chave = grupo[0].id
        rev = revisoes.get(chave)
        if somente_pendentes and rev:
            continue
        sequencias.append({
            "chave": chave, "arquivos": grupo, "deteccoes": {a.id: dets[a.id] for a in com_det},
            "inicio": grupo[0].data, "fim": grupo[-1].data, "categorias": dict(categorias),
            "max_individuos": max(sum(1 for d in dets[a.id] if d.categoria == "animal") for a in com_det),
            "sugestao": sugestao, "especie_sugerida": especie_sugerida, "revisao": rev,
        })
    return {"sequencias": sequencias, "vazias": vazias, "nao_analisadas": nao_analisadas, "limiar": corte,
            "simulado": simulado, "revisadas": sum(1 for s in sequencias if s["revisao"])}


def salvar(sessao, importacao_id: int, chave: int, arquivos: list[int], resultado: str, especie_id: int | None = None,
           quantidade: int | None = None, comportamento: str | None = None, divulgacao: bool = False,
           observacao: str | None = None, sugestao: dict | None = None) -> Revisao:
    if resultado not in RESULTADOS:
        raise ValueError("resultado inválido")
    if resultado == "especie" and not (especie_id and sessao.get(Especie, especie_id)):
        raise ValueError("escolha a espécie")
    if quantidade is not None and quantidade < 0:
        raise ValueError("quantidade inválida")
    rev = sessao.scalar(select(Revisao).where(Revisao.importacao_id == importacao_id, Revisao.chave_sequencia == chave))
    rev = rev or Revisao(importacao_id=importacao_id, chave_sequencia=chave)
    rev.arquivos, rev.resultado = arquivos, resultado
    rev.especie_id = especie_id if resultado == "especie" else None
    rev.quantidade = quantidade if resultado == "especie" else None
    rev.comportamento, rev.divulgacao, rev.observacao = comportamento or None, divulgacao, observacao or None
    rev.sugestao_ia, rev.revisado_em = sugestao, agora()
    sessao.add(rev)
    sessao.commit()
    return rev
