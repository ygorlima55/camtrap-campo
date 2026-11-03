"""Validação por espécie: agrupa as sequências analisadas pela IA por espécie (sugerida ou já confirmada) para a
pessoa conferir em bloco. Só o que a pessoa valida vira ``Revisao`` — é isso que entra em análises, planilha e
relatório. Sugestões de alta confiança chegam apenas pré-marcadas na tela, nunca gravadas sozinhas.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import select

from camtrap_campo.db import Arquivo, Deteccao, Especie, Importacao, Inferencia, Revisao
from camtrap_campo.ia import revisao

CONFIANCA_ALTA = 0.80  # a partir daqui a sugestão já vem marcada para validar com Enter
ROTULOS = {"pessoa": "Pessoa", "veiculo": "Veículo", "vazio": "Vazio (falso disparo)", "indeterminado": "Indeterminado",
           "sem-especie": "Animal: espécie a definir"}
ORDEM_FINAL = ["sem-especie", "pessoa", "veiculo", "indeterminado", "vazio"]


def importacoes(sessao, campanha_id: int | None = None, camera_id: int | None = None) -> list[Importacao]:
    q = select(Importacao).order_by(Importacao.id)
    if campanha_id:
        q = q.where(Importacao.campanha_id == campanha_id)
    if camera_id:
        q = q.where(Importacao.camera_id == camera_id)
    lista = sessao.scalars(q).all()
    for imp in lista:
        _ = imp.camera, imp.ponto, imp.campanha
    return lista


def capa(arquivos: list[Arquivo], deteccoes: dict[int, list[Deteccao]], tamanho: int = 480) -> str:
    """Imagem que melhor mostra o bicho: a foto (ou o quadro do vídeo) com a detecção mais confiante."""
    melhor = None
    for a in arquivos:
        for d in deteccoes.get(a.id, []):
            if melhor is None or d.confianca > melhor[1].confianca:
                melhor = (a, d)
    if melhor is None:
        fotos = [a for a in arquivos if a.tipo == "foto"]
        return f"/arquivos/{fotos[0].id}/miniatura?tamanho={tamanho}" if fotos else ""
    a, d = melhor
    return f"/arquivos/{a.id}/miniatura?tamanho={tamanho}" if a.tipo == "foto" else f"/deteccoes/{d.id}/imagem?tamanho={tamanho}"


def _texto_sugestao(sug: dict) -> str:
    nome = sug.get("nome_cientifico") or sug.get("rotulo") or sug.get("nome_popular_en")
    return f"IA: {nome} {round(100 * sug.get('confianca', 0))}%" if nome else "IA sem sugestão de espécie"


def montar(sessao, campanha_id: int | None = None, camera_id: int | None = None) -> dict:
    especies = {e.id: e for e in sessao.scalars(select(Especie))}
    grupos: dict[str, dict] = {}
    simulado = False
    for imp in importacoes(sessao, campanha_id, camera_id):
        dados = revisao.montar(sessao, imp.id)
        simulado = simulado or dados["simulado"]
        for sq in dados["sequencias"]:
            rev, sug, cats = sq["revisao"], sq["sugestao"] or {}, sq["categorias"]
            conf_det = max((d.confianca for ds in sq["deteccoes"].values() for d in ds), default=0)
            if rev:
                estado, resultado = "validada", rev.resultado
                esp = especies.get(rev.especie_id) if rev.resultado == "especie" else None
                chave_grupo = f"esp-{esp.id}" if esp else rev.resultado
                conf, pre = sug.get("confianca"), False
            elif sq["especie_sugerida"]:
                estado, resultado, esp = "sugerida", "especie", sq["especie_sugerida"]
                chave_grupo, conf = f"esp-{esp.id}", sug.get("confianca", 0)
                pre = conf >= CONFIANCA_ALTA
            elif "animal" not in cats and ("pessoa" in cats or "veiculo" in cats):
                estado, esp = "sugerida", None
                resultado = chave_grupo = "pessoa" if "pessoa" in cats else "veiculo"
                conf, pre = conf_det, conf_det >= CONFIANCA_ALTA
            else:  # animal detectado, mas a IA não chegou a uma espécie da lista
                estado, resultado, esp, chave_grupo = "sugerida", None, None, "sem-especie"
                conf, pre = sug.get("confianca"), False
            g = grupos.setdefault(chave_grupo, {
                "chave": chave_grupo, "especie": esp, "resultado": resultado,
                "titulo": esp.nome_popular if esp else ROTULOS.get(chave_grupo, chave_grupo),
                "subtitulo": esp.nome_cientifico if esp else "", "itens": []})
            g["itens"].append({
                "imp_id": imp.id, "chave": sq["chave"], "arquivos": [a.id for a in sq["arquivos"]],
                "capa": capa(sq["arquivos"], sq["deteccoes"]), "capa_grande": capa(sq["arquivos"], sq["deteccoes"], 1280),
                "inicio": sq["inicio"], "camera": imp.camera.etiqueta, "ponto": imp.ponto.nome, "campanha": imp.campanha.nome,
                "conf": conf, "estado": estado, "pre": pre,
                "quantidade": (rev.quantidade if rev else None) or sq["max_individuos"] or 1,
                "sugestao": _texto_sugestao(sug), "n_fotos": len(sq["arquivos"])})
    for g in grupos.values():
        g["itens"].sort(key=lambda i: (i["estado"] == "validada", i["inicio"] or dt.datetime.min))
        g["validadas"] = sum(i["estado"] == "validada" for i in g["itens"])
        g["pendentes"] = len(g["itens"]) - g["validadas"]
        g["marcadas"] = sum(i["pre"] for i in g["itens"])
    ordenados = sorted(grupos.values(), key=lambda g: (
        g["chave"] in ORDEM_FINAL, ORDEM_FINAL.index(g["chave"]) if g["chave"] in ORDEM_FINAL else 0,
        -len(g["itens"]), g["titulo"]))
    return {"grupos": ordenados, "simulado": simulado,
            "validadas": sum(g["validadas"] for g in ordenados), "pendentes": sum(g["pendentes"] for g in ordenados),
            "especies": sum(1 for g in ordenados if g["especie"])}


def validar(sessao, itens: list[dict], resultado: str, especie_id: int | None = None) -> int:
    """Grava a identificação escolhida pela pessoa para várias sequências de uma vez. Devolve quantas salvou."""
    salvos = 0
    for item in itens:
        imp_id, arquivos = int(item["imp_id"]), sorted(int(x) for x in item["arquivos"])
        validos = set(sessao.scalars(select(Arquivo.id).where(Arquivo.importacao_id == imp_id, Arquivo.id.in_(arquivos))))
        if not arquivos or set(arquivos) != validos or int(item["chave"]) != arquivos[0]:
            raise ValueError("sequência inválida")
        anterior = sessao.scalar(select(Revisao).where(Revisao.importacao_id == imp_id, Revisao.chave_sequencia == arquivos[0]))
        sug = sessao.scalars(select(Inferencia.classificacao).where(Inferencia.arquivo_id.in_(arquivos),
                                                                     Inferencia.classificacao.is_not(None))).first()
        quantidade = (anterior.quantidade if anterior and anterior.quantidade else None) or int(item.get("quantidade") or 1)
        revisao.salvar(sessao, imp_id, arquivos[0], arquivos, resultado, especie_id, max(quantidade, 1),
                       anterior.comportamento if anterior else None, bool(anterior and anterior.divulgacao),
                       anterior.observacao if anterior else None, sug)
        salvos += 1
    return salvos


def por_camera(sessao, camera_id: int) -> list[dict]:
    """Espécies da câmera: quantas sequências já validadas e quantas aguardando validação."""
    return [{"titulo": g["titulo"], "subtitulo": g["subtitulo"], "validadas": g["validadas"], "pendentes": g["pendentes"],
             "chave": g["chave"]}
            for g in montar(sessao, camera_id=camera_id)["grupos"] if g["especie"] or g["chave"] == "sem-especie"]


def registros_validados(sessao, campanha_id: int | None = None, camera_id: int | None = None) -> list[dict]:
    """Sequências validadas como espécie, com tudo o que a planilha e o relatório fotográfico precisam."""
    imps = {i.id: i for i in importacoes(sessao, campanha_id, camera_id)}
    if not imps:
        return []
    revs = sessao.scalars(select(Revisao).where(Revisao.importacao_id.in_(imps), Revisao.resultado == "especie")).all()
    todos = {a.id: a for a in sessao.scalars(select(Arquivo).where(Arquivo.id.in_([x for r in revs for x in r.arquivos])))}
    dets: dict[int, list[Deteccao]] = defaultdict(list)
    for d in sessao.scalars(select(Deteccao).where(Deteccao.arquivo_id.in_(list(todos)))):
        dets[d.arquivo_id].append(d)
    saida = []
    for r in revs:
        imp, arquivos = imps[r.importacao_id], [todos[x] for x in r.arquivos if x in todos]
        datas = [a.data for a in arquivos if a.data]
        sug = r.sugestao_ia or {}
        nome_ia = sug.get("nome_cientifico")
        saida.append({
            "especie": r.especie, "data": min(datas) if datas else None, "campanha": imp.campanha.nome,
            "ponto": imp.ponto.nome, "camera": imp.camera.etiqueta, "latitude": imp.ponto.latitude,
            "longitude": imp.ponto.longitude, "quantidade": r.quantidade, "comportamento": r.comportamento,
            "divulgacao": r.divulgacao, "observacao": r.observacao, "revisado_em": r.revisado_em,
            "sugestao_ia": nome_ia, "confianca_ia": sug.get("confianca"),
            "ia_concordou": None if not nome_ia else nome_ia.lower() == r.especie.nome_cientifico.lower(),
            "arquivos": [a.caminho_final for a in arquivos], "capa": capa(arquivos, dets, 900),
            "capa_conf": max((d.confianca for a in arquivos for d in dets.get(a.id, [])), default=0)})
    saida.sort(key=lambda x: (x["especie"].nome_popular, x["data"] or dt.datetime.min))
    return saida


def resumo_especies(registros: list[dict]) -> list[dict]:
    por: dict[int, dict] = {}
    for r in registros:
        e = r["especie"]
        g = por.setdefault(e.id, {"especie": e, "registros": 0, "individuos": 0, "cameras": set(), "pontos": set(),
                                  "primeiro": None, "ultimo": None, "fotos": []})
        g["registros"] += 1
        g["individuos"] += r["quantidade"] or 1
        g["cameras"].add(r["camera"])
        g["pontos"].add(r["ponto"])
        if r["data"]:
            g["primeiro"] = min(filter(None, [g["primeiro"], r["data"]]))
            g["ultimo"] = max(filter(None, [g["ultimo"], r["data"]]))
        g["fotos"].append(r)
    for g in por.values():  # melhores fotos: marcadas para divulgação, depois a IA mais confiante, variando a câmera
        g["fotos"].sort(key=lambda r: (not r["divulgacao"], -r["capa_conf"]))
        escolhidas, cams = [], set()
        for r in g["fotos"]:
            if r["capa"] and (r["camera"] not in cams or len(cams) >= len(g["cameras"])):
                escolhidas.append(r)
                cams.add(r["camera"])
            if len(escolhidas) == 4:
                break
        g["fotos"] = escolhidas
    return sorted(por.values(), key=lambda g: (-g["registros"], g["especie"].nome_popular))
