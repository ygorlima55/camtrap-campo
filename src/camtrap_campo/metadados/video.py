"""Duração, data e quadros de vídeos: FFprobe (FFmpeg) quando instalado; cabeçalho AVI como reserva."""

from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

from camtrap_campo.config import localizar_ferramenta
from camtrap_campo.metadados.exif import interpretar_data


def _avi(caminho: Path) -> dict:
    with caminho.open("rb") as f:
        cab = f.read(64 * 1024)
    if cab[:4] != b"RIFF" or cab[8:12] != b"AVI ":
        return {"fonte": None, "erro": "não é AVI ou cabeçalho ilegível"}
    k = cab.find(b"avih")
    us, _, _, _, quadros = struct.unpack("<IIIII", cab[k + 8:k + 28])
    largura, altura = struct.unpack("<II", cab[k + 40:k + 48])
    dados = {"fonte": "cabecalho_avi", "quadros": quadros, "largura": largura, "altura": altura,
             "fps": round(1e6 / us, 3) if us else None, "duracao_s": round(us * quadros / 1e6, 2) if us else None,
             "tem_audio": b"auds" in cab}
    return dados


def ler_video(caminho: Path) -> dict:
    exe = localizar_ferramenta("ffprobe")
    if exe:
        try:
            proc = subprocess.run(
                [exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(caminho)],
                capture_output=True, timeout=120,
            )
            info = json.loads(proc.stdout or b"{}")
            v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
            fmt = info.get("format", {})
            tags = {**fmt.get("tags", {}), **v.get("tags", {})}
            num, _, den = (v.get("r_frame_rate") or "0/1").partition("/")
            data = interpretar_data((tags.get("creation_time") or "").replace("T", " ").split(".")[0])
            return {
                "fonte": "ffprobe", "duracao_s": float(fmt["duration"]) if fmt.get("duration") else None,
                "quadros": int(v["nb_frames"]) if v.get("nb_frames") else None,
                "fps": round(int(num) / int(den or 1), 3) if num.isdigit() else None,
                "largura": v.get("width"), "altura": v.get("height"), "codec": v.get("codec_name"),
                "tem_audio": any(s.get("codec_type") == "audio" for s in info.get("streams", [])),
                "data": data.isoformat() if data else None,
            }
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError) as exc:
            reserva = _avi(caminho) if caminho.suffix.lower() == ".avi" else {"fonte": None}
            reserva["aviso"] = f"ffprobe falhou: {exc}"
            return reserva
    if caminho.suffix.lower() == ".avi":
        dados = _avi(caminho)
        dados["aviso"] = "FFmpeg não instalado: só o cabeçalho AVI foi lido (sem data)"
        return dados
    return {"fonte": None, "aviso": "FFmpeg não instalado"}
