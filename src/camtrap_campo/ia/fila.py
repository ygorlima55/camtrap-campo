"""Fila de tarefas em segundo plano (uma thread), com pausar e retomar.

O progresso fica no banco: cada arquivo processado ganha uma linha em Inferencia, então uma tarefa pausada (ou
interrompida por fechar o programa) recomeça de onde parou, sem repetir arquivos.
"""

from __future__ import annotations

import shutil
import threading
import traceback
from pathlib import Path

from sqlalchemy import select

from camtrap_campo import config
from camtrap_campo.db import Arquivo, Deteccao, Importacao, Inferencia, Tarefa, agora
from camtrap_campo.ia import midia
from camtrap_campo.ia.motor import Resultado, criar_motor


def criar_tarefa(sessao, tipo: str, importacao_id: int) -> Tarefa:
    if tipo not in ("ia", "audio"):
        raise ValueError("tipo de tarefa inválido")
    if sessao.get(Importacao, importacao_id) is None:
        raise ValueError("importação não encontrada")
    ativa = sessao.scalar(select(Tarefa).where(Tarefa.tipo == tipo, Tarefa.importacao_id == importacao_id,
                                               Tarefa.estado.in_(("pendente", "executando", "pausada"))))
    if ativa:
        return ativa
    t = Tarefa(tipo=tipo, importacao_id=importacao_id)
    sessao.add(t)
    sessao.commit()
    return t


def _pendentes(sessao, tarefa: Tarefa) -> list[Arquivo]:
    tipos = ("foto", "video") if tarefa.tipo == "ia" else ("video",)
    feitos = select(Inferencia.arquivo_id).where(Inferencia.etapa == tarefa.tipo)
    return list(sessao.scalars(select(Arquivo).where(
        Arquivo.importacao_id == tarefa.importacao_id, Arquivo.estado == "copiado", Arquivo.tipo.in_(tipos),
        Arquivo.id.not_in(feitos)).order_by(Arquivo.id)))


def _salvar_ia(sessao, arq: Arquivo, resultados: list[tuple[float | None, str | None, Resultado]]) -> None:
    melhor = None
    for segundo, quadro, r in resultados:
        for d in r.deteccoes:
            sessao.add(Deteccao(arquivo_id=arq.id, quadro_s=segundo, quadro_caminho=quadro, categoria=d["categoria"],
                                confianca=d["confianca"], bbox=d["bbox"], modelo=r.modelo, simulado=r.simulado))
        if r.classificacao and (melhor is None or r.classificacao.get("confianca", 0) > melhor.get("confianca", 0)):
            melhor = r.classificacao
    erros = [r.erro for _, _, r in resultados if r.erro]
    primeiro = resultados[0][2] if resultados else None
    sessao.add(Inferencia(arquivo_id=arq.id, etapa="ia", modelo=primeiro.modelo if primeiro else None,
                          simulado=bool(primeiro and primeiro.simulado),
                          quadros=len(resultados) if arq.tipo == "video" else None,
                          classificacao=melhor, erro="; ".join(erros) or None))


def _processar_ia(sessao, motor, arq: Arquivo, dados: Path) -> None:
    origem = dados / arq.caminho_final
    if arq.tipo == "foto":
        _salvar_ia(sessao, arq, [(None, None, motor.analisar([origem])[0])])
        return
    pasta = dados / "_quadros" / str(arq.id)
    quadros = midia.extrair_quadros(origem, pasta)
    resultados = []
    for (segundo, q), r in zip(quadros, motor.analisar([q for _, q in quadros]), strict=True):
        resultados.append((segundo, q.relative_to(dados).as_posix(), r))
    _salvar_ia(sessao, arq, resultados)
    # guarda só os quadros com detecção (para a revisão); apaga os vazios
    com_det = {q for _, q, r in resultados if r.deteccoes}
    for _, q, _ in resultados:
        if q not in com_det:
            (dados / q).unlink(missing_ok=True)
    if not com_det:
        shutil.rmtree(pasta, ignore_errors=True)


def _processar_audio(sessao, arq: Arquivo, dados: Path) -> None:
    origem = dados / arq.caminho_final
    wav = origem.parent / "_audio" / (origem.stem + ".wav")
    gerado = midia.extrair_audio(origem, wav)
    sessao.add(Inferencia(arquivo_id=arq.id, etapa="audio", modelo="ffmpeg pcm_s16le",
                          resultado={"wav": gerado.relative_to(dados).as_posix() if gerado else None,
                                     "sem_audio": gerado is None}))


def executar(fabrica, tarefa_id: int, motor=None, pasta_dados: Path | None = None) -> str:
    """Executa uma tarefa até terminar ou ser pausada. Devolve o estado final."""
    dados = Path(pasta_dados or config.pasta_dados())
    with fabrica() as s:
        t = s.get(Tarefa, tarefa_id)
        if t is None or t.estado in ("concluida", "pausada"):
            return t.estado if t else "inexistente"
        t.estado, t.iniciada_em, t.mensagem = "executando", t.iniciada_em or agora(), None
        pendentes = _pendentes(s, t)
        t.total = t.feitos + len(pendentes)
        s.commit()
        try:
            if t.tipo == "ia" and pendentes:
                motor = motor or criar_motor()
            for arq in pendentes:
                s.refresh(t)
                if t.estado == "pausada":
                    return "pausada"
                try:
                    if t.tipo == "ia":
                        _processar_ia(s, motor, arq, dados)
                    else:
                        _processar_audio(s, arq, dados)
                except midia.FFmpegAusente:
                    if t.tipo == "audio":
                        raise  # sem FFmpeg não há o que fazer nesta tarefa
                    s.rollback()  # IA: só os vídeos ficam sem análise; as fotos seguem
                    s.add(Inferencia(arquivo_id=arq.id, etapa="ia", erro="FFmpeg não instalado: vídeo não analisado"))
                    t.falhas += 1
                except Exception as exc:  # noqa: BLE001 — um arquivo ruim não para a fila
                    s.rollback()
                    s.add(Inferencia(arquivo_id=arq.id, etapa=t.tipo, erro=f"{type(exc).__name__}: {exc}"))
                    t.falhas += 1
                t.feitos += 1
                s.commit()
            t.estado, t.concluida_em = "concluida", agora()
        except Exception as exc:  # noqa: BLE001
            s.rollback()
            t.estado, t.mensagem = "erro", f"{type(exc).__name__}: {exc}"
            t.mensagem += "" if isinstance(exc, (midia.FFmpegAusente,)) else "\n" + traceback.format_exc(limit=3)
        s.commit()
        return t.estado


class Trabalhador:
    """Uma thread que processa tarefas pendentes em ordem. ``acordar()`` após criar/retomar tarefas."""

    def __init__(self, fabrica):
        self.fabrica = fabrica
        self._evento = threading.Event()
        self._thread = threading.Thread(target=self._laco, daemon=True, name="camtrap-ia")
        with fabrica() as s:  # tarefas interrompidas (programa fechado) voltam para a fila
            for t in s.scalars(select(Tarefa).where(Tarefa.estado == "executando")):
                t.estado = "pendente"
            s.commit()

    def iniciar(self):
        self._thread.start()
        self.acordar()

    def acordar(self):
        self._evento.set()

    def _laco(self):
        while True:
            self._evento.wait(timeout=5)
            self._evento.clear()
            while True:
                with self.fabrica() as s:
                    proxima = s.scalar(select(Tarefa.id).where(Tarefa.estado == "pendente").order_by(Tarefa.id))
                if proxima is None:
                    break
                executar(self.fabrica, proxima)


def pausar(sessao, tarefa_id: int) -> None:
    t = sessao.get(Tarefa, tarefa_id)
    if t and t.estado in ("pendente", "executando"):
        t.estado = "pausada"
        sessao.commit()


def retomar(sessao, tarefa_id: int) -> None:
    t = sessao.get(Tarefa, tarefa_id)
    if t and t.estado in ("pausada", "erro"):
        t.estado = "pendente"
        sessao.commit()
