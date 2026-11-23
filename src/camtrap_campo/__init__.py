"""CamTrap Campo — dados de armadilhas fotográficas, do cartão à análise, 100% local."""

__version__ = "0.2.0"


def main() -> None:
    import argparse
    import threading
    import webbrowser

    import uvicorn

    from camtrap_campo.web.app import criar_app

    p = argparse.ArgumentParser(prog="camtrap-campo", description="Abre a interface no navegador (somente neste computador).")
    p.add_argument("--porta", type=int, default=8765)
    p.add_argument("--sem-navegador", action="store_true")
    a = p.parse_args()
    porta = porta_livre(a.porta)
    endereco = f"http://127.0.0.1:{porta}/"
    if not a.sem_navegador:
        threading.Timer(1.5, webbrowser.open, args=(endereco,)).start()
    print(f"CamTrap Campo rodando em {endereco} — feche esta janela para encerrar.")
    uvicorn.run(criar_app(), host="127.0.0.1", port=porta, log_level="warning")


def porta_livre(inicial: int, tentativas: int = 20) -> int:
    """Primeira porta livre a partir de ``inicial`` (outro programa pode estar usando a padrão)."""
    import socket

    for porta in range(inicial, inicial + tentativas):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", porta))
                return porta
            except OSError:
                continue
    raise SystemExit(f"Nenhuma porta livre entre {inicial} e {inicial + tentativas - 1}")
