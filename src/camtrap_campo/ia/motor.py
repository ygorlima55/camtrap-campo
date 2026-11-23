"""Motores de IA com uma interface única: ``analisar(caminhos) -> list[Resultado]``.

- ``MotorSpeciesNet``: SpeciesNet (Google) — detector MegaDetector v5a + classificador + filtro geográfico (país).
  Roda localmente; os pesos são baixados uma vez na instalação.
- ``MotorSimulado``: SÓ para testes automáticos. Ativado apenas com CAMTRAP_IA_SIMULADA=1; todo resultado sai com
  ``simulado=True`` e a interface mostra a marca "SIMULADO". Nunca é usado por padrão.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

CATEGORIAS_MD = {"1": "animal", "2": "pessoa", "3": "veiculo", "animal": "animal", "human": "pessoa",
                 "person": "pessoa", "vehicle": "veiculo"}


@dataclass
class Resultado:
    caminho: str
    deteccoes: list[dict] = field(default_factory=list)  # {categoria, confianca, bbox[x,y,w,h]}
    classificacao: dict | None = None  # {rotulo, nome_cientifico, nome_popular_en, confianca, fonte}
    modelo: str = ""
    simulado: bool = False
    erro: str | None = None


class MotorIndisponivel(RuntimeError):
    pass


def descrever(sug: dict | None) -> str | None:
    """Nome legível de uma sugestão: espécie/gênero, ou o grupo mais fino (ex.: "rodent (ordem Rodentia)")."""
    if not sug:
        return None
    if sug.get("nome_cientifico"):
        return sug["nome_cientifico"]
    for nivel in ("familia", "ordem", "classe"):
        if sug.get(nivel):
            rotulo = {"familia": "família", "ordem": "ordem", "classe": "classe"}[nivel]
            comum = sug.get("nome_popular_en")
            return f"{comum} ({rotulo} {sug[nivel].capitalize()})" if comum else f"{rotulo} {sug[nivel].capitalize()}"
    rotulo = sug.get("nome_popular_en") or sug.get("rotulo")
    return rotulo.split(";")[-1] if rotulo else None


def interpretar_rotulo(rotulo: str | None) -> dict:
    """Rótulo SpeciesNet 'uuid;classe;ordem;família;gênero;espécie;nome comum' → partes legíveis."""
    if not rotulo:
        return {}
    partes = rotulo.split(";")
    if len(partes) < 7:
        return {"rotulo": rotulo, "nome_popular_en": partes[-1] if partes else rotulo}
    _, classe, ordem, familia, genero, especie, comum = partes[:7]
    cientifico = " ".join(p for p in (genero.capitalize(), especie.lower()) if p) or None
    nivel = "espécie" if genero and especie else "gênero" if genero else "família" if familia else \
        "ordem" if ordem else "classe" if classe else "sem táxon"
    return {"rotulo": rotulo, "classe": classe or None, "ordem": ordem or None, "familia": familia or None,
            "nome_cientifico": cientifico, "nivel": nivel, "nome_popular_en": comum or None}


class MotorSpeciesNet:
    nome = "SpeciesNet"

    def __init__(self, pais: str = "BRA", modelo: str | None = None):
        try:
            from speciesnet import DEFAULT_MODEL, SpeciesNet
        except ImportError as exc:
            raise MotorIndisponivel("SpeciesNet não instalado — rode instalar_ia.bat") from exc
        self.pais = pais
        self.versao = modelo or DEFAULT_MODEL
        self._sn = SpeciesNet(self.versao, components="all", geofence=True)
        self.nome = f"SpeciesNet {self.versao} (MegaDetector + classificador, filtro {pais})"

    def analisar(self, caminhos: list[Path]) -> list[Resultado]:
        saida = self._sn.predict(filepaths=[str(c) for c in caminhos], country=self.pais, batch_size=1,
                                 progress_bars=False)
        por_caminho = {p["filepath"]: p for p in (saida or {}).get("predictions", [])}
        return [converter_predicao(por_caminho.get(str(c), {}), str(c), self.nome) for c in caminhos]


ROTULOS_NAO_ESPECIE = {"blank", "human", "vehicle", "animal", "no cv result"}


def converter_predicao(p: dict, caminho: str, modelo: str) -> Resultado:
    """Saída do SpeciesNet → Resultado.

    Formato observado no modelo 4.0.3a: cada detecção traz ``processed_classification`` {class, score, source};
    não há previsão única por foto. Versões que trazem ``prediction`` no nível da foto também são aceitas.
    """
    r = Resultado(caminho, modelo=modelo)
    if p.get("failures"):
        r.erro = "falha do modelo: " + ", ".join(p["failures"])
    candidatas = []
    for d in p.get("detections", []):
        categoria = CATEGORIAS_MD.get(str(d.get("category")), CATEGORIAS_MD.get(str(d.get("label")), "animal"))
        pc = d.get("processed_classification") or {}
        classificacao = None
        if pc.get("class"):
            classificacao = {**interpretar_rotulo(pc["class"]), "confianca": float(pc.get("score", 0) or 0),
                             "fonte": pc.get("source")}
            comum = (classificacao.get("nome_popular_en") or "").lower()
            if categoria == "animal" and comum not in ROTULOS_NAO_ESPECIE:
                candidatas.append(classificacao)
        r.deteccoes.append({"categoria": categoria, "confianca": float(d.get("conf", 0)),
                            "bbox": [float(v) for v in d.get("bbox", [0, 0, 0, 0])], "classificacao": classificacao})
    if candidatas:
        r.classificacao = max(candidatas, key=lambda c: c["confianca"])
    elif p.get("prediction"):
        geral = interpretar_rotulo(p["prediction"])
        if (geral.get("nome_popular_en") or "").lower() not in ROTULOS_NAO_ESPECIE:
            r.classificacao = {**geral, "confianca": float(p.get("prediction_score", 0) or 0),
                               "fonte": p.get("prediction_source")}
    return r


class MotorSimulado:
    """Resultado determinístico a partir do hash do arquivo. Exclusivo para testes."""

    nome = "SIMULADO (apenas testes)"

    def analisar(self, caminhos: list[Path]) -> list[Resultado]:
        out = []
        for c in caminhos:
            h = int(hashlib.sha256(Path(c).read_bytes()).hexdigest()[:8], 16)
            r = Resultado(str(c), modelo=self.nome, simulado=True)
            if h % 3 != 0:  # ~2/3 com animal
                r.deteccoes.append({"categoria": "animal", "confianca": 0.5 + (h % 50) / 100, "bbox": [0.3, 0.3, 0.25, 0.3]})
                r.classificacao = {**interpretar_rotulo(
                    "00000000;mammalia;carnivora;canidae;cerdocyon;thous;crab-eating fox"),
                    "confianca": 0.6, "fonte": "simulado"}
            out.append(r)
        return out


def criar_motor(pais: str = "BRA"):
    if os.environ.get("CAMTRAP_IA_SIMULADA") == "1":
        return MotorSimulado()
    return MotorSpeciesNet(pais=pais)


def disponivel() -> tuple[bool, str]:
    if os.environ.get("CAMTRAP_IA_SIMULADA") == "1":
        return True, "motor SIMULADO (modo de teste)"
    try:
        import speciesnet  # noqa: F401
    except ImportError:
        return False, "SpeciesNet não instalado (rode instalar_ia.bat)"
    return True, "SpeciesNet instalado"


def dispositivo() -> str:
    try:
        import torch
    except ImportError:
        return "indisponível"
    return "GPU (CUDA)" if torch.cuda.is_available() else "CPU"
