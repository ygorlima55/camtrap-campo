"""Gera a pasta de exportação completa de uma campanha e o ZIP para download."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from camtrap_campo import config
from camtrap_campo.analises.resultado import Analise
from camtrap_campo.exportacao import camtrapdp, tabelas
from camtrap_campo.importacao.copiar import sanitizar


def exportar_tudo(sessao, an: Analise, relatorio_html: str, autor: str = "") -> Path:
    base = config.pasta_dados() / "_exportacoes" / f"{sanitizar(an.conjunto.campanha.nome)}_{dt.datetime.now():%Y%m%d_%H%M%S}"
    camtrapdp.exportar(sessao, an, base / "camtrap-dp", autor)
    tabelas.escrever_excel(base / "analises.xlsx", an)
    for nome, linhas in (("registros_independentes", tabelas.linhas_registros(an)), ("esforco", tabelas.linhas_esforco(an)),
                         ("taxa_captura", tabelas.linhas_taxas(an)), ("sobreposicao", tabelas.linhas_sobreposicao(an))):
        tabelas.escrever_csv(base / "csv" / f"{nome}.csv", linhas)
    tabelas.escrever_csv(base / "camtrapR" / "CTtable.csv", tabelas.ct_table(an))
    tabelas.escrever_csv(base / "camtrapR" / "recordTable.csv", tabelas.record_table(an))
    (base / "relatorio.html").write_text(relatorio_html, encoding="utf-8")
    (base / "LEIA-ME.txt").write_text(
        "Exportação do CamTrap Campo\n\n"
        "relatorio.html        relatório com gráficos (abra no navegador; Imprimir > Salvar como PDF)\n"
        "analises.xlsx         todas as tabelas numa planilha\n"
        "csv/                  as mesmas tabelas em CSV\n"
        "camtrap-dp/           pacote Camtrap DP 1.0 (datapackage.json + 3 tabelas)\n"
        "camtrapR/             CTtable.csv e recordTable.csv no formato do pacote R camtrapR\n\n"
        f"Intervalo de independência: {an.intervalo_min} min. Só identificações confirmadas na revisão.\n"
        + ("\nAVISOS\n" + "".join(f"- {a}\n" for a in an.avisos) if an.avisos else ""),
        encoding="utf-8")
    zip_base = shutil.make_archive(str(base), "zip", root_dir=base)
    return Path(zip_base)
