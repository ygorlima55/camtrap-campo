"""Vídeos e áudio com o FFmpeg real. Os vídeos são gerados na hora pelo próprio FFmpeg (imagem de teste + tom de 440 Hz)."""

import subprocess
import wave

import pytest
from sqlalchemy import select

from camtrap_campo import amostras, config
from camtrap_campo.db import Arquivo, Inferencia
from camtrap_campo.ia import especies, fila, midia
from camtrap_campo.importacao.copiar import importar
from camtrap_campo.metadados.video import ler_video

FFMPEG = config.localizar_ferramenta("ffmpeg")
pytestmark = pytest.mark.skipif(not FFMPEG, reason="FFmpeg não instalado")


def _video(destino, segundos=3, audio=True, quando="2026-10-24T05:42:10Z"):
    """AVI MJPEG + PCM (formato comum em armadilhas fotográficas) ou MP4, conforme a extensão.

    A data vai com "Z" para o FFmpeg gravá-la literalmente, como as câmeras fazem (relógio local, sem fuso).
    """
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=10:duration={segundos}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=32000:duration={segundos}"]
    if destino.suffix.lower() == ".avi":
        cmd += ["-c:v", "mjpeg", "-q:v", "5"] + (["-c:a", "pcm_s16le"] if audio else [])
    else:
        cmd += ["-c:v", "mpeg4"] + (["-c:a", "aac"] if audio else [])
    destino.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd + ["-metadata", f"creation_time={quando}", str(destino)], check=True, capture_output=True)
    return destino


@pytest.mark.parametrize("nome", ["v.AVI", "v.MP4"])
def test_ler_video_com_ffprobe(tmp_path, nome):
    v = ler_video(_video(tmp_path / nome))
    assert v["fonte"] == "ffprobe" and v["largura"] == 320 and v["altura"] == 240 and v["tem_audio"]
    assert v["duracao_s"] == pytest.approx(3, abs=0.2) and v["fps"] == 10
    if nome.endswith("MP4"):
        assert v["data"] == "2026-10-24T05:42:10"
    assert not ler_video(_video(tmp_path / "mudo.AVI", audio=False))["tem_audio"]


def test_quadros_e_audio(tmp_path):
    v = _video(tmp_path / "v.AVI")
    quadros = midia.extrair_quadros(v, tmp_path / "q")
    assert [s for s, _ in quadros] == [0, 1, 2] and all(q.stat().st_size > 0 for _, q in quadros)
    wav = midia.extrair_audio(v, tmp_path / "a" / "v.wav")
    with wave.open(str(wav)) as w:
        assert (w.getframerate(), w.getsampwidth(), w.getnchannels()) == (32000, 2, 1)  # taxa original, 16 bits
        assert w.getnframes() / w.getframerate() == pytest.approx(3, abs=0.1)
    assert midia.extrair_audio(_video(tmp_path / "mudo.AVI", audio=False), tmp_path / "a" / "mudo.wav") is None


def test_fluxo_importacao_ia_e_audio(ambiente, tmp_path, monkeypatch):
    """Cartão com fotos + vídeo real: a importação lê o vídeo, a IA (simulada) analisa os quadros e o áudio vira WAV."""
    monkeypatch.setenv("CAMTRAP_IA_SIMULADA", "1")
    cartao = amostras.cartao_bushnell(tmp_path / "cartao")
    falso = next((cartao / "DCIM" / "100EK113").glob("*.AVI"))
    falso.unlink()
    _video(falso)  # mesmo nome, agora um vídeo de verdade
    imp = importar(ambiente["fabrica"], cartao, "P7", "Ponto 1", "Seca2026")
    with ambiente["fabrica"]() as s:
        especies.semear(s)
        video = s.scalar(select(Arquivo).where(Arquivo.importacao_id == imp, Arquivo.tipo == "video"))
        assert video.estado == "copiado" and video.video["fonte"] == "ffprobe"
        t_ia, t_audio = fila.criar_tarefa(s, "ia", imp), fila.criar_tarefa(s, "audio", imp)
    assert fila.executar(ambiente["fabrica"], t_ia.id) == "concluida"
    assert fila.executar(ambiente["fabrica"], t_audio.id) == "concluida"
    with ambiente["fabrica"]() as s:
        ia = s.scalar(select(Inferencia).where(Inferencia.arquivo_id == video.id, Inferencia.etapa == "ia"))
        assert ia.erro is None and ia.quadros == 3 and ia.simulado
        au = s.scalar(select(Inferencia).where(Inferencia.arquivo_id == video.id, Inferencia.etapa == "audio"))
        wav = ambiente["dados"] / au.resultado["wav"]
    assert wav.is_file() and "_audio" in wav.parts and wav.suffix == ".wav"
