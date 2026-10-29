"""Módulo 3: independência, esforço, taxas, atividade, sobreposição, acumulação, exportações e telas.

Dados sintéticos montados no banco (sem IA): 2 pontos com coordenadas, uma espécie noturna e uma diurna.
"""

import csv
import datetime as dt
import json
import math
import zipfile
from io import BytesIO

import numpy as np
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

from camtrap_campo.analises import atividade
from camtrap_campo.analises.acumulacao import acumulacao
from camtrap_campo.analises.basicas import Esforco, esforco, independentes, taxa_captura
from camtrap_campo.analises.dados import Estacao, Registro, carregar
from camtrap_campo.analises.resultado import analisar
from camtrap_campo.db import Arquivo, Camera, Campanha, Especie, EventoCamera, Importacao, Ponto, Revisao
from camtrap_campo.exportacao import camtrapdp, tabelas
from camtrap_campo.ia import especies
from camtrap_campo.web.app import criar_app

INICIO = dt.datetime(2026, 9, 1, 0, 0)


def _reg(especie, ponto, minutos):
    return Registro(especie, especie, ponto, "P1", INICIO + dt.timedelta(minutes=minutos), 1, None, False, [1], 1, 1)


def test_independencia_ultimo_independente_e_ultimo_registro():
    regs = [_reg("A", "X", m) for m in (0, 20, 40, 70)] + [_reg("B", "X", 5), _reg("A", "Y", 10)]
    ind = independentes(regs, 30)
    assert sorted((r.especie, r.ponto, int((r.data - INICIO).total_seconds() // 60)) for r in ind) == [
        ("A", "X", 0), ("A", "X", 40), ("A", "X", 70), ("A", "Y", 10), ("B", "X", 5)]
    ind2 = independentes(regs, 30, comparar_com="ultimo_registro")
    assert [int((r.data - INICIO).total_seconds() // 60) for r in ind2 if (r.especie, r.ponto) == ("A", "X")] == [0, 70]
    with pytest.raises(ValueError):
        independentes(regs, 30, comparar_com="outro")


def test_esforco_desconta_falhas_e_taxa():
    e = Estacao("C", "X", "P1", None, -15.8, -47.9, dt.datetime(2026, 10, 1, 10), dt.datetime(2026, 10, 10, 9), "eventos",
                [(dt.datetime(2026, 10, 3, 8), dt.datetime(2026, 10, 4, 20))])
    sem = Estacao("C", "Y", "P2", None, None, None, None, None, "midias")
    esf = esforco([e, sem])
    assert (esf[0].dias_totais, esf[0].dias_falha, esf[0].camaras_dia) == (10, 2, 8)
    assert esf[1].camaras_dia == 0
    t = taxa_captura([_reg("A", "X", 0), _reg("A", "X", 100), _reg("A", "X", 200)], esf)
    assert t["camaras_dia"] == 8 and t["especies"][0]["taxa"] == 37.5


def test_bessel_e_densidade():
    assert atividade.bessel_i(0, 1) == pytest.approx(1.2660658777520082, rel=1e-12)
    assert atividade.bessel_i(1, 1) == pytest.approx(0.5651591039924851, rel=1e-12)
    assert atividade.bessel_i(2, 2) == pytest.approx(0.6889484476987382, rel=1e-12)
    rad = atividade.para_radianos([20, 21, 22, 23, 23.5, 0.5, 1, 2, 3, 4, 22.5, 21.5])
    grade = np.linspace(0, 2 * math.pi, 2000, endpoint=False)
    assert atividade.densidade(rad, grade).sum() * 2 * math.pi / 2000 == pytest.approx(1.0, abs=1e-6)


def test_sobreposicao_estimadores():
    noite = atividade.para_radianos([20 + i * 0.4 for i in range(20)])
    dia = atividade.para_radianos([8 + i * 0.4 for i in range(20)])
    assert atividade.sobreposicao(noite, noite)["delta"] == pytest.approx(1.0, abs=0.01)
    d = atividade.sobreposicao(noite, dia)
    assert d["estimador"] == "Δ̂1" and d["delta"] < 0.2
    grande = atividade.para_radianos([(i * 0.29) % 24 for i in range(80)])
    assert atividade.sobreposicao(grande, grande)["estimador"] == "Δ̂4"
    assert atividade.sobreposicao(noite[:5], dia)["delta"] is None


def test_hora_solar_brasilia():
    lat, lon = -15.7801, -47.9292
    dia = dt.date(2026, 9, 15)
    nascer, por = atividade.nascer_por(dia, lat, lon)
    assert 5 <= nascer.hour <= 7 and 17 <= por.hour <= 19
    assert atividade.hora_solar(nascer, lat, lon) == pytest.approx(6, abs=1e-6)
    assert atividade.hora_solar(por, lat, lon) == pytest.approx(18, abs=1e-6)
    meio = nascer + (por - nascer) / 2
    assert atividade.hora_solar(meio, lat, lon) == pytest.approx(12, abs=1e-6)
    madrugada = dt.datetime(2026, 9, 15, 2, 0)
    assert 0 <= atividade.hora_solar(madrugada, lat, lon) < 6
    assert atividade.hora_solar(madrugada, None, None) == 2.0  # sem coordenadas: hora do relógio
    assert atividade.classificar_periodo([1, 2, 3, 22]) == "noturno"
    assert atividade.classificar_periodo([9, 10, 12, 14, 15]) == "diurno"


def test_acumulacao_simples():
    esf = [Esforco("X", "P1", dt.date(2026, 9, 1), dt.date(2026, 9, 3), 3, 0, 3, "eventos")]
    regs = [_reg("A", "X", 60), _reg("A", "X", 60 * 25), _reg("B", "X", 60 * 26)]
    a = acumulacao(regs, esf, permutacoes=50)
    assert a["observada"] == 2 and a["dias"] == [1, 2, 3] and a["media"][-1] == 2
    assert 0 < a["media"][0] < 2


@pytest.fixture
def campanha(ambiente):
    """Campanha sintética: P1 no ponto X (noturna: cachorro-do-mato), P2 no ponto Y (diurna: cutia)."""
    with ambiente["fabrica"]() as s:
        especies.semear(s)
        cmp = Campanha(nome="Seca2026")
        x, y = Ponto(nome="X", latitude=-15.78, longitude=-47.93), Ponto(nome="Y", latitude=-15.80, longitude=-47.90)
        c1, c2 = Camera(etiqueta="P1", modelo="Bushnell 119837"), Camera(etiqueta="P2")
        s.add_all([cmp, x, y, c1, c2])
        s.flush()
        cao = s.scalar(select(Especie).where(Especie.nome_cientifico == "Cerdocyon thous"))
        cutia = s.scalar(select(Especie).where(Especie.nome_cientifico == "Dasyprocta azarae"))
        for cam, pto, esp, horas in ((c1, x, cao, [21, 23, 1, 3]), (c2, y, cutia, [8, 10, 13, 16])):
            imp = Importacao(camera_id=cam.id, ponto_id=pto.id, campanha_id=cmp.id, origem="sintetico", estado="concluida")
            s.add(imp)
            s.flush()
            for d in range(12):  # 12 dias, 1 registro/dia (independentes)
                h = horas[d % 4]
                momento = dt.datetime(2026, 9, 1) + dt.timedelta(days=d, hours=h, minutes=7 * d)
                a = Arquivo(importacao_id=imp.id, caminho_cartao=f"DCIM/{d}.JPG", nome_original=f"{d}.JPG", tipo="foto",
                            tamanho=1, estado="copiado", caminho_final=f"Seca2026/{pto.nome}/{cam.etiqueta}/{d}.jpg",
                            data_original=momento, fonte_data="exif")
                s.add(a)
                s.flush()
                s.add(Revisao(importacao_id=imp.id, chave_sequencia=a.id, arquivos=[a.id], resultado="especie",
                              especie_id=esp.id, quantidade=1, comportamento="deslocamento", divulgacao=d == 0))
            vazio = Arquivo(importacao_id=imp.id, caminho_cartao="DCIM/v.JPG", nome_original="v.JPG", tipo="foto", tamanho=1,
                            estado="copiado", caminho_final="x/v.jpg", data_original=dt.datetime(2026, 9, 5, 12),
                            fonte_data="exif")
            s.add(vazio)
            s.flush()
            s.add(Revisao(importacao_id=imp.id, chave_sequencia=vazio.id, arquivos=[vazio.id], resultado="vazio"))
        local = {"ponto_id": x.id, "campanha_id": cmp.id}
        s.add(EventoCamera(camera_id=c1.id, tipo="instalacao", data=dt.datetime(2026, 8, 31, 15), **local))
        s.add(EventoCamera(camera_id=c1.id, tipo="retirada", data=dt.datetime(2026, 9, 14, 10), **local))
        s.add(EventoCamera(camera_id=c1.id, tipo="falha", data=dt.datetime(2026, 9, 13, 0), fim=dt.datetime(2026, 9, 14, 0),
                           ponto_id=x.id, campanha_id=cmp.id))
        s.commit()
        return cmp.id


def test_analise_completa(ambiente, campanha):
    with ambiente["fabrica"]() as s:
        c = carregar(s, campanha)
        assert len(c.registros) == 24 and c.outros_resultados == {"vazio": 2}
        an = analisar(s, campanha)
    esf = {e.ponto: e for e in an.esforco}
    assert (esf["X"].dias_totais, esf["X"].dias_falha, esf["X"].camaras_dia, esf["X"].fonte_periodo) == (15, 2, 13, "eventos")
    assert esf["Y"].fonte_periodo == "midias" and esf["Y"].camaras_dia == 12
    assert len(an.independentes) == 24 and an.taxas["camaras_dia"] == 25
    assert {t["especie"]: t["taxa"] for t in an.taxas["especies"]} == {"Cerdocyon thous": 48.0, "Dasyprocta azarae": 48.0}
    assert an.periodos == {"Cerdocyon thous": "noturno", "Dasyprocta azarae": "diurno"}
    assert an.curvas["Cerdocyon thous"]["n"] == 12
    so = an.sobreposicoes[0]
    assert so["estimador"] == "Δ̂1" and so["delta"] < 0.3
    assert an.acumulacao["observada"] == 2
    assert {p["ponto"]: p["riqueza"] for p in an.pontos} == {"X": 1, "Y": 1}
    assert any("primeira e a última mídia" in a for a in an.avisos)


def test_exportacoes(ambiente, campanha, tmp_path):
    with ambiente["fabrica"]() as s:
        an = analisar(s, campanha)
        destino = camtrapdp.exportar(s, an, tmp_path / "dp", autor="Equipe Teste")
    pacote = json.loads((destino / "datapackage.json").read_text(encoding="utf-8"))
    assert pacote["profile"].endswith("/1.0/camtrap-dp-profile.json")
    assert [r["name"] for r in pacote["resources"]] == ["deployments", "media", "observations"]
    assert pacote["temporal"]["start"] == "2026-08-31" and pacote["spatial"]["type"] == "Polygon"
    obrig = {"deployments": {"deploymentID", "latitude", "longitude", "deploymentStart", "deploymentEnd"},
             "media": {"mediaID", "deploymentID", "timestamp", "filePath", "filePublic", "fileMediatype"},
             "observations": {"observationID", "deploymentID", "eventStart", "eventEnd", "observationLevel", "observationType"}}
    for nome, campos in obrig.items():
        with (destino / f"{nome}.csv").open(encoding="utf-8") as f:
            linhas = list(csv.DictReader(f))
        assert campos <= set(linhas[0]), nome
        assert not (destino / f"{nome}.csv").read_bytes().startswith(b"\xef\xbb\xbf")  # sem BOM
    with (destino / "observations.csv").open(encoding="utf-8") as f:
        obs = list(csv.DictReader(f))
    assert {o["observationType"] for o in obs} == {"animal", "blank"}
    assert obs[0]["eventStart"].endswith("-03:00") and obs[0]["classificationMethod"] == "human"
    ct = tabelas.ct_table(an)
    assert ct[0]["Station"] == "X" and ct[0]["Problem1_from"] == "2026-09-13" and ct[1]["Problem1_from"] == ""
    rt = tabelas.record_table(an)
    assert rt[0]["delta.time.secs"] == 0 and rt[1]["delta.time.days"] >= 0.9
    xlsx = tabelas.escrever_excel(tmp_path / "a.xlsx", an)
    assert load_workbook(xlsx).sheetnames == ["Registros independentes", "Esforço", "Taxa de captura", "Sobreposição",
                                              "CTtable (camtrapR)", "recordTable (camtrapR)"]


def test_web_analises_relatorio_e_zip(ambiente, campanha):
    c = TestClient(criar_app(ambiente["fabrica"], sincrono=True))
    r = c.get("/analises", params={"campanha": campanha})
    assert r.status_code == 200 and "25</strong> câmeras-dia" in r.text and "Cerdocyon thous" in r.text
    assert "data:image/png;base64," in r.text and "<svg" in r.text
    r = c.get(f"/analises/{campanha}/relatorio")
    assert "<style>" in r.text and "/static/" not in r.text.split("<main>")[1]  # autocontido
    r = c.get(f"/analises/{campanha}/exportar")
    assert r.headers["content-type"] == "application/zip"
    nomes = zipfile.ZipFile(BytesIO(r.content)).namelist()
    for esperado in ("relatorio.html", "analises.xlsx", "camtrap-dp/datapackage.json", "camtrapR/CTtable.csv",
                     "camtrapR/recordTable.csv", "csv/taxa_captura.csv", "LEIA-ME.txt"):
        assert esperado in [n.replace("\\", "/") for n in nomes]
    assert c.get("/analises", params={"campanha": 999}).status_code == 404
    assert c.get("/analises", params={"campanha": campanha, "intervalo": 0}).status_code == 400


def test_web_evento_falha_com_fim(ambiente, campanha):
    c = TestClient(criar_app(ambiente["fabrica"], sincrono=True))
    with ambiente["fabrica"]() as s:
        cam = s.scalar(select(Camera).where(Camera.etiqueta == "P2"))
    ok = c.post(f"/cameras/{cam.id}/eventos", data={"tipo": "falha", "data": "2026-09-05T00:00", "fim": "2026-09-07T00:00",
                                                     "campanha": "Seca2026", "ponto": "Y"})
    assert ok.status_code == 200
    assert c.post(f"/cameras/{cam.id}/eventos", data={"tipo": "falha", "data": "2026-09-05T00:00",
                                                       "fim": "2026-09-01T00:00"}).status_code == 400
    with ambiente["fabrica"]() as s:
        an = analisar(s, campanha)
    assert {e.ponto: e.dias_falha for e in an.esforco}["Y"] == 3
