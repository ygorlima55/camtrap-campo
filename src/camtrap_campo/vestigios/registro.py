"""Importação das fotos de vestígios, caracterização e validação."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from camtrap_campo import config
from camtrap_campo.db import Campanha, Especie, Ponto, Vestigio, agora
from camtrap_campo.importacao.copiar import IGNORAR, _copiar_com_hash, _livre, obter_ou_criar, sanitizar, sha256
from camtrap_campo.metadados.exif import interpretar_data
from camtrap_campo.vestigios import comparar

EXTENSOES = {".jpg", ".jpeg", ".png"}


def listar_fotos(raiz: Path) -> list[Path]:
    fotos = []
    for pasta, subpastas, nomes in os.walk(raiz):
        subpastas[:] = [s for s in subpastas if s.lower() not in IGNORAR and not s.startswith(".")]
        fotos += [Path(pasta) / n for n in nomes if Path(n).suffix.lower() in EXTENSOES and not n.startswith(".")]
    return sorted(fotos)


def _graus(valor, ref) -> float | None:
    try:
        g, m, s = (float(x) for x in valor)
    except (TypeError, ValueError):
        return None
    graus = g + m / 60 + s / 3600
    return -graus if ref in ("S", "W") else graus


def ler_foto(caminho: Path) -> dict:
    """Data (EXIF) e GPS (celulares costumam gravar). Sem EXIF, usa a data do arquivo."""
    info: dict = {"data": None, "fonte_data": None, "latitude": None, "longitude": None}
    try:
        with Image.open(caminho) as im:
            exif = im.getexif()
            data = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal ou DateTime
            info["data"] = interpretar_data(data)
            gps = exif.get_ifd(0x8825)
            if gps:
                info["latitude"], info["longitude"] = _graus(gps.get(2), gps.get(1)), _graus(gps.get(4), gps.get(3))
    except OSError:
        pass
    if info["data"]:
        info["fonte_data"] = "exif"
    else:
        info["data"] = dt.datetime.fromtimestamp(caminho.stat().st_mtime).replace(microsecond=0)
        info["fonte_data"] = "arquivo"
    return info


def importar_pasta(sessao, origem: Path, campanha: str, ponto: str = "", tipo: str | None = None) -> dict:
    """Copia as fotos (conferindo o SHA-256) para Dados\\<campanha>\\_vestigios\\<ponto>\\. Nunca apaga a origem."""
    if tipo and tipo not in comparar.TIPOS:
        raise ValueError("Tipo de vestígio inválido")
    fotos = listar_fotos(origem)
    if not fotos:
        raise ValueError("Nenhuma foto (JPG ou PNG) nesta pasta")
    cmp = obter_ou_criar(sessao, Campanha, campanha)
    pto = obter_ou_criar(sessao, Ponto, ponto) if ponto else None
    pasta = config.pasta_dados() / sanitizar(campanha) / "_vestigios" / (sanitizar(ponto) if ponto else "sem-ponto")
    conhecidos = set(sessao.scalars(select(Vestigio.sha256)))
    res = {"novos": 0, "duplicados": 0, "erros": [], "ids": []}
    for n, foto in enumerate(fotos, 1):
        try:
            hash_origem = sha256(foto)
            if hash_origem in conhecidos:
                res["duplicados"] += 1
                continue
            info = ler_foto(foto)
            carimbo = info["data"].strftime("%Y%m%d_%H%M%S")
            nome = f"{sanitizar(campanha)}_{sanitizar(ponto or 'sem-ponto')}_vestigio_{carimbo}_{n:04d}{foto.suffix.lower()}"
            destino = _livre(pasta / nome)
            if _copiar_com_hash(foto, destino) != hash_origem:
                destino.unlink()
                raise OSError("cópia diferente do original (SHA-256)")
            v = Vestigio(campanha_id=cmp.id, ponto_id=pto.id if pto else None, origem=str(foto), nome_original=foto.name,
                         sha256=hash_origem, tamanho=foto.stat().st_size, tipo=tipo,
                         caminho_final=destino.relative_to(config.pasta_dados()).as_posix(), **info)
            sessao.add(v)
            sessao.flush()
            conhecidos.add(hash_origem)
            res["novos"] += 1
            res["ids"].append(v.id)
        except OSError as exc:
            res["erros"].append(f"{foto.name}: {exc}")
    sessao.commit()
    return res


def caracterizar(sessao, vest: Vestigio, tipo: str, bruto: dict, observacao: str | None = None) -> Vestigio:
    """Grava as características e recalcula a comparação com o guia."""
    vest.tipo = tipo
    vest.caracteristicas = comparar.limpar(tipo, bruto)
    vest.sugestoes = comparar.comparar(sessao, tipo, vest.caracteristicas)
    if observacao is not None:
        vest.observacao = observacao.strip() or None
    sessao.commit()
    return vest


def validar(sessao, vest: Vestigio, resultado: str, especie_id: int | None = None) -> Vestigio:
    """Só a pessoa valida. ``resultado``: especie | indeterminado | limpar (volta a não validado)."""
    if resultado == "limpar":
        vest.resultado = vest.especie_id = vest.sugestao_aceita = vest.validado_em = None
    elif resultado == "indeterminado":
        vest.resultado, vest.especie_id, vest.validado_em = "indeterminado", None, agora()
        vest.sugestao_aceita = False if vest.sugestoes else None
    elif resultado == "especie":
        if not especie_id or sessao.get(Especie, especie_id) is None:
            raise ValueError("Espécie não encontrada")
        vest.resultado, vest.especie_id, vest.validado_em = "especie", especie_id, agora()
        vest.sugestao_aceita = bool(vest.sugestoes) and vest.sugestoes[0].get("especie_id") == especie_id
    else:
        raise ValueError("Resultado inválido")
    sessao.commit()
    return vest


def especie_do_guia(sessao, nome_cientifico: str, nome_popular: str) -> int:
    """Id da espécie (cria na lista de espécies se o guia tiver uma que ainda não está lá)."""
    e = sessao.scalar(select(Especie).where(Especie.nome_cientifico == nome_cientifico))
    if e is None:
        e = Especie(nome_cientifico=nome_cientifico, nome_popular=nome_popular, grupo="mamífero")
        sessao.add(e)
        sessao.commit()
    return e.id


def quadro(sessao, campanha_id: int | None = None, tipo: str | None = None, estado: str | None = None) -> dict:
    consulta = select(Vestigio).order_by(Vestigio.data, Vestigio.id)
    if campanha_id:
        consulta = consulta.where(Vestigio.campanha_id == campanha_id)
    if tipo:
        consulta = consulta.where(Vestigio.tipo == tipo)
    todos = sessao.scalars(consulta).all()
    for v in todos:
        _ = v.campanha, v.ponto, v.especie
    estados = {"sem_ficha": [v for v in todos if not v.caracteristicas and not v.resultado],
               "a_validar": [v for v in todos if v.caracteristicas and not v.resultado],
               "validados": [v for v in todos if v.resultado]}
    lista = estados.get(estado, todos) if estado else todos
    especies: dict[str, dict] = {}
    for v in estados["validados"]:
        if v.especie:
            e = especies.setdefault(v.especie.nome_cientifico, {"especie": v.especie, "pegada": 0, "fezes": 0, "sinal": 0,
                                                                 "total": 0, "pontos": set()})
            e[v.tipo or "sinal"] += 1
            e["total"] += 1
            e["pontos"].add(v.ponto.nome if v.ponto else "sem ponto")
    return {"itens": lista, "total": len(todos), **{k: len(x) for k, x in estados.items()},
            "especies": sorted(especies.values(), key=lambda e: -e["total"]),
            "acertos": sum(1 for v in estados["validados"] if v.sugestao_aceita),
            "com_sugestao": sum(1 for v in estados["validados"] if v.sugestao_aceita is not None)}
