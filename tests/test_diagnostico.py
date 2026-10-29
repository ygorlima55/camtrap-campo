"""Módulo 4: identificação ao conectar, teste sem tela, dias ativos, eventos, roteiros e checklist."""

import datetime as dt
import shutil

import pytest
from fastapi.testclient import TestClient

from camtrap_campo import amostras
from camtrap_campo.db import Camera, EventoCamera, PassoRoteiro
from camtrap_campo.diagnostico import historico, sem_tela
from camtrap_campo.diagnostico.identificar import identificar
from camtrap_campo.importacao.copiar import importar
from camtrap_campo.web.app import criar_app


@pytest.fixture
def cartao(tmp_path):
    return amostras.cartao_bushnell(tmp_path / "cartao")


def test_identificar_antes_e_depois_de_importar(ambiente, cartao):
    with ambiente["fabrica"]() as s:
        antes = identificar(s, cartao, hoje=dt.datetime(2026, 10, 30))
    assert antes.total_midias == 6 and antes.novas == 6 and antes.camera_provavel is None
    assert antes.modelo == "Bushnell 119837 (firmware BS598BWNx05232)" or antes.modelo.startswith("provável Bushnell")
    assert antes.padrao.startswith("MMDDNNNN")
    importar(ambiente["fabrica"], cartao, "P7", "Ponto 1", "Seca2026")
    nova = amostras.foto(dt.datetime(2026, 10, 29, 6, 0), "Bushnell", "119837")
    (cartao / "DCIM" / "100EK113" / "10290020.JPG").write_bytes(nova)
    with ambiente["fabrica"]() as s:
        depois = identificar(s, cartao, hoje=dt.datetime(2026, 10, 30))
        assert depois.ja_importadas == 6 and depois.novas == 1 and depois.camera_provavel == "P7"
        assert depois.ultima_midia.endswith("10290020.JPG") and depois.fonte_ultima_data == "exif"
        assert depois.dias_desde_ultima == 1
        cam = s.query(Camera).filter_by(etiqueta="P7").one()
        assert cam.modelo == "Bushnell 119837" and cam.firmware == "BS598BWNx05232"  # preenchido pelo EXIF


def test_identificar_mac_sem_fotos(ambiente, tmp_path):
    raiz = amostras.cartao_problemas(tmp_path / "c")
    with ambiente["fabrica"]() as s:
        assert identificar(s, raiz).appledouble_orfaos == 1


def test_identificar_bushnell_so_com_arquivos_de_mac(ambiente, tmp_path):
    # situação real observada: só restaram '._10200007.JPG' etc. na pasta 100EK113
    pasta = tmp_path / "c" / "DCIM" / "100EK113"
    pasta.mkdir(parents=True)
    (pasta / "._10200007.JPG").write_bytes(b"\x00\x05\x16\x07" + b"\x00" * 4092)
    with ambiente["fabrica"]() as s:
        ident = identificar(s, tmp_path / "c")
    assert ident.total_midias == 0 and ident.appledouble_orfaos == 1
    assert ident.modelo == "provável Bushnell (pasta 100EK113)"


def test_teste_sem_tela_gravacao_ok_sem_novos_e_nao_montou(ambiente, cartao, tmp_path):
    with ambiente["fabrica"]() as s:
        t1 = sem_tela.iniciar(s, cartao)
        (cartao / "DCIM" / "100EK113" / "10300030.JPG").write_bytes(amostras.foto(None))
        assert sem_tela.verificar(s, t1.id).resultado == "gravacao_ok"
        tamanho = (cartao / "DCIM/100EK113/10300030.JPG").stat().st_size
        assert sem_tela.verificar(s, t1.id).novos == [["DCIM/100EK113/10300030.JPG", tamanho]]
        t2 = sem_tela.iniciar(s, cartao)
        assert sem_tela.verificar(s, t2.id).resultado == "sem_novos"
        t3 = sem_tela.iniciar(s, cartao)
        shutil.move(str(cartao), str(tmp_path / "removido"))
        assert sem_tela.verificar(s, t3.id).resultado == "nao_montou"
        with pytest.raises(ValueError):
            sem_tela.iniciar(s, tmp_path / "nao-existe")


def test_dias_ativos_e_lacunas(ambiente, cartao):
    importar(ambiente["fabrica"], cartao, "P7", "Ponto 1", "Seca2026")
    with ambiente["fabrica"]() as s:
        cam = s.query(Camera).filter_by(etiqueta="P7").one()
        a = historico.atividade(s, cam.id)
    # fotos em 20/10, 21/10 e 24/10 (EXIF); o vídeo sem data interna é ignorado
    assert a.dias_com_registro == 3 and a.primeiro == dt.date(2026, 10, 20) and a.ultimo == dt.date(2026, 10, 24)
    assert a.lacunas == [(dt.date(2026, 10, 22), dt.date(2026, 10, 23), 2)] and a.midias_ignoradas == 1


def test_relogio_resetado_nao_conta_como_dia_ativo(ambiente, tmp_path):
    importar(ambiente["fabrica"], amostras.cartao_problemas(tmp_path / "c"), "MINI", "P2", "Seca2026")
    with ambiente["fabrica"]() as s:
        a = historico.atividade(s, s.query(Camera).filter_by(etiqueta="MINI").one().id)
    assert a.dias_com_registro == 0 and a.midias_ignoradas == 2


@pytest.fixture
def cliente(ambiente, cartao):
    return TestClient(criar_app(ambiente["fabrica"], sincrono=True, extras_cartoes=[str(cartao)])), cartao, ambiente


def test_web_diagnostico_e_sem_tela(cliente):
    c, cartao, amb = cliente
    r = c.get("/diagnostico", params={"origem": str(cartao)})
    assert r.status_code == 200 and "6 novas" in r.text and "Começar teste" in r.text
    assert c.get("/cartao/miniatura", params={"caminho": str(cartao / "DCIM/100EK113/10200007.JPG")}).status_code == 200
    r = c.post("/sem-tela/iniciar", data={"origem": str(cartao), "camera": "P4"}, follow_redirects=False)
    url = r.headers["location"]
    (cartao / "DCIM" / "100EK113" / "10300031.JPG").write_bytes(amostras.foto(None))
    r = c.post(url + "/verificar", follow_redirects=True)
    assert "Processador e gravação OK" in r.text and "TELA" in r.text
    with amb["fabrica"]() as s:  # resultado foi para o histórico da câmera
        cam = s.query(Camera).filter_by(etiqueta="P4").one()
        assert s.query(EventoCamera).filter_by(camera_id=cam.id).count() == 1


def test_miniatura_fora_do_cartao_e_dados_protegidos(cliente, tmp_path):
    c, _, amb = cliente
    externo = tmp_path / "fora.jpg"
    externo.write_bytes(amostras.foto(None))
    assert c.get("/cartao/miniatura", params={"caminho": str(externo)}).status_code == 404
    assert c.get("/dados/../banco.sqlite3").status_code == 404
    assert c.get("/dados/Seca2026/Ponto-1/P7/qualquer.jpg").status_code == 404  # só fotos de eventos


def test_web_eventos_com_foto_e_lista_de_cameras(cliente):
    c, cartao, amb = cliente
    c.post("/importar", data={"origem": str(cartao), "camera": "P7", "ponto": "Ponto 1", "campanha": "Seca2026"})
    with amb["fabrica"]() as s:
        cam_id = s.query(Camera).filter_by(etiqueta="P7").one().id
    r = c.post(f"/cameras/{cam_id}/eventos", data={"tipo": "pilhas", "data": "2026-10-25T09:00", "ponto": "Ponto 1",
                                                     "pilhas_marca": "Duracell", "pilhas_tipo": "alcalina AA"},
               files=[("fotos", ("campo.jpg", amostras.foto(None), "image/jpeg"))], follow_redirects=True)
    assert "Troca de pilhas" in r.text and "Duracell alcalina AA" in r.text and "foto 1" in r.text
    with amb["fabrica"]() as s:
        ev = s.query(EventoCamera).one()
        assert ev.fotos and (amb["dados"] / ev.fotos[0]).is_file()
        assert c.get(f"/dados/{ev.fotos[0]}").status_code == 200
    r = c.get("/cameras")
    assert "P7" in r.text and "Bushnell 119837" in r.text
    assert "3" in r.text  # dias com registro
    assert c.post(f"/cameras/{cam_id}/eventos", data={"tipo": "inventado", "data": "2026-10-25T09:00"}).status_code == 400


def test_web_roteiro_e_impressao(cliente):
    c, _, amb = cliente
    for ordem, ajuste, botoes in ((1, "Modo: foto", "MENU, OK, ↓, OK"), (2, "Resolução 8 MP", "MENU, ↓, ↓, OK, →, OK")):
        c.post("/roteiros", data={"modelo": "Bushnell 119837", "ordem": ordem, "ajuste": ajuste, "botoes": botoes})
    r = c.get("/roteiros", params={"modelo": "Bushnell 119837"})
    assert "Resolução 8 MP" in r.text and "MENU, ↓, ↓, OK, →, OK" in r.text
    r = c.get("/roteiros/imprimir", params={"modelo": "Bushnell 119837"})
    assert "Reset de fábrica" in r.text and "ainda não confirmado em campo" in r.text
    with amb["fabrica"]() as s:
        passo = s.query(PassoRoteiro).filter_by(ordem=1).one()
    c.post(f"/roteiros/{passo.id}/remover")
    with amb["fabrica"]() as s:
        assert s.query(PassoRoteiro).count() == 1


def test_web_checklist(cliente):
    c, cartao, amb = cliente
    c.post("/importar", data={"origem": str(cartao), "camera": "P7", "ponto": "Ponto 1", "campanha": "Seca2026"})
    from camtrap_campo.db import Campanha

    with amb["fabrica"]() as s:
        cmp_id = s.query(Campanha).filter_by(nome="Seca2026").one().id
    r = c.get(f"/campanhas/{cmp_id}/checklist")
    assert r.status_code == 200 and "Cartão formatado NA CÂMERA" in r.text and "Ponto 1" in r.text and "P7" in r.text
    assert c.get("/campanhas/999/checklist").status_code == 404
