"""Diagnóstico de câmera com a tela apagada (o processador pode estar funcionando).

Roteiro: (1) conectar e registrar o estado do cartão; (2) desconectar, ligar a câmera e provocar disparos
(passar a mão na frente do sensor por ~1 min); (3) reconectar e verificar se surgiram mídias novas.
A comparação usa a lista de arquivos (não o relógio da câmera, que pode estar errado).
"""

from __future__ import annotations

from pathlib import Path

from camtrap_campo.db import TesteSemTela, agora
from camtrap_campo.importacao.copiar import listar_cartao, tipo_de

CONCLUSOES = {
    "gravacao_ok": (
        "Processador e gravação OK — a câmera montou pelo USB e gravou mídias novas no teste. "
        "Defeito provável na TELA: cabo flat solto/rompido ou luz de fundo (backlight). "
        "A câmera pode ir a campo configurada às cegas (veja o roteiro de botões do modelo)."),
    "sem_novos": (
        "A câmera montou pelo USB, mas NÃO gravou mídias novas no teste. Próximos passos, nesta ordem: "
        "1) pilhas novas e iguais (ou fonte externa); 2) chave em ON (não SETUP/TEST); "
        "3) aguardar 30–60 s após ligar antes de disparar; 4) testar com outro cartão formatado NA câmera; "
        "5) disparar no escuro e no claro. Se continuar sem gravar, suspeitar do sensor (PIR) ou do processador."),
    "nao_montou": (
        "O cartão/câmera não está acessível agora. Confira o cabo (de dados, não só de carga), outra porta USB "
        "e se a câmera está no modo USB. Sem montar, não é possível separar defeito de tela de defeito geral."),
}


def _midias(raiz: Path) -> list[list]:
    return sorted([p.relative_to(raiz).as_posix(), p.stat().st_size] for p in listar_cartao(raiz)
                  if tipo_de(p) in ("foto", "video"))


def iniciar(sessao, raiz: str | Path, camera_id: int | None = None) -> TesteSemTela:
    raiz = Path(raiz)
    if not raiz.is_dir():
        raise ValueError(f"{raiz} não está acessível")
    teste = TesteSemTela(camera_id=camera_id, raiz=str(raiz), antes=_midias(raiz))
    sessao.add(teste)
    sessao.commit()
    return teste


def verificar(sessao, teste_id: int) -> TesteSemTela:
    teste = sessao.get(TesteSemTela, teste_id)
    if teste is None:
        raise ValueError("teste não encontrado")
    raiz = Path(teste.raiz)
    teste.verificado_em = agora()
    if not raiz.is_dir():
        teste.resultado, teste.novos = "nao_montou", []
    else:
        antes = {tuple(x) for x in teste.antes}
        teste.novos = [x for x in _midias(raiz) if tuple(x) not in antes]
        teste.resultado = "gravacao_ok" if teste.novos else "sem_novos"
    sessao.commit()
    return teste
