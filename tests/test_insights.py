# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test di `viaggiatreno.insights` con tabelloni finti (nessuna chiamata di rete).

I valori attesi sono calcolati a mano nei commenti, non riprodotti con la stessa logica.
"""

import httpx
import pytest
from viaggiatreno import StationDetail, TrainBoardItem, TrainStatus
from viaggiatreno.insights import (
    Collegamento,
    Corsa,
    Itinerario,
    ParametriProfilo,
    ProfiloStazione,
    RuoloTreno,
    TipoCorsa,
    Verso,
    accoppia,
    calcola_frequenza,
    da_tabellone,
    finestra_comune,
    profilo_stazione,
    unisci_corse,
)

MIN = 60_000
T0 = 1_800_000_000_000  # un istante qualsiasi, in ms
GIORNO = 1_799_971_200_000
LECCO, PG, MONZA = "S01520", "S01645", "S01322"


def partenza(numero, orig, dest_nome, orario, *, dest_cod=None, bin_p=None, bin_e=None, **kw):
    return TrainBoardItem.model_validate(
        {
            "numeroTreno": numero,
            "codOrigine": orig,
            "destinazione": dest_nome,
            "codDestinazione": dest_cod,
            "dataPartenzaTreno": GIORNO,
            "orarioPartenza": orario,
            "binarioProgrammatoPartenzaDescrizione": bin_p,
            "binarioEffettivoPartenzaDescrizione": bin_e,
            "categoria": kw.pop("categoria", "REG"),
            **kw,
        }
    )


def arrivo(numero, orig, orig_nome, orario, *, bin_p=None, bin_e=None, **kw):
    return TrainBoardItem.model_validate(
        {
            "numeroTreno": numero,
            "codOrigine": orig,
            "origine": orig_nome,
            "dataPartenzaTreno": GIORNO,
            "orarioArrivo": orario,
            "binarioProgrammatoArrivoDescrizione": bin_p,
            "binarioEffettivoArrivoDescrizione": bin_e,
            "categoria": kw.pop("categoria", "REG"),
            **kw,
        }
    )


# ------------------------------------------------------------------------------ Corsa


def test_corsa_partenza_legge_i_campi_di_partenza():
    (c,) = da_tabellone(
        [partenza(10, LECCO, "MILANO P.G.", T0, bin_p="1", bin_e="2", ritardo=3)],
        LECCO,
        TipoCorsa.PARTENZA,
    )
    assert (c.stazione, c.tipo, c.numero, c.orario) == (LECCO, TipoCorsa.PARTENZA, 10, T0)
    assert (c.origine_codice, c.destinazione_nome, c.destinazione_codice) == (
        LECCO,
        "MILANO P.G.",
        None,
    )
    # il binario di riferimento e' il programmato; l'effettivo (2) e' una variazione del momento
    assert (c.binario_programmato, c.binario_effettivo, c.binari) == ("1", "2", ("1", "2"))
    assert c.binario_cambiato and c.ritardo == 3 and not c.soppressa


def test_corsa_arrivo_legge_i_campi_di_arrivo_e_non_ha_destinazione():
    (c,) = da_tabellone([arrivo(11, PG, "MILANO P.G.", T0, bin_p="3")], LECCO, TipoCorsa.ARRIVO)
    assert (c.origine_codice, c.origine_nome) == (PG, "MILANO P.G.")
    assert c.destinazione_codice is None and c.destinazione_nome is None
    assert (c.orario, c.binari, c.binario_cambiato) == (T0, ("3",), False)


def test_corsa_non_mescola_i_binari_di_arrivo_e_partenza():
    it = partenza(12, LECCO, "X", T0, bin_p="1")
    it_arr = it.model_copy(update={"binarioProgrammatoArrivoDescrizione": "9"})
    (p,) = da_tabellone([it_arr], LECCO, TipoCorsa.PARTENZA)
    (a,) = da_tabellone([it_arr], LECCO, TipoCorsa.ARRIVO)
    assert p.binari == ("1",) and a.binari == ("9",)


def test_corsa_stringhe_vuote_e_orario_non_numerico_diventano_none():
    it = partenza(13, LECCO, "  ", "2026-11-11", bin_p="", bin_e="  ")
    (c,) = da_tabellone([it], LECCO, TipoCorsa.PARTENZA)
    assert c.orario is None and c.binari == () and c.destinazione_nome is None
    assert c.binario_cambiato is False


def test_corsa_soppressa_dal_provvedimento():
    (c,) = da_tabellone([partenza(14, LECCO, "X", T0, provvedimento=1)], LECCO, TipoCorsa.PARTENZA)
    assert c.soppressa


def test_corsa_chiave_distingue_origine_e_giorno():
    a = da_tabellone([partenza(15, LECCO, "X", T0)], LECCO, TipoCorsa.PARTENZA)[0]
    b = da_tabellone([partenza(15, PG, "X", T0)], LECCO, TipoCorsa.PARTENZA)[0]
    assert a.chiave != b.chiave


# ------------------------------------------------------------------------------ Collegamento


def test_collegamento_uguaglianza_per_codice_non_per_nome():
    a = Collegamento(LECCO, PG, "LECCO", "MILANO PORTA GARIBALDI")
    b = Collegamento(LECCO, PG, "Lecco", "MI P.G.")
    assert a == b and hash(a) == hash(b)
    assert a != a.inverso()


def test_collegamento_senza_codice_usa_il_nome_normalizzato():
    a = Collegamento(None, None, " lecco ", "milano  p.g.")
    b = Collegamento(None, None, "LECCO", "MILANO P.G.")
    assert a == b


def test_collegamento_senza_codice_ne_nome_non_e_valido():
    with pytest.raises(ValueError):
        Collegamento(None, PG, None, "X")


def test_collegamento_coppia_e_indipendente_dal_verso():
    a = Collegamento(LECCO, PG, "LECCO", "PG")
    assert a.coppia == a.inverso().coppia == (LECCO, PG)
    assert a.inverso().inverso() == a
    assert a.etichetta == "LECCO -> PG"


def test_accoppia_riunisce_i_due_versi():
    a = Collegamento(LECCO, PG)
    b = a.inverso()
    c = Collegamento(LECCO, MONZA)
    out = accoppia([a, c, b])
    assert (a, b) in out and (c, None) in out and len(out) == 2


# ------------------------------------------------------------------------------ Itinerario


def test_itinerario_stessa_chiave_nei_due_versi():
    d, v1 = Itinerario.da_fermate(["S01520", "S01511", "S01645"])
    i, v2 = Itinerario.da_fermate(["S01645", "S01511", "S01520"])
    assert d == i and d.chiave == i.chiave == "S01520>S01511>S01645"
    assert (v1, v2) == (Verso.DIRETTO, Verso.INVERSO)


def test_itinerario_inverso_inverte_anche_i_nomi():
    itin, verso = Itinerario.da_fermate(["S9", "S5", "S1"], ["NOVE", "CINQUE", "UNO"])
    assert verso is Verso.INVERSO
    assert itin.codici == ("S1", "S5", "S9") and itin.nomi == ("UNO", "CINQUE", "NOVE")
    assert itin.nome == "UNO - NOVE"


def test_itinerario_non_e_il_capolinea_con_id_minore_per_significato_geografico():
    # la forma canonica e' solo una convenzione: primo codice <= ultimo
    itin, _ = Itinerario.da_fermate([PG, "S01511", LECCO])
    assert itin.estremo_a == LECCO and itin.estremo_b == PG
    assert itin.collegamento().etichetta == f"{LECCO} -> {PG}"
    assert itin.collegamento(Verso.INVERSO).origine_codice == PG


def test_itinerario_validazioni():
    with pytest.raises(ValueError):
        Itinerario.da_fermate(["S1"])
    with pytest.raises(ValueError):
        Itinerario.da_fermate(["S1", "S2"], ["solo uno"])
    with pytest.raises(ValueError):
        Itinerario(("S9", "S1"))  # non canonico
    with pytest.raises(ValueError):
        Itinerario.da_chiave("S9>S1")


def test_itinerario_da_chiave_e_contains():
    itin = Itinerario.da_chiave("S1>S2>S3")
    assert "S2" in itin and "S7" not in itin and itin.n_fermate == 3
    assert Itinerario.da_chiave(itin.chiave) == itin


def _status(fermate):
    return TrainStatus.model_validate({"numeroTreno": 1, "fermate": fermate})


def _f(id_, nome, prog, tipo="F", actual=1):
    return {
        "id": id_,
        "stazione": nome,
        "tipoFermata": tipo,
        "progressivo": prog,
        "actualFermataType": actual,
    }


def test_itinerario_da_status_segue_l_ordine_dell_api_e_include_le_soppresse():
    st = _status([_f("S1", "A", 1, "P"), _f("S2", "B", 2, actual=3), _f("S3", "C", 3, "A")])
    itin, verso = Itinerario.da_status(st) or (None, None)
    assert itin is not None and itin.codici == ("S1", "S2", "S3") and verso is Verso.DIRETTO


def test_itinerario_non_riordina_per_progressivo():
    # il progressivo non e' affidabile (vedi treno 17154): vale l'ordine in cui l'API elenca
    st = _status([_f("S3", "C", 3, "P"), _f("S1", "A", 1, "F"), _f("S2", "B", 2, "A")])
    itin, verso = Itinerario.da_status(st) or (None, None)
    assert itin is not None
    assert itin.codici == ("S2", "S1", "S3") and verso is Verso.INVERSO  # inversa di S3,S1,S2


def test_itinerario_soppresse_escluse_solo_su_richiesta():
    st = _status([_f("S1", "A", 1, "P"), _f("S2", "B", 2, actual=3), _f("S3", "C", 3, "A")])
    esclusa = Itinerario.da_status(st, includi_soppresse=False)
    assert esclusa is not None and esclusa[0].codici == ("S1", "S3")


def test_itinerario_da_status_senza_fermate_e_none():
    assert Itinerario.da_status(_status([])) is None
    assert Itinerario.da_status(_status([_f("S1", "A", 1)])) is None


# ------------------------------------------------------------------------------ frequenza


def test_frequenza_regolare_ogni_30_minuti():
    f = calcola_frequenza([T0 + i * 30 * MIN for i in range(5)])
    # 5 treni -> 4 intervalli da 30 min
    assert f.n_treni == 5 and f.intervallo_medio_min == 30 and f.intervallo_mediano_min == 30
    assert f.treni_ora == 2.0 and f.regolare is True
    assert (f.intervallo_min_min, f.intervallo_max_min) == (30, 30)


def test_frequenza_irregolare():
    # intervalli: 10, 50, 10, 50 -> medio 30, mediano 30, scarto 20 > tolleranza 6
    orari = [T0, T0 + 10 * MIN, T0 + 60 * MIN, T0 + 70 * MIN, T0 + 120 * MIN]
    f = calcola_frequenza(orari)
    assert f.intervallo_medio_min == 30 and f.regolare is False
    assert (f.intervallo_min_min, f.intervallo_max_min) == (10, 50)


def test_frequenza_ordina_e_ignora_gli_orari_assenti():
    f = calcola_frequenza([T0 + 60 * MIN, None, T0, T0 + 30 * MIN])
    assert f.n_treni == 3 and f.treni_ora == 2.0


def test_frequenza_con_due_treni_ha_un_solo_intervallo():
    f = calcola_frequenza([T0, T0 + 30 * MIN])
    # un solo intervallo: la cadenza c'e', la regolarita' non e' valutabile
    assert f.n_treni == 2 and f.intervallo_medio_min == 30 and f.treni_ora == 2.0
    assert f.intervallo_min_min == f.intervallo_max_min == 30 and f.regolare is None
    assert f.primo_ms == T0 and f.ultimo_ms == T0 + 30 * MIN


def test_frequenza_con_un_treno_non_ha_intervalli():
    f = calcola_frequenza([T0])
    assert f.n_treni == 1 and f.treni_ora is None and f.regolare is None and f.primo_ms == T0
    assert calcola_frequenza([]).n_treni == 0


def test_soglia_minima_treni_configurabile():
    tre = ParametriProfilo(min_treni_frequenza=3)
    assert calcola_frequenza([T0, T0 + 30 * MIN], tre).treni_ora is None
    assert calcola_frequenza([T0, T0 + 30 * MIN, T0 + 60 * MIN], tre).treni_ora == 2.0


def test_frequenza_stesso_orario_non_divide_per_zero():
    f = calcola_frequenza([T0, T0, T0])
    assert f.intervallo_medio_min == 0 and f.treni_ora is None


def test_parametri_validati():
    with pytest.raises(ValueError):
        ParametriProfilo(min_treni_frequenza=1)


# ------------------------------------------------------------------------------ profilo


def _capolinea():
    """Lecco: 5 treni nascono qui per Milano, 4 arrivano da Milano e finiscono qui."""
    parts = [
        partenza(
            100 + i,
            LECCO,
            "MILANO PORTA GARIBALDI",
            T0 + i * 30 * MIN,
            bin_p="1" if i % 2 == 0 else "2",
            bin_e="1" if i % 2 == 0 else "2",
        )
        for i in range(5)
    ]
    arrs = [
        arrivo(
            200 + i, PG, "MILANO PORTA GARIBALDI", T0 + 5 * MIN + i * 30 * MIN, bin_p="2", bin_e="2"
        )
        for i in range(4)
    ]
    return parts, arrs


def test_profilo_capolinea():
    parts, arrs = _capolinea()
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs, nome="LECCO")
    # partenze alle +0,30,60,90,120; l'ultimo arrivo e' a +95, entro 120-15=105: non incerto.
    # Gli arrivi non dichiarano la destinazione: i 4 che non ripartono sono terminali *dedotti*
    r = p.ruolo
    assert (r.n_origina, r.n_termina, r.n_termina_dedotti, r.n_passaggio) == (5, 0, 4, 0)
    assert r.n_incerti == 0
    assert r.capolinea and r.capolinea_certo and not r.transito
    assert r.e_origine and r.e_destinazione
    assert (p.n_treni, p.n_soppressi, p.n_corse) == (9, 0, 9)
    assert p.frequenza_partenze.treni_ora == 2.0 and p.frequenza_partenze.regolare
    assert p.frequenza_arrivi.intervallo_medio_min == 30
    assert p.finestra_ms == (T0, T0 + 120 * MIN) and p.finestra_min == 120


def test_profilo_collegamenti_completano_il_codice_dal_nome():
    parts, arrs = _capolinea()
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs, nome="LECCO")
    # le partenze danno solo il nome della destinazione, gli arrivi nome+codice di PG:
    # i due versi devono risultare dello stesso collegamento Lecco <-> PG
    etichette = {
        (c.collegamento.origine_codice, c.collegamento.destinazione_codice): c
        for c in p.collegamenti
    }
    assert set(etichette) == {(LECCO, PG), (PG, LECCO)}
    assert etichette[(LECCO, PG)].n_treni == 5 and etichette[(PG, LECCO)].n_treni == 4
    assert etichette[(LECCO, PG)].categorie == (("REG", 5),)
    assert etichette[(LECCO, PG)].collegamento.etichetta == "LECCO -> MILANO PORTA GARIBALDI"
    (coppia,) = accoppia([c.collegamento for c in p.collegamenti])
    assert coppia[1] is not None and coppia[0].coppia == (LECCO, PG)
    assert p.collegamenti[0].n_treni == 5  # ordinati per numero di treni


def test_profilo_binari_e_collegamenti_per_binario():
    parts, arrs = _capolinea()
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs)
    by = {b.binario: b for b in p.binari_programmati}
    assert p.n_binari == 2 and list(by) == ["1", "2"]
    # binario 1: partenze 100,102,104 (3). binario 2: partenze 101,103 + arrivi 200..203 (6)
    assert (by["1"].n_treni, by["1"].n_partenze, by["1"].n_arrivi) == (3, 3, 0)
    assert (by["2"].n_treni, by["2"].n_partenze, by["2"].n_arrivi) == (6, 2, 4)
    assert dict(by["1"].collegamenti) == {Collegamento(LECCO, PG): 3}
    assert dict(by["2"].collegamenti) == {Collegamento(LECCO, PG): 2, Collegamento(PG, LECCO): 4}
    assert set(p.collegamenti_per_binario_programmato()) == {"1", "2"}
    assert p.n_senza_binario == 0


def test_profilo_binari_cambiati_e_senza_binario():
    parts = [
        partenza(1, LECCO, "X", T0, dest_cod="S9", bin_p="1", bin_e="4"),
        partenza(2, LECCO, "X", T0 + 30 * MIN, dest_cod="S9"),  # nessun binario
        partenza(3, LECCO, "X", T0 + 60 * MIN, dest_cod="S9", bin_p="1"),
    ]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    by = {b.binario: b for b in p.binari_programmati}
    # il binario e' il programmato: il treno 1 resta sul binario 1 anche se dirottato sul 4
    assert set(by) == {"1"} and by["1"].n_treni == 2 and by["1"].n_cambiati == 1
    assert p.n_senza_binario == 1


def test_due_liste_binari_programmati_e_reali():
    # 3 treni previsti sul binario 1 ma arrivati sul 5
    parts = [
        partenza(i, LECCO, "X", T0 + i * MIN, dest_cod="S9", bin_p="1", bin_e="5") for i in range(3)
    ]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    assert [b.binario for b in p.binari_programmati] == ["1"]
    assert [b.binario for b in p.binari_reali] == ["5"]
    assert p.binari_programmati[0].n_cambiati == 3 and p.binari_reali[0].n_cambiati == 3
    # il numero di binari della stazione e' l'unione dei due
    assert p.elenco_binari == ("1", "5") and p.n_binari == 2


def test_solo_effettivo_compare_solo_tra_i_reali_ma_conta_nei_binari():
    parts = [
        partenza(1, LECCO, "X", T0, dest_cod="S9", bin_e="3"),  # solo effettivo
        partenza(2, LECCO, "X", T0 + MIN, dest_cod="S9", bin_p="1"),  # solo programmato
    ]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    assert [b.binario for b in p.binari_programmati] == ["1"]
    assert [b.binario for b in p.binari_reali] == ["3"]
    assert p.elenco_binari == ("1", "3") and p.n_senza_binario == 0
    # senza programmato non si puo' dire che sia cambiato
    (c,) = da_tabellone([parts[0]], LECCO, TipoCorsa.PARTENZA)
    assert c.binari == ("3",) and c.binario_cambiato is False


def test_stesso_binario_programmato_ed_effettivo_conta_una_volta():
    parts = [partenza(1, LECCO, "X", T0, dest_cod="S9", bin_p="2", bin_e="2")]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    assert p.elenco_binari == ("2",) and p.n_binari == 1
    assert p.binari_programmati[0].n_treni == 1 and p.binari_reali[0].n_treni == 1
    assert p.binari_programmati[0].n_cambiati == 0


def test_collegamenti_per_binario_programmato_e_reale_differiscono():
    # Milano->Lecco previsti sul binario 1: 2 ci vanno, 1 va sul 2. Lecco->Milano sul 2.
    parts = [
        partenza(1, PG, "LECCO", T0, bin_p="1", bin_e="1"),
        partenza(2, PG, "LECCO", T0 + 30 * MIN, bin_p="1", bin_e="1"),
        partenza(3, PG, "LECCO", T0 + 60 * MIN, bin_p="1", bin_e="2"),
        partenza(4, LECCO, "MILANO", T0 + 10 * MIN, bin_p="2", bin_e="2"),
    ]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    prog = p.collegamenti_per_binario_programmato()
    reale = p.collegamenti_per_binario_reale()
    ml = Collegamento(PG, "LECCO")
    assert set(prog) == {"1", "2"} and dict(prog["1"]) == {ml: 3}
    assert dict(reale["1"]) == {ml: 2}
    assert dict(reale["2"]) == {ml: 1, Collegamento(LECCO, None, None, "MILANO"): 1}


def test_binari_del_collegamento_programmati_e_reali():
    parts = [
        partenza(1, PG, "LECCO", T0, bin_p="1", bin_e="4"),
        partenza(2, PG, "LECCO", T0 + MIN, bin_p="1", bin_e="1"),
    ]
    (c,) = ProfiloStazione.da_tabelloni(LECCO, parts, []).collegamenti
    assert c.binari_programmati == ("1",) and c.binari_reali == ("1", "4")


def test_i_cancellati_non_hanno_binari_reali():
    parts = [
        partenza(1, PG, "LECCO", T0, bin_p="1", bin_e="1"),
        partenza(2, PG, "LECCO", T0 + 30 * MIN, provvedimento=1),
        partenza(3, PG, "LECCO", T0 + 60 * MIN, bin_p="1", bin_e="1"),
    ]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    assert p.binari_programmati[0].n_soppressi == 1
    assert p.binari_reali[0].n_soppressi == 0
    # la teorica del binario reale coincide con l'effettiva: il cancellato non e' su un binario reale
    assert p.binari_reali[0].frequenza_teorica_partenze == p.binari_reali[0].frequenza_partenze


def test_profilo_binari_in_ordine_naturale():
    parts = [
        partenza(i, LECCO, "X", T0 + i * MIN, dest_cod="S9", bin_p=b)
        for i, b in enumerate(["10", "2", "1", "Tronco", "1 EST"])
    ]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    assert [b.binario for b in p.binari_programmati] == ["1", "1 EST", "2", "10", "Tronco"]


def test_profilo_stazione_di_passaggio():
    # stesso treno in arrivo e in partenza (origine altrove), 4 treni
    arrs = [arrivo(300 + i, PG, "PG", T0 + i * 30 * MIN) for i in range(4)]
    parts = [
        partenza(300 + i, PG, "COLICO", T0 + 2 * MIN + i * 30 * MIN, dest_cod="S01420")
        for i in range(4)
    ]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs)
    r = p.ruolo
    assert (r.n_origina, r.n_termina, r.n_termina_dedotti, r.n_passaggio) == (0, 0, 0, 4)
    assert r.transito and not r.capolinea
    assert p.n_treni == 4  # arrivo e partenza dello stesso treno contano una volta
    assert [c.collegamento.etichetta for c in p.collegamenti] == ["PG -> COLICO"]


def test_profilo_stazione_mista():
    parts = [
        partenza(400 + i, LECCO, "X", T0 + i * MIN, dest_cod="S9") for i in range(3)
    ]  # nascono
    parts += [partenza(410 + i, PG, "X", T0 + i * MIN, dest_cod="S9") for i in range(3)]  # passano
    arrs = [arrivo(410 + i, PG, "PG", T0 - 5 * MIN) for i in range(3)]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs)
    assert (p.ruolo.n_origina, p.ruolo.n_passaggio) == (3, 3)
    assert p.ruolo.capolinea and p.ruolo.transito  # entrambe: una stazione puo' essere le due cose


def test_arrivi_vicini_alla_fine_della_finestra_sono_incerti_non_terminali():
    parts = [partenza(500 + i, LECCO, "X", T0 + i * 30 * MIN, dest_cod="S9") for i in range(4)]
    # ultima partenza a +90. Un arrivo a +85 e' entro 15 min dalla fine: potrebbe ripartire dopo
    arrs = [arrivo(600, PG, "PG", T0 + 10 * MIN), arrivo(601, PG, "PG", T0 + 85 * MIN)]
    r = ProfiloStazione.da_tabelloni(LECCO, parts, arrs).ruolo
    assert r.n_termina_dedotti == 1 and r.n_incerti == 1
    assert r.n_certi == 5  # 4 che nascono + 1 che termina; l'incerto non entra


def test_arrivo_senza_partenze_e_incerto():
    # senza il tabellone delle partenze non si sa nulla di cosa succede dopo
    p = ProfiloStazione.da_tabelloni(
        LECCO, [], [arrivo(700 + i, PG, "PG", T0 + i * MIN) for i in range(5)]
    )
    assert p.ruolo.n_incerti == 5 and not p.ruolo.capolinea and not p.ruolo.transito


def test_un_solo_treno_che_nasce_basta_per_essere_capolinea():
    # nessuna soglia: 1 treno che nasce e 10 di passaggio -> capolinea E transito
    parts = [partenza(1200, LECCO, "X", T0, dest_cod="S9")]
    parts += [partenza(1210 + i, PG, "X", T0 + i * MIN, dest_cod="S9") for i in range(10)]
    arrs = [arrivo(1210 + i, PG, "PG", T0 - MIN) for i in range(10)]
    r = ProfiloStazione.da_tabelloni(LECCO, parts, arrs).ruolo
    assert (r.n_origina, r.n_passaggio) == (1, 10)
    assert r.capolinea and r.transito and r.e_origine and not r.e_destinazione


def test_destinazione_dichiarata_nell_arrivo_vale_piu_della_deduzione():
    # se l'API riporta la destinazione anche negli arrivi, non si deduce nulla
    qui = arrivo(1300, PG, "PG", T0, destinazione="LECCO", codDestinazione=LECCO)
    altrove = arrivo(1301, PG, "PG", T0 + MIN, destinazione="COLICO", codDestinazione="S01420")
    parts = [partenza(1302, LECCO, "X", T0 + 90 * MIN, dest_cod="S9")]
    r = ProfiloStazione.da_tabelloni(LECCO, parts, [qui, altrove]).ruolo
    assert (r.n_termina, r.n_termina_dedotti, r.n_passaggio, r.n_origina) == (1, 0, 1, 1)
    assert r.e_destinazione and r.capolinea_certo


def test_destinazione_confrontata_per_nome_se_manca_il_codice():
    # nelle partenze di solito c'e' solo il nome della destinazione
    qui = arrivo(1400, PG, "PG", T0, destinazione=" lecco ")
    altrove = arrivo(1401, PG, "PG", T0, destinazione="COLICO")
    r = ProfiloStazione.da_tabelloni(LECCO, [], [qui, altrove], nome="LECCO").ruolo
    assert (r.n_termina, r.n_passaggio) == (1, 1)


def test_terminali_dedotti_non_sono_capolinea_certo():
    parts = [partenza(1500 + i, PG, "X", T0 + i * 30 * MIN, dest_cod="S9") for i in range(4)]
    arrs = [arrivo(1600, PG, "PG", T0 + 5 * MIN)]  # non riparte: dedotto
    r = ProfiloStazione.da_tabelloni(LECCO, parts, arrs).ruolo
    assert r.n_termina_dedotti == 1 and r.capolinea and not r.capolinea_certo


def test_deduzione_disattivabile():
    parts = [partenza(1700 + i, PG, "X", T0 + i * 30 * MIN, dest_cod="S9") for i in range(4)]
    arrs = [arrivo(1800, PG, "PG", T0 + 5 * MIN)]
    r = ProfiloStazione.da_tabelloni(
        LECCO, parts, arrs, parametri=ParametriProfilo(deduci_termine=False)
    ).ruolo
    assert r.n_termina_dedotti == 0 and r.n_incerti == 1 and not r.capolinea


def test_treno_parzialmente_soppresso_non_rende_capolinea():
    # nasce qui *a causa* della soppressione di un tratto: non e' un capolinea vero
    parts = [partenza(1900, LECCO, "X", T0, dest_cod="S9", provvedimento=2)]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    assert p.ruolo.n_incerti == 1 and not p.ruolo.capolinea and p.n_treni == 1
    # ...e lo stesso vale per un terminale dedotto
    parts2 = [partenza(1901 + i, PG, "X", T0 + i * 30 * MIN, dest_cod="S9") for i in range(4)]
    arr = arrivo(1950, PG, "PG", T0 + 5 * MIN, provvedimento=2)
    r = ProfiloStazione.da_tabelloni(LECCO, parts2, [arr]).ruolo
    assert r.n_termina_dedotti == 0 and r.n_incerti == 1 and not r.capolinea


def test_treno_cancellato_non_rende_capolinea():
    parts = [partenza(2000, LECCO, "X", T0, dest_cod="S9", provvedimento=1)]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    assert p.n_soppressi == 1 and not p.ruolo.capolinea and p.ruolo.n_certi == 0


def test_ruolo_treno_enum_ha_i_valori_attesi():
    assert {r.value for r in RuoloTreno} == {
        "origina",
        "termina",
        "termina_dedotto",
        "passaggio",
        "incerto",
    }


def test_corsa_arrivo_legge_la_destinazione_se_l_api_la_da():
    (c,) = da_tabellone(
        [arrivo(1, PG, "PG", T0, destinazione="LECCO", codDestinazione=LECCO)],
        LECCO,
        TipoCorsa.ARRIVO,
    )
    assert (c.destinazione_nome, c.destinazione_codice) == ("LECCO", LECCO)


def test_corsa_parziale_dal_provvedimento_2():
    (c,) = da_tabellone([partenza(1, LECCO, "X", T0, provvedimento=2)], LECCO, TipoCorsa.PARTENZA)
    assert c.parziale and not c.soppressa


def test_treni_soppressi_esclusi_dai_conteggi_ma_contati():
    parts = [
        partenza(900, LECCO, "X", T0, dest_cod="S9", bin_p="1"),
        partenza(901, LECCO, "X", T0 + 30 * MIN, dest_cod="S9", bin_p="7", provvedimento=1),
    ]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    assert (p.n_treni, p.n_soppressi) == (1, 1) and [b.binario for b in p.binari_programmati] == [
        "1"
    ]


def test_treno_senza_destinazione_non_ha_collegamento():
    parts = [
        partenza(1000, LECCO, None, T0),
        partenza(1001, LECCO, "X", T0 + MIN, dest_cod="S9"),
    ]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    assert p.n_senza_collegamento == 1 and len(p.collegamenti) == 1 and p.n_treni == 2


def test_nome_ambiguo_non_completa_il_codice():
    # "MILANO" corrisponde a due codici diversi: non si deve scegliere a caso
    arrs = [arrivo(1100, "S01700", "MILANO", T0), arrivo(1101, "S01645", "MILANO", T0 + MIN)]
    parts = [partenza(1102, LECCO, "MILANO", T0 + 2 * MIN)]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs)
    dest = [c.collegamento for c in p.collegamenti if c.collegamento.origine_codice == LECCO]
    assert dest and dest[0].destinazione_codice is None and dest[0].destinazione_nome == "MILANO"


def test_profilo_vuoto():
    p = ProfiloStazione.da_corse(LECCO, [])
    assert (p.n_treni, p.n_binari, p.finestra_ms, p.finestra_min) == (0, 0, None, None)
    assert not p.ruolo.capolinea and not p.ruolo.transito and p.collegamenti == ()
    assert p.frequenza.treni_ora is None


def test_corse_di_un_altra_stazione_sono_rifiutate():
    c = da_tabellone([partenza(1, LECCO, "X", T0)], PG, TipoCorsa.PARTENZA)
    with pytest.raises(ValueError, match="altre stazioni"):
        ProfiloStazione.da_corse(LECCO, c)


def test_unisci_corse_toglie_i_duplicati_e_tiene_l_ultima():
    vecchia = da_tabellone([partenza(1, LECCO, "X", T0, bin_p="1")], LECCO, TipoCorsa.PARTENZA)
    nuova = da_tabellone(
        [partenza(1, LECCO, "X", T0, bin_p="1", bin_e="3")], LECCO, TipoCorsa.PARTENZA
    )
    altra = da_tabellone([partenza(2, LECCO, "X", T0 + MIN, bin_p="5")], LECCO, TipoCorsa.PARTENZA)
    unite = unisci_corse(vecchia, nuova, altra)
    assert len(unite) == 2 and {c.binario_effettivo for c in unite} == {"3", None}  # vale la nuova
    assert {c.binari for c in unite} == {("1", "3"), ("5",)}
    p = ProfiloStazione.da_corse(LECCO, unite)
    assert (
        p.elenco_binari == ("1", "3", "5") and p.n_binari == 3
    )  # unione di programmati ed effettivi


def test_binari_osservati_crescono_unendo_le_finestre():
    mattina = da_tabellone([partenza(1, LECCO, "X", T0, bin_p="1")], LECCO, TipoCorsa.PARTENZA)
    sera = da_tabellone(
        [partenza(2, LECCO, "X", T0 + 600 * MIN, bin_p="4")], LECCO, TipoCorsa.PARTENZA
    )
    assert ProfiloStazione.da_corse(LECCO, mattina).n_binari == 1
    assert ProfiloStazione.da_corse(LECCO, unisci_corse(mattina, sera)).n_binari == 2


def test_corsa_e_immutabile():
    (c,) = da_tabellone([partenza(1, LECCO, "X", T0)], LECCO, TipoCorsa.PARTENZA)
    with pytest.raises(AttributeError):
        c.numero = 2  # type: ignore[misc]
    assert isinstance(c, Corsa)


# ------------------------------------------------------------------------------ live


class ClienteFinto:
    """Client finto: registra le chiamate; `dettaglio`/`errore_dettaglio` controllano la risposta."""

    def __init__(
        self, partenze, arrivi, dettaglio=None, regione: int | None = 1, errore_dettaglio=None
    ):
        self._p, self._a, self._d = partenze, arrivi, dettaglio
        self._regione, self._errore = regione, errore_dettaglio
        self.chiamate = []

    async def partenze(self, codice_stazione, data_ora=None):
        self.chiamate.append(("partenze", codice_stazione))
        return self._p

    async def arrivi(self, codice_stazione, data_ora=None):
        self.chiamate.append(("arrivi", codice_stazione))
        return self._a

    async def regione(self, codice_stazione):
        self.chiamate.append(("regione", codice_stazione))
        if self._errore:
            raise self._errore
        return self._regione

    async def dettaglio_stazione(self, codice_stazione, codice_regione):
        self.chiamate.append(("dettaglio", codice_stazione, codice_regione))
        return self._d


def dettaglio_lecco(**kw):
    dati = {
        "codiceStazione": LECCO,
        "codReg": 1,
        "lat": 45.856,
        "lon": 9.393,
        "nomeCitta": "Lecco",
        "tipoStazione": 3,
        "localita": {"id": LECCO, "nomeLungo": "LECCO", "nomeBreve": "Lecco"},
    }
    return StationDetail.model_validate({**dati, **kw})


async def test_profilo_stazione_live_chiede_tutto_all_api():
    parts, arrs = _capolinea()
    client = ClienteFinto(parts, arrs, dettaglio_lecco())
    p = await profilo_stazione(client, LECCO)
    assert client.chiamate == [
        ("partenze", LECCO),
        ("arrivi", LECCO),
        ("regione", LECCO),
        ("dettaglio", LECCO, 1),
    ]
    assert p.ruolo.capolinea
    assert (p.nome, p.nome_fonte, p.citta) == ("LECCO", "dettaglio", "Lecco")
    assert (p.regione_codice, p.regione_nome, p.tipo_stazione) == (1, "Lombardia", 3)
    assert (p.lat, p.lon) == (45.856, 9.393)


async def test_profilo_stazione_con_tutto_passato_non_chiama_l_api():
    parts, arrs = _capolinea()
    client = ClienteFinto([], [])
    p = await profilo_stazione(
        client, LECCO, partenze=parts, arrivi=arrs, dettaglio=dettaglio_lecco()
    )
    assert client.chiamate == []
    assert p.n_treni == 9 and p.nome == "LECCO" and p.nome_fonte == "dettaglio"


async def test_profilo_stazione_chiede_solo_cio_che_manca():
    parts, arrs = _capolinea()
    client = ClienteFinto([], [], dettaglio_lecco())
    await profilo_stazione(client, LECCO, partenze=parts, arrivi=arrs)
    assert client.chiamate == [("regione", LECCO), ("dettaglio", LECCO, 1)]
    client2 = ClienteFinto(parts, arrs, dettaglio_lecco())
    await profilo_stazione(client2, LECCO, dettaglio=dettaglio_lecco())
    assert client2.chiamate == [("partenze", LECCO), ("arrivi", LECCO)]


async def test_profilo_stazione_senza_dettaglio_non_lo_chiede():
    parts, arrs = _capolinea()
    client = ClienteFinto(parts, arrs)
    p = await profilo_stazione(client, LECCO, con_dettaglio=False)
    assert client.chiamate == [("partenze", LECCO), ("arrivi", LECCO)]
    # il nome della stazione NON e' nelle righe dei suoi tabelloni (verificato su Milano
    # Centrale, Monza, Olgiate): senza dettaglio ne' parametro il nome e' ignoto
    assert (p.nome, p.nome_fonte, p.citta, p.regione_codice) == (None, None, None, None)


async def test_errore_sul_dettaglio_non_fa_fallire_il_profilo(caplog):
    parts, arrs = _capolinea()
    err = httpx.HTTPStatusError("403", request=None, response=None)  # type: ignore[arg-type]
    client = ClienteFinto(parts, arrs, dettaglio_lecco(), errore_dettaglio=err)
    with caplog.at_level("WARNING"):
        p = await profilo_stazione(client, LECCO)
    assert p.n_treni == 9 and p.ruolo.capolinea  # il profilo c'e' comunque
    assert p.regione_codice is None and "non disponibile" in caplog.text


async def test_regione_ignota_salta_il_dettaglio():
    parts, arrs = _capolinea()
    client = ClienteFinto(parts, arrs, dettaglio_lecco(), regione=None)
    p = await profilo_stazione(client, LECCO)
    assert ("dettaglio", LECCO, 1) not in client.chiamate and p.regione_codice is None


async def test_dettaglio_assente_204_lascia_i_campi_vuoti():
    parts, arrs = _capolinea()
    client = ClienteFinto(parts, arrs, dettaglio=None)
    p = await profilo_stazione(client, LECCO)
    assert p.nome is None and p.nome_fonte is None and p.citta is None and p.lat is None


def test_nome_passato_ha_la_precedenza_sul_dettaglio():
    parts, arrs = _capolinea()
    p = ProfiloStazione.da_tabelloni(
        LECCO, parts, arrs, nome="NOME MIO", dettaglio=dettaglio_lecco()
    )
    assert (p.nome, p.nome_fonte) == ("NOME MIO", "parametro")


def test_nome_della_stazione_risolve_il_confronto_per_nome_della_destinazione():
    # Olgiate e' una stazione di transito: non e' origine ne' destinazione, il nome dalle righe
    # manca. Con il dettaglio il confronto per nome funziona: "LECCO" e' la destinazione di
    # questo treno solo se la stazione si chiama LECCO.
    arr = arrivo(1, PG, "PG", T0, destinazione="LECCO")
    senza = ProfiloStazione.da_tabelloni(LECCO, [], [arr])
    assert senza.nome is None and senza.ruolo.n_termina == 0
    con = ProfiloStazione.da_tabelloni(LECCO, [], [arr], dettaglio=dettaglio_lecco())
    assert con.ruolo.n_termina == 1


def test_segnaposto_della_citta_non_e_una_citta():
    # l'API usa "A" quando non c'e' una citta (es. Olgiate, Milano Porta Garibaldi)
    d = dettaglio_lecco(nomeCitta="A")
    p = ProfiloStazione.da_tabelloni(LECCO, [], [], dettaglio=d)
    assert p.citta is None and p.nome == "LECCO"


def test_dettaglio_senza_localita_non_da_il_nome():
    d = dettaglio_lecco(localita=None)
    p = ProfiloStazione.da_tabelloni(LECCO, [], [], dettaglio=d)
    assert p.nome is None and p.nome_fonte is None and p.regione_codice == 1


# ------------------------------------------------------------------------------ elenco e frequenze per binario


def test_elenco_collegamenti_senza_duplicati():
    # 5 treni Lecco->X e 4 treni X->Lecco: due voci, non nove
    parts, arrs = _capolinea()
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs, nome="LECCO")
    e = p.elenco_collegamenti
    assert len(e) == 2 and len(set(e)) == 2
    assert e[0] == Collegamento(LECCO, PG)  # il piu' frequente (5 treni) per primo
    assert e[1] == Collegamento(PG, LECCO)
    assert (e[0].origine_nome, e[0].destinazione_nome) == ("LECCO", "MILANO PORTA GARIBALDI")


def test_elenco_collegamenti_vuoto_senza_treni():
    assert ProfiloStazione.da_corse(LECCO, []).elenco_collegamenti == ()


def test_elenco_collegamenti_del_binario():
    parts, arrs = _capolinea()
    by = {b.binario: b for b in ProfiloStazione.da_tabelloni(LECCO, parts, arrs).binari_programmati}
    assert by["1"].elenco_collegamenti == (Collegamento(LECCO, PG),)
    assert set(by["2"].elenco_collegamenti) == {Collegamento(LECCO, PG), Collegamento(PG, LECCO)}


def test_frequenza_per_binario_partenze_e_arrivi():
    parts, arrs = _capolinea()
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs)
    by = {b.binario: b for b in p.binari_programmati}
    # Finestra comune: partenze +0..+120, arrivi +5..+95 -> +5..+95. Le partenze a +0 e +120
    # (binario 1) restano fuori. Binario 1: partenza a +60 soltanto; nessun arrivo.
    f1 = by["1"].frequenza_partenze
    assert (f1.n_treni, f1.treni_ora) == (1, None)
    assert by["1"].frequenza_arrivi.n_treni == 0 and by["1"].frequenza_arrivi.treni_ora is None
    # binario 2: 2 partenze (+30, +90) dentro la finestra -> un solo intervallo di 60 min
    f2p = by["2"].frequenza_partenze
    assert (f2p.n_treni, f2p.intervallo_medio_min, f2p.treni_ora) == (2, 60, 1.0)
    assert f2p.regolare is None and f2p.primo_ms == T0 + 30 * MIN
    # binario 2: 4 arrivi a +5, +35, +65, +95 -> intervallo 30 min
    f2a = by["2"].frequenza_arrivi
    assert (f2a.n_treni, f2a.intervallo_medio_min, f2a.treni_ora) == (4, 30, 2.0)


def test_frequenza_binario_esclude_i_soppressi():
    parts = [
        partenza(1, LECCO, "X", T0, dest_cod="S9", bin_p="1"),
        partenza(2, LECCO, "X", T0 + 30 * MIN, dest_cod="S9", bin_p="1", provvedimento=1),
        partenza(3, LECCO, "X", T0 + 60 * MIN, dest_cod="S9", bin_p="1"),
        partenza(4, LECCO, "X", T0 + 90 * MIN, dest_cod="S9", bin_p="1"),
    ]
    (b,) = ProfiloStazione.da_tabelloni(LECCO, parts, []).binari_programmati
    # senza il soppresso: +0, +60, +90 -> intervalli 60 e 30
    f = b.frequenza_partenze
    assert f.n_treni == 3 and f.intervallo_min_min == 30 and f.intervallo_max_min == 60
    assert f.regolare is False


def test_frequenza_stazione_e_binario_sono_coerenti_su_un_solo_binario():
    parts = [partenza(i, LECCO, "X", T0 + i * 20 * MIN, dest_cod="S9", bin_p="3") for i in range(4)]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    assert p.frequenza_partenze == p.binari_programmati[0].frequenza_partenze


# ------------------------------------------------------------------------------ frequenza teorica


def _ogni_30(binario, n=4, soppresso=(), base=0, numero=0, origine=PG, dest="LECCO"):
    """n partenze ogni 30 minuti sullo stesso binario; `soppresso` = indici cancellati."""
    out = []
    for i in range(n):
        kw = {"provvedimento": 1} if i in soppresso else {}
        out.append(
            partenza(numero + i, origine, dest, T0 + (base + i * 30) * MIN, bin_p=binario, **kw)
        )
    return out


def test_teorica_senza_soppressioni_coincide_con_l_effettiva():
    p = ProfiloStazione.da_tabelloni(LECCO, _ogni_30("1"), [])
    assert p.n_soppressi == 0 and p.quota_soppressi == 0
    assert p.frequenza_teorica_partenze == p.frequenza_partenze
    assert p.frequenza_teorica == p.frequenza
    assert (
        p.binari_programmati[0].frequenza_teorica_partenze
        == p.binari_programmati[0].frequenza_partenze
    )
    assert p.collegamenti[0].frequenza_teorica == p.collegamenti[0].frequenza


def test_teorica_include_il_treno_cancellato_e_ripristina_la_cadenza():
    # 4 treni ogni 30 min; il secondo e' cancellato (nel tabellone senza binario, come nei dati)
    parts = _ogni_30("1", soppresso=(1,))
    parts[1] = partenza(1, PG, "LECCO", T0 + 30 * MIN, provvedimento=1)  # nessun binario
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    eff, teo = p.frequenza_partenze, p.frequenza_teorica_partenze
    # effettiva: +0, +60, +90 -> intervalli 60, 30
    assert (eff.n_treni, eff.intervallo_min_min, eff.intervallo_max_min) == (3, 30, 60)
    assert eff.regolare is False
    # teorica: +0, +30, +60, +90 -> 30, 30, 30
    assert (teo.n_treni, teo.intervallo_medio_min, teo.treni_ora, teo.regolare) == (
        4,
        30,
        2.0,
        True,
    )
    assert (p.n_treni, p.n_soppressi) == (3, 1) and p.quota_soppressi == 0.25


def test_teorica_per_binario_assegna_il_cancellato_se_il_collegamento_ha_un_solo_binario():
    parts = _ogni_30("1")
    parts[1] = partenza(1, PG, "LECCO", T0 + 30 * MIN, provvedimento=1)  # senza binario
    (b,) = ProfiloStazione.da_tabelloni(LECCO, parts, []).binari_programmati
    assert b.n_soppressi == 1
    assert b.frequenza_partenze.n_treni == 3 and b.frequenza_teorica_partenze.n_treni == 4
    assert b.frequenza_teorica_partenze.regolare is True


def test_teorica_per_binario_usa_il_binario_proprio_del_cancellato():
    # il cancellato ha un binario programmato: va su quello, anche se il collegamento ne usa due
    parts = [
        partenza(1, PG, "LECCO", T0, bin_p="1"),
        partenza(2, PG, "LECCO", T0 + 30 * MIN, bin_p="2"),
        partenza(3, PG, "LECCO", T0 + 60 * MIN, bin_p="1"),
        partenza(4, PG, "LECCO", T0 + 45 * MIN, bin_p="2", provvedimento=1),
    ]
    by = {b.binario: b for b in ProfiloStazione.da_tabelloni(LECCO, parts, []).binari_programmati}
    assert by["2"].n_soppressi == 1 and by["1"].n_soppressi == 0
    assert by["2"].frequenza_teorica_partenze.n_treni == 2


def test_cancellato_senza_binario_su_collegamento_con_due_binari_non_e_assegnato():
    parts = [
        partenza(1, PG, "LECCO", T0, bin_p="1"),
        partenza(2, PG, "LECCO", T0 + 30 * MIN, bin_p="2"),
        partenza(3, PG, "LECCO", T0 + 45 * MIN, provvedimento=1),  # quale binario? ignoto
    ]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    assert p.n_soppressi == 1 and p.n_soppressi_non_assegnati == 1
    assert all(b.n_soppressi == 0 for b in p.binari_programmati)
    # ...ma conta nella frequenza teorica di stazione e di collegamento
    assert p.frequenza_teorica_partenze.n_treni == 3
    assert p.collegamenti[0].frequenza_teorica.n_treni == 3 and p.collegamenti[0].n_soppressi == 1


def test_cancellato_senza_collegamento_noto_non_e_assegnato():
    parts = [
        partenza(1, PG, "LECCO", T0, bin_p="1"),
        partenza(2, PG, None, T0 + MIN, provvedimento=1),
    ]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    assert p.n_soppressi_non_assegnati == 1 and p.binari_programmati[0].n_soppressi == 0


def test_teorica_conta_una_volta_il_treno_cancellato_in_partenza_e_arrivo():
    parts = [partenza(1, PG, "LECCO", T0 + 5 * MIN, provvedimento=1)]
    arrs = [arrivo(1, PG, "MILANO", T0, provvedimento=1)]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs)
    assert p.n_soppressi == 1
    assert p.frequenza_teorica.n_treni == 1  # un treno, non due
    assert p.frequenza_teorica_partenze.n_treni == 1 and p.frequenza_teorica_arrivi.n_treni == 1


def test_quota_soppressi_none_senza_treni():
    assert ProfiloStazione.da_corse(LECCO, []).quota_soppressi is None


def test_teorica_per_collegamento_non_mescola_i_versi():
    parts = _ogni_30("1", origine=PG, dest="LECCO")
    parts[1] = partenza(1, PG, "LECCO", T0 + 30 * MIN, provvedimento=1)
    parts += _ogni_30("2", numero=50, origine=LECCO, dest="MILANO P.G.", base=7)
    by = {
        c.collegamento.origine_codice: c
        for c in ProfiloStazione.da_tabelloni(LECCO, parts, []).collegamenti
    }
    assert by[PG].n_soppressi == 1 and by[PG].frequenza_teorica.n_treni == 4
    assert by[LECCO].n_soppressi == 0 and by[LECCO].frequenza_teorica == by[LECCO].frequenza


# ------------------------------------------------------------------------------ frequentazione del binario


def test_frequenza_binario_conta_ogni_treno_una_volta_anche_se_arriva_e_riparte():
    # 4 treni che arrivano e ripartono sul binario 1, ogni 30 min: 4 treni, non 8
    parts = [
        partenza(i, PG, "X", T0 + (i * 30 + 2) * MIN, dest_cod="S9", bin_p="1") for i in range(4)
    ]
    arrs = [arrivo(i, PG, "PG", T0 + i * 30 * MIN, bin_p="1") for i in range(4)]
    (b,) = ProfiloStazione.da_tabelloni(LECCO, parts, arrs).binari_programmati
    assert b.n_treni == 4
    # finestra comune: arrivi +0..+90, partenze +2..+92 -> +2..+90; il treno 0 (arrivo +0,
    # partenza +2) conta con la partenza (+2), il treno 3 con la partenza (+92, fuori): 3 treni
    assert b.frequenza.n_treni == 3 and b.frequenza.treni_ora == 2.0
    assert b.frequenza.intervallo_medio_min == 30
    assert b.frequenza_partenze.n_treni == 3 and b.frequenza_arrivi.n_treni == 3


def test_frequenza_binario_usa_l_arrivo_se_il_treno_non_riparte_da_li():
    # solo arrivi sul binario 2 (nessuna partenza): ogni treno conta con il suo arrivo
    arrs = [arrivo(i, PG, "PG", T0 + i * 20 * MIN, bin_p="2") for i in range(4)]
    (b,) = ProfiloStazione.da_tabelloni(LECCO, [], arrs).binari_programmati
    assert b.frequenza.n_treni == 4 and b.frequenza.intervallo_medio_min == 20
    assert b.frequenza.treni_ora == 3.0 and b.frequenza_partenze.n_treni == 0


def test_frequenza_binario_non_dipende_dai_collegamenti():
    # due collegamenti diversi sullo stesso binario si sommano: conta il binario, non il percorso
    parts = [
        partenza(1, PG, "LECCO", T0, bin_p="1"),
        partenza(2, MONZA, "COMO", T0 + 10 * MIN, bin_p="1"),
        partenza(3, PG, "LECCO", T0 + 20 * MIN, bin_p="1"),
        partenza(4, MONZA, "COMO", T0 + 30 * MIN, bin_p="1"),
    ]
    (b,) = ProfiloStazione.da_tabelloni(LECCO, parts, []).binari_programmati
    assert len(b.collegamenti) == 2
    assert b.frequenza.n_treni == 4 and b.frequenza.intervallo_medio_min == 10
    assert b.frequenza.treni_ora == 6.0


def test_frequenza_teorica_del_binario_include_i_cancellati_una_volta_per_treno():
    parts = [
        partenza(1, PG, "LECCO", T0, bin_p="1"),
        partenza(2, PG, "LECCO", T0 + 30 * MIN, provvedimento=1),  # cancellato, senza binario
        partenza(3, PG, "LECCO", T0 + 60 * MIN, bin_p="1"),
    ]
    (b,) = ProfiloStazione.da_tabelloni(LECCO, parts, []).binari_programmati
    # 2 treni (+0, +60): un intervallo di 60 min, quindi 1 treno/h; con il cancellato in mezzo 2/h
    assert b.frequenza.n_treni == 2 and b.frequenza.treni_ora == 1.0
    assert b.frequenza_teorica.n_treni == 3 and b.frequenza_teorica.treni_ora == 2.0
    assert b.n_soppressi == 1


def test_frequenza_stazione_e_somma_dei_binari_per_treni_distinti():
    parts = [
        partenza(i, PG, "X", T0 + i * 10 * MIN, dest_cod="S9", bin_p=str(1 + i % 2))
        for i in range(6)
    ]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, [])
    assert p.frequenza.n_treni == sum(b.frequenza.n_treni for b in p.binari_programmati) == 6
    assert p.frequenza.treni_ora == 6.0
    assert [b.frequenza.treni_ora for b in p.binari_programmati] == [3.0, 3.0]


# ------------------------------------------------------------------------------ collegamenti inventati


def test_arrivo_incerto_non_crea_un_collegamento_verso_la_stazione():
    # un treno solo in arrivo a ridosso della fine delle partenze: potrebbe ripartire dopo,
    # quindi non si sa dove va e non deve comparire un collegamento "X -> stazione"
    parts = [
        partenza(1 + i, PG, "X", T0 + i * 30 * MIN, dest_cod="S9", bin_p="1") for i in range(4)
    ]
    arrs = [arrivo(50, MONZA, "MONZA", T0 + 88 * MIN, bin_p="2")]  # entro 15 min dalla fine (+90)
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs)
    assert p.ruolo.n_incerti == 1 and p.n_senza_collegamento == 1
    assert all(c.collegamento.origine_codice != MONZA for c in p.collegamenti)
    # il treno resta tra i binari (ha il binario 2), ma senza collegamenti: nessuna voce spuria
    b2 = next(b for b in p.binari_programmati if b.binario == "2")
    assert b2.collegamenti == ()


def test_terminale_dedotto_ha_il_collegamento_verso_la_stazione():
    parts = [
        partenza(1 + i, PG, "X", T0 + i * 30 * MIN, dest_cod="S9", bin_p="1") for i in range(4)
    ]
    arrs = [arrivo(50, MONZA, "MONZA", T0 + 5 * MIN, bin_p="2")]  # lontano dalla fine: dedotto
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs)
    assert p.ruolo.n_termina_dedotti == 1
    assert Collegamento(MONZA, LECCO) in p.elenco_collegamenti


def test_arrivo_incerto_resta_nei_binari_e_nelle_frequenze():
    # non crea un collegamento, ma il treno c'e': conta per i binari e per la frequentazione
    parts = [
        partenza(1 + i, PG, "X", T0 + i * 30 * MIN, dest_cod="S9", bin_p="1") for i in range(4)
    ]
    arrs = [arrivo(50, MONZA, "MONZA", T0 + 88 * MIN, bin_p="2")]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs)
    assert p.elenco_binari == ("1", "2") and p.n_treni == 5
    assert dict(next(b for b in p.binari_programmati if b.binario == "2").collegamenti) == {}


# ------------------------------------------------------------------------------ finestra comune


def test_finestra_comune_e_l_intersezione_di_partenze_e_arrivi():
    assert finestra_comune([T0, T0 + 100 * MIN], [T0 + 10 * MIN, T0 + 150 * MIN]) == (
        T0 + 10 * MIN,
        T0 + 100 * MIN,
    )
    assert finestra_comune([None, T0], [T0, None]) == (T0, T0)


def test_finestra_comune_assente_se_manca_un_tabellone_o_non_si_sovrappone():
    assert finestra_comune([], [T0]) is None and finestra_comune([T0], []) is None
    assert finestra_comune([T0, T0 + 10 * MIN], [T0 + 60 * MIN, T0 + 70 * MIN]) is None


def _bologna_in_piccolo():
    """Arrivi isolati molte ore prima delle partenze, come nei dati di Bologna Centrale."""
    arrs_lontani = [
        arrivo(900 + i, MONZA, "MONZA", T0 - (300 - i * 60) * MIN, bin_p="9") for i in range(5)
    ]
    parts = [
        partenza(1 + i, PG, "X", T0 + i * 3 * MIN, dest_cod="S9", bin_p="1") for i in range(20)
    ]
    arrs = [arrivo(1 + i, PG, "PG", T0 + (i * 3 - 1) * MIN, bin_p="1") for i in range(20)]
    return parts, arrs_lontani + arrs


def test_arrivi_isolati_lontani_non_abbassano_i_treni_all_ora():
    parts, arrs = _bologna_in_piccolo()
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs)
    # i 5 arrivi lontani + il primo treno regolare (arrivo a -1 min, partenza a 0: la finestra
    # comune parte dalla prima partenza, quindi il suo arrivo resta fuori)
    assert p.n_treni == 25 and p.n_fuori_finestra == 6
    # 19 treni ogni 3 minuti -> 20 treni/h, non 25 treni su 5+ ore
    assert p.frequenza.treni_ora == pytest.approx(20.0, rel=0.05)
    aperta = ProfiloStazione.da_tabelloni(
        LECCO, parts, arrs, parametri=ParametriProfilo(usa_finestra_comune=False)
    )
    assert aperta.frequenza.treni_ora is not None and aperta.frequenza.treni_ora < 8  # falsato
    assert aperta.n_fuori_finestra == 0 and aperta.finestra_frequenze_ms is None


def test_treni_fuori_finestra_restano_in_n_treni_e_nei_binari():
    parts, arrs = _bologna_in_piccolo()
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs)
    b9 = next(b for b in p.binari_programmati if b.binario == "9")
    assert b9.n_treni == 5  # presenti nei binari...
    assert b9.frequenza.n_treni == 0  # ...ma fuori dalla finestra delle frequenze


def test_finestra_comune_vale_anche_per_collegamenti_e_teoriche():
    parts, arrs = _bologna_in_piccolo()
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs)
    lontani = [c for c in p.collegamenti if c.collegamento.origine_codice == MONZA]
    assert all(c.frequenza.n_treni == 0 and c.frequenza_teorica.n_treni == 0 for c in lontani)
    assert p.frequenza_teorica.n_treni == p.frequenza.n_treni


def test_senza_partenze_non_si_filtra_nulla():
    arrs = [arrivo(i, PG, "PG", T0 + i * 10 * MIN) for i in range(4)]
    p = ProfiloStazione.da_tabelloni(LECCO, [], arrs)
    assert p.finestra_frequenze_ms is None and p.n_fuori_finestra == 0
    assert p.frequenza.n_treni == 4


def test_treno_a_cavallo_del_bordo_usa_il_proprio_orario_di_riferimento():
    # partenze +2..+122, arrivi 0..+120 -> finestra +2..+120; il treno 3 (arrivo +120,
    # partenza +122) ha il riferimento (la partenza) fuori dalla finestra
    parts = [partenza(i, PG, "X", T0 + (2 + 60 * (i - 1)) * MIN, bin_p="1") for i in (1, 2, 3)]
    arrs = [arrivo(i, PG, "PG", T0 + 60 * (i - 1) * MIN, bin_p="1") for i in (1, 2, 3)]
    p = ProfiloStazione.da_tabelloni(LECCO, parts, arrs)
    assert p.finestra_frequenze_ms == (T0 + 2 * MIN, T0 + 120 * MIN) and p.n_fuori_finestra == 1
    assert p.frequenza.n_treni == 2  # treni 1 e 2
    assert p.frequenza_partenze.n_treni == 2 and p.frequenza_arrivi.n_treni == 2
