"""Importação de um cartão: copia TUDO (inclusive ocultos), verifica SHA-256, renomeia e registra no banco.

Garantias:
- o cartão é aberto só para leitura; nada é apagado nem alterado nele;
- cada arquivo vai para ``.parcial``, é re-hasheado no destino e só então recebe o nome final;
- reimportação não duplica: arquivo com SHA-256 já importado vira "duplicado" (sem nova cópia);
- fotos/vídeos recebem ``<campanha>_<ponto>_<camera>_<AAAAMMDD>_<HHMMSS>_<seq>.<ext>``;
  os demais arquivos (._*, configurações, etc.) vão para ``_cartao_original/`` com o nome de origem.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import shutil
import unicodedata
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select

from camtrap_campo import config
from camtrap_campo.db import Alerta, Arquivo, Camera, Campanha, Importacao, Ponto, agora
from camtrap_campo.importacao import alertas
from camtrap_campo.importacao.padroes import classificar, detectar_padrao, sugerir_modelo
from camtrap_campo.metadados.exif import ler_exif
from camtrap_campo.metadados.rodape import ler_rodape
from camtrap_campo.metadados.video import ler_video

BLOCO = 1024 * 1024
IGNORAR = {"system volume information", "$recycle.bin"}  # criadas pelo Windows, não pela câmera


def sanitizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9\-]+", "-", texto).strip("-") or "sem-nome"


def tipo_de(caminho: Path) -> str:
    if caminho.name.startswith("._"):
        return "appledouble"
    ext = caminho.suffix.lower()
    if ext in config.EXT_FOTO:
        return "foto"
    if ext in config.EXT_VIDEO:
        return "video"
    return "outro"


def _oculto(caminho: Path) -> bool:
    if caminho.name.startswith("."):
        return True
    atributos = getattr(os.stat(caminho), "st_file_attributes", 0)
    return bool(atributos & 0x2)  # FILE_ATTRIBUTE_HIDDEN


def listar_cartao(raiz: Path) -> list[Path]:
    arquivos = []
    for pasta, subpastas, nomes in os.walk(raiz):
        subpastas[:] = [s for s in subpastas if s.lower() not in IGNORAR]
        arquivos += [Path(pasta) / n for n in nomes]
    return sorted(arquivos)


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        while bloco := f.read(BLOCO):
            h.update(bloco)
    return h.hexdigest()


def _copiar_com_hash(origem: Path, destino: Path) -> str:
    h = hashlib.sha256()
    destino.parent.mkdir(parents=True, exist_ok=True)
    with origem.open("rb") as fo, destino.open("xb") as fd:
        while bloco := fo.read(BLOCO):
            h.update(bloco)
            fd.write(bloco)
        fd.flush()
        os.fsync(fd.fileno())
    shutil.copystat(origem, destino)
    return h.hexdigest()


def _livre(caminho: Path) -> Path:
    if not caminho.exists():
        return caminho
    n = 2
    while (alt := caminho.with_name(f"{caminho.stem}_{n}{caminho.suffix}")).exists():
        n += 1
    return alt


def nome_final(campanha: str, ponto: str, camera: str, data: dt.datetime | None, seq: int, ext: str) -> str:
    carimbo = data.strftime("%Y%m%d_%H%M%S") if data else "00000000_000000"
    return f"{sanitizar(campanha)}_{sanitizar(ponto)}_{sanitizar(camera)}_{carimbo}_{seq:04d}{ext.lower()}"


def _metadados(arq: Arquivo, copia: Path) -> None:
    """Preenche data, EXIF, rodapé e vídeo a partir da CÓPIA (o cartão é lido uma vez só)."""
    if arq.tipo == "foto":
        arq.exif = ler_exif(copia)
        data = dt.datetime.fromisoformat(arq.exif["data"]) if arq.exif.get("data") else None
        arq.rodape = ler_rodape(copia, data)
        data_rodape = dt.datetime.fromisoformat(arq.rodape["data"]) if arq.rodape.get("data") else None
        if data and data_rodape:
            arq.rodape_diverge = abs((data - data_rodape).total_seconds()) > config.DIVERGENCIA_RODAPE_MIN * 60
        if data:
            arq.data_original, arq.fonte_data = data, "exif"
        elif data_rodape:
            arq.data_original, arq.fonte_data = data_rodape, "rodape"
    elif arq.tipo == "video":
        arq.video = ler_video(copia)
        if arq.video.get("data"):
            arq.data_original, arq.fonte_data = dt.datetime.fromisoformat(arq.video["data"]), "video"
    if arq.tipo in ("foto", "video") and arq.data_original is None:
        arq.data_original = dt.datetime.fromtimestamp(copia.stat().st_mtime).replace(microsecond=0)
        arq.fonte_data = "arquivo"


def obter_ou_criar(sessao, modelo, nome: str, **extras):
    obj = sessao.scalar(select(modelo).where((modelo.etiqueta if modelo is Camera else modelo.nome) == nome))
    if obj is None:
        campo = "etiqueta" if modelo is Camera else "nome"
        obj = modelo(**{campo: nome}, **extras)
        sessao.add(obj)
        sessao.flush()
    return obj


def importar(fabrica_sessao, origem: Path, camera: str, ponto: str, campanha: str,
             pasta_dados: Path | None = None, progresso: Callable[[int, int], None] | None = None,
             importacao_id: int | None = None) -> int:
    """Executa a importação e devolve o id da Importacao. Pode ser chamada numa thread."""
    origem, pasta_dados = Path(origem), Path(pasta_dados or config.pasta_dados())
    with fabrica_sessao() as s:
        cam = obter_ou_criar(s, Camera, camera)
        pto = obter_ou_criar(s, Ponto, ponto)
        cmp = obter_ou_criar(s, Campanha, campanha)
        cam.ultimo_ponto_id, cam.ultima_campanha_id = pto.id, cmp.id  # lembrar a última escolha
        imp = s.get(Importacao, importacao_id) if importacao_id else None
        if imp is None:
            imp = Importacao(camera_id=cam.id, ponto_id=pto.id, campanha_id=cmp.id, origem=str(origem))
            s.add(imp)
        s.commit()
        imp_id = imp.id

        destino = pasta_dados / sanitizar(campanha) / sanitizar(ponto) / sanitizar(camera)
        parcial = destino / ".parcial"
        try:
            arquivos = listar_cartao(origem)
        except OSError as exc:
            imp.estado, imp.mensagem = "falhou", f"não foi possível ler a origem: {exc}"
            s.commit()
            return imp_id
        imp.total = len(arquivos)
        midias = [p.stem for p in arquivos if tipo_de(p) in ("foto", "video")]
        imp.padrao_nomes = detectar_padrao(midias).get("descricao")
        s.commit()

        for i, caminho in enumerate(arquivos, 1):
            rel = caminho.relative_to(origem).as_posix()
            arq = Arquivo(importacao_id=imp_id, caminho_cartao=rel, nome_original=caminho.name, tipo=tipo_de(caminho),
                          oculto=_oculto(caminho), tamanho=caminho.stat().st_size, estado="erro")
            s.add(arq)
            try:
                temp = _livre(parcial / f"{imp_id}_{i}{caminho.suffix}")
                hash_origem = _copiar_com_hash(caminho, temp)
                arq.sha256 = hash_origem
                # foto/vídeo: mesmo conteúdo = mesmo registro. Outros arquivos pequenos (._*, configs) podem ter
                # conteúdo igual sendo arquivos diferentes: só são duplicata se também tiverem o mesmo caminho.
                consulta = select(Arquivo).where(Arquivo.sha256 == hash_origem, Arquivo.estado == "copiado")
                if arq.tipo not in ("foto", "video"):
                    consulta = consulta.where(Arquivo.caminho_cartao == rel)
                anterior = s.scalar(consulta.limit(1))
                if anterior is not None:
                    temp.unlink()
                    arq.estado, arq.duplicado_de_id = "duplicado", anterior.id
                    arq.detalhe = f"já importado como {anterior.caminho_final}"
                    imp.duplicados += 1
                else:
                    if sha256(temp) != hash_origem:
                        raise OSError("hash da cópia difere do cartão")
                    _, arq.contador_original, _ = classificar(caminho.stem)
                    _metadados(arq, temp)
                    if arq.tipo in ("foto", "video"):
                        nome = nome_final(campanha, ponto, camera, arq.data_original, arq.contador_original or i, caminho.suffix)
                        final = _livre(destino / nome)
                    else:
                        final = _livre(destino / "_cartao_original" / rel)
                    final.parent.mkdir(parents=True, exist_ok=True)
                    temp.rename(final)
                    arq.caminho_final = final.relative_to(pasta_dados).as_posix()
                    arq.estado = "copiado"
                    imp.copiados += 1
            except OSError as exc:
                arq.detalhe = f"{type(exc).__name__}: {exc}"
                imp.erros += 1
            imp.processados = i
            s.commit()
            if progresso:
                progresso(i, len(arquivos))

        try:
            parcial.rmdir()
        except OSError:
            pass
        primeira_foto = next((a for a in imp.arquivos if a.tipo == "foto" and a.exif), None)
        pastas = sorted({Path(a.caminho_cartao).parts[1] for a in imp.arquivos
                         if a.caminho_cartao.upper().startswith("DCIM/") and len(Path(a.caminho_cartao).parts) > 2})
        imp.modelo_detectado = sugerir_modelo(pastas, primeira_foto.exif if primeira_foto else None)
        for alerta in alertas.gerar(imp, cmp):
            s.add(Alerta(importacao_id=imp_id, **alerta))
        imp.estado = "concluida" if imp.erros == 0 else "com_erros"
        imp.concluida_em = agora()
        s.commit()
        return imp_id
