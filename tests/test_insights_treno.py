# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test di `ProfiloTreno`, con una risposta reale di `andamentoTreno` e treni costruiti a mano.

La fixture `dati/andamentoTreno_24845.json` e' una risposta vera (REG 24845 Lecco -> Milano P.G.,
12/11/2026): parzialmente soppresso, 13 fermate, le ultime 5 soppresse da Carnate in poi. I valori
attesi sono letti dai dati, non ricalcolati con la stessa logica.
"""

import json
from pathlib import Path

import pytest
from viaggiatreno import TrainStatus
from viaggiatreno.insights import (
    Arco,
    Avanzamento,
    Itinerario,
    ProfiloTreno,
    StatoFermata,
    StatoTreno,
    Verso,
    distanza_km,
    ha_anomalie,
    profilo_treno,
)

DATI = Path(__file__).parent / "dati"
MIN = 60_000
T0 = 1_800_000_000_000


def reale() -> TrainStatus:
    return TrainStatus.model_validate(json.loads((DATI / "andamentoTreno_24845.json").read_text()))


def fermata(
    codice,
    prog,
    *,
    arr_t=None,
    par_t=None,
    arr_r=None,
    par_r=None,
    tipo="F",
    act=1,
    bin_ap=None,
    bin_ae=None,
    bin_pp=None,
    bin_pe=None,
):
    """Una fermata sintetica (orari in minuti da T0)."""
    ms = lambda m: None if m is None else T0 + m * MIN
    return {
        "id": codice,
        "stazione": f"STAZ {codice}",
        "tipoFermata": tipo,
        "progressivo": prog,
        "arrivo_teorico": ms(arr_t),
        "partenza_teorica": ms(par_t),
        "arrivoReale": ms(arr_r),
        "partenzaReale": ms(par_r),
        "actualFermataType": act,
        "binarioProgrammatoArrivoDescrizione": bin_ap,
        "binarioEffettivoArrivoDescrizione": bin_ae,
        "binarioProgrammatoPartenzaDescrizione": bin_pp,
        "binarioEffettivoPartenzaDescrizione": bin_pe,
    }


def treno(fermate, **kw):
    dati = {"numeroTreno": 1, "categoria": "REG", "fermate": fermate}
    return TrainStatus.model_validate({**dati, **kw})


def tre_fermate():
    """S1 -> S2 -> S3: S1 parte alle 0 (+2 di ritardo), S2 arriva alle 10 (+3) e riparte alle 12 (+4)."""
    return [
        fermata("S1", 1, par_t=0, par_r=2, tipo="P"),
        fermata("S2", 2, arr_t=10, par_t=12, arr_r=13, par_r=16),
        fermata("S3", 3, arr_t=20, arr_r=24, tipo="A"),
    ]


# ------------------------------------------------------------------ treno reale


def test_treno_reale_identita_e_stato():
    p = ProfiloTreno.da_status(reale())
    assert (p.numero, p.categoria, p.operatore, p.data) == (24845, "REG", "Trenord", "2026-11-12")
    assert p.stato is StatoTreno.PARZIALMENTE_SOPPRESSO
    assert len(p.fermate) == 13 and len(p.archi) == 12


def test_treno_reale_itinerario_programmato_con_le_soppresse():
    p = ProfiloTreno.da_status(reale())
    assert p.itinerario is not None and p.verso is Verso.DIRETTO
    assert p.itinerario.n_fermate == 13  # tutte, soppresse comprese
    assert p.itinerario.estremo_a == "S01520" and p.itinerario.estremo_b == "S01645"
    assert "S01322" in p.itinerario  # Monza, soppressa, resta nel percorso programmato


def test_treno_reale_collegamento_programmato_ed_effettivo_differiscono():
    p = ProfiloTreno.da_status(reale())
    assert p.collegamento_programmato is not None and p.collegamento_effettivo is not None
    assert p.collegamento_programmato.chiave == ("S01520", "S01645")  # Lecco -> Milano P.G.
    assert p.collegamento_effettivo.chiave == ("S01520", "S01511")  # Lecco -> Carnate


def test_treno_reale_fermate_effettuate_e_soppresse():
    p = ProfiloTreno.da_status(reale())
    assert len(p.fermate_effettuate) == 8 and len(p.fermate_soppresse) == 5
    assert p.ultima_effettuata is not None and p.ultima_effettuata.codice == "S01511"
    assert p.fermate_soppresse[0].nome == "ARCORE"
    assert all(f.stato is StatoFermata.SOPPRESSA for f in p.fermate_soppresse)


def test_treno_reale_archi_dal_primo_all_ultimo():
    p = ProfiloTreno.da_status(reale())
    a = p.archi[0]  # Lecco -> Lecco Maggianico: 12:06 -> 12:10, partito con 5' di ritardo
    assert (a.da.codice, a.a.codice) == ("S01520", "S01522")
    assert a.durata_programmata == 4 and a.durata_effettiva == 4
    assert a.ritardo_accumulato == 0
    assert p.archi[1].durata_programmata == 4 and p.archi[1].durata_effettiva == 3
    assert p.archi[1].a.nome == "CALOLZIOCORTE OLGINATE"


def test_treno_reale_archi_effettuati_e_soppressi():
    p = ProfiloTreno.da_status(reale())
    assert len(p.archi_effettuati) == 7
    assert sum(1 for a in p.archi if a.soppresso) == 5
    assert all(not a.effettuato for a in p.archi if a.soppresso)


def test_treno_reale_arco_verso_la_destinazione_effettiva_manca_la_durata_prevista():
    # Carnate e' la destinazione effettiva: il sito non da' la sua partenza teorica, quindi
    # l'arco Carnate -> Arcore non ha durata programmata. Va dichiarato, non inventato.
    p = ProfiloTreno.da_status(reale())
    a = next(x for x in p.archi if x.da.codice == "S01511")
    assert a.da.partenza_teorica is None and a.durata_programmata is None and a.soppresso


def test_treno_reale_ritardi_dai_millisecondi_non_dall_api():
    p = ProfiloTreno.da_status(reale())
    f = p.fermate[1]  # Lecco Maggianico: l'API dice 6' in partenza, i ms dicono 5,5'
    assert f.ritardo_api_partenza == 6 and f.ritardo_partenza == 5.5
    assert f.ritardo_arrivo == 5.0
    assert p.ritardo_massimo == 5.5 and p.ritardo_finale == 4.5 and p.ritardo_attuale == 5


def test_treno_reale_durata_e_binari():
    p = ProfiloTreno.da_status(reale())
    assert p.durata_programmata == 62  # 12:06 -> 13:08
    assert p.fermate[0].binari == ("3",) and p.fermate[1].binari == ("1",)
    assert p.fermate[-1].binari == ("17",)  # Milano P.G.: solo programmato, soppressa


def test_treno_reale_soste_programmate_di_un_minuto():
    p = ProfiloTreno.da_status(reale())
    assert p.fermate[0].sosta_programmata is None  # prima fermata: non c'e' arrivo
    assert [f.sosta_programmata for f in p.fermate[1:7]] == [1.0] * 6


# ------------------------------------------------------------------ itinerario e verso


def test_itinerario_indipendente_dal_verso():
    avanti = ProfiloTreno.da_status(treno(tre_fermate()))
    indietro = ProfiloTreno.da_status(
        treno(
            [
                fermata("S3", 1, par_t=0, tipo="P"),
                fermata("S2", 2, arr_t=10, par_t=12),
                fermata("S1", 3, arr_t=20, tipo="A"),
            ]
        )
    )
    assert avanti.itinerario == indietro.itinerario
    assert (avanti.verso, indietro.verso) == (Verso.DIRETTO, Verso.INVERSO)
    # le fermate e gli archi restano nell'ordine di marcia
    assert [f.codice for f in indietro.fermate] == ["S3", "S2", "S1"]
    assert indietro.archi[0].coppia == avanti.archi[-1].coppia == ("S2", "S3")


def test_le_fermate_restano_nell_ordine_dell_api():
    f = tre_fermate()
    p = ProfiloTreno.da_status(treno(f))
    assert [x.codice for x in p.fermate] == ["S1", "S2", "S3"]
    assert [x.posizione for x in p.fermate] == [0, 1, 2]
    assert p.fermate[0].prima and p.fermate[-1].ultima and not p.fermate[1].prima


def test_progressivo_ripetuto_non_mescola_i_tratti():
    # Treno reale 17154 (REG Merano -> Bolzano -> Brennero): unisce due tratti e il progressivo
    # riparte da 1 a Bolzano. Ordinando per progressivo gli orari tornavano indietro.
    dati = json.loads((DATI / "andamentoTreno_17154_progressivo_ripetuto.json").read_text())
    p = ProfiloTreno.da_status(TrainStatus.model_validate(dati))
    assert [f.nome for f in p.fermate][:3] == ["MERANO", "MERANO-MAIA BASSA", "LANA-POSTAL"]
    assert not any(a.durata_programmata is not None and a.durata_programmata < 0 for a in p.archi)
    assert p.itinerario is not None and p.itinerario.n_fermate == 19
    prog = [f.progressivo or 0 for f in TrainStatus.model_validate(dati).fermate]
    assert prog != sorted(prog)  # il progressivo e' davvero non crescente in questo treno


def test_il_progressivo_con_buchi_non_crea_archi_inesistenti():
    p = ProfiloTreno.da_status(
        treno(
            [
                fermata("S1", 1, par_t=0),
                fermata("S2", 6, arr_t=5, par_t=6),
                fermata("S3", 20, arr_t=9),
            ]
        )
    )
    assert [(a.da.codice, a.a.codice) for a in p.archi] == [("S1", "S2"), ("S2", "S3")]


# ------------------------------------------------------------------ archi: valori calcolati a mano


def test_arco_durate_ritardo_e_sosta_a_mano():
    p = ProfiloTreno.da_status(treno(tre_fermate()))
    a1, a2 = p.archi
    # S1 -> S2: previsto 0 -> 10 = 10'; reale 2 -> 13 = 11'; ritardo 2 in partenza, 3 in arrivo
    assert (a1.durata_programmata, a1.durata_effettiva, a1.ritardo_accumulato) == (10, 11, 1)
    # S2 -> S3: previsto 12 -> 20 = 8'; reale 16 -> 24 = 8'; ritardo 4 -> 4
    assert (a2.durata_programmata, a2.durata_effettiva, a2.ritardo_accumulato) == (8, 8, 0)
    # sosta a S2: prevista 12 - 10 = 2'; reale 16 - 13 = 3'
    s2 = p.fermate[1]
    assert (s2.sosta_programmata, s2.sosta_effettiva) == (2, 3)
    assert (s2.ritardo_arrivo, s2.ritardo_partenza) == (3, 4)


def test_arco_che_recupera_ritardo_ha_valore_negativo():
    p = ProfiloTreno.da_status(
        treno([fermata("S1", 1, par_t=0, par_r=5), fermata("S2", 2, arr_t=10, arr_r=12, tipo="A")])
    )
    assert p.archi[0].ritardo_accumulato == -3  # partito con 5', arrivato con 2'


def test_arco_non_ancora_percorso_non_ha_durata_effettiva():
    p = ProfiloTreno.da_status(
        treno(
            [
                fermata("S1", 1, par_t=0, par_r=1),
                fermata("S2", 2, arr_t=10, par_t=11, act=0),
                fermata("S3", 3, arr_t=20, act=0, tipo="A"),
            ]
        )
    )
    assert p.archi[0].durata_effettiva is None and not p.archi[0].effettuato
    assert p.archi[0].durata_programmata == 10 and not p.archi[0].soppresso
    assert p.fermate[1].stato is StatoFermata.ATTESA


def test_ritardo_massimo_e_finale_ignorano_le_fermate_non_effettuate():
    p = ProfiloTreno.da_status(
        treno(
            [
                fermata("S1", 1, par_t=0, par_r=1),
                fermata("S2", 2, arr_t=10, par_t=11, arr_r=17, par_r=18),
                fermata("S3", 3, arr_t=20, act=0, tipo="A"),
            ]
        )
    )
    assert p.ritardo_massimo == 7 and p.ritardo_finale == 7  # arrivo a S2: +7; S3 non raggiunta
    assert p.ultima_effettuata is not None and p.ultima_effettuata.codice == "S2"


def test_ritardi_nulli_quando_il_treno_non_e_partito():
    p = ProfiloTreno.da_status(
        treno(
            [
                fermata("S1", 1, par_t=0, act=0),
                fermata("S2", 2, arr_t=10, act=0, tipo="A"),
            ]
        )
    )
    assert p.ultima_effettuata is None and p.ritardo_massimo is None and p.ritardo_finale is None
    assert p.archi_effettuati == ()


# ------------------------------------------------------------------ binari


def test_binari_della_fermata_unione_e_cambio():
    p = ProfiloTreno.da_status(
        treno(
            [
                fermata("S1", 1, par_t=0, tipo="P", bin_pp="1", bin_pe="1"),
                fermata(
                    "S2", 2, arr_t=10, par_t=12, bin_ap="2", bin_ae="5", bin_pp="2", bin_pe="2"
                ),
                fermata("S3", 3, arr_t=20, tipo="A", bin_ap="4"),
            ]
        )
    )
    assert p.fermate[0].binari == ("1",) and not p.fermate[0].binario_cambiato
    assert p.fermate[1].binari == ("2", "5") and p.fermate[1].binario_cambiato
    assert p.fermate[2].binari == ("4",) and not p.fermate[2].binario_cambiato


def test_binari_vuoti_o_spazi_sono_assenti():
    p = ProfiloTreno.da_status(
        treno(
            [fermata("S1", 1, par_t=0, bin_pp="  ", bin_pe=""), fermata("S2", 2, arr_t=5, tipo="A")]
        )
    )
    assert p.fermate[0].binari == ()


# ------------------------------------------------------------------ stati del treno


def test_treno_regolare():
    p = ProfiloTreno.da_status(treno(tre_fermate(), tipoTreno="PG"))
    assert p.stato is StatoTreno.REGOLARE and p.fermate_soppresse == ()
    assert p.collegamento_programmato == p.collegamento_effettivo


def test_treno_cancellato_senza_fermate():
    p = ProfiloTreno.da_status(treno([], tipoTreno="ST", provvedimento=1))
    assert p.stato is StatoTreno.CANCELLATO
    assert p.itinerario is None and p.verso is None and p.archi == () and p.fermate == ()
    assert p.collegamento_programmato is None and p.durata_programmata is None
    assert p.distanza_km is None and p.ultima_effettuata is None


def test_treno_con_una_sola_fermata_non_ha_itinerario_ne_archi():
    p = ProfiloTreno.da_status(treno([fermata("S1", 1, par_t=0)], tipoTreno="PG"))
    assert p.itinerario is None and p.archi == () and p.collegamento_programmato is None


def test_stato_parziale_anche_senza_fermate_soppresse_se_il_tipo_lo_dice():
    p = ProfiloTreno.da_status(treno(tre_fermate(), tipoTreno="SI"))
    assert p.stato is StatoTreno.PARZIALMENTE_SOPPRESSO


# ------------------------------------------------------------------ distanze


def test_distanza_haversine_nota():
    # Milano Centrale -> Roma Termini in linea d'aria: circa 477 km
    d = distanza_km((45.486347, 9.204528), (41.900636, 12.502026))
    assert d == pytest.approx(477, abs=5)
    assert distanza_km((45.0, 9.0), (45.0, 9.0)) == 0


def test_distanze_e_velocita_con_le_coordinate():
    coord = {"S1": (45.0, 9.0), "S2": (45.0, 9.1), "S3": (45.0, 9.2)}
    p = ProfiloTreno.da_status(treno(tre_fermate()), coordinate=coord)
    d12 = distanza_km(coord["S1"], coord["S2"])
    assert p.archi[0].distanza_km == pytest.approx(d12)
    assert p.distanza_km == pytest.approx(2 * d12, rel=0.01)
    # S1 -> S2: 10' previsti
    assert p.archi[0].velocita_programmata_kmh == pytest.approx(d12 / (10 / 60))


def test_senza_coordinate_distanza_e_velocita_sono_none():
    p = ProfiloTreno.da_status(treno(tre_fermate()))
    assert p.distanza_km is None and p.archi[0].distanza_km is None
    assert p.archi[0].velocita_programmata_kmh is None


def test_coordinate_parziali_non_danno_una_distanza_totale_falsa():
    p = ProfiloTreno.da_status(
        treno(tre_fermate()), coordinate={"S1": (45.0, 9.0), "S2": (45.0, 9.1)}
    )
    assert p.archi[0].distanza_km is not None and p.archi[1].distanza_km is None
    assert p.distanza_km is None  # manca un arco: meglio nessun totale che uno parziale


def test_arco_coppia_e_uguale_nei_due_versi():
    f = tre_fermate()
    p = ProfiloTreno.da_status(treno(f))
    q = ProfiloTreno.da_status(treno([dict(x, progressivo=4 - x["progressivo"]) for x in f]))
    assert {a.coppia for a in p.archi} == {a.coppia for a in q.archi}
    assert isinstance(p.archi[0], Arco) and isinstance(p.itinerario, Itinerario)


# ------------------------------------------------------------------ live


class ClienteFinto:
    def __init__(self, status):
        self._s, self.chiamate = status, []

    async def andamento_treno(self, codice_stazione_origine, numero_treno, data_partenza):
        self.chiamate.append((codice_stazione_origine, numero_treno, data_partenza))
        return self._s


async def test_profilo_treno_live_fa_una_sola_richiesta():
    client = ClienteFinto(reale())
    p = await profilo_treno(client, "S01520", 24845, 1794438000000)
    assert client.chiamate == [("S01520", 24845, 1794438000000)]
    assert p is not None and p.numero == 24845 and len(p.archi) == 12


async def test_profilo_treno_live_senza_treno_da_none():
    assert await profilo_treno(ClienteFinto(None), "S01520", 1, 0) is None


# ------------------------------------------------------------------ arrivo previsto, avanzamento, anomalie
# (prima nel crawler: `eventi.arrivo_previsto`, `poller._stato_da_train_status`, `_ha_anomalie`)


def _prog(codice, prog, tipo, ms, att=0):
    return {
        "id": codice,
        "stazione": codice,
        "tipoFermata": tipo,
        "progressivo": prog,
        "programmata": T0 + ms * MIN,
        "actualFermataType": att,
    }


def _due():
    return [_prog("S1", 1, "P", 0), _prog("S2", 2, "A", 30)]


def test_arrivo_previsto_e_ultima_fermata_piu_ritardo():
    p = ProfiloTreno.da_status(treno(_due(), ritardo=7))
    assert p.arrivo_previsto == T0 + 37 * MIN


def test_arrivo_previsto_salta_le_fermate_soppresse():
    f = [_prog("S1", 1, "P", 0), _prog("S2", 2, "F", 20), _prog("S3", 3, "A", 40, att=3)]
    p = ProfiloTreno.da_status(treno(f, ritardo=0))
    assert p.arrivo_previsto == T0 + 20 * MIN  # S3 e' soppressa: la corsa finisce a S2
    assert p.fermata_destinazione_effettiva is not None
    assert p.fermata_destinazione_effettiva.codice == "S2"


def test_arrivo_previsto_ritardo_negativo_non_anticipa():
    p = ProfiloTreno.da_status(treno(_due(), ritardo=-3))
    assert p.arrivo_previsto == T0 + 30 * MIN


def test_arrivo_previsto_senza_fermate_e_senza_orario_e_ignoto():
    assert ProfiloTreno.da_status(treno([])).arrivo_previsto is None


def test_arrivo_previsto_ripiega_sull_arrivo_programmato_del_treno():
    p = ProfiloTreno.da_status(treno([], orarioArrivo=T0 + 50 * MIN, ritardo=4))
    assert p.arrivo_previsto == T0 + 54 * MIN
    assert ProfiloTreno.da_status(treno([], orarioArrivo="2026-11-12")).arrivo_previsto is None


def test_arrivo_previsto_senza_ritardo_e_l_orario_programmato():
    assert ProfiloTreno.da_status(treno(_due())).arrivo_previsto == T0 + 30 * MIN


def test_fermata_origine_e_destinazione_effettive_saltano_le_soppresse():
    f = [_prog("S1", 1, "P", 0, att=3), _prog("S2", 2, "F", 10), _prog("S3", 3, "A", 20, att=3)]
    p = ProfiloTreno.da_status(treno(f))
    assert p.fermata_origine_effettiva is not None and p.fermata_origine_effettiva.codice == "S2"
    assert p.fermata_destinazione_effettiva is not None
    assert p.fermata_destinazione_effettiva.codice == "S2"
    solo = ProfiloTreno.da_status(
        treno([_prog("S1", 1, "P", 0, att=3), _prog("S2", 2, "A", 5, att=3)])
    )
    assert solo.fermata_origine_effettiva is None and solo.fermata_destinazione_effettiva is None


def test_avanzamento_in_corso_arrivato_soppresso():
    assert ProfiloTreno.da_status(treno(_due())).avanzamento is Avanzamento.IN_CORSO
    assert ProfiloTreno.da_status(treno(_due(), arrivato=True)).avanzamento is Avanzamento.ARRIVATO
    assert ProfiloTreno.da_status(treno([], tipoTreno="ST")).avanzamento is Avanzamento.SOPPRESSO


def test_avanzamento_arrivato_vince_e_il_parziale_resta_in_corso():
    # regola del crawler: arrivato vince su tutto; PP/SI/SF e provvedimento 1 senza ST restano in corso
    assert (
        ProfiloTreno.da_status(treno(_due(), arrivato=True, tipoTreno="ST")).avanzamento
        is Avanzamento.ARRIVATO
    )
    assert ProfiloTreno.da_status(treno(_due(), tipoTreno="PP")).avanzamento is Avanzamento.IN_CORSO
    assert (
        ProfiloTreno.da_status(treno(_due(), provvedimento=1)).avanzamento is Avanzamento.IN_CORSO
    )


def test_treno_reale_avanzamento_e_anomalie():
    p = ProfiloTreno.da_status(reale())
    assert p.avanzamento is Avanzamento.ARRIVATO  # arrivato a Carnate, destinazione effettiva
    assert p.ha_anomalie is True  # parzialmente soppresso, con fermate soppresse e una nota
    carnate = reale().fermate[7].programmata  # Carnate, fermata di arrivo effettiva
    assert carnate is not None and p.arrivo_previsto == carnate + 5 * MIN  # +5' di ritardo


def test_treno_regolare_senza_anomalie():
    assert ha_anomalie(treno(_due(), tipoTreno="PG")) is False
    assert ProfiloTreno.da_status(treno(_due(), tipoTreno="PG")).ha_anomalie is False


@pytest.mark.parametrize(
    "extra",
    [
        {"tipoTreno": "PP"},
        {"tipoTreno": "DV"},
        {"provvedimento": 2},
        {"riprogrammazione": "Y"},
        {"subTitle": "Treno limitato a Monza"},
        {"fermateSoppresse": [{"id": "S2"}]},
        {"cambiNumero": [{"numero": 2}]},
        {"anormalita": [{"x": 1}]},
        {"provvedimenti": [{"x": 1}]},
    ],
)
def test_le_anomalie_sono_riconosciute(extra):
    assert ha_anomalie(treno(_due(), **extra)) is True


def test_fermate_non_previste_o_soppresse_sono_anomalie():
    for att in (2, 3):
        f = [_prog("S1", 1, "P", 0), _prog("S2", 2, "A", 5, att=att)]
        assert ha_anomalie(treno(f)) is True


def test_collegamento_effettivo_senza_id_usa_le_fermate_non_soppresse():
    # L'API non da' idOrigine/idDestinazione: la destinazione effettiva e' l'ultima fermata NON
    # soppressa, non l'ultima della lista (che e' la destinazione programmata).
    f = [_prog("S1", 1, "P", 0), _prog("S2", 2, "F", 20), _prog("S3", 3, "A", 40, att=3)]
    p = ProfiloTreno.da_status(treno(f, tipoTreno="PP"))
    assert p.collegamento_programmato is not None and p.collegamento_effettivo is not None
    assert p.collegamento_programmato.chiave == ("S1", "S3")
    assert p.collegamento_effettivo.chiave == ("S1", "S2")


def test_collegamento_effettivo_assente_se_tutte_le_fermate_sono_soppresse():
    f = [_prog("S1", 1, "P", 0, att=3), _prog("S2", 2, "A", 5, att=3)]
    p = ProfiloTreno.da_status(treno(f))
    assert p.collegamento_programmato is not None and p.collegamento_effettivo is None


def test_collegamento_effettivo_con_id_dell_api_ha_la_precedenza():
    p = ProfiloTreno.da_status(treno(_due(), idOrigine="S7", idDestinazione="S8"))
    assert p.collegamento_effettivo is not None and p.collegamento_effettivo.chiave == ("S7", "S8")
