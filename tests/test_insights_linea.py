# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test di `Linea`, `costruisci_linee` e `aggrega_archi`, con treni costruiti a mano.

I valori attesi sono calcolati a mano nei commenti. Tre casi vengono dai dati reali: Lecco - Milano
P.G. (un solo itinerario percorso nei due versi), Edolo - Brescia (alternativo per una fermata in
piu') e il treno 24845 (parzialmente soppresso).
"""

import json
from pathlib import Path

import pytest
from viaggiatreno import TrainStatus
from viaggiatreno.insights import (
    Linea,
    ProfiloTreno,
    RapportoItinerario,
    aggrega_archi,
    costruisci_linee,
    e_sottosequenza,
)

DATI = Path(__file__).parent / "dati"
MIN = 60_000
T0 = 1_800_000_000_000


def treno(codici, *, cat="REG", op=None, partenza=0, passo=10, ritardi=None, tipo="PG", **kw):
    """Treno che tocca `codici` in ordine, un arco ogni `passo` minuti, sosta di 1'.

    `ritardi`: ritardo in minuti per ogni fermata (default: nessuno, orari reali = teorici).
    """
    ritardi = ritardi or [0] * len(codici)
    fermate = []
    for i, c in enumerate(codici):
        arr = None if i == 0 else partenza + i * passo + (i - 1)
        par = None if i == len(codici) - 1 else partenza + i * passo + i
        r = ritardi[i]
        fermate.append(
            {
                "id": c,
                "stazione": f"NOME {c}",
                "tipoFermata": "P" if i == 0 else ("A" if i == len(codici) - 1 else "F"),
                "progressivo": i + 1,
                "arrivo_teorico": None if arr is None else T0 + arr * MIN,
                "partenza_teorica": None if par is None else T0 + par * MIN,
                "arrivoReale": None if arr is None else T0 + (arr + r) * MIN,
                "partenzaReale": None if par is None else T0 + (par + r) * MIN,
                "programmata": T0 + (par if par is not None else (arr or 0)) * MIN,
                "actualFermataType": 1,
            }
        )
    dati = {"numeroTreno": 1, "categoria": cat, "tipoTreno": tipo, "fermate": fermate}
    if op:
        dati["codiceCliente"] = op
    return ProfiloTreno.da_status(TrainStatus.model_validate({**dati, **kw}))


# ------------------------------------------------------------------ e_sottosequenza


def test_sottosequenza():
    assert e_sottosequenza(("A", "C"), ("A", "B", "C"))
    assert e_sottosequenza(("A", "B", "C"), ("A", "B", "C"))
    assert not e_sottosequenza(("C", "A"), ("A", "B", "C"))  # ordine diverso
    assert not e_sottosequenza(("A", "D"), ("A", "B", "C"))  # D non c'e'
    assert e_sottosequenza((), ("A", "B"))


# ------------------------------------------------------------------ linee


def test_stessi_estremi_nei_due_versi_sono_una_linea():
    linee = costruisci_linee([treno(["S1", "S2", "S3"]), treno(["S3", "S2", "S1"])])
    assert len(linee) == 1
    (linea,) = linee
    assert (linea.estremo_a, linea.estremo_b, linea.chiave) == ("S1", "S3", "S1|S3")
    assert linea.n_treni == 2 and linea.n_varianti == 1
    v = linea.completa
    assert (v.n_treni, v.n_verso_diretto, v.n_verso_inverso) == (2, 1, 1)


def test_estremi_diversi_sono_linee_diverse():
    linee = costruisci_linee([treno(["S1", "S2", "S3"]), treno(["S1", "S2", "S4"])])
    assert {x.chiave for x in linee} == {"S1|S3", "S1|S4"}


def test_variante_che_salta_fermate():
    linee = costruisci_linee(
        [
            treno(["S1", "S2", "S3", "S4"]),
            treno(["S1", "S2", "S3", "S4"]),
            treno(["S1", "S3", "S4"]),
        ]
    )
    (linea,) = linee
    completa, veloce = linea.varianti
    assert completa.rapporto is RapportoItinerario.COMPLETO and completa.n_treni == 2
    assert veloce.rapporto is RapportoItinerario.SALTA_FERMATE and veloce.n_treni == 1
    assert linea.stazioni == ("S1", "S2", "S3", "S4")


def test_variante_alternativa_ha_fermate_che_l_altra_non_ha():
    # come Edolo - Brescia: una fermata in piu' (Sonico) che il completo non ha
    linee = costruisci_linee(
        [
            treno(["S1", "S2", "S3", "S5"]),
            treno(["S1", "S2", "S3", "S5"]),
            treno(["S1", "S4", "S5"]),
        ]
    )
    (linea,) = linee
    alt = next(v for v in linea.varianti if v.rapporto is RapportoItinerario.ALTERNATIVO)
    assert alt.itinerario.codici == ("S1", "S4", "S5")


def test_l_itinerario_completo_e_quello_con_piu_fermate_non_quello_piu_frequente():
    # 5 treni veloci e 1 solo completo: il "completo" resta quello con piu' fermate
    veloci = [treno(["S1", "S3"]) for _ in range(5)]
    (linea,) = costruisci_linee([*veloci, treno(["S1", "S2", "S3"])])
    assert linea.completa.itinerario.n_fermate == 3 and linea.completa.n_treni == 1
    assert linea.varianti[1].rapporto is RapportoItinerario.SALTA_FERMATE
    assert linea.varianti[1].n_treni == 5


def test_a_parita_di_fermate_vince_l_itinerario_con_piu_treni():
    a, b = ["S1", "S2", "S4"], ["S1", "S3", "S4"]
    (linea,) = costruisci_linee([treno(a), treno(b), treno(b)])
    assert linea.completa.itinerario.codici == ("S1", "S3", "S4")  # b ha 2 treni
    assert linea.varianti[1].rapporto is RapportoItinerario.ALTERNATIVO


def test_categorie_e_operatori_della_linea():
    linee = costruisci_linee(
        [
            treno(["S1", "S2"], cat="REG", op=63),
            treno(["S1", "S2"], cat="REG", op=63),
            treno(["S2", "S1"], cat="IC", op=1),
        ]
    )
    (linea,) = linee
    assert linea.categorie == (("REG", 2), ("IC", 1))
    assert linea.completa.categorie == (("REG", 2), ("IC", 1))
    assert dict(linea.operatori) == {"Trenord": 2, "Trenitalia (alta velocità)": 1}


def test_treno_cancellato_o_con_una_fermata_non_forma_una_linea():
    cancellato = ProfiloTreno.da_status(
        TrainStatus.model_validate({"numeroTreno": 9, "tipoTreno": "ST", "fermate": []})
    )
    assert costruisci_linee([cancellato, treno(["S1", "S2"])])[0].n_treni == 1
    assert costruisci_linee([cancellato]) == ()
    assert costruisci_linee([]) == ()


def test_le_soppresse_restano_nella_linea_programmata():
    # il 24845 e' parzialmente soppresso (si ferma a Carnate) ma e' sulla linea Lecco - Milano P.G.
    reale = TrainStatus.model_validate(json.loads((DATI / "andamentoTreno_24845.json").read_text()))
    (linea,) = costruisci_linee([ProfiloTreno.da_status(reale)])
    assert linea.chiave == "S01520|S01645" and linea.completa.itinerario.n_fermate == 13
    assert linea.collegamento.chiave == ("S01520", "S01645")


def test_ordine_delle_linee_per_numero_di_treni():
    linee = costruisci_linee([treno(["S1", "S2"]), treno(["S5", "S6"]), treno(["S6", "S5"])])
    assert [x.chiave for x in linee] == ["S5|S6", "S1|S2"]


def test_il_risultato_non_dipende_dall_ordine_dei_treni():
    ts = [
        treno(["S1", "S2", "S3"]),
        treno(["S1", "S3"]),
        treno(["S3", "S2", "S1"]),
        treno(["S1", "S4", "S3"]),
    ]
    a = costruisci_linee(ts)
    b = costruisci_linee(list(reversed(ts)))
    assert a == b and isinstance(a[0], Linea)


def test_nome_della_linea_dai_nomi_degli_estremi():
    (linea,) = costruisci_linee([treno(["S1", "S2", "S3"])])
    assert linea.nome == "NOME S1 - NOME S3"


# ------------------------------------------------------------------ archi aggregati


def test_arco_aggregato_somma_i_due_versi():
    # S1 -> S2 e S2 -> S1: stessa coppia
    archi = aggrega_archi([treno(["S1", "S2"]), treno(["S2", "S1"])])
    (a,) = archi
    assert a.coppia == ("S1", "S2") and a.n_treni == 2


def test_durate_mediane_a_mano():
    # tre treni sullo stesso arco: durata prevista sempre 10'. reali: 10', 12', 20' (via ritardi
    # crescenti di 0, 2 e 10 minuti sulla seconda fermata) -> mediana 12
    def uno(rit_arrivo):
        return treno(["S1", "S2"], passo=10, ritardi=[0, rit_arrivo])

    (a,) = aggrega_archi([uno(0), uno(2), uno(10)])
    assert a.durata_programmata_mediana == 10
    assert a.durata_effettiva_mediana == 12
    assert a.scarto_mediano == 2  # mediana di 0, 2, 10
    assert a.ritardo_accumulato_medio == pytest.approx(4.0)  # (0 + 2 + 10) / 3
    assert (a.n_treni, a.n_percorsi, a.n_soppressi) == (3, 3, 0)


def test_mediana_resiste_a_un_valore_anomalo():
    treni = [treno(["S1", "S2"], ritardi=[0, r]) for r in (0, 0, 0, 0, 60)]
    (a,) = aggrega_archi(treni)
    assert a.scarto_mediano == 0 and a.ritardo_accumulato_medio == pytest.approx(12.0)


def test_arco_recupero_di_ritardo_e_negativo():
    (a,) = aggrega_archi([treno(["S1", "S2"], ritardi=[5, 2])])
    assert a.ritardo_accumulato_medio == -3 and a.scarto_mediano == -3


def test_arco_soppresso_conta_ma_non_entra_nelle_durate():
    t = treno(["S1", "S2", "S3"])
    soppresso = ProfiloTreno.da_status(
        TrainStatus.model_validate(
            {
                "numeroTreno": 2,
                "fermate": [
                    dict(f.model_dump(), actualFermataType=3 if f.id == "S2" else 1)
                    for f in TrainStatus.model_validate(
                        {"numeroTreno": 2, "fermate": [_f(x) for x in t.fermate]}
                    ).fermate
                ],
            }
        )
    )
    archi = {a.coppia: a for a in aggrega_archi([t, soppresso])}
    assert archi[("S1", "S2")].n_treni == 2 and archi[("S1", "S2")].n_soppressi == 1
    assert archi[("S1", "S2")].n_percorsi == 1  # solo il treno regolare ha la durata effettiva


def _f(fermata):
    return {
        "id": fermata.codice,
        "stazione": fermata.nome,
        "tipoFermata": "F",
        "progressivo": fermata.posizione + 1,
        "arrivo_teorico": fermata.arrivo_teorico,
        "partenza_teorica": fermata.partenza_teorica,
        "arrivoReale": fermata.arrivo_reale,
        "partenzaReale": fermata.partenza_reale,
        "actualFermataType": 1,
    }


def test_arco_non_percorso_non_ha_durata_effettiva():
    prog = treno(["S1", "S2"]).fermate
    s = TrainStatus.model_validate(
        {
            "numeroTreno": 3,
            "fermate": [
                dict(_f(f), arrivoReale=None, partenzaReale=None, actualFermataType=0) for f in prog
            ],
        }
    )
    (a,) = aggrega_archi([ProfiloTreno.da_status(s)])
    assert a.durata_programmata_mediana == 10 and a.durata_effettiva_mediana is None
    assert a.n_percorsi == 0 and a.scarto_mediano is None and a.ritardo_accumulato_medio is None


def test_min_treni_scarta_le_coppie_rare():
    ts = [treno(["S1", "S2"]), treno(["S1", "S2"]), treno(["S5", "S6"])]
    assert {a.coppia for a in aggrega_archi(ts, min_treni=2)} == {("S1", "S2")}
    assert len(aggrega_archi(ts)) == 2


def test_distanza_e_velocita_con_le_coordinate():
    t = treno(["S1", "S2"])
    con = ProfiloTreno.da_status(
        TrainStatus.model_validate({"numeroTreno": 1, "fermate": [_f(f) for f in t.fermate]}),
        coordinate={"S1": (45.0, 9.0), "S2": (45.0, 9.1)},
    )
    (a,) = aggrega_archi([con])
    assert a.distanza_km is not None and a.distanza_km > 7
    assert a.velocita_programmata_kmh == pytest.approx(a.distanza_km / (10 / 60))
    (b,) = aggrega_archi([t])  # senza coordinate
    assert b.distanza_km is None and b.velocita_programmata_kmh is None


def test_archi_ordinati_per_numero_di_treni_e_nomi():
    ts = [treno(["S1", "S2"]), treno(["S3", "S4"]), treno(["S4", "S3"])]
    archi = aggrega_archi(ts)
    assert [a.coppia for a in archi] == [("S3", "S4"), ("S1", "S2")]
    assert (archi[0].nome_a, archi[0].nome_b) == ("NOME S3", "NOME S4")
    assert archi[0].categorie == (("REG", 2),)


def test_fermata_che_viene_saltata_genera_un_arco_diverso():
    # S1 -> S2 -> S3 e S1 -> S3: l'arco S1-S3 (veloce) non si confonde con S1-S2 e S2-S3
    archi = {a.coppia for a in aggrega_archi([treno(["S1", "S2", "S3"]), treno(["S1", "S3"])])}
    assert archi == {("S1", "S2"), ("S2", "S3"), ("S1", "S3")}


# ------------------------------------------------------------------ dati reali


def test_treno_reale_aggregato_con_se_stesso_nei_due_versi():
    reale = ProfiloTreno.da_status(
        TrainStatus.model_validate(json.loads((DATI / "andamentoTreno_24845.json").read_text()))
    )
    archi = aggrega_archi([reale])
    assert len(archi) == 12 and sum(a.n_soppressi for a in archi) == 5
    primo = next(a for a in archi if a.coppia == ("S01520", "S01522"))
    assert (primo.durata_programmata_mediana, primo.durata_effettiva_mediana) == (4, 4)
