"""CSV, Excel e tabelas camtrapR (CTtable e recordTable)."""

from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from camtrap_campo.analises.resultado import Analise


def linhas_registros(an: Analise) -> list[dict]:
    return [{"ponto": r.ponto, "camera": r.camera, "especie": r.especie, "nome_popular": r.nome_popular,
             "data_hora": r.data.strftime("%Y-%m-%d %H:%M:%S"), "quantidade": r.quantidade,
             "comportamento": r.comportamento or "", "divulgacao": "sim" if r.divulgacao else "",
             "revisao_id": r.revisao_id} for r in an.independentes]


def linhas_esforco(an: Analise) -> list[dict]:
    return [{"ponto": e.ponto, "camera": e.camera, "inicio": e.inicio.isoformat() if e.inicio else "",
             "fim": e.fim.isoformat() if e.fim else "", "dias_totais": e.dias_totais, "dias_falha": e.dias_falha,
             "camaras_dia": e.camaras_dia, "periodo_por": e.fonte_periodo} for e in an.esforco]


def linhas_taxas(an: Analise) -> list[dict]:
    return [{"especie": t["especie"], "nome_popular": t["nome_popular"], "registros_independentes": t["registros"],
             "taxa_por_100_camaras_dia": t["taxa"], "pontos_com_registro": t["pontos_com_registro"],
             "periodo_atividade": an.periodos.get(t["especie"], "")} for t in an.taxas["especies"]]


def linhas_sobreposicao(an: Analise) -> list[dict]:
    return [{"especie_a": s["a"], "especie_b": s["b"], "n_a": s["na"], "n_b": s["nb"], "delta": s.get("delta"),
             "estimador": s.get("estimador") or "", "obs": s.get("motivo", "")} for s in an.sobreposicoes]


def ct_table(an: Analise) -> list[dict]:
    """Formato de tabela de câmeras do camtrapR (CTtable): uma linha por estação, com períodos de falha."""
    linhas = []
    maximo = max((len(e.falhas) for e in an.conjunto.estacoes), default=0)
    for e in an.conjunto.estacoes:
        linha = {"Station": e.ponto, "Camera": e.camera, "Latitude": e.latitude, "Longitude": e.longitude,
                 "Setup_date": e.inicio.strftime("%Y-%m-%d") if e.inicio else "",
                 "Retrieval_date": e.fim.strftime("%Y-%m-%d") if e.fim else ""}
        for i in range(maximo):
            ini, fim = e.falhas[i] if i < len(e.falhas) else (None, None)
            linha[f"Problem{i + 1}_from"] = ini.strftime("%Y-%m-%d") if ini else ""
            linha[f"Problem{i + 1}_to"] = fim.strftime("%Y-%m-%d") if fim else ""
        linhas.append(linha)
    return linhas


def record_table(an: Analise, pasta_dados_rel: str = "Dados") -> list[dict]:
    """Formato da saída de recordTable() do camtrapR (registros independentes)."""
    linhas, anterior = [], {}
    for r in sorted(an.independentes, key=lambda r: (r.ponto, r.especie, r.data)):
        chave = (r.ponto, r.especie)
        delta = (r.data - anterior[chave]).total_seconds() if chave in anterior else 0
        anterior[chave] = r.data
        linhas.append({"Station": r.ponto, "Camera": r.camera, "Species": r.especie,
                       "DateTimeOriginal": r.data.strftime("%Y-%m-%d %H:%M:%S"), "Date": r.data.strftime("%Y-%m-%d"),
                       "Time": r.data.strftime("%H:%M:%S"), "delta.time.secs": int(delta),
                       "delta.time.mins": round(delta / 60, 1), "delta.time.hours": round(delta / 3600, 1),
                       "delta.time.days": round(delta / 86400, 1), "Directory": pasta_dados_rel,
                       "FileName": f"revisao_{r.revisao_id}", "n_images": len(r.arquivos)})
    return linhas


def escrever_csv(caminho: Path, linhas: list[dict]) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    campos = list(linhas[0]) if linhas else ["sem_dados"]
    with caminho.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: o Excel abre com acentos certos
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(linhas)
    return caminho


def escrever_excel(caminho: Path, an: Analise) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    for titulo, linhas in (("Registros independentes", linhas_registros(an)), ("Esforço", linhas_esforco(an)),
                           ("Taxa de captura", linhas_taxas(an)), ("Sobreposição", linhas_sobreposicao(an)),
                           ("CTtable (camtrapR)", ct_table(an)), ("recordTable (camtrapR)", record_table(an))):
        ws = wb.create_sheet(titulo[:31])  # o Excel limita nomes de aba a 31 caracteres
        campos = list(linhas[0]) if linhas else ["sem dados"]
        ws.append(campos)
        for linha in linhas:
            ws.append([linha.get(c) for c in campos])
        for i, c in enumerate(campos, 1):
            ws.column_dimensions[get_column_letter(i)].width = max(12, min(40, len(str(c)) + 4))
        ws.freeze_panes = "A2"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    wb.save(caminho)
    return caminho
