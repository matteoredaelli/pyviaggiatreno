# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crawler a eventi: limitatore, scheduler, calcolo delle scadenze e i tre tipi di lavoro."""

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from viaggiatreno import TrainStatus, ViaggiaTrenoClient
from viaggiatreno_crawler import storage
from viaggiatreno_crawler.__main__ import parse_args_eventi
from viaggiatreno_crawler.config import ConfigEventi
from viaggiatreno_crawler.eventi import (
    CENSISCI,
    SONDA,
    VERIFICA,
    Motore,
    prossima_sonda_ms,
)
from viaggiatreno_crawler.rete import LimitatoreRichieste
from viaggiatreno_crawler.scheduler import Pianificatore

ORA = 1_800_000_000_000
SEC = 1000
MIN = 60 * SEC
GIORNO = 1_799_971_200_000  # "mezzanotte" di riferimento (valore qualsiasi, coerente)


# ============================================================ limitatore di richieste


class OrologioFinto:
    def __init__(self):
        self.t = 100.0
        self.attese: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.attese.append(round(s, 6))
        self.t += s


async def test_limitatore_distanzia_le_richieste():
    o = OrologioFinto()
    lim = LimitatoreRichieste(2.0, orologio=o, sleep=o.sleep)  # 2 al secondo = 0,5 s
    for _ in range(4):
        await lim.attendi()
    assert o.attese == [0.5, 0.5, 0.5]  # la prima passa subito
    assert lim.n_richieste == 4


async def test_limitatore_richieste_concorrenti_prendono_slot_diversi():
    inizi: list[float] = []
    o = OrologioFinto()
    lim = LimitatoreRichieste(4.0, orologio=o, sleep=o.sleep)

    async def una():
        await lim.attendi()
        inizi.append(o.t)

    await asyncio.gather(*[una() for _ in range(5)])
    # con un solo task alla volta l'orologio finto avanza: gli slot sono a 0,25 s l'uno
    assert sorted(inizi) == sorted(set(inizi)) or len(set(inizi)) >= 4
    assert o.t - 100.0 == pytest.approx(1.0, abs=0.01)  # 5 richieste = 4 intervalli da 0,25 s


async def test_limitatore_senza_limite_non_attende():
    o = OrologioFinto()
    lim = LimitatoreRichieste(0, orologio=o, sleep=o.sleep)
    for _ in range(10):
        await lim.attendi()
    assert o.attese == []


async def test_limitatore_dopo_una_pausa_non_accumula_credito():
    o = OrologioFinto()
    lim = LimitatoreRichieste(1.0, orologio=o, sleep=o.sleep)
    await lim.attendi()
    o.t += 60  # un minuto di inattivita'
    await lim.attendi()
    await lim.attendi()
    assert o.attese == [1.0]  # niente raffica dopo la pausa: solo la seconda e' distanziata


async def test_il_limitatore_conta_anche_i_retry_nel_trasporto():
    import httpx
    from viaggiatreno_crawler.rete import TransportResiliente

    class Sempre500(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(500, request=request)

    o = OrologioFinto()
    lim = LimitatoreRichieste(0, orologio=o, sleep=o.sleep)
    t = TransportResiliente(Sempre500(), max_tentativi=3, limitatore=lim, sleep=o.sleep)
    async with httpx.AsyncClient(transport=t) as c:
        r = await c.get("http://x/")
    assert r.status_code == 500
    assert lim.n_richieste == 3  # ogni tentativo passa dal limitatore


# ============================================================ scheduler


class Esecutore:
    def __init__(self, durata=0.0):
        self.fatti: list[tuple[str, str]] = []
        self.in_corso = 0
        self.max_in_corso = 0
        self.durata = durata

    async def __call__(self, tipo, chiave):
        self.in_corso += 1
        self.max_in_corso = max(self.max_in_corso, self.in_corso)
        await asyncio.sleep(self.durata)
        self.fatti.append((tipo, chiave))
        self.in_corso -= 1


async def _fino_a_inattivo(p: Pianificatore, secondi=3.0):
    task = asyncio.create_task(p.esegui())
    try:
        async with asyncio.timeout(secondi):
            while not p.inattivo:
                await asyncio.sleep(0.01)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_i_lavori_escono_in_ordine_di_scadenza():
    e = Esecutore()
    p = Pianificatore(e, workers=1)
    ora = p._ora()
    p.pianifica("a", "tardi", ora + 150)
    p.pianifica("a", "presto", ora + 10)
    p.pianifica("a", "meta", ora + 80)
    await _fino_a_inattivo(p)
    assert [c for _, c in e.fatti] == ["presto", "meta", "tardi"]


async def test_ripianificare_sposta_la_scadenza_e_non_duplica():
    e = Esecutore()
    p = Pianificatore(e, workers=2)
    ora = p._ora()
    p.pianifica("a", "x", ora + 5_000)
    p.pianifica("a", "x", ora + 20)  # anticipa
    p.pianifica("a", "y", ora + 10)
    p.pianifica("a", "y", ora + 80)  # posticipa
    await _fino_a_inattivo(p)
    assert e.fatti == [("a", "x"), ("a", "y")]  # una volta sola ciascuno


async def test_solo_se_prima_non_rimanda_in_avanti():
    p = Pianificatore(Esecutore(), workers=1)
    p.pianifica("a", "x", 1000)
    p.pianifica("a", "x", 5000, solo_se_prima=True)
    assert p.scadenza("a", "x") == 1000
    p.pianifica("a", "x", 500, solo_se_prima=True)
    assert p.scadenza("a", "x") == 500


async def test_annulla_toglie_il_lavoro():
    e = Esecutore()
    p = Pianificatore(e, workers=1)
    p.pianifica("a", "x", p._ora() + 20)
    p.annulla("a", "x")
    assert p.inattivo
    await asyncio.sleep(0.05)
    assert e.fatti == []


async def test_il_numero_di_worker_limita_i_lavori_in_parallelo():
    e = Esecutore(durata=0.05)
    p = Pianificatore(e, workers=3)
    for i in range(12):
        p.pianifica("a", str(i), 0)
    await _fino_a_inattivo(p)
    assert len(e.fatti) == 12
    assert e.max_in_corso == 3


async def test_lo_stesso_lavoro_non_gira_due_volte_insieme():
    e = Esecutore(durata=0.08)
    p = Pianificatore(e, workers=4)
    p.pianifica("a", "x", 0)

    async def ripianifica():
        await asyncio.sleep(0.02)  # mentre "x" e' in esecuzione
        p.pianifica("a", "x", 0)

    asyncio.create_task(ripianifica())
    await _fino_a_inattivo(p, 5.0)
    assert e.fatti == [("a", "x"), ("a", "x")]
    assert e.max_in_corso == 1


async def test_un_errore_non_ferma_gli_altri_e_riprova():
    chiamate: list[str] = []

    async def esegui(tipo, chiave):
        chiamate.append(chiave)
        if chiave == "rotto" and chiamate.count("rotto") == 1:
            raise RuntimeError("boom")

    p = Pianificatore(esegui, workers=1, ritardo_errore_ms=30)
    p.pianifica("a", "rotto", 0)
    p.pianifica("a", "ok", 0)
    await _fino_a_inattivo(p)
    assert chiamate.count("ok") == 1
    assert chiamate.count("rotto") == 2  # riprovato dopo l'errore
    assert p.errori["a"] == 1


# ============================================================ calcolo delle scadenze


def _cfg(**kw) -> ConfigEventi:
    return ConfigEventi(sonda_jitter=0.0, **kw)


def test_sonda_senza_finestre_usa_l_intervallo_standard():
    assert prossima_sonda_ms(ORA, [], _cfg()) == ORA + 4500 * SEC


def test_sonda_usa_la_finestra_osservata_se_e_piu_corta():
    # tabellone pieno che arriva solo a +40 minuti: si richiama a 40 - 10 = 30 minuti
    fine = ORA + 40 * MIN
    assert prossima_sonda_ms(ORA, [(20, fine)], _cfg()) == ORA + 30 * MIN


def test_sonda_ignora_la_finestra_di_un_tabellone_quasi_vuoto():
    # con 2 righe l'ultimo orario non e' il limite della finestra: non accorcia nulla
    assert prossima_sonda_ms(ORA, [(2, ORA + 5 * MIN)], _cfg()) == ORA + 4500 * SEC


def test_sonda_non_scende_sotto_il_minimo():
    assert prossima_sonda_ms(ORA, [(30, ORA + 11 * MIN)], _cfg()) == ORA + 10 * MIN


def test_sonda_il_jitter_anticipa_soltanto():
    cfg = ConfigEventi(sonda_jitter=0.2)
    pieno = prossima_sonda_ms(ORA, [], cfg, rng=lambda: 0.0)
    anticipato = prossima_sonda_ms(ORA, [], cfg, rng=lambda: 1.0)
    assert pieno == ORA + 4500 * SEC
    assert ORA + 3600 * SEC - 1 <= anticipato < pieno


def _status(fermate, **extra) -> TrainStatus:
    base = {"numeroTreno": 10, "tipoTreno": "PG", "provvedimento": 0, "fermate": fermate}
    return TrainStatus.model_validate({**base, **extra})


def _f(sid, nome, tipo, prog, prog_ms, att=0):
    return {
        "stazione": nome,
        "id": sid,
        "tipoFermata": tipo,
        "progressivo": prog,
        "programmata": prog_ms,
        "actualFermataType": att,
    }


# ============================================================ motore: i tre lavori


class Orologio:
    def __init__(self, t=ORA):
        self.t = t

    def __call__(self):
        return self.t


def _riga(numero, origine, dest, orario_part, nome_o="Origine", nome_d="Dest"):
    return SimpleNamespace(
        numeroTreno=numero,
        codOrigine=origine,
        dataPartenzaTreno=GIORNO,
        categoria="REG",
        codDestinazione=dest,
        origine=nome_o,
        destinazione=nome_d,
        codiceCliente=63,
        ritardo=0,
        orarioPartenza=orario_part,
        orarioArrivo=None,
        model_dump_json=lambda: "{}",
    )


class ClientFinto:
    def __init__(self):
        self.board: dict[tuple[str, str], list] = {}
        self.stati: dict[int, TrainStatus | None] = {}
        self.chiamate: list[tuple] = []
        self.falliscono: set[str] = set()

    async def partenze(self, stop_id):
        self.chiamate.append(("partenze", stop_id))
        if stop_id in self.falliscono:
            raise RuntimeError("giu'")
        return self.board.get(("partenze", stop_id), [])

    async def arrivi(self, stop_id):
        self.chiamate.append(("arrivi", stop_id))
        return self.board.get(("arrivi", stop_id), [])

    async def andamento_treno(self, origine, numero, data):
        self.chiamate.append(("andamento", numero))
        return self.stati.get(numero)


def _motore(tmp_path, client=None, **kw):
    conn = storage.connect(tmp_path / "e.db")
    clock = Orologio()
    client = client or ClientFinto()
    m = Motore(
        conn,
        cast(ViaggiaTrenoClient, client),
        _cfg(**kw),
        orologio_ms=clock,
    )
    return m, client, clock


def _stazione(m: Motore, sid: str, nome="X", **flag):
    storage.registra_stop_se_nuovo(m.conn, sid, nome, "test")
    if flag:
        storage.segna_capolinea(m.conn, sid, **flag)


async def test_censimento_trova_il_treno_la_origine_e_la_destinazione(tmp_path):
    m, c, _ = _motore(tmp_path)
    _stazione(m, "S1")
    c.board[("partenze", "S1")] = [_riga(100, "S1", "S9", ORA + 30 * MIN, "Uno", "Nove")]
    await m._esegui(CENSISCI, "S1")

    nomi = dict(m.conn.execute("SELECT stop_id, stop_name FROM stops").fetchall())
    assert nomi["S9"] == "Nove"  # stazione sconosciuta scoperta dalla destinazione
    cap = {
        r[0]: (r[1], r[2])
        for r in m.conn.execute("SELECT stop_id,e_origine,e_destinazione FROM stops")
    }
    assert cap["S1"] == (1, 0) and cap["S9"] == (0, 1)
    t = m.conn.execute("SELECT * FROM treni").fetchone()
    assert t["numero_treno"] == 100 and t["orario_partenza"] == ORA + 30 * MIN
    # prima verifica 10 minuti prima della partenza
    assert t["prossima_verifica"] == ORA + 20 * MIN
    assert m.pian.scadenza(VERIFICA, str(t["id"])) == ORA + 20 * MIN


async def test_scoperto_capolinea_si_fanno_subito_anche_gli_arrivi(tmp_path):
    m, c, _ = _motore(tmp_path)
    _stazione(m, "S1")
    c.board[("partenze", "S1")] = [_riga(100, "S1", "S9", ORA + 30 * MIN)]
    await m._esegui(CENSISCI, "S1")
    assert m.pian.scadenza(SONDA, "S1") == ORA  # subito
    assert m.pian.scadenza(CENSISCI, "S1") is None
    await m._esegui(SONDA, "S1")
    assert ("arrivi", "S1") in c.chiamate
    assert m.pian.scadenza(SONDA, "S1") == ORA + 4500 * SEC


async def test_stazione_di_transito_non_diventa_capolinea_e_si_richiama_dopo_un_giorno(tmp_path):
    m, c, _ = _motore(tmp_path)
    _stazione(m, "S5")
    c.board[("partenze", "S5")] = []  # nessun treno nasce qui
    await m._esegui(CENSISCI, "S5")
    assert m.pian.scadenza(CENSISCI, "S5") == ORA + 86_400 * SEC
    assert m.pian.scadenza(SONDA, "S5") is None
    assert c.chiamate == [("partenze", "S5")]  # una sola richiesta, niente arrivi


async def test_orario_di_transito_non_diventa_orario_di_partenza(tmp_path):
    """Un treno visto su un tabellone di transito ha l'orario *di quella stazione*."""
    m, c, _ = _motore(tmp_path)
    _stazione(m, "S5")
    c.board[("partenze", "S5")] = [_riga(200, "S1", "S9", ORA + 60 * MIN)]  # origine S1, non S5
    await m._esegui(CENSISCI, "S5")
    t = m.conn.execute("SELECT orario_partenza, prossima_verifica FROM treni").fetchone()
    assert t["orario_partenza"] is None
    assert t["prossima_verifica"] == ORA  # orario ignoto: verifica subito


async def test_il_tabellone_dell_origine_completa_l_orario_mancante(tmp_path):
    m, c, _ = _motore(tmp_path)
    _stazione(m, "S5")
    _stazione(m, "S1")
    c.board[("partenze", "S5")] = [_riga(200, "S1", "S9", ORA + 60 * MIN)]
    await m._esegui(CENSISCI, "S5")
    c.board[("partenze", "S1")] = [_riga(200, "S1", "S9", ORA + 15 * MIN)]
    await m._esegui(CENSISCI, "S1")
    t = m.conn.execute("SELECT orario_partenza FROM treni").fetchone()
    assert t["orario_partenza"] == ORA + 15 * MIN


async def test_un_treno_gia_noto_non_viene_riprogrammato(tmp_path):
    m, c, _ = _motore(tmp_path)
    _stazione(m, "S1")
    c.board[("partenze", "S1")] = [_riga(100, "S1", "S9", ORA + 30 * MIN)]
    await m._esegui(CENSISCI, "S1")
    tid = m.conn.execute("SELECT id FROM treni").fetchone()["id"]
    m.pian.annulla(VERIFICA, str(tid))
    await m._esegui(SONDA, "S1")  # lo rivede
    assert m.pian.scadenza(VERIFICA, str(tid)) is None  # non rimesso in coda
    assert m.conn.execute("SELECT COUNT(*) FROM treni").fetchone()[0] == 1


async def test_tabellone_fallito_si_riprova_dopo_l_attesa_e_viene_registrato(tmp_path):
    m, c, _ = _motore(tmp_path)
    _stazione(m, "S1")
    c.falliscono.add("S1")
    await m._esegui(CENSISCI, "S1")
    assert m.pian.scadenza(CENSISCI, "S1") == ORA + 300 * SEC
    assert m.conn.execute("SELECT esito FROM tabelloni_richieste").fetchone()[0] == "errore"
    assert m.conn.execute("SELECT ultimo_tabellone FROM stops").fetchone()[0] is None


async def test_la_finestra_corta_del_tabellone_accorcia_la_sonda(tmp_path):
    m, c, _ = _motore(tmp_path)
    _stazione(m, "S1", origine=True)
    c.board[("partenze", "S1")] = [
        _riga(300 + i, "S1", "S9", ORA + (5 + i) * MIN) for i in range(10)
    ]  # 10 righe, l'ultima a +14 minuti
    await m._esegui(SONDA, "S1")
    # finestra: +14 min - 10 min di margine = 4 min, ma il minimo e' 10 minuti
    assert m.pian.scadenza(SONDA, "S1") == ORA + 10 * MIN


def _status_completo(origine="S1", dest="S9", ritardo=0, arrivato=False, durata=60):
    return _status(
        [
            _f(origine, "Uno", "P", 1, ORA, att=1),
            _f("S5", "Cinque", "F", 2, ORA + 20 * MIN, att=1),
            _f(dest, "Nove", "A", 3, ORA + durata * MIN, att=1 if arrivato else 0),
        ],
        ritardo=ritardo,
        arrivato=arrivato,
        orarioPartenza=ORA,
    )


def _treno_in_coda(m: Motore, c: ClientFinto, partenza=ORA) -> int:
    _stazione(m, "S1")
    tid = storage.upsert_treno(
        m.conn,
        numero_treno=10,
        cod_origine="S1",
        data_partenza_treno=GIORNO,
        orario_partenza=partenza,
    )
    m.conn.commit()
    return tid


async def test_verifica_programma_la_seconda_chiamata_dopo_l_arrivo_previsto(tmp_path):
    m, c, _ = _motore(tmp_path)
    tid = _treno_in_coda(m, c)
    c.stati[10] = _status_completo(ritardo=5)
    await m._esegui(VERIFICA, str(tid))

    t = m.conn.execute("SELECT * FROM treni WHERE id = ?", (tid,)).fetchone()
    assert t["arrivo_previsto"] == ORA + 65 * MIN  # 60 min + 5 di ritardo
    assert t["prossima_verifica"] == ORA + 75 * MIN  # + margine di 10 minuti
    assert m.pian.scadenza(VERIFICA, str(tid)) == ORA + 75 * MIN
    # itinerario applicato: stazioni nuove e capolinea
    cap = {
        r[0]: (r[1], r[2])
        for r in m.conn.execute("SELECT stop_id,e_origine,e_destinazione FROM stops")
    }
    assert cap["S9"] == (0, 1) and cap["S1"][0] == 1
    assert "S5" in cap and cap["S5"] == (0, 0)  # transito: nuova ma non capolinea
    assert (
        m.conn.execute("SELECT COUNT(*) FROM fermate WHERE treno_id = ?", (tid,)).fetchone()[0] == 3
    )
    # una sola chiamata: non e' stato ripianificato prima
    assert [x for x in c.chiamate if x[0] == "andamento"] == [("andamento", 10)]


async def test_verifica_dopo_l_arrivo_chiude_il_treno_e_non_ripianifica(tmp_path):
    m, c, clock = _motore(tmp_path)
    tid = _treno_in_coda(m, c)
    c.stati[10] = _status_completo(ritardo=4, arrivato=True)
    clock.t = ORA + 70 * MIN
    await m._esegui(VERIFICA, str(tid))
    t = m.conn.execute("SELECT * FROM treni WHERE id = ?", (tid,)).fetchone()
    assert t["stato"] == "arrivato" and t["prossima_verifica"] is None
    assert m.pian.scadenza(VERIFICA, str(tid)) is None


async def test_verifica_su_treno_non_ancora_arrivato_riprova_senza_martellare(tmp_path):
    m, c, clock = _motore(tmp_path)
    tid = _treno_in_coda(m, c)
    c.stati[10] = _status_completo(ritardo=0)
    await m._esegui(VERIFICA, str(tid))
    clock.t = ORA + 71 * MIN  # alla scadenza, ma il treno ha accumulato ritardo
    c.stati[10] = _status_completo(ritardo=30)
    await m._esegui(VERIFICA, str(tid))
    t = m.conn.execute("SELECT * FROM treni WHERE id = ?", (tid,)).fetchone()
    assert t["arrivo_previsto"] == ORA + 90 * MIN
    assert t["prossima_verifica"] == ORA + 100 * MIN  # nuovo arrivo + margine


async def test_204_prima_della_partenza_non_conta_e_attende_la_partenza(tmp_path):
    m, c, _ = _motore(tmp_path)
    tid = _treno_in_coda(m, c, partenza=ORA + 3 * 3600 * SEC)
    c.stati[10] = None
    await m._esegui(VERIFICA, str(tid))
    t = m.conn.execute(
        "SELECT tentativi_204, prossima_verifica FROM treni WHERE id = ?", (tid,)
    ).fetchone()
    assert t["tentativi_204"] == 0
    assert t["prossima_verifica"] == ORA + 3 * 3600 * SEC - 600 * SEC


async def test_cinque_204_dopo_la_partenza_chiudono_il_treno(tmp_path):
    m, c, clock = _motore(tmp_path)
    tid = _treno_in_coda(m, c, partenza=ORA - 10 * MIN)
    c.stati[10] = None
    for _ in range(5):
        await m._esegui(VERIFICA, str(tid))
        clock.t += 6 * MIN
    t = m.conn.execute(
        "SELECT stato, chiusura_motivo, prossima_verifica FROM treni WHERE id = ?", (tid,)
    ).fetchone()
    assert (t["stato"], t["chiusura_motivo"], t["prossima_verifica"]) == (
        "non_disponibile",
        "204",
        None,
    )
    assert m.pian.scadenza(VERIFICA, str(tid)) is None


async def test_treno_gia_chiuso_non_chiama_la_rete(tmp_path):
    m, c, _ = _motore(tmp_path)
    tid = _treno_in_coda(m, c)
    m.conn.execute("UPDATE treni SET stato = 'arrivato' WHERE id = ?", (tid,))
    await m._esegui(VERIFICA, str(tid))
    assert c.chiamate == []


async def test_treno_che_non_arriva_mai_viene_chiuso_come_scaduto(tmp_path):
    m, c, clock = _motore(tmp_path, verifica_scadenza_max_sec=3600)
    tid = _treno_in_coda(m, c)
    c.stati[10] = _status_completo(ritardo=0)  # arrivo previsto a ORA+60min, mai 'arrivato'
    clock.t = ORA + 3 * 3600 * SEC
    await m._esegui(VERIFICA, str(tid))
    t = m.conn.execute("SELECT stato, chiusura_motivo FROM treni WHERE id = ?", (tid,)).fetchone()
    assert (t["stato"], t["chiusura_motivo"]) == ("non_disponibile", "scaduto")


# ============================================================ riavvio


def test_ricostruisci_riprende_le_scadenze_salvate(tmp_path):
    m, c, clock = _motore(tmp_path)
    _stazione(m, "S1", origine=True)
    _stazione(m, "S5")
    storage.imposta_scadenza_stazione(m.conn, "S1", ORA + 40 * MIN)
    tid = storage.upsert_treno(
        m.conn,
        numero_treno=1,
        cod_origine="S1",
        data_partenza_treno=GIORNO,
        orario_partenza=ORA + MIN,
    )
    storage.imposta_scadenza_treno(m.conn, tid, ORA + 55 * MIN)
    m.conn.commit()

    nuovo = Motore(m.conn, cast(ViaggiaTrenoClient, c), _cfg(), orologio_ms=clock)  # "riavvio"
    assert nuovo.pian.n_programmati == 0
    assert nuovo.ricostruisci() == (2, 1)
    assert nuovo.pian.scadenza(SONDA, "S1") == ORA + 40 * MIN  # salvata: non si sonda subito
    assert nuovo.pian.scadenza(CENSISCI, "S5") == ORA  # mai sondata: subito
    assert nuovo.pian.scadenza(VERIFICA, str(tid)) == ORA + 55 * MIN


def test_ricostruisci_senza_scadenza_calcola_la_prima_verifica_dalla_partenza(tmp_path):
    m, _, _ = _motore(tmp_path)
    t1 = storage.upsert_treno(
        m.conn,
        numero_treno=1,
        cod_origine="S1",
        data_partenza_treno=GIORNO,
        orario_partenza=ORA + 2 * 3600 * SEC,
    )
    t2 = storage.upsert_treno(
        m.conn, numero_treno=2, cod_origine="S1", data_partenza_treno=GIORNO, orario_partenza=None
    )
    m.conn.commit()
    m.ricostruisci()
    assert m.pian.scadenza(VERIFICA, str(t1)) == ORA + 2 * 3600 * SEC - 600 * SEC
    assert m.pian.scadenza(VERIFICA, str(t2)) == ORA


def test_ricostruisci_deduce_i_capolinea_dai_dati_vecchi(tmp_path):
    """Un DB di prima del crawler a eventi non ha i flag: si ricavano da treni e fermate."""
    m, _, _ = _motore(tmp_path)
    _stazione(m, "S1")
    _stazione(m, "S9")
    tid = storage.upsert_treno(
        m.conn, numero_treno=1, cod_origine="S1", data_partenza_treno=GIORNO, cod_destinazione="S9"
    )
    storage.sostituisci_fermate(m.conn, tid, [{"stop_id": "S9", "tipo_fermata": "A"}])
    m.conn.commit()
    m.ricostruisci()
    assert m.pian.scadenza(SONDA, "S1") is not None and m.pian.scadenza(SONDA, "S9") is not None


def test_chiudi_scaduti_rispetta_i_treni_notturni(tmp_path):
    conn = storage.connect(tmp_path / "e.db")
    sera = storage.upsert_treno(
        conn,
        numero_treno=1,
        cod_origine="S1",
        data_partenza_treno=GIORNO,
        orario_partenza=ORA - 3600 * SEC,
    )
    vecchio = storage.upsert_treno(
        conn,
        numero_treno=2,
        cod_origine="S1",
        data_partenza_treno=GIORNO,
        orario_partenza=ORA - 40 * 3600 * SEC,
    )
    conn.execute("UPDATE treni SET arrivo_previsto = ? WHERE id = ?", (ORA + 3600 * SEC, sera))
    conn.commit()
    assert storage.chiudi_scaduti(conn, ORA, 6 * 3600 * SEC) == 1
    stati = dict(conn.execute("SELECT id, stato FROM treni").fetchall())
    assert stati[sera] == "in_corso" and stati[vecchio] == "non_disponibile"


# ============================================================ storage / CLI


def test_segna_capolinea_segnala_solo_la_prima_volta(tmp_path):
    conn = storage.connect(tmp_path / "e.db")
    storage.registra_stop_se_nuovo(conn, "S1", "Uno", "t")
    assert storage.segna_capolinea(conn, "S1", origine=True) is True
    assert storage.segna_capolinea(conn, "S1", origine=True) is False
    assert storage.segna_capolinea(conn, "S1", destinazione=True) is False  # gia' capolinea
    assert storage.segna_capolinea(conn, "NOPE", origine=True) is False


def test_registra_stop_se_nuovo_non_sovrascrive(tmp_path):
    conn = storage.connect(tmp_path / "e.db")
    storage.upsert_stop(conn, "S1", "Nome vero", 45.0, 9.0, regione_codice=1)
    assert storage.registra_stop_se_nuovo(conn, "S1", "Altro", "itinerario") is False
    r = conn.execute("SELECT stop_name, stop_lat FROM stops").fetchone()
    assert (r[0], r[1]) == ("Nome vero", 45.0)
    assert storage.registra_stop_se_nuovo(conn, "S2", None, "itinerario") is True
    assert storage.registra_stop_se_nuovo(conn, "S2", "Nome tardivo", "tabellone") is False
    assert (
        conn.execute("SELECT stop_name FROM stops WHERE stop_id='S2'").fetchone()[0]
        == "Nome tardivo"
    )


def test_db_di_prima_viene_migrato_con_le_nuove_colonne(tmp_path):
    import sqlite3

    p = tmp_path / "vecchio.db"
    storage.connect(p).close()
    raw = sqlite3.connect(p)
    raw.execute("ALTER TABLE treni DROP COLUMN prossima_verifica")
    raw.execute("ALTER TABLE stops DROP COLUMN e_origine")
    raw.commit()
    raw.close()
    conn = storage.connect(p)
    assert "prossima_verifica" in {r[1] for r in conn.execute("PRAGMA table_info(treni)")}
    assert "e_origine" in {r[1] for r in conn.execute("PRAGMA table_info(stops)")}


def test_cli_eventi_default_e_opzioni():
    c = parse_args_eventi(["eventi"])
    assert (c.richieste_al_secondo, c.workers, c.db_path) == (1.0, 4, "data/eventi.db")
    c = parse_args_eventi(
        ["eventi", "--richieste-al-secondo", "0.5", "--workers", "2", "--db-path", "x.db"]
    )
    assert (c.richieste_al_secondo, c.workers, c.db_path) == (0.5, 2, "x.db")


# ============================================================ tratte e scan nel motore a eventi


class ClientTratte(ClientFinto):
    """Aggiunge elencoTratte/dettagliTratta/cercaNumeroTreno al client finto."""

    def __init__(self):
        super().__init__()
        self.segmenti: list = []
        self.gruppi: dict[int, list] = {}
        self.numeri: dict[int, object] = {}
        self.chiamate_tratte = 0

    async def elenco_tratte(self, **kw):
        self.chiamate_tratte += 1
        return self.segmenti

    async def dettagli_tratta(self, ab, ba, **kw):
        return self.gruppi.get(ab, [])

    async def cerca_numero_treno(self, n):
        return self.numeri.get(n)


def _segmento(ab, ba, occupata):
    return SimpleNamespace(
        trattaAB=ab,
        trattaBA=ba,
        nodoA="A",
        nodoB="B",
        latitudineA=1.0,
        longitudineA=2.0,
        latitudineB=3.0,
        longitudineB=4.0,
        parentAB=None,
        parentBA=None,
        occupata=occupata,
    )


def _treno_tratta(numero, origine, dest, partenza):
    return SimpleNamespace(
        numeroTreno=numero,
        codOrigine=origine,
        dataPartenzaTreno=GIORNO,
        categoria="REG",
        codDestinazione=dest,
        origine="Uno",
        destinazione="Nove",
        codiceCliente=63,
        ritardo=0,
        orarioPartenza=partenza,
        model_dump_json=lambda: "{}",
    )


async def test_tratte_salva_nelle_stesse_tabelle_e_mette_in_coda_i_treni(tmp_path):
    c = ClientTratte()
    c.segmenti = [_segmento(5, 87, True), _segmento(6, 88, False)]
    c.gruppi[5] = [SimpleNamespace(treni=[_treno_tratta(100, "S1", "S9", ORA + 30 * MIN)])]
    m, _, _ = _motore(tmp_path, client=c, tratte_intervallo_sec=300)
    await m._esegui("scopri_tratte", "scopri_tratte")

    q = lambda s: m.conn.execute(s).fetchone()[0]
    assert q("SELECT COUNT(*) FROM tratte") == 2
    assert q("SELECT COUNT(*) FROM tratte_osservazioni") == 2  # tutti i segmenti, anche liberi
    assert q("SELECT COUNT(*) FROM avvistamenti_tratta") == 1
    t = m.conn.execute("SELECT id, prossima_verifica FROM treni").fetchone()
    assert t["prossima_verifica"] == ORA + 20 * MIN  # 10 minuti prima della partenza
    assert m.pian.scadenza(VERIFICA, str(t["id"])) == ORA + 20 * MIN
    # origine e destinazione del treno diventano capolinea e finiscono in censimento/sonda
    assert m.pian.scadenza(SONDA, "S1") is not None and m.pian.scadenza(SONDA, "S9") is not None
    assert m.pian.scadenza("scopri_tratte", "scopri_tratte") == ORA + 300 * SEC  # si riprogramma


async def test_tratte_non_riprogramma_un_treno_gia_in_coda(tmp_path):
    c = ClientTratte()
    c.segmenti = [_segmento(5, 87, True)]
    c.gruppi[5] = [SimpleNamespace(treni=[_treno_tratta(100, "S1", "S9", ORA + 30 * MIN)])]
    m, _, _ = _motore(tmp_path, client=c, tratte_intervallo_sec=300)
    await m._esegui("scopri_tratte", "scopri_tratte")
    tid = m.conn.execute("SELECT id FROM treni").fetchone()["id"]
    m.pian.pianifica(VERIFICA, str(tid), ORA + 7 * MIN)  # nel frattempo spostato
    await m._esegui("scopri_tratte", "scopri_tratte")  # lo rivede
    assert m.pian.scadenza(VERIFICA, str(tid)) == ORA + 7 * MIN


async def test_tratte_ignora_i_treni_senza_origine(tmp_path):
    c = ClientTratte()
    c.segmenti = [_segmento(5, 87, True)]
    c.gruppi[5] = [SimpleNamespace(treni=[_treno_tratta(100, None, None, None)])]
    m, _, _ = _motore(tmp_path, client=c, tratte_intervallo_sec=300)
    await m._esegui("scopri_tratte", "scopri_tratte")
    assert m.pian.scadenza(VERIFICA, "1") is None


async def test_scan_numeri_registra_i_treni_nuovi_e_li_mette_in_coda(tmp_path):
    c = ClientTratte()
    c.numeri[101] = SimpleNamespace(
        numeroTreno=101, codLocOrig="S1", millisDataPartenza=GIORNO, descLocOrig="Uno"
    )
    m, _, _ = _motore(tmp_path, client=c, scan_intervallo_sec=900, scan_finestra=2)
    _stazione(m, "S1")
    storage.upsert_treno(
        m.conn, numero_treno=100, cod_origine="S1", data_partenza_treno=GIORNO, stato="arrivato"
    )
    m.conn.commit()
    await m._esegui("scan_numeri", "scan_numeri")
    nuovo = m.conn.execute("SELECT id, stato FROM treni WHERE numero_treno = 101").fetchone()
    assert nuovo["stato"] == "in_corso"
    assert m.pian.scadenza(VERIFICA, str(nuovo["id"])) == ORA  # partenza ignota: subito
    assert m.pian.scadenza("scan_numeri", "scan_numeri") == ORA + 900 * SEC


def test_i_lavori_periodici_restano_spenti_di_default(tmp_path):
    m, _, _ = _motore(tmp_path)
    m.ricostruisci()
    assert m.pian.scadenza("scopri_tratte", "scopri_tratte") is None
    assert m.pian.scadenza("scan_numeri", "scan_numeri") is None


def test_riavvio_non_rilancia_subito_le_tratte_appena_fatte(tmp_path):
    m, _, _ = _motore(tmp_path, tratte_intervallo_sec=300)
    storage.set_stato(m.conn, "ultimo_giro_eventi_tratte", str(ORA - 100 * SEC))
    m.ricostruisci()
    assert m.pian.scadenza("scopri_tratte", "scopri_tratte") == ORA + 200 * SEC
    storage.set_stato(m.conn, "ultimo_giro_eventi_tratte", str(ORA - 900 * SEC))  # scaduto
    m.ricostruisci()
    assert m.pian.scadenza("scopri_tratte", "scopri_tratte") == ORA


def test_cli_eventi_tratte_e_scan():
    c = parse_args_eventi(
        ["eventi", "--intervallo-tratte", "300", "--intervallo-scan", "1800", "--zoomlevel", "7"]
    )
    assert (c.tratte_intervallo_sec, c.scan_intervallo_sec, c.zoomlevel) == (300, 1800, 7)
    c = parse_args_eventi(["eventi"])
    assert (c.tratte_intervallo_sec, c.scan_intervallo_sec) == (0, 0)


# ============================================================ provenienza delle stazioni (`stops.fonte`)


def _fonti(conn):
    return dict(conn.execute("SELECT stop_id, fonte FROM stops").fetchall())


async def test_stazione_nuova_da_tabellone_e_itinerario_ha_la_sua_fonte(tmp_path):
    m, c, _ = _motore(tmp_path)
    _stazione(m, "S1")
    c.board[("partenze", "S1")] = [_riga(100, "S1", "S9", ORA + 30 * MIN)]
    await m._esegui(CENSISCI, "S1")
    assert _fonti(m.conn)["S9"] == "tabellone"  # destinazione di una riga di tabellone

    tid = m.conn.execute("SELECT id FROM treni").fetchone()["id"]
    c.stati[100] = _status(
        [
            _f("S1", "Uno", "P", 1, ORA),
            _f("S5", "Cinque", "F", 2, ORA + 20 * MIN),
            _f("S9", "Nove", "A", 3, ORA + 60 * MIN),
        ]
    )
    await m._esegui(VERIFICA, str(tid))
    fonti = _fonti(m.conn)
    assert fonti["S5"] == "itinerario"  # fermata intermedia mai vista prima
    assert fonti["S9"] == "tabellone"  # gia' censita: la prima scoperta resta


def test_la_stazione_da_tabellone_poi_trovata_in_elenco_accumula_le_fonti(tmp_path):
    conn = storage.connect(tmp_path / "e.db")
    storage.registra_stop_se_nuovo(conn, "S7", None, "tabellone")
    assert conn.execute("SELECT stop_lat FROM stops").fetchone()[0] is None  # niente coordinate
    storage.upsert_stop(conn, "S7", "SETTE", 45.0, 9.0, regione_codice=1)  # arriva elencoStazioni
    r = conn.execute("SELECT fonte, stop_name, stop_lat FROM stops").fetchone()
    assert (r["fonte"], r["stop_name"], r["stop_lat"]) == ("tabellone+viaggiatreno", "SETTE", 45.0)
    storage.upsert_stop(
        conn, "S7", "SETTE", 45.0, 9.0, regione_codice=1
    )  # di nuovo: nessun duplicato
    assert conn.execute("SELECT fonte FROM stops").fetchone()[0] == "tabellone+viaggiatreno"


def test_le_fonti_non_si_confondono_per_prefisso(tmp_path):
    conn = storage.connect(tmp_path / "e.db")
    storage.upsert_stop(conn, "S1", "X", 1.0, 2.0, fonte="gtfs_trenord")
    storage.upsert_stop(
        conn, "S1", "X", 1.0, 2.0, fonte="trenord"
    )  # contenuta nel nome, ma diversa
    assert conn.execute("SELECT fonte FROM stops").fetchone()[0] == "gtfs_trenord+trenord"


def test_il_comando_run_non_esiste_piu():
    from viaggiatreno_crawler.__main__ import _parser

    with pytest.raises(SystemExit):
        _parser().parse_args(["run"])


# ============================================================ caricamento una tantum delle stazioni


def _stazione_api(codice, nome, reg, lat=45.0, lon=9.0):
    return SimpleNamespace(
        codiceStazione=codice,
        localita=SimpleNamespace(nomeLungo=nome),
        lat=lat,
        lon=lon,
        codReg=reg,
        nomeCitta=nome.title(),
    )


class ClientElenco:
    def __init__(self, per_regione, falliscono=()):
        self.per_regione = per_regione
        self.falliscono = set(falliscono)
        self.chiesti: list[int] = []

    async def elenco_stazioni(self, cod):
        self.chiesti.append(cod)
        if cod in self.falliscono:
            raise RuntimeError("403")
        return self.per_regione.get(cod, [])


async def test_carica_stazioni_di_default_chiede_le_regioni_1_22(tmp_path):
    from viaggiatreno_crawler.poller import carica_stazioni

    conn = storage.connect(tmp_path / "s.db")
    c = ClientElenco(
        {1: [_stazione_api("S1", "UNO", 1)], 14: [_stazione_api("S14", "PALERMO", 14)]}
    )
    esito = await carica_stazioni(conn, cast(ViaggiaTrenoClient, c))
    assert c.chiesti == list(range(1, 23))  # niente regione 0 ("solo principali")
    assert esito[1] == 1 and esito[14] == 1 and esito[5] == 0
    r = dict(conn.execute("SELECT stop_id, regione_codice FROM stops").fetchall())
    assert r == {"S1": 1, "S14": 14}
    assert conn.execute("SELECT COUNT(*) FROM regioni").fetchone()[0] >= 22


async def test_una_regione_che_fallisce_non_ferma_le_altre(tmp_path):
    from viaggiatreno_crawler.poller import carica_stazioni

    conn = storage.connect(tmp_path / "s.db")
    c = ClientElenco(
        {1: [_stazione_api("S1", "UNO", 1)], 3: [_stazione_api("S3", "TRE", 3)]}, falliscono={2}
    )
    esito = await carica_stazioni(conn, cast(ViaggiaTrenoClient, c), [1, 2, 3])
    assert esito[1] == 1 and esito[3] == 1
    assert isinstance(esito[2], str) and "403" in esito[2]
    assert {r[0] for r in conn.execute("SELECT stop_id FROM stops")} == {"S1", "S3"}


async def test_carica_stazioni_aggiorna_quelle_note_e_accumula_la_fonte(tmp_path):
    from viaggiatreno_crawler.poller import carica_stazioni

    conn = storage.connect(tmp_path / "s.db")
    storage.registra_stop_se_nuovo(conn, "S1", None, "itinerario")  # nota solo da un itinerario
    c = ClientElenco({1: [_stazione_api("S1", "UNO", 1, lat=45.5)]})
    await carica_stazioni(conn, cast(ViaggiaTrenoClient, c), [1])
    r = conn.execute("SELECT stop_name, stop_lat, regione_codice, fonte FROM stops").fetchone()
    assert (r[0], r[1], r[2], r[3]) == ("UNO", 45.5, 1, "itinerario+viaggiatreno")
    assert conn.execute("SELECT COUNT(*) FROM stops").fetchone()[0] == 1


async def test_carica_stazioni_non_blocca_un_writer_concorrente(tmp_path):
    """Il goal si puo' lanciare a crawler acceso: scrive a pezzi (un commit per regione)."""
    import sqlite3

    from viaggiatreno_crawler.poller import carica_stazioni

    percorso = tmp_path / "s.db"
    conn = storage.connect(percorso)
    altro = storage.connect(percorso)  # il "crawler" in esecuzione

    class ClientConScritturaIntermedia(ClientElenco):
        async def elenco_stazioni(self, cod):
            out = await super().elenco_stazioni(cod)
            altro.execute(
                "INSERT INTO crawler_stato (chiave, valore) VALUES (?, '1')", (f"k{cod}",)
            )
            altro.commit()  # scrive tra una regione e l'altra: non deve trovare il DB bloccato
            return out

    c = ClientConScritturaIntermedia(
        {r: [_stazione_api(f"S{r}", f"R{r}", r)] for r in range(1, 23)}
    )
    try:
        await carica_stazioni(conn, cast(ViaggiaTrenoClient, c))
    except sqlite3.OperationalError as exc:  # pragma: no cover
        pytest.fail(f"writer concorrente bloccato: {exc}")
    assert conn.execute("SELECT COUNT(*) FROM stops").fetchone()[0] == 22
    assert (
        conn.execute("SELECT COUNT(*) FROM crawler_stato WHERE chiave LIKE 'k%'").fetchone()[0]
        == 22
    )


def test_cli_stazioni_default_e_regioni_ripetibili():
    from viaggiatreno_crawler.__main__ import _parser

    a = _parser().parse_args(["stazioni"])
    assert (a.db_path, a.regione, a.richieste_al_secondo) == ("data/eventi.db", None, 1.0)
    b = _parser().parse_args(["stazioni", "--regione", "1", "--regione", "5"])
    assert b.regione == [1, 5]


# ============================================================ cod_destinazione dalla verifica


async def test_la_verifica_scrive_cod_destinazione_dall_andamento(tmp_path):
    """Prima la verifica riscriveva il valore vecchio (NULL per i treni dei tabelloni)."""
    m, c, _ = _motore(tmp_path)
    tid = _treno_in_coda(m, c)
    assert (
        m.conn.execute("SELECT cod_destinazione FROM treni WHERE id=?", (tid,)).fetchone()[0]
        is None
    )
    c.stati[10] = _status_completo(ritardo=0)
    await m._esegui(VERIFICA, str(tid))
    assert (
        m.conn.execute("SELECT cod_destinazione FROM treni WHERE id=?", (tid,)).fetchone()[0]
        == "S9"
    )


async def test_la_verifica_di_un_treno_parzialmente_soppresso_usa_la_destinazione_effettiva(
    tmp_path,
):
    m, c, _ = _motore(tmp_path)
    tid = _treno_in_coda(m, c)
    c.stati[10] = _status(
        [
            _f("S1", "Uno", "P", 1, ORA, att=1),
            _f("S5", "Cinque", "A", 2, ORA + 20 * MIN, att=0),
            _f("S9", "Nove", "", 3, ORA + 40 * MIN, att=3),  # soppressa
        ],
        tipoTreno="PP",
    )
    await m._esegui(VERIFICA, str(tid))
    assert (
        m.conn.execute("SELECT cod_destinazione FROM treni WHERE id=?", (tid,)).fetchone()[0]
        == "S5"
    )
    cap = dict(m.conn.execute("SELECT stop_id, e_destinazione FROM stops").fetchall())
    assert cap["S5"] == 1 and cap.get("S9", 0) == 0  # S9 non diventa capolinea per una soppressione


async def test_la_verifica_non_perde_il_codice_noto_se_l_api_non_lo_da(tmp_path):
    m, c, _ = _motore(tmp_path)
    tid = _treno_in_coda(m, c)
    m.conn.execute("UPDATE treni SET cod_destinazione = 'S9' WHERE id = ?", (tid,))
    m.conn.commit()
    c.stati[10] = _status(
        [_f("S1", "Uno", "P", 1, ORA, att=0)]
    )  # una sola fermata: nessun collegamento
    await m._esegui(VERIFICA, str(tid))
    assert (
        m.conn.execute("SELECT cod_destinazione FROM treni WHERE id=?", (tid,)).fetchone()[0]
        == "S9"
    )
