"""Correção do relógio: a hora real de uma foto de referência define a diferença aplicada ao cartão inteiro.

A hora original fica guardada (data_original); a corrigida vai para data_corrigida e para o nome do arquivo.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from camtrap_campo import config
from camtrap_campo.db import Arquivo, Importacao
from camtrap_campo.importacao.copiar import _livre, nome_final


def aplicar_correcao(sessao, importacao_id: int, arquivo_ref_id: int, hora_real: dt.datetime,
                     pasta_dados: Path | None = None) -> int:
    """Aplica a correção e devolve o deslocamento em segundos."""
    pasta_dados = Path(pasta_dados or config.pasta_dados())
    imp = sessao.get(Importacao, importacao_id)
    ref = sessao.get(Arquivo, arquivo_ref_id)
    if imp is None or ref is None or ref.importacao_id != importacao_id or ref.data_original is None:
        raise ValueError("foto de referência inválida para esta importação")
    delta = hora_real.replace(microsecond=0) - ref.data_original
    for a in imp.arquivos:
        if a.estado != "copiado" or a.data_original is None or a.tipo not in ("foto", "video"):
            continue
        a.data_corrigida = a.data_original + delta
        atual = pasta_dados / a.caminho_final
        novo = _livre(atual.with_name(nome_final(imp.campanha.nome, imp.ponto.nome, imp.camera.etiqueta,
                                                  a.data_corrigida, a.contador_original or a.id, atual.suffix)))
        if novo.name != atual.name and atual.exists():
            atual.rename(novo)
            a.caminho_final = novo.relative_to(pasta_dados).as_posix()
    imp.deslocamento_s = int(delta.total_seconds())
    sessao.commit()
    return imp.deslocamento_s


def descrever(segundos: int | None) -> str:
    if segundos is None:
        return "sem correção"
    sinal = "+" if segundos >= 0 else "−"
    d = dt.timedelta(seconds=abs(segundos))
    return f"{sinal}{d.days} dia(s) {d.seconds // 3600:02d}:{d.seconds % 3600 // 60:02d}:{d.seconds % 60:02d}"
