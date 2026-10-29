"""Lista inicial de espécies (Mata Atlântica = MA, Cerrado = CE). Editável na interface; não é exaustiva.

Nomes científicos seguem a taxonomia usual em listas brasileiras recentes; onde houve mudança recente,
o nome antigo aparece no nome popular entre parênteses para facilitar a busca.
"""

from __future__ import annotations

from sqlalchemy import select

from camtrap_campo.db import Especie

INICIAIS: list[tuple[str, str, str, str]] = [
    # nome científico, nome popular, grupo, biomas
    ("Panthera onca", "onça-pintada", "mamífero", "MA, CE"),
    ("Puma concolor", "onça-parda / suçuarana", "mamífero", "MA, CE"),
    ("Leopardus pardalis", "jaguatirica", "mamífero", "MA, CE"),
    ("Leopardus guttulus", "gato-do-mato-pequeno", "mamífero", "MA, CE"),
    ("Leopardus wiedii", "gato-maracajá", "mamífero", "MA, CE"),
    ("Herpailurus yagouaroundi", "gato-mourisco", "mamífero", "MA, CE"),
    ("Chrysocyon brachyurus", "lobo-guará", "mamífero", "CE"),
    ("Cerdocyon thous", "cachorro-do-mato", "mamífero", "MA, CE"),
    ("Lycalopex vetulus", "raposinha-do-campo", "mamífero", "CE"),
    ("Speothos venaticus", "cachorro-vinagre", "mamífero", "MA, CE"),
    ("Nasua nasua", "quati", "mamífero", "MA, CE"),
    ("Procyon cancrivorus", "mão-pelada", "mamífero", "MA, CE"),
    ("Eira barbara", "irara", "mamífero", "MA, CE"),
    ("Galictis cuja", "furão-pequeno", "mamífero", "MA, CE"),
    ("Lontra longicaudis", "lontra", "mamífero", "MA, CE"),
    ("Conepatus semistriatus", "jaritataca", "mamífero", "CE"),
    ("Tapirus terrestris", "anta", "mamífero", "MA, CE"),
    ("Tayassu pecari", "queixada", "mamífero", "MA, CE"),
    ("Dicotyles tajacu", "cateto (Pecari tajacu)", "mamífero", "MA, CE"),
    ("Mazama americana", "veado-mateiro", "mamífero", "MA, CE"),
    ("Subulo gouazoubira", "veado-catingueiro (Mazama gouazoubira)", "mamífero", "MA, CE"),
    ("Ozotoceros bezoarticus", "veado-campeiro", "mamífero", "CE"),
    ("Myrmecophaga tridactyla", "tamanduá-bandeira", "mamífero", "MA, CE"),
    ("Tamandua tetradactyla", "tamanduá-mirim", "mamífero", "MA, CE"),
    ("Priodontes maximus", "tatu-canastra", "mamífero", "CE"),
    ("Euphractus sexcinctus", "tatu-peba", "mamífero", "MA, CE"),
    ("Dasypus novemcinctus", "tatu-galinha", "mamífero", "MA, CE"),
    ("Cabassous unicinctus", "tatu-de-rabo-mole", "mamífero", "CE"),
    ("Cuniculus paca", "paca", "mamífero", "MA, CE"),
    ("Dasyprocta azarae", "cutia", "mamífero", "MA, CE"),
    ("Hydrochoerus hydrochaeris", "capivara", "mamífero", "MA, CE"),
    ("Coendou spinosus", "ouriço-cacheiro", "mamífero", "MA"),
    ("Guerlinguetus brasiliensis", "serelepe / esquilo", "mamífero", "MA"),
    ("Sylvilagus brasiliensis", "tapiti", "mamífero", "MA, CE"),
    ("Didelphis aurita", "gambá-de-orelha-preta", "mamífero", "MA"),
    ("Didelphis albiventris", "gambá-de-orelha-branca", "mamífero", "CE"),
    ("Sapajus nigritus", "macaco-prego", "mamífero", "MA"),
    ("Sapajus libidinosus", "macaco-prego", "mamífero", "CE"),
    ("Cariama cristata", "seriema", "ave", "CE"),
    ("Crax fasciolata", "mutum-de-penacho", "ave", "CE"),
    ("Penelope superciliaris", "jacupemba", "ave", "MA, CE"),
    ("Penelope obscura", "jacuaçu", "ave", "MA"),
    ("Crypturellus parvirostris", "inhambu-chororó", "ave", "CE"),
    ("Crypturellus obsoletus", "inhambuguaçu", "ave", "MA"),
    ("Leptotila verreauxi", "juriti-pupu", "ave", "MA, CE"),
    ("Aramides saracura", "saracura-do-mato", "ave", "MA"),
    ("Salvator merianae", "teiú", "réptil", "MA, CE"),
    ("Canis familiaris", "cachorro doméstico", "doméstico", ""),
    ("Felis catus", "gato doméstico", "doméstico", ""),
    ("Bos taurus", "gado bovino", "doméstico", ""),
    ("Equus caballus", "cavalo", "doméstico", ""),
    ("Sus scrofa", "javali / porco (exótico)", "exótico", ""),
    ("Lepus europaeus", "lebre-europeia (exótica)", "exótico", ""),
]

COMPORTAMENTOS = ["deslocamento", "forrageio", "vigilância", "descanso", "interação social", "marcação de território",
                  "com filhote", "outro"]


def semear(sessao) -> int:
    """Insere as espécies iniciais que faltarem (não altera as já editadas). Devolve quantas inseriu."""
    existentes = set(sessao.scalars(select(Especie.nome_cientifico)))
    novas = [Especie(nome_cientifico=c, nome_popular=p, grupo=g, biomas=b or None)
             for c, p, g, b in INICIAIS if c not in existentes]
    sessao.add_all(novas)
    sessao.commit()
    return len(novas)
