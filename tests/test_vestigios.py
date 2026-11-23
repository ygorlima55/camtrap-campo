"""Vestígios: guia de referência, comparação (porcentagens), importação das fotos, validação, telas e campanhas."""

import datetime as dt
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image
from PIL.TiffImagePlugin import IFDRational
from sqlalchemy import func, select

from camtrap_campo import amostras
from camtrap_campo.db import Campanha, GuiaVestigio, Vestigio
from camtrap_campo.ia import especies
from camtrap_campo.vestigios import comparar, registro
from camtrap_campo.web import rotas_campanhas
from camtrap_campo.web.app import criar_app

ONCA = {"comprimento": 9.5, "largura": 10, "dedos": 4, "garras": "nao", "forma": "redonda"}


def _foto_gps(data: dt.datetime) -> bytes:
    im = Image.open(BytesIO(amostras.foto(data)))
    exif = im.getexif()
    gps = exif.get_ifd(0x8825)
    gps.update({1: "S", 2: tuple(IFDRational(x) for x in (15, 47, 30)), 3: "W", 4: tuple(IFDRational(x) for x in (47, 55, 0))})
    buf = BytesIO()
    im.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


@pytest.fixture
def pasta_vestigios(tmp_path):
    p = tmp_path / "fotos_vestigios"
    (p / "sub").mkdir(parents=True)
    (p / "pegada1.jpg").write_bytes(_foto_gps(dt.datetime(2026, 9, 1, 8, 30)))
    (p / "fezes1.JPG").write_bytes(amostras.foto(dt.datetime(2026, 9, 1, 9, 0)))
    (p / "sub" / "copia.jpg").write_bytes((p / "fezes1.JPG").read_bytes())  # mesma foto duas vezes
    (p / "anotacoes.txt").write_text("não é foto")
    return p


@pytest.fixture
def sessao(ambiente):
    with ambiente["fabrica"]() as s:
        especies.semear(s)
        comparar.semear(s)
        yield s


def test_guia_e_comparacao(sessao):
    assert comparar.semear(sessao) == 0  # não duplica
    top = comparar.comparar(sessao, "pegada", ONCA)
    # com essas medidas onça-pintada e onça-parda empatam (é o caso real: só a forma dos dedos e da almofada separa)
    assert {c["nome_cientifico"] for c in top[:2]} == {"Panthera onca", "Puma concolor"} and top[0]["nota"] == 1
    assert top[1]["porcentagem"] > 2 * top[2]["porcentagem"] and sum(c["porcentagem"] for c in top) <= 101
    assert {c["nome_cientifico"] for c in top} <= {"Panthera onca", "Puma concolor", "Leopardus pardalis", "Tapirus terrestris",
                                                    "Hydrochoerus hydrochaeris", "Myrmecophaga tridactyla", "Priodontes maximus",
                                                    "Bos taurus", "Procyon cancrivorus", "Canis familiaris"}
    assert all(m["ok"] for m in top[0]["motivos"])
    canideo = comparar.comparar(sessao, "pegada", {"comprimento": 4.8, "largura": 3.8, "dedos": 4,
                                                     "garras": "sim", "forma": "oval"})
    assert canideo[0]["nome_cientifico"] == "Cerdocyon thous"
    lontra = comparar.comparar(sessao, "fezes", {"diametro": 1.5, "conteudo": ["escamas_peixe"], "local": ["agua"]})
    assert lontra[0]["nome_cientifico"] == "Lontra longicaudis"
    sinal = comparar.comparar(sessao, "sinal", {"sinal": "cupinzeiro_aberto"})
    assert {c["nome_cientifico"] for c in sinal[:2]} == {"Myrmecophaga tridactyla", "Tamandua tetradactyla"}
    assert comparar.comparar(sessao, "pegada", {}) == []
    estranho = comparar.comparar(sessao, "pegada", {"comprimento": 40, "largura": 40})  # nada no guia tem esse tamanho
    assert comparar.ajuste_fraco(estranho)


def test_limpar_ficha():
    c = comparar.limpar("pegada", {"comprimento": "8,5", "largura": "", "dedos": "4", "garras": "nao sei", "forma": "redonda",
                                   "conteudo": ["pelos"]})
    assert c == {"comprimento": 8.5, "dedos": 4, "forma": "redonda"}  # ignora campo de outro tipo e opção inválida
    assert comparar.limpar("fezes", {"conteudo": ["pelos", "xyz"], "forma": "redonda"}) == {"conteudo": ["pelos"]}
    with pytest.raises(ValueError):
        comparar.limpar("pena", {})
    with pytest.raises(ValueError):
        comparar.limpar("pegada", {"dedos": "7"})


def test_importar_caracterizar_validar(ambiente, sessao, pasta_vestigios):
    antes = sorted(p.name for p in pasta_vestigios.rglob("*"))
    res = registro.importar_pasta(sessao, pasta_vestigios, "Seca2026", "Trilha 1", None)
    assert (res["novos"], res["duplicados"], res["erros"]) == (2, 1, [])
    assert sorted(p.name for p in pasta_vestigios.rglob("*")) == antes  # origem intacta
    v = sessao.scalars(select(Vestigio).order_by(Vestigio.data)).first()
    assert v.caminho_final.startswith("Seca2026/_vestigios/Trilha-1/") and (ambiente["dados"] / v.caminho_final).is_file()
    assert v.data == dt.datetime(2026, 9, 1, 8, 30) and v.fonte_data == "exif"
    assert v.latitude == pytest.approx(-15.7917, abs=1e-3) and v.longitude == pytest.approx(-47.9167, abs=1e-3)
    assert registro.importar_pasta(sessao, pasta_vestigios, "Seca2026")["novos"] == 0  # reimportar não duplica

    registro.caracterizar(sessao, v, "pegada", {k: str(x) for k, x in ONCA.items()})
    assert v.sugestoes[0]["nome_cientifico"] == "Panthera onca"
    eid = registro.especie_do_guia(sessao, "Panthera onca", "onça-pintada")
    registro.validar(sessao, v, "especie", eid)
    assert v.resultado == "especie" and v.sugestao_aceita is True
    outro = sessao.scalars(select(Vestigio).order_by(Vestigio.data)).all()[1]
    registro.validar(sessao, outro, "indeterminado")
    q = registro.quadro(sessao)
    assert (q["total"], q["validados"], q["sem_ficha"], q["acertos"], q["com_sugestao"]) == (2, 2, 0, 1, 1)
    assert q["especies"][0]["especie"].nome_cientifico == "Panthera onca" and q["especies"][0]["pegada"] == 1
    registro.validar(sessao, v, "limpar")
    assert v.resultado is None and registro.quadro(sessao, estado="a_validar")["itens"] == [v]
    with pytest.raises(ValueError):
        registro.validar(sessao, v, "especie", 99999)


def test_telas_vestigios(ambiente, pasta_vestigios):
    c = TestClient(criar_app(ambiente["fabrica"], sincrono=True, extras_cartoes=[]))
    assert 'href="/vestigios"' in c.get("/").text and 'href="/campanhas"' in c.get("/").text  # itens no menu
    form = c.get("/vestigios/importar", params={"origem": str(pasta_vestigios)})
    assert "3</strong> foto(s)" in form.text
    r = c.post("/vestigios/importar", data={"origem": str(pasta_vestigios), "campanha": "Seca2026", "ponto": "",
                                                 "tipo": "pegada"})
    assert r.status_code == 200 and "2 foto(s) importada(s)" in r.text and "1 já estavam" in r.text
    with ambiente["fabrica"]() as s:
        vid = s.scalar(select(Vestigio.id).order_by(Vestigio.data))
    assert c.get(f"/vestigios/{vid}/foto").headers["content-type"] == "image/jpeg"
    ficha = c.get(f"/vestigios/{vid}")
    assert "Ficha do vestígio" in ficha.text and "Preencha a ficha" in ficha.text
    r = c.post(f"/vestigios/{vid}/ficha", data={"tipo": "pegada", **{k: str(x) for k, x in ONCA.items()}, "observacao": "lama"})
    assert "onça-pintada" in r.text and "É onça-pintada (1)" in r.text and "%</b>" in r.text
    r = c.post(f"/vestigios/{vid}/validar", data={"resultado": "especie", "guia_nome": "Panthera onca", "seguir": "1"})
    assert r.url.path != f"/vestigios/{vid}"  # foi para o próximo sem validação
    quadro = c.get("/vestigios").text
    assert "✓ onça-pintada" in quadro and "Espécies confirmadas por vestígios" in quadro
    assert c.post(f"/vestigios/{vid}/ficha", data={"tipo": "pena"}).status_code == 400

    guia = c.get("/vestigios/guia", params={"tipo": "fezes"})
    assert "lontra" in guia.text and "Becker" in guia.text
    with ambiente["fabrica"]() as s:
        gid = s.scalar(select(GuiaVestigio.id).where(GuiaVestigio.tipo == "pegada",
                                                     GuiaVestigio.nome_cientifico == "Puma concolor"))
    c.post(f"/vestigios/guia/{gid}", data={"comprimento_min": "8", "comprimento_max": "12,5", "largura_min": "7",
                                           "largura_max": "11", "dedos": "4", "garras": "nao", "_forma": "1",
                                           "forma": "redonda", "descricao": "ajustado"})
    with ambiente["fabrica"]() as s:
        g = s.get(GuiaVestigio, gid)
        assert g.dados["comprimento"] == [8, 12.5] and g.editada and not g.ativa  # sem "ativa" = fora da comparação

    xlsx = c.get("/vestigios/planilha")
    wb = load_workbook(BytesIO(xlsx.content))
    assert wb.sheetnames == ["Vestígios", "Espécies (validadas)", "Sobre"]
    assert wb["Vestígios"]["I2"].value == "onça-pintada" and wb["Vestígios"]["O2"].value == "onça-pintada"


def test_campanhas(ambiente, tmp_path, pasta_vestigios, monkeypatch):
    cartao = amostras.cartao_bushnell(tmp_path / "cartao")
    c = TestClient(criar_app(ambiente["fabrica"], sincrono=True, extras_cartoes=[]))
    c.post("/importar", data={"origem": str(cartao), "camera": "P7", "ponto": "Ponto 1", "campanha": "Seca2026"})
    c.post("/vestigios/importar", data={"origem": str(pasta_vestigios), "campanha": "Seca2026"})
    lista = c.get("/campanhas").text
    assert "Seca2026" in lista and "<strong>5</strong> fotos" in lista and "2 vestígio(s)" in lista
    with ambiente["fabrica"]() as s:
        cid = s.scalar(select(Campanha.id).where(Campanha.nome == "Seca2026"))
    pag = c.get(f"/campanhas/{cid}")
    assert pag.text.count("/miniatura?tamanho=300") == 5 and "Seca2026\\Ponto-1\\P7" in pag.text
    assert "/vestigios/" in pag.text and "Abrir pasta" in pag.text
    videos = c.get(f"/campanhas/{cid}", params={"tipo": "video"})
    assert "▶ vídeo" in videos.text and "1 arquivo(s)" in videos.text
    abertas = []
    monkeypatch.setattr(rotas_campanhas, "abrir_no_explorer", abertas.append)
    assert c.post(f"/campanhas/{cid}/abrir", data={"pasta": "Seca2026/Ponto-1/P7"}).status_code == 200
    assert abertas and abertas[0].name == "P7"
    assert c.post(f"/campanhas/{cid}/abrir", data={"pasta": "../.."}, follow_redirects=False).status_code == 400


def test_arquivos_danificados_na_importacao(ambiente, tmp_path):
    """Cartão recuperado: foto/vídeo só com zeros ou embaralhados são guardados à parte, sem lixo em .parcial."""
    from camtrap_campo.db import Alerta, Arquivo, Importacao
    from camtrap_campo.importacao.copiar import importar

    cartao = amostras.cartao_bushnell(tmp_path / "cartao")
    pasta = cartao / "DCIM" / "100EK113"
    (pasta / "ZERADA01.JPG").write_bytes(bytes(5000))
    (pasta / "EMBARALHADA.JPG").write_bytes(b"\x12\x34" * 4000)
    (pasta / "ZERADO.AVI").write_bytes(bytes(9000))
    imp_id = importar(ambiente["fabrica"], cartao, "P7", "Ponto 1", "Seca2026")
    with ambiente["fabrica"]() as s:
        imp = s.get(Importacao, imp_id)
        danificados = s.scalars(select(Arquivo).where(Arquivo.tipo == "danificado")).all()
        assert imp.estado == "concluida" and imp.erros == 0
        assert sorted(a.nome_original for a in danificados) == ["EMBARALHADA.JPG", "ZERADA01.JPG", "ZERADO.AVI"]
        assert all("/_danificados/" in a.caminho_final and (ambiente["dados"] / a.caminho_final).is_file() for a in danificados)
        assert "zerado" in next(a.detalhe for a in danificados if a.nome_original == "ZERADO.AVI")
        alerta = s.scalar(select(Alerta).where(Alerta.tipo == "danificados"))
        assert alerta and alerta.mensagem.startswith("3 foto(s)/vídeo(s) danificado(s)")
        assert s.scalar(select(func.count()).select_from(Arquivo).where(Arquivo.tipo == "foto")) == 5
    assert not list((ambiente["dados"]).rglob(".parcial/*"))


def test_tempo_restante_e_porcentagem(ambiente, monkeypatch):
    from camtrap_campo.web.app import tempo_restante

    agora = dt.datetime.now()
    assert tempo_restante(agora - dt.timedelta(minutes=10), 10, 30) == "≈ 20 min restantes"
    assert tempo_restante(agora - dt.timedelta(hours=1), 10, 40) == "≈ 3,0 h restantes"
    assert tempo_restante(agora - dt.timedelta(seconds=30), 29, 30) == "≈ menos de 1 min restante"
    assert tempo_restante(None, 5, 10) == "" and tempo_restante(agora, 0, 10) == "" and tempo_restante(agora, 10, 10) == ""
    from camtrap_campo.db import Tarefa
    with ambiente["fabrica"]() as s:
        s.add(Tarefa(tipo="ia", estado="executando", total=40, feitos=10, iniciada_em=agora - dt.timedelta(minutes=5)))
        s.commit()
    c = TestClient(criar_app(ambiente["fabrica"], sincrono=True, extras_cartoes=[]))
    lista = c.get("/tarefas/lista").text
    assert "<b>25%</b>" in lista and "≈ 15 min restantes" in lista
