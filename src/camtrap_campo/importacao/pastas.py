"""Pastas do computador que o usuário quer importar além dos cartões (cópias de cartões, registros de teste).

Só a lista de caminhos fica guardada (tabela de configuração); nada é movido nem apagado nessas pastas.
"""

from __future__ import annotations

from pathlib import Path

from camtrap_campo import config
from camtrap_campo.db import Configuracao

CHAVE = "pastas_importacao"


def listar(sessao) -> list[str]:
    c = sessao.get(Configuracao, CHAVE)
    return list(c.valor) if c and c.valor else []


def _gravar(sessao, caminhos: list[str]) -> None:
    sessao.merge(Configuracao(chave=CHAVE, valor=caminhos))
    sessao.commit()


def validar(caminho: str) -> Path:
    """Caminho absoluto de uma pasta que pode ser importada; ValueError com o motivo, em português."""
    texto = caminho.strip().strip('"').strip()
    if not texto:
        raise ValueError("Informe o caminho da pasta.")
    p = Path(texto).expanduser()
    if not p.is_absolute():
        raise ValueError("Use o caminho completo, por exemplo C:\\Users\\voce\\Pictures\\Câmera P7.")
    if not p.is_dir():
        raise ValueError(f"A pasta não existe ou não pode ser aberta: {p}")
    p = p.resolve()
    dados = config.pasta_dados().resolve()
    if p == dados or dados in p.parents:
        raise ValueError("Essa pasta é onde o programa guarda as importações; escolha a pasta de origem das fotos.")
    if p in dados.parents:
        raise ValueError("Essa pasta contém a pasta de dados do programa (seria copiar o programa para dentro dele). "
                         "Escolha uma subpasta só com as fotos e vídeos.")
    return p


def adicionar(sessao, caminho: str) -> str:
    p = str(validar(caminho))
    atuais = listar(sessao)
    if p not in atuais:
        _gravar(sessao, atuais + [p])
    return p


def remover(sessao, caminho: str) -> None:
    """Tira a pasta da lista do programa. Os arquivos da pasta não são tocados."""
    _gravar(sessao, [c for c in listar(sessao) if c != caminho])


def escolher_no_windows(titulo: str = "Escolha a pasta com as fotos e vídeos das câmeras") -> str | None:
    """Abre a janela "Selecionar pasta" do sistema (o programa roda neste computador). None se cancelar."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None
    janela = tk.Tk()
    janela.withdraw()
    janela.attributes("-topmost", True)  # aparece na frente do navegador
    try:
        escolhida = filedialog.askdirectory(parent=janela, title=titulo, mustexist=True)
    finally:
        janela.destroy()
    return escolhida or None


def em_nuvem(caminho: str) -> bool:
    """Pasta do OneDrive: arquivos "só na nuvem" serão baixados durante a importação."""
    return "onedrive" in caminho.lower()
