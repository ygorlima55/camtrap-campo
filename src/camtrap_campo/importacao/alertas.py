"""Alertas gerados ao fim de cada importação (dicts prontos para a tabela Alerta)."""

from __future__ import annotations

import datetime as dt
from pathlib import PurePosixPath

from camtrap_campo import config


def gerar(imp, campanha=None, hoje: dt.datetime | None = None) -> list[dict]:
    hoje = hoje or dt.datetime.now()
    out: list[dict] = []
    todos = imp.arquivos
    no_cartao = {a.caminho_cartao.lower() for a in todos}

    for a in todos:
        if a.tipo == "appledouble":
            par = (PurePosixPath(a.caminho_cartao).parent / a.nome_original[2:]).as_posix().lower()
            if par not in no_cartao:
                out.append(dict(arquivo_id=a.id, tipo="mac_sem_foto", nivel="erro", mensagem=(
                    f"{a.caminho_cartao}: arquivo '._' de Mac sem a foto '{a.nome_original[2:]}' — "
                    "cartão lido num Mac, a foto original não está mais no cartão")))
        if a.estado == "erro":
            out.append(dict(arquivo_id=a.id, tipo="erro_copia", nivel="erro",
                            mensagem=f"{a.caminho_cartao}: não copiado ({a.detalhe})"))
        if a.rodape_diverge:
            out.append(dict(arquivo_id=a.id, tipo="rodape_diverge", nivel="aviso", mensagem=(
                f"{a.nome_original}: data do EXIF ({a.data_original}) difere da faixa do rodapé "
                f"({a.rodape.get('data')})")))

    midias = [a for a in todos if a.tipo in ("foto", "video") and a.estado != "erro"]
    if not midias:
        orfaos = sum(1 for a in todos if a.tipo == "appledouble")
        out.append(dict(arquivo_id=None, tipo="cartao_vazio", nivel="aviso", mensagem=(
            "Nenhuma foto ou vídeo no cartão" + (f" (há {orfaos} arquivos '._' de Mac)" if orfaos else ""))))
        return out

    datadas = sorted((a for a in midias if a.data_original), key=lambda a: a.data_original)
    resetadas = [a for a in datadas if a.data_original.year < config.ANO_MINIMO_VALIDO]
    futuras = [a for a in datadas if a.data_original > hoje + dt.timedelta(days=1)]
    if resetadas:
        out.append(dict(arquivo_id=resetadas[0].id, tipo="relogio_resetado", nivel="erro", mensagem=(
            f"{len(resetadas)} arquivo(s) com data anterior a {config.ANO_MINIMO_VALIDO} "
            f"(ex.: {resetadas[0].nome_original} em {resetadas[0].data_original:%d/%m/%Y %H:%M}) — relógio resetado; "
            "use a correção de horário")))
    if futuras:
        out.append(dict(arquivo_id=futuras[0].id, tipo="data_futura", nivel="erro", mensagem=(
            f"{len(futuras)} arquivo(s) com data no futuro (ex.: {futuras[0].nome_original} em "
            f"{futuras[0].data_original:%d/%m/%Y %H:%M}) — relógio errado")))
    if campanha is not None and (campanha.inicio or campanha.fim):
        fora = [a for a in datadas if (campanha.inicio and a.data_original.date() < campanha.inicio)
                or (campanha.fim and a.data_original.date() > campanha.fim)]
        if fora:
            out.append(dict(arquivo_id=fora[0].id, tipo="fora_da_campanha", nivel="aviso", mensagem=(
                f"{len(fora)} arquivo(s) fora do período da campanha {campanha.nome}")))

    # Intervalos só com datas internas (EXIF/rodapé/vídeo): a data do arquivo pode ser a da cópia e criaria buracos falsos.
    validas = [a for a in datadas if a not in resetadas and a not in futuras and a.fonte_data != "arquivo"]
    for anterior, atual in zip(validas, validas[1:], strict=False):
        lacuna = atual.data_original - anterior.data_original
        if lacuna > dt.timedelta(hours=config.INTERVALO_SEM_FOTOS_H):
            out.append(dict(arquivo_id=atual.id, tipo="intervalo_sem_fotos", nivel="aviso", mensagem=(
                f"{lacuna.days} dia(s) e {lacuna.seconds // 3600} h sem registros entre "
                f"{anterior.data_original:%d/%m %H:%M} e {atual.data_original:%d/%m %H:%M}")))
    sem_exif = [a for a in midias if a.fonte_data == "arquivo"]
    if sem_exif:
        out.append(dict(arquivo_id=sem_exif[0].id, tipo="sem_data_interna", nivel="info", mensagem=(
            f"{len(sem_exif)} arquivo(s) sem data no EXIF/rodapé/vídeo; usada a data do arquivo no cartão")))
    return out
