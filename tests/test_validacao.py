"""Validação por espécie: grupos com sugestões da IA (pré-marcadas só com confiança alta), validação em bloco,
correção, espécies por câmera, planilha e relatório fotográfico. Dados montados no banco (sem rodar IA)."""

import datetime as dt
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

from camtrap_campo.db import Arquivo, Camera, Campanha, Deteccao, Especie, Importacao, Inferencia, Ponto, Revisao
from camtrap_campo.exportacao import especies as planilha_especies
from camtrap_campo.ia import especies, revisao, validacao
from camtrap_campo.web.app import criar_app

T0 = dt.datetime(2026, 9, 10, 20, 0)


def _sug(nome, conf):
    return {"nome_cientifico": nome, "confianca": conf, "rotulo": nome, "fonte": "classifier"} if nome else None


@pytest.fixture
def cenario(ambiente):
    with ambiente["fabrica"]() as s:
        especies.semear(s)
        cmp, pto = Campanha(nome="Chuva2026"), Ponto(nome="Trilha", latitude=-15.8, longitude=-47.9)
        p1, p2 = Camera(etiqueta="P1"), Camera(etiqueta="P2")
        s.add_all([cmp, pto, p1, p2])
        s.flush()
        ids = {}
        planos = {p1: [("cao_alta", "animal", .9, "Cerdocyon thous", .93),
                       ("cutia_baixa", "animal", .7, "Dasyprocta azarae", .55),
                       ("pessoa", "pessoa", .95, None, None), ("felino_generico", "animal", .6, "Felidae", .5),
                       ("vazio", "animal", .1, None, None)],
                  p2: [("cao_validado", "animal", .88, "Cerdocyon thous", .85)]}
        for cam, seqs in planos.items():
            imp = Importacao(camera_id=cam.id, ponto_id=pto.id, campanha_id=cmp.id, origem="sintetico", estado="concluida")
            s.add(imp)
            s.flush()
            for n, (nome, cat, conf_det, esp, conf_esp) in enumerate(seqs):
                a = Arquivo(importacao_id=imp.id, caminho_cartao=f"DCIM/{nome}.JPG", nome_original=f"{nome}.JPG", tipo="foto",
                            tamanho=1, estado="copiado", caminho_final=f"Chuva2026/Trilha/{cam.etiqueta}/{nome}.jpg",
                            data_original=T0 + dt.timedelta(hours=n), fonte_data="exif")
                s.add(a)
                s.flush()
                s.add(Inferencia(arquivo_id=a.id, etapa="ia", modelo="teste", classificacao=_sug(esp, conf_esp)))
                s.add(Deteccao(arquivo_id=a.id, categoria=cat, confianca=conf_det, bbox=[.1, .1, .3, .3], modelo="teste"))
                ids[nome] = (imp.id, a.id)
        s.commit()
        cao = s.scalar(select(Especie).where(Especie.nome_cientifico == "Cerdocyon thous"))
        imp2, a6 = ids["cao_validado"]
        revisao.salvar(s, imp2, a6, [a6], "especie", cao.id, 2, "forrageando", True, "par", _sug("Cerdocyon thous", .85))
        return {"ids": ids, "cao": cao.id, "p1": p1.id, "p2": p2.id, "campanha": cmp.id,
                "cutia": s.scalar(select(Especie.id).where(Especie.nome_cientifico == "Dasyprocta azarae"))}


def _item(cenario, nome):
    imp, a = cenario["ids"][nome]
    return {"imp_id": imp, "chave": a, "arquivos": [a], "quantidade": 1}


def test_grupos_por_especie_e_pre_marcacao(ambiente, cenario):
    with ambiente["fabrica"]() as s:
        d = validacao.montar(s)
    grupos = {g["chave"]: g for g in d["grupos"]}
    cao = grupos[f"esp-{cenario['cao']}"]
    assert [g["chave"] for g in d["grupos"]][-2:] == ["sem-especie", "pessoa"]  # espécies primeiro, depois o resto
    assert (cao["validadas"], cao["pendentes"], cao["marcadas"]) == (1, 1, 1)
    assert [i["estado"] for i in cao["itens"]] == ["sugerida", "validada"]  # pendentes primeiro
    cutia = grupos[f"esp-{cenario['cutia']}"]
    assert cutia["itens"][0]["pre"] is False and cutia["itens"][0]["conf"] == .55  # confiança baixa não vem marcada
    assert grupos["pessoa"]["itens"][0]["pre"] is True and grupos["pessoa"]["resultado"] == "pessoa"
    sem = grupos["sem-especie"]
    assert sem["resultado"] is None and "Felidae 50%" in sem["itens"][0]["sugestao"]
    assert sum(len(g["itens"]) for g in d["grupos"]) == 5  # a sequência abaixo do limiar (vazia) não aparece
    assert (d["validadas"], d["pendentes"], d["especies"]) == (1, 4, 2)
    with ambiente["fabrica"]() as s:
        assert [g["chave"] for g in validacao.montar(s, camera_id=cenario["p2"])["grupos"]] == [f"esp-{cenario['cao']}"]


def test_validar_corrigir_e_preservar_detalhes(ambiente, cenario):
    with ambiente["fabrica"]() as s:
        assert validacao.validar(s, [_item(cenario, "cao_alta")], "especie", cenario["cao"]) == 1
        validacao.validar(s, [_item(cenario, "cutia_baixa")], "especie", cenario["cao"])  # correção: era cão, não cutia
        validacao.validar(s, [_item(cenario, "pessoa")], "pessoa")
        validacao.validar(s, [_item(cenario, "cao_validado")], "especie", cenario["cutia"])  # corrige uma já validada
        revs = {r.chave_sequencia: r for r in s.scalars(select(Revisao))}
        assert revs[cenario["ids"]["cutia_baixa"][1]].especie_id == cenario["cao"]
        sugerido = revs[cenario["ids"]["cutia_baixa"][1]].sugestao_ia
        assert sugerido["nome_cientifico"] == "Dasyprocta azarae"  # guarda o que a IA disse
        c = revs[cenario["ids"]["cao_validado"][1]]
        detalhes = (c.especie_id, c.quantidade, c.comportamento, c.divulgacao, c.observacao)
        assert detalhes == (cenario["cutia"], 2, "forrageando", True, "par")  # detalhes da revisão anterior não se perdem
        d = validacao.montar(s)
        assert d["pendentes"] == 1  # só o felino sem espécie
        with pytest.raises(ValueError):  # arquivo de outra importação
            outro = _item(cenario, "cao_alta")
            validacao.validar(s, [{**outro, "imp_id": cenario["ids"]["cao_validado"][0]}], "especie", cenario["cao"])


def test_por_camera_planilha_e_resumo(ambiente, cenario):
    with ambiente["fabrica"]() as s:
        p1 = validacao.por_camera(s, cenario["p1"])
        assert [e["titulo"] for e in p1] == ["cachorro-do-mato", "cutia", "Animal: espécie a definir"]
        validacao.validar(s, [_item(cenario, "cao_alta")], "especie", cenario["cao"])
        regs = validacao.registros_validados(s, campanha_id=cenario["campanha"])
    assert len(regs) == 2 and all(r["ia_concordou"] for r in regs)
    resumo = validacao.resumo_especies(regs)
    g = resumo[0]
    assert len(resumo) == 1 and (g["registros"], g["individuos"], g["cameras"]) == (2, 3, {"P1", "P2"})
    assert resumo[0]["fotos"][0]["divulgacao"]  # foto marcada para divulgação vem primeiro
    wb = load_workbook(BytesIO(planilha_especies.planilha(resumo, regs, "teste")))
    assert wb.sheetnames == ["Espécies", "Registros", "Sobre"]
    assert wb["Espécies"]["A2"].value == "cachorro-do-mato" and wb["Espécies"]["D2"].value == 2
    assert wb["Registros"].max_row == 3 and wb["Registros"]["O2"].value == "sim"


def test_telas(ambiente, cenario):
    c = TestClient(criar_app(ambiente["fabrica"], sincrono=True, extras_cartoes=[]))
    r = c.get("/validacao")
    assert r.status_code == 200 and "cachorro-do-mato" in r.text and "Animal: espécie a definir" in r.text
    assert r.text.count('class="marca" tabindex="-1" aria-label="marcar" checked') == 2  # cão 93% e pessoa 95%
    assert 'href="/validacao"' in r.text  # item no menu
    ok = c.post("/validacao", json={"itens": [_item(cenario, "cao_alta")], "resultado": "especie", "especie_id": cenario["cao"]})
    assert ok.status_code == 200 and ok.json()["salvos"] == 1
    assert c.post("/validacao", json={"itens": [], "resultado": "especie"}).status_code == 400
    assert c.post("/validacao", json={"itens": [_item(cenario, "pessoa")], "resultado": "onça"}).status_code == 400
    xlsx = c.get("/validacao/planilha", params={"camera": cenario["p1"]})
    assert xlsx.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "attachment" in xlsx.headers["content-disposition"]
    rel = c.get("/validacao/relatorio", params={"campanha": cenario["campanha"]})
    assert rel.status_code == 200 and "Relatório fotográfico" in rel.text and "cachorro-do-mato" in rel.text
    assert "aguardam validação" in rel.text and "/arquivos/" in rel.text
    cam = c.get(f"/cameras/{cenario['p1']}")
    assert "Espécies registradas por esta câmera" in cam.text and f"/validacao?camera={cenario['p1']}" in cam.text
