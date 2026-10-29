"""Quadros de vídeo (para a IA) e áudio WAV (para o futuro sistema de cantos de aves e anuros), via FFmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path

from camtrap_campo.config import localizar_ferramenta


class FFmpegAusente(RuntimeError):
    pass


def _ffmpeg() -> str:
    exe = localizar_ferramenta("ffmpeg")
    if not exe:
        raise FFmpegAusente("FFmpeg não instalado (install.bat → FFmpeg)")
    return exe


def extrair_quadros(video: Path, destino: Path, por_segundo: float = 1.0) -> list[tuple[float, Path]]:
    """Extrai quadros (JPEG) a ``por_segundo``; devolve [(segundo, caminho)]. O vídeo é só lido."""
    destino.mkdir(parents=True, exist_ok=True)
    for antigo in destino.glob("q_*.jpg"):
        antigo.unlink()
    subprocess.run([_ffmpeg(), "-v", "error", "-i", str(video), "-vf", f"fps={por_segundo}", "-q:v", "3",
                    str(destino / "q_%05d.jpg")], check=True, capture_output=True, timeout=1800)
    quadros = sorted(destino.glob("q_*.jpg"))
    return [((i) / por_segundo, q) for i, q in enumerate(quadros)]


def tem_audio(video: Path) -> bool:
    exe = localizar_ferramenta("ffprobe")
    if not exe:
        raise FFmpegAusente("FFprobe não instalado")
    proc = subprocess.run([exe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type",
                           "-of", "csv=p=0", str(video)], capture_output=True, timeout=120)
    return b"audio" in proc.stdout


def extrair_audio(video: Path, wav: Path) -> Path | None:
    """WAV PCM 16 bits na taxa original. Devolve None se o vídeo não tiver áudio."""
    if not tem_audio(video):
        return None
    wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([_ffmpeg(), "-v", "error", "-y", "-i", str(video), "-vn", "-acodec", "pcm_s16le", str(wav)],
                   check=True, capture_output=True, timeout=1800)
    return wav
