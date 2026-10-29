"""Leitura de metadados: EXIF (Pillow), interpretação da faixa do rodapé e vídeo AVI."""

import datetime as dt

import pytest

from camtrap_campo import amostras
from camtrap_campo.metadados.exif import ler_exif
from camtrap_campo.metadados.rodape import interpretar_texto, ler_rodape
from camtrap_campo.metadados.video import ler_video


def test_exif_sintetico(tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(amostras.foto(dt.datetime(2026, 10, 20, 5, 42, 10), "Bushnell", "119837", "BS598BWNx05232"))
    e = ler_exif(p)
    assert e["data"] == "2026-10-20T05:42:10" and e["Make"] == "Bushnell" and e["Software"] == "BS598BWNx05232"


def test_exif_sem_data(tmp_path):
    p = tmp_path / "b.jpg"
    p.write_bytes(amostras.foto(None))
    assert ler_exif(p)["data"] is None


def test_rodape_bushnell_em_ingles():
    r = interpretar_texto("10/20/2026 05:42 AM  25C  P7", dt.datetime(2026, 10, 20, 5, 42))
    assert r["data"] == "2026-10-20T05:42:00" and r["temperatura_c"] == 25.0 and r["nome_camera"] == "P7"
    assert "ícone" in r["fase_lua"]  # não inventa a fase da lua


def test_rodape_fahrenheit_e_pm():
    r = interpretar_texto("03/05/2026 11:15 PM 77F CAM-A", None)
    assert r["temperatura_c"] == 25.0 and r["temperatura_original"] == "77F"
    assert r["data"].endswith("T23:15:00") and len(r["data_ambigua"]) == 2


def test_rodape_ambiguo_resolvido_pelo_exif():
    r = interpretar_texto("10/11/2026 08:00", dt.datetime(2026, 11, 10, 8, 0))
    assert r["data"] == "2026-11-10T08:00:00"  # DD/MM, o mais próximo do EXIF
    r = interpretar_texto("10/11/2026 08:00", dt.datetime(2026, 10, 11, 8, 0))
    assert r["data"] == "2026-10-11T08:00:00"  # MM/DD


def test_rodape_sem_tesseract_informa(tmp_path, monkeypatch):
    import camtrap_campo.metadados.rodape as mod

    monkeypatch.setattr(mod, "localizar_ferramenta", lambda nome: None)
    p = tmp_path / "c.jpg"
    p.write_bytes(amostras.foto(dt.datetime(2026, 1, 1), rodape="01/01/2026 10:00 AM 20C P4"))
    assert ler_rodape(p) == {"disponivel": False, "motivo": "Tesseract não instalado"}


def test_rodape_ocr_real(tmp_path):
    import camtrap_campo.metadados.rodape as mod

    if not mod.localizar_ferramenta("tesseract"):
        pytest.skip("Tesseract não instalado")
    p = tmp_path / "d.jpg"
    d = dt.datetime(2026, 10, 20, 5, 42)
    p.write_bytes(amostras.foto(d, rodape="10/20/2026 05:42 AM  25C  P7", tamanho=(1920, 1080)))
    r = ler_rodape(p, d)
    assert r["data"] == "2026-10-20T05:42:00"


def test_video_avi_sem_ffmpeg(tmp_path, monkeypatch):
    import camtrap_campo.metadados.video as mod

    monkeypatch.setattr(mod, "localizar_ferramenta", lambda nome: None)
    p = tmp_path / "v.avi"
    p.write_bytes(amostras.avi(quadros=150))
    v = ler_video(p)
    assert v["fonte"] == "cabecalho_avi" and v["quadros"] == 150 and v["duracao_s"] == pytest.approx(5.0, abs=0.01)
    assert v["largura"] == 1920 and "FFmpeg não instalado" in v["aviso"]
