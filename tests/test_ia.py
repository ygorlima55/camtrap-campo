"""Módulo 2 com o motor SIMULADO (só testes): fila, pausa/retomada, sequências, revisão e telas.

Nenhum teste aqui afirma algo sobre a qualidade da IA real; isso é verificado à parte com os modelos instalados.
"""

import datetime as dt
import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from camtrap_campo import amostras, config
from camtrap_campo.db import Deteccao, Especie, Importacao, Inferencia, Revisao, Tarefa
from camtrap_campo.ia import especies, fila, motor, revisao
from camtrap_campo.ia.sequencias import agrupar
from camtrap_campo.importacao.copiar import importar
from camtrap_campo.web.app import criar_app


@pytest.fixture(autouse=True)
def simulado(monkeypatch):
    monkeypatch.setenv("CAMTRAP_IA_SIMULADA", "1")


@pytest.fixture
def importado(ambiente, tmp_path):
    imp_id = importar(ambiente["fabrica"], amostras.cartao_bushnell(tmp_path / "cartao"), "P7", "Ponto 1", "Seca2026")
    with ambiente["fabrica"]() as s:
        especies.semear(s)
    return imp_id


def test_interpretar_rotulo_speciesnet():
    r = motor.interpretar_rotulo("abc;mammalia;carnivora;canidae;cerdocyon;thous;crab-eating fox")
    assert r["nome_cientifico"] == "Cerdocyon thous" and r["nivel"] == "espécie" and r["familia"] == "canidae"
    assert motor.interpretar_rotulo("abc;mammalia;rodentia;;;;rodent")["nivel"] == "ordem"
    assert motor.interpretar_rotulo("blank")["rotulo"] == "blank"


def test_lista_de_especies_sem_duplicatas(ambiente):
    nomes = [c for c, *_ in especies.INICIAIS]
    assert len(nomes) == len(set(nomes)) and all(len(n.split()) == 2 for n in nomes)
    with ambiente["fabrica"]() as s:
        assert especies.semear(s) == len(nomes) and especies.semear(s) == 0


def test_agrupar_sequencias():
    a = lambda i, seg: types.SimpleNamespace(id=i, data=dt.datetime(2026, 1, 1) + dt.timedelta(seconds=seg))  # noqa: E731
    sem = types.SimpleNamespace(id=9, data=None)
    grupos = agrupar([a(1, 0), a(2, 30), a(3, 200), a(4, 230), sem])
    assert [[x.id for x in g] for g in grupos] == [[1, 2], [3, 4], [9]]


def test_tarefa_ia_simulada_processa_fotos(ambiente, importado):
    with ambiente["fabrica"]() as s:
        t = fila.criar_tarefa(s, "ia", importado)
        assert fila.criar_tarefa(s, "ia", importado).id == t.id  # não duplica tarefa ativa
    assert fila.executar(ambiente["fabrica"], t.id) == "concluida"
    with ambiente["fabrica"]() as s:
        t = s.get(Tarefa, t.id)
        infs = s.scalars(select(Inferencia).where(Inferencia.etapa == "ia")).all()
        assert t.total == 6 and t.feitos == 6 and len(infs) == 6
        assert all(i.simulado for i in infs if i.erro is None)
        assert all(d.simulado for d in s.scalars(select(Deteccao)))
        video = [i for i in infs if i.arquivo_id in {a.id for a in s.get(Importacao, importado).arquivos if a.tipo == "video"}]
        if not config.localizar_ferramenta("ffmpeg"):
            assert video[0].erro.startswith("FFmpeg não instalado") and t.falhas == 1


def test_pausar_e_retomar_sem_repetir(ambiente, importado):
    with ambiente["fabrica"]() as s:
        t = fila.criar_tarefa(s, "ia", importado)
        tid = t.id

    class PausaNoMeio(motor.MotorSimulado):
        chamadas = 0

        def analisar(self, caminhos):
            PausaNoMeio.chamadas += 1
            if PausaNoMeio.chamadas == 2:
                with ambiente["fabrica"]() as s2:
                    fila.pausar(s2, tid)
            return super().analisar(caminhos)

    assert fila.executar(ambiente["fabrica"], tid, motor=PausaNoMeio()) == "pausada"
    with ambiente["fabrica"]() as s:
        feitos = s.get(Tarefa, tid).feitos
        assert 0 < feitos < 6
        fila.retomar(s, tid)
    assert fila.executar(ambiente["fabrica"], tid) == "concluida"
    with ambiente["fabrica"]() as s:
        ids = s.scalars(select(Inferencia.arquivo_id).where(Inferencia.etapa == "ia")).all()
        assert len(ids) == len(set(ids)) == 6  # cada arquivo uma vez só


def test_trabalhador_recoloca_tarefa_interrompida(ambiente, importado):
    with ambiente["fabrica"]() as s:
        t = fila.criar_tarefa(s, "ia", importado)
        t.estado = "executando"  # como se o programa tivesse fechado no meio
        s.commit()
    fila.Trabalhador(ambiente["fabrica"])
    with ambiente["fabrica"]() as s:
        assert s.get(Tarefa, t.id).estado == "pendente"


def test_tarefa_audio_sem_ffmpeg(ambiente, importado):
    if config.localizar_ferramenta("ffmpeg"):
        pytest.skip("FFmpeg instalado")
    with ambiente["fabrica"]() as s:
        t = fila.criar_tarefa(s, "audio", importado)
    assert fila.executar(ambiente["fabrica"], t.id) == "erro"
    with ambiente["fabrica"]() as s:
        assert "FFmpeg" in s.get(Tarefa, t.id).mensagem


def test_revisao_montar_e_salvar(ambiente, importado):
    with ambiente["fabrica"]() as s:
        assert revisao.montar(s, importado)["nao_analisadas"] > 0  # antes da IA
        t = fila.criar_tarefa(s, "ia", importado)
    fila.executar(ambiente["fabrica"], t.id)
    with ambiente["fabrica"]() as s:
        dados = revisao.montar(s, importado)
        assert dados["simulado"] and dados["sequencias"]
        sq = dados["sequencias"][0]
        assert sq["especie_sugerida"].nome_cientifico == "Cerdocyon thous"  # sugestão do motor simulado → lista
        cachorro = sq["especie_sugerida"]
        rev = revisao.salvar(s, importado, sq["chave"], [a.id for a in sq["arquivos"]], "especie", cachorro.id, 2,
                             "forrageio", True, "par", sq["sugestao"])
        assert rev.quantidade == 2 and rev.divulgacao
        assert revisao.montar(s, importado, somente_pendentes=True)["sequencias"] != dados["sequencias"]
        with pytest.raises(ValueError):
            revisao.salvar(s, importado, sq["chave"], [1], "especie", None)
        with pytest.raises(ValueError):
            revisao.salvar(s, importado, sq["chave"], [1], "inventado")
        revisao.definir_limiar(s, 0.99)  # acima de tudo: some da revisão
        assert revisao.montar(s, importado)["sequencias"] == []
        with pytest.raises(ValueError):
            revisao.definir_limiar(s, 1.5)


def test_motor_real_indisponivel_sem_pacote(monkeypatch):
    monkeypatch.delenv("CAMTRAP_IA_SIMULADA")
    try:
        import speciesnet  # noqa: F401
        pytest.skip("SpeciesNet instalado")
    except ImportError:
        pass
    assert motor.disponivel()[0] is False
    with pytest.raises(motor.MotorIndisponivel):
        motor.criar_motor()


def test_web_fluxo_ia_e_revisao(ambiente, importado):
    c = TestClient(criar_app(ambiente["fabrica"], sincrono=True))
    r = c.post(f"/importacoes/{importado}/tarefa", data={"tipo": "ia"}, follow_redirects=True)
    assert "concluida" in r.text and "motor SIMULADO (modo de teste)" in r.text  # a tela avisa que não é IA real
    r = c.get(f"/revisao/{importado}")
    assert "SIMULADO" in r.text and "Confirmar espécie" in r.text and "cachorro-do-mato" in r.text
    with ambiente["fabrica"]() as s:
        sq = revisao.montar(s, importado)["sequencias"][0]
        cachorro = s.scalar(select(Especie).where(Especie.nome_cientifico == "Cerdocyon thous"))
        arquivos = [a.id for a in sq["arquivos"]]
    corpo = {"chave": sq["chave"], "arquivos": arquivos, "resultado": "especie", "especie_id": cachorro.id,
             "quantidade": 1, "comportamento": "deslocamento", "divulgacao": False, "observacao": ""}
    assert c.post(f"/revisao/{importado}", json=corpo).json()["ok"]
    assert c.post(f"/revisao/{importado}", json={**corpo, "chave": 99999}).status_code == 400
    assert c.post(f"/revisao/{importado}", json={**corpo, "especie_id": None}).status_code == 400
    with ambiente["fabrica"]() as s:
        assert s.scalar(select(Revisao)).especie_id == cachorro.id
    det = next(iter(sq["deteccoes"].values()))[0]
    assert c.get(f"/deteccoes/{det.id}/imagem").headers["content-type"] == "image/jpeg"
    c.post("/especies", data={"nome_cientifico": "Chironectes  minimus", "nome_popular": "cuíca-d'água", "grupo": "mamífero"})
    assert "Chironectes minimus" in c.get("/especies").text
    c.post("/configuracao/limiar", data={"limiar": "0,35"})
    with ambiente["fabrica"]() as s:
        assert revisao.limiar(s) == 0.35
    assert "Processamento em segundo plano" in c.get("/tarefas").text
