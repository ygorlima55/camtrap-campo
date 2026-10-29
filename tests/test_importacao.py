"""Módulo 1: importação, renomeação, hash, duplicatas, alertas e correção de horário (cartões sintéticos)."""

import datetime as dt
import hashlib

import pytest

from camtrap_campo import amostras
from camtrap_campo.db import Alerta, Arquivo, Camera, Importacao
from camtrap_campo.importacao.copiar import importar, nome_final, sanitizar
from camtrap_campo.importacao.detectar import detectar_cartoes, resumir
from camtrap_campo.importacao.horario import aplicar_correcao
from camtrap_campo.importacao.padroes import classificar, detectar_padrao


def _hashes(raiz):
    return {p.relative_to(raiz).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in raiz.rglob("*") if p.is_file()}


@pytest.mark.parametrize(("nome", "esperado"), [
    ("10200007", ("MMDD+contador", 7, None)), ("DSCF0012", ("prefixo+contador", 12, "DSCF")),
    ("MFDC0594", ("prefixo+contador", 594, "MFDC")), ("13450001", ("numerico", 13450001, None)),
    ("foto_qualquer", ("desconhecido", None, None)),
])
def test_classificar_nomes(nome, esperado):
    assert classificar(nome) == esperado


def test_detectar_padrao_predominante():
    assert detectar_padrao(["10200007", "10200008", "10210009"])["padrao"] == "MMDD+contador"
    p = detectar_padrao(["DSCF0001", "DSCF0002", "IMAG0003"])
    assert p["descricao"] == "DSCFNNNN" and p["proporcao"] == 1.0


def test_resumo_do_cartao(tmp_path):
    raiz = amostras.cartao_bushnell(tmp_path / "cartao")
    c = resumir(raiz)
    assert c.tem_dcim and c.pastas_dcim == ["100EK113"] and c.fotos == 5 and c.videos == 1
    assert c.ultima_midia.endswith("0012.AVI")  # mesmo horário de arquivo: decide o contador
    assert str(raiz) in [x.raiz for x in detectar_cartoes([str(raiz)])]  # pode haver cartões reais também


def test_nome_final_padrao():
    nome = nome_final("Campanha Seca 2026", "Ponto Ângelo", "P7", dt.datetime(2026, 10, 20, 5, 42, 10), 7, ".JPG")
    assert nome == "Campanha-Seca-2026_Ponto-Angelo_P7_20261020_054210_0007.jpg"
    assert sanitizar("  ") == "sem-nome"


def test_importacao_bushnell_completa(ambiente, tmp_path):
    raiz = amostras.cartao_bushnell(tmp_path / "cartao")
    antes = _hashes(raiz)
    imp_id = importar(ambiente["fabrica"], raiz, "P7", "Ponto 1", "Seca2026")
    assert _hashes(raiz) == antes  # cartão intacto
    with ambiente["fabrica"]() as s:
        imp = s.get(Importacao, imp_id)
        assert imp.estado == "concluida" and imp.copiados == 6 and imp.erros == 0 and imp.duplicados == 0
        assert imp.padrao_nomes.startswith("MMDDNNNN")
        assert imp.modelo_detectado == "Bushnell 119837 (firmware BS598BWNx05232)"
        fotos = [a for a in imp.arquivos if a.tipo == "foto"]
        assert all(a.fonte_data == "exif" for a in fotos)
        primeira = min(fotos, key=lambda a: a.data_original)
        assert primeira.nome_original == "10200007.JPG"
        assert primeira.caminho_final == "Seca2026/Ponto-1/P7/Seca2026_Ponto-1_P7_20261020_054210_0007.jpg"
        for a in imp.arquivos:  # cada cópia confere com o hash do cartão
            assert hashlib.sha256((ambiente["dados"] / a.caminho_final).read_bytes()).hexdigest() == a.sha256
        video = next(a for a in imp.arquivos if a.tipo == "video")
        assert video.video["quadros"] == 300 and video.video["duracao_s"] == pytest.approx(10.0, abs=0.01)
        tipos = [al.tipo for al in imp.alertas]
        # só o buraco real entre as fotos (30 h → 100 h); o vídeo sem data interna não cria intervalo falso
        assert tipos.count("intervalo_sem_fotos") == 1 and "relogio_resetado" not in tipos
        assert s.get(Camera, imp.camera_id).ultimo_ponto_id == imp.ponto_id  # lembra a última escolha


def test_reimportacao_nao_duplica(ambiente, tmp_path):
    raiz = amostras.cartao_bushnell(tmp_path / "cartao")
    importar(ambiente["fabrica"], raiz, "P7", "Ponto 1", "Seca2026")
    segunda = importar(ambiente["fabrica"], raiz, "P7", "Ponto 1", "Seca2026")
    with ambiente["fabrica"]() as s:
        imp = s.get(Importacao, segunda)
        assert imp.copiados == 0 and imp.duplicados == 6
        assert all(a.duplicado_de_id for a in imp.arquivos)
    arquivos = [p for p in ambiente["dados"].rglob("*") if p.is_file()]
    assert len(arquivos) == 6  # nenhuma cópia extra


def test_alertas_mac_relogio_e_ocultos(ambiente, tmp_path):
    raiz = amostras.cartao_problemas(tmp_path / "cartao")
    imp_id = importar(ambiente["fabrica"], raiz, "MINI", "Ponto 2", "Seca2026")
    with ambiente["fabrica"]() as s:
        imp = s.get(Importacao, imp_id)
        por_tipo = {}
        for al in imp.alertas:
            por_tipo.setdefault(al.tipo, []).append(al)
        assert len(por_tipo["mac_sem_foto"]) == 1 and "DSCF0003.JPG" in por_tipo["mac_sem_foto"][0].mensagem
        assert "relogio_resetado" in por_tipo
        mac = [a for a in imp.arquivos if a.tipo == "appledouble"]
        assert len(mac) == 2 and all(a.oculto and a.caminho_final.startswith("Seca2026/Ponto-2/MINI/_cartao_original/")
                                     for a in mac)
        cfg = next(a for a in imp.arquivos if a.nome_original == "SDFS_CFG.BIN")
        assert cfg.caminho_final.endswith("_cartao_original/SDFS_CFG.BIN") and cfg.estado == "copiado"


def test_cartao_vazio(ambiente, tmp_path):
    (tmp_path / "vazio" / "DCIM" / "100MEDIA").mkdir(parents=True)
    imp_id = importar(ambiente["fabrica"], tmp_path / "vazio", "P4", "Ponto 3", "Seca2026")
    with ambiente["fabrica"]() as s:
        assert [a.tipo for a in s.get(Importacao, imp_id).alertas] == ["cartao_vazio"]


def test_correcao_de_horario(ambiente, tmp_path):
    raiz = amostras.cartao_problemas(tmp_path / "cartao")
    imp_id = importar(ambiente["fabrica"], raiz, "MINI", "Ponto 2", "Seca2026")
    with ambiente["fabrica"]() as s:
        ref = s.query(Arquivo).filter_by(importacao_id=imp_id, nome_original="DSCF0001.JPG").one()
        delta = aplicar_correcao(s, imp_id, ref.id, dt.datetime(2026, 10, 25, 9, 30, 0))
        assert delta == int((dt.datetime(2026, 10, 25, 9, 30) - dt.datetime(2000, 1, 1, 0, 0, 12)).total_seconds())
        outra = s.query(Arquivo).filter_by(importacao_id=imp_id, nome_original="DSCF0002.JPG").one()
        assert outra.data_original == dt.datetime(2000, 1, 1, 0, 1, 40)  # original guardada
        assert outra.data_corrigida == dt.datetime(2026, 10, 25, 9, 31, 28)
        assert outra.caminho_final.endswith("_20261025_093128_0002.jpg")
        assert (ambiente["dados"] / outra.caminho_final).is_file()
        with pytest.raises(ValueError):
            aplicar_correcao(s, imp_id, 999, dt.datetime(2026, 1, 1))


def test_origem_inexistente_falha_sem_quebrar(ambiente, tmp_path):
    imp_id = importar(ambiente["fabrica"], tmp_path / "nao-existe", "P4", "X", "Y")
    with ambiente["fabrica"]() as s:
        imp = s.get(Importacao, imp_id)
        assert imp.total == 0 and not s.query(Alerta).filter_by(tipo="erro_copia").all()
