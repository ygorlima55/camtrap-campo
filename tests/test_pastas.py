"""Importar de pastas do computador (sem DCIM): resumo, validação, lista salva, escolha pelo Windows e importação."""

import datetime as dt
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from camtrap_campo import amostras
from camtrap_campo.db import Arquivo, Importacao
from camtrap_campo.importacao import detectar, pastas
from camtrap_campo.importacao.detectar import detectar_cartoes, resumir, resumir_pastas
from camtrap_campo.web.app import criar_app


def _pasta_de_teste(raiz):
    """Registros salvos no computador, sem DCIM, com subpasta e um arquivo que não é mídia."""
    sub = raiz / "Câmera P7" / "out-2026"
    sub.mkdir(parents=True)
    for i in range(3):
        (sub / f"IMG_{i:04d}.JPG").write_bytes(amostras.foto(dt.datetime(2026, 10, 1, 6, i)))
    (raiz / "Câmera P7" / "anotacoes.txt").write_text("teste", encoding="utf-8")
    return raiz / "Câmera P7"


@pytest.fixture
def cliente(ambiente):
    return TestClient(criar_app(ambiente["fabrica"], sincrono=True, extras_cartoes=[]))


def test_resumo_de_pasta_sem_dcim(tmp_path):
    p = _pasta_de_teste(tmp_path)
    r = resumir(p)
    assert (r.tipo, r.fotos, r.videos, r.tem_dcim, r.nome) == ("pasta", 3, 0, False, "Câmera P7")
    assert r.ultima_midia.endswith("IMG_0002.JPG")
    assert detectar_cartoes([str(p)]) == [] or all(c.raiz != str(p) for c in detectar_cartoes([str(p)]))  # não é cartão


def test_resumo_de_pastas_usa_cache_e_ignora_sumidas(tmp_path, monkeypatch):
    p = _pasta_de_teste(tmp_path)
    detectar._cache.clear()
    assert [c.fotos for c in resumir_pastas([str(p), str(tmp_path / "nao-existe")])] == [3]
    (p / "out-2026" / "IMG_9999.JPG").write_bytes(amostras.foto(None))
    assert resumir_pastas([str(p)])[0].fotos == 3  # ainda no cache (o painel atualiza a cada 6 s)
    monkeypatch.setattr(detectar, "CACHE_PASTAS_S", 0)
    assert resumir_pastas([str(p)])[0].fotos == 4


def test_validar_caminho(ambiente, tmp_path):
    p = _pasta_de_teste(tmp_path)
    assert pastas.validar(f'  "{p}"  ') == p.resolve()  # aceita o "Copiar como caminho" do Explorador (com aspas)
    for ruim, trecho in [("", "Informe"), ("relativa/pasta", "caminho completo"), (str(tmp_path / "x"), "não existe")]:
        with pytest.raises(ValueError, match=trecho):
            pastas.validar(ruim)
    ambiente["dados"].mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="guarda as importações"):
        pastas.validar(str(ambiente["dados"]))
    with pytest.raises(ValueError, match="contém a pasta de dados"):
        pastas.validar(str(ambiente["dados"].parent))


def test_lista_de_pastas_no_inicio(ambiente, cliente, tmp_path):
    p = _pasta_de_teste(tmp_path / "fotos")
    detectar._cache.clear()
    r = cliente.post("/pastas", data={"caminho": str(p)}, follow_redirects=False)
    assert r.status_code == 303 and "adicionada" in r.headers["location"]
    cliente.post("/pastas", data={"caminho": str(p)})  # repetida não duplica
    with ambiente["fabrica"]() as s:
        assert pastas.listar(s) == [str(p.resolve())]
    html = cliente.get("/").text
    assert "Câmera P7" in html and "Importar esta pasta" in html and "Tirar da lista" in html
    assert "pronta para importar" in html  # próximo passo aponta a pasta ainda não importada
    assert "Importar de uma pasta do computador" in html and 'id="nova-pasta"' in html
    assert 'id="nova-pasta"' not in cliente.get("/painel").text  # formulário fica fora da área que se atualiza

    erro = cliente.post("/pastas", data={"caminho": str(tmp_path / "nao-existe")}, follow_redirects=False)
    assert "não existe" in parse_qs(urlparse(erro.headers["location"]).query)["erro"][0]
    assert "não existe" in cliente.get(erro.headers["location"]).text

    cliente.post("/pastas/remover", data={"caminho": str(p.resolve())})
    with ambiente["fabrica"]() as s:
        assert pastas.listar(s) == []
    assert (p / "out-2026" / "IMG_0000.JPG").exists()  # tirar da lista não mexe nos arquivos


def test_escolher_pasta_pela_janela_do_windows(ambiente, cliente, tmp_path, monkeypatch):
    p = _pasta_de_teste(tmp_path)
    monkeypatch.setattr(pastas, "escolher_no_windows", lambda: str(p))
    assert "adicionada" in cliente.post("/pastas/escolher", follow_redirects=False).headers["location"]
    monkeypatch.setattr(pastas, "escolher_no_windows", lambda: None)  # cancelou a janela
    assert cliente.post("/pastas/escolher", follow_redirects=False).headers["location"] == "/"
    with ambiente["fabrica"]() as s:
        assert pastas.listar(s) == [str(p.resolve())]


def test_importar_de_pasta_sem_dcim(ambiente, cliente, tmp_path):
    p = _pasta_de_teste(tmp_path)
    assert "3 fotos" in cliente.get("/importar", params={"origem": str(p)}).text
    r = cliente.post("/importar", data={"origem": str(p), "camera": "P7", "ponto": "Teste", "campanha": "Testes"},
                     follow_redirects=False)
    assert r.status_code == 303
    with ambiente["fabrica"]() as s:
        imp = s.query(Importacao).one()
        arquivos = s.query(Arquivo).filter_by(importacao_id=imp.id).all()
        assert imp.estado == "concluida" and imp.copiados == 4  # 3 fotos + o .txt (vai para _cartao_original)
        assert sorted(a.tipo for a in arquivos) == ["foto", "foto", "foto", "outro"]
    assert len(list(p.rglob("*.JPG"))) == 3  # a pasta de origem fica intacta
    vazia = tmp_path / "vazia"
    vazia.mkdir()
    dados = {"camera": "P7", "ponto": "T", "campanha": "T"}
    assert cliente.post("/importar", data={"origem": str(vazia), **dados}).status_code == 400
    ambiente["dados"].mkdir(parents=True, exist_ok=True)
    assert cliente.post("/importar", data={"origem": str(ambiente["dados"]), "camera": "P7", "ponto": "T",
                                           "campanha": "T"}).status_code == 400
