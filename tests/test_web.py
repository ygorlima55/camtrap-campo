"""Interface web: páginas, fluxo de importação, correção de horário, miniatura e cadastros."""

import datetime as dt
import re

import pytest
from fastapi.testclient import TestClient

from camtrap_campo import amostras
from camtrap_campo.db import Arquivo, Camera, Ponto
from camtrap_campo.web.app import criar_app


@pytest.fixture
def cliente(ambiente, tmp_path):
    cartao = amostras.cartao_bushnell(tmp_path / "cartao")
    app = criar_app(ambiente["fabrica"], sincrono=True, extras_cartoes=[str(cartao)])
    return TestClient(app), cartao, ambiente


def test_inicio_lista_cartao(cliente):
    c, cartao, _ = cliente
    r = c.get("/")
    assert r.status_code == 200 and "Importar este cartão" in r.text and "100EK113" in r.text
    assert "/static/htmx.min.js" in r.text and c.get("/static/htmx.min.js").status_code == 200


def test_fluxo_importacao_e_correcao(cliente):
    c, cartao, amb = cliente
    r = c.get("/importar", params={"origem": str(cartao)})
    assert r.status_code == 200 and "Copiar e organizar" in r.text
    r = c.post("/importar", data={"origem": str(cartao), "camera": "P7", "ponto": "Ponto 1", "campanha": "Seca2026"},
               follow_redirects=False)
    assert r.status_code == 303
    url = r.headers["location"]
    pagina = c.get(url).text
    assert "concluida" in pagina and "Seca2026_Ponto-1_P7_20261020_054210_0007.jpg" in pagina
    assert "sem registros entre" in pagina  # alerta de intervalo
    imp_id = int(re.search(r"/importacoes/(\d+)", url).group(1))
    with amb["fabrica"]() as s:
        ref = s.query(Arquivo).filter_by(importacao_id=imp_id, nome_original="10200007.JPG").one()
    assert c.get(f"/arquivos/{ref.id}/miniatura").headers["content-type"] == "image/jpeg"
    r = c.post(f"/importacoes/{imp_id}/horario", data={"arquivo_id": ref.id, "hora_real": "2026-10-20T06:42:10"},
               follow_redirects=True)
    assert "+0 dia(s) 01:00:00" in r.text
    with amb["fabrica"]() as s:
        assert s.get(Arquivo, ref.id).data_corrigida == dt.datetime(2026, 10, 20, 6, 42, 10)
    # segunda abertura do formulário lembra ponto e campanha da câmera P7
    assert '"P7": {"campanha": "Seca2026", "ponto": "Ponto 1"}' in c.get("/importar", params={"origem": str(cartao)}).text


def test_importar_sem_dcim_recusa(cliente, tmp_path):
    c, _, _ = cliente
    (tmp_path / "sem").mkdir()
    r = c.post("/importar", data={"origem": str(tmp_path / "sem"), "camera": "P1", "ponto": "X", "campanha": "Y"})
    assert r.status_code == 400


def test_cadastros(cliente):
    c, _, amb = cliente
    c.post("/cadastros/ponto", data={"nome": "Ponto 9", "latitude": "-15,78", "longitude": "-47,93"})
    c.post("/cadastros/camera", data={"etiqueta": "P4", "modelo": "Bushnell Color Viewer"})
    c.post("/cadastros/campanha", data={"nome": "Chuva2027", "inicio": "2027-01-10", "fim": "2027-03-10"})
    r = c.get("/cadastros")
    assert "Ponto 9" in r.text and "Bushnell Color Viewer" in r.text and "2027-01-10" in r.text
    with amb["fabrica"]() as s:
        assert s.query(Ponto).filter_by(nome="Ponto 9").one().latitude == -15.78
        assert s.query(Camera).filter_by(etiqueta="P4").one().modelo == "Bushnell Color Viewer"
