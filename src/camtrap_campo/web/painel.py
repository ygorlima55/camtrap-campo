"""Números do painel inicial: só contagens no banco (rápidas), mais o "próximo passo" sugerido ao usuário."""

from __future__ import annotations

import datetime as dt
from urllib.parse import quote

from sqlalchemy import distinct, func, select

from camtrap_campo.db import Arquivo, Camera, Campanha, Especie, Importacao, Inferencia, Ponto, Revisao, Tarefa
from camtrap_campo.ia import revisao

ATIVAS = ("pendente", "executando", "pausada")


def _contar(s, consulta) -> int:
    return s.scalar(consulta) or 0


def midias_por_dia(s, dias: int = 30) -> list[tuple[dt.date, int]]:
    """Mídias por dia nos ``dias`` que terminam na data mais recente com registro (dados de campo são antigos)."""
    dia = func.date(Arquivo.data_original)
    linhas = dict(s.execute(select(dia, func.count()).where(Arquivo.estado == "copiado", Arquivo.tipo.in_(("foto", "video")),
                                                            Arquivo.data_original.is_not(None)).group_by(dia)).all())
    if not linhas:
        return []
    fim = max(dt.date.fromisoformat(d) for d in linhas)
    return [(d, linhas.get(d.isoformat(), 0)) for d in (fim - dt.timedelta(days=i) for i in range(dias - 1, -1, -1))]


def resumo(s, cartoes: list, pastas: list = ()) -> dict:
    midia = (Arquivo.estado == "copiado") & Arquivo.tipo.in_(("foto", "video"))
    fotos = _contar(s, select(func.count()).where(midia, Arquivo.tipo == "foto"))
    videos = _contar(s, select(func.count()).where(midia, Arquivo.tipo == "video"))
    analisadas = _contar(s, select(func.count(distinct(Inferencia.arquivo_id))).join(Arquivo, Arquivo.id == Inferencia.arquivo_id)
                         .where(midia, Inferencia.etapa == "ia", Inferencia.erro.is_(None)))
    confirmadas = _contar(s, select(func.count()).where(Revisao.resultado == "especie"))
    n_especies = _contar(s, select(func.count(distinct(Revisao.especie_id))).where(Revisao.resultado == "especie"))
    ranking = s.execute(select(Especie.nome_popular, Especie.nome_cientifico, func.count().label("n"))
                        .join(Revisao, Revisao.especie_id == Especie.id).where(Revisao.resultado == "especie")
                        .group_by(Especie.id).order_by(func.count().desc()).limit(6)).all()
    tarefas = s.scalars(select(Tarefa).where(Tarefa.estado.in_(ATIVAS)).order_by(Tarefa.id)).all()
    recentes = s.scalars(select(Importacao).order_by(Importacao.id.desc()).limit(6)).all()
    for imp in recentes:
        _ = imp.camera, imp.ponto, imp.campanha

    # importações que já passaram pela IA mas ainda têm sequências por revisar (só as recentes, para ser rápido)
    com_ia = set(s.scalars(select(Tarefa.importacao_id).where(Tarefa.tipo == "ia")))
    a_revisar = []
    for imp in s.scalars(select(Importacao).where(Importacao.id.in_(com_ia)).order_by(Importacao.id.desc()).limit(10)):
        pend = len(revisao.montar(s, imp.id, somente_pendentes=True)["sequencias"])
        if pend:
            a_revisar.append((imp, pend))
    sem_ia = [i for i in recentes if i.id not in com_ia and i.estado != "em_andamento" and i.copiados]
    origens = set(s.scalars(select(Importacao.origem)))
    pastas_novas = [p for p in pastas if (p.fotos or p.videos) and p.raiz not in origens]

    total = fotos + videos
    return {
        "fotos": fotos, "videos": videos, "midias": total, "analisadas": analisadas,
        "pct_analisadas": round(100 * analisadas / total) if total else 0,
        "confirmadas": confirmadas, "n_especies": n_especies, "ranking": ranking,
        "cameras": _contar(s, select(func.count(Camera.id))), "pontos": _contar(s, select(func.count(Ponto.id))),
        "campanhas": _contar(s, select(func.count(Campanha.id))),
        "tarefas": tarefas, "recentes": recentes, "a_revisar": a_revisar, "sem_ia": sem_ia,
        "por_dia": midias_por_dia(s),
        "proximo": proximo_passo(cartoes, tarefas, sem_ia, a_revisar, confirmadas, pastas_novas),
    }


def proximo_passo(cartoes, tarefas, sem_ia, a_revisar, confirmadas, pastas_novas=()) -> dict:
    """A ação mais útil agora, na ordem do fluxo: cartão (ou pasta nova) → IA → revisão → análises."""
    if cartoes:
        c = cartoes[0]
        return {"icone": "cartao", "titulo": "Cartão conectado", "texto": f"{c.raiz} tem {c.fotos} fotos e {c.videos} vídeos.",
                "botao": "Importar este cartão", "href": f"/importar?origem={quote(str(c.raiz))}"}
    if pastas_novas:
        p = pastas_novas[0]
        return {"icone": "cadastros", "titulo": f"Pasta “{p.nome}” pronta para importar",
                "texto": f"{p.fotos} fotos e {p.videos} vídeos ainda não importados.",
                "botao": "Importar esta pasta", "href": f"/importar?origem={quote(str(p.raiz))}"}
    if any(t.estado == "executando" for t in tarefas):
        return {"icone": "ia", "titulo": "A IA está trabalhando",
                "texto": "Você pode revisar o que já foi analisado enquanto isso.", "botao": "Ver tarefas", "href": "/tarefas"}
    if a_revisar:
        imp, n = a_revisar[0]
        return {"icone": "revisar", "titulo": f"{n} sequência(s) esperando revisão",
                "texto": f"{imp.campanha.nome} · {imp.ponto.nome} · câmera {imp.camera.etiqueta}",
                "botao": "Revisar agora", "href": f"/revisao/{imp.id}?pendentes=1"}
    if sem_ia:
        imp = sem_ia[0]
        return {"icone": "ia", "titulo": "Importação ainda sem IA",
                "texto": f"{imp.campanha.nome} · {imp.ponto.nome} · {imp.copiados} arquivos. Rode a IA para poder revisar.",
                "botao": "Abrir importação", "href": f"/importacoes/{imp.id}"}
    if confirmadas:
        return {"icone": "analises", "titulo": "Tudo revisado", "texto": "Veja taxas, atividade e exporte os resultados.",
                "botao": "Abrir análises", "href": "/analises"}
    return {"icone": "cartao", "titulo": "Comece conectando um cartão SD",
            "texto": "Ele aparece aqui sozinho em até 5 segundos, ou use “Importar de uma pasta”. "
                     "Primeira vez? O guia explica cada etapa.",
            "botao": "Abrir o guia", "href": "/guia"}
