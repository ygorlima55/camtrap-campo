"""Planilha das espécies validadas: resumo por espécie e um registro (sequência) por linha."""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

CABECALHO = PatternFill("solid", fgColor="F4E7C7")  # ocre suave da identidade v2, texto escuro


def _aba(wb, titulo: str, colunas: list[tuple[str, int]], linhas: list[list]):
    ws = wb.create_sheet(titulo)
    ws.append([c for c, _ in colunas])
    for i, (_, largura) in enumerate(colunas, 1):
        cel = ws.cell(row=1, column=i)
        cel.font, cel.fill, cel.alignment = Font(bold=True), CABECALHO, Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[cel.column_letter].width = largura
    for linha in linhas:
        ws.append(linha)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def _dh(d):
    return d.strftime("%d/%m/%Y %H:%M:%S") if d else ""


def planilha(resumo: list[dict], registros: list[dict], titulo: str) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    _aba(wb, "Espécies", [("Nome popular", 24), ("Nome científico", 28), ("Grupo", 14), ("Registros (sequências)", 14),
                          ("Indivíduos (soma)", 12), ("Câmeras", 18), ("Pontos", 18), ("Primeiro registro", 20),
                          ("Último registro", 20)],
         [[g["especie"].nome_popular, g["especie"].nome_cientifico, g["especie"].grupo or "", g["registros"], g["individuos"],
           ", ".join(sorted(g["cameras"])), ", ".join(sorted(g["pontos"])), _dh(g["primeiro"]), _dh(g["ultimo"])]
          for g in resumo])
    _aba(wb, "Registros", [("Nome popular", 22), ("Nome científico", 26), ("Data e hora", 20), ("Campanha", 14), ("Ponto", 12),
                           ("Câmera", 10), ("Latitude", 11), ("Longitude", 11), ("Indivíduos", 10), ("Comportamento", 16),
                           ("Boa p/ divulgação", 10), ("Observação", 28), ("Sugestão da IA", 26), ("Confiança IA", 11),
                           ("IA acertou?", 10), ("Validado em", 20), ("Arquivos", 60)],
         [[r["especie"].nome_popular, r["especie"].nome_cientifico, _dh(r["data"]), r["campanha"], r["ponto"], r["camera"],
           r["latitude"], r["longitude"], r["quantidade"], r["comportamento"] or "", "sim" if r["divulgacao"] else "",
           r["observacao"] or "", r["sugestao_ia"] or "", round(r["confianca_ia"], 3) if r["confianca_ia"] is not None else "",
           "" if r["ia_concordou"] is None else ("sim" if r["ia_concordou"] else "não"), _dh(r["revisado_em"]),
           "; ".join(filter(None, r["arquivos"]))] for r in registros])
    info = wb.create_sheet("Sobre")
    info.append(["CamTrap Campo — espécies validadas", titulo])
    info.append(["Critério", "Só identificações confirmadas por pessoa (sugestões da IA não validadas ficam de fora)."])
    info.column_dimensions["A"].width, info.column_dimensions["B"].width = 34, 90
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
