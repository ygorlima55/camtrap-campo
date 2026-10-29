"""Agrupa fotos/vídeos de uma importação em sequências (mesmo evento de disparo) pelo intervalo entre registros."""

from __future__ import annotations

import datetime as dt

INTERVALO_SEQUENCIA_S = 60


def agrupar(arquivos, intervalo_s: int = INTERVALO_SEQUENCIA_S) -> list[list]:
    """Recebe Arquivo (com .data) de uma importação; devolve listas ordenadas por tempo.

    Arquivos sem data ficam cada um na sua própria sequência.
    """
    datados = sorted((a for a in arquivos if a.data), key=lambda a: (a.data, a.id))
    grupos: list[list] = []
    for a in datados:
        if grupos and a.data - grupos[-1][-1].data <= dt.timedelta(seconds=intervalo_s):
            grupos[-1].append(a)
        else:
            grupos.append([a])
    grupos += [[a] for a in arquivos if not a.data]
    return grupos
