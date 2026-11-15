# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Registro degli errori del crawler e comando `errori` (`make errors`)."""

import asyncio

import pytest
from test_eventi import CENSISCI, ORA, VERIFICA, _motore, _stazione
from viaggiatreno_crawler import storage
from viaggiatreno_crawler.__main__ import main, mostra_errori
from viaggiatreno_crawler.scheduler import Pianificatore


async def test_un_tabellone_fallito_viene_registrato_con_il_messaggio(tmp_path):
    m, c, _ = _motore(tmp_path)
    _stazione(m, "S1")
    c.falliscono.add("S1")
    await m._esegui(CENSISCI, "S1")
    m.conn.commit()
    (r,) = storage.ultimi_errori(m.conn, 10)
    assert (r["ts"], r["fonte"], r["chiave"]) == (ORA, "tabellone partenze", "S1")
    assert r["messaggio"] == "RuntimeError: giu'"


async def test_un_lavoro_che_solleva_viene_registrato_dal_motore(tmp_path):
    """Percorso reale: il Motore passa `su_errore` al Pianificatore, che lo chiama nel worker."""
    m, _c, _ = _motore(tmp_path)

    async def rompe(tipo, chiave):
        raise ValueError("scoppiato")

    m.pian._esegui = rompe
    m.pian.pianifica(VERIFICA, "7", 0)
    run = asyncio.create_task(m.pian.esegui())
    try:
        for _ in range(200):
            await asyncio.sleep(0.01)
            if storage.ultimi_errori(m.conn, 1):
                break
    finally:
        run.cancel()
    (r,) = storage.ultimi_errori(m.conn, 5)[:1]
    assert (r["fonte"], r["chiave"], r["messaggio"]) == (VERIFICA, "7", "ValueError: scoppiato")


async def test_un_errore_nel_registrare_non_ferma_il_worker():
    chiamate: list[str] = []

    async def esegui(tipo, chiave):
        chiamate.append(chiave)
        if chiave == "rotto":
            raise RuntimeError("boom")

    def registra(tipo, chiave, exc):
        raise OSError("disco pieno")

    p = Pianificatore(esegui, workers=1, ritardo_errore_ms=10_000_000, su_errore=registra)
    p.pianifica("a", "rotto", 0)
    p.pianifica("a", "ok", 0)
    run = asyncio.create_task(p.esegui())
    try:
        for _ in range(200):
            await asyncio.sleep(0.01)
            if "ok" in chiamate:
                break
    finally:
        run.cancel()
    assert "ok" in chiamate


def test_gli_ultimi_errori_sono_dal_piu_recente_e_limitati(tmp_path):
    conn = storage.connect(tmp_path / "e.db")
    for i in range(5):
        storage.registra_errore(conn, 1000 + i, "x", str(i), ValueError(f"e{i}"))
    conn.commit()
    assert [r["chiave"] for r in storage.ultimi_errori(conn, 3)] == ["4", "3", "2"]
    assert storage.ultimi_errori(conn, 0) == []


def test_il_messaggio_lungo_viene_troncato(tmp_path):
    conn = storage.connect(tmp_path / "e.db")
    storage.registra_errore(conn, 1, "x", None, ValueError("a" * 5000))
    assert len(storage.ultimi_errori(conn, 1)[0]["messaggio"]) == 500


def test_il_comando_stampa_riepilogo_e_righe(tmp_path, capsys):
    db = tmp_path / "e.db"
    conn = storage.connect(db)
    storage.registra_errore(conn, ORA, "tabellone arrivi", "S1", TimeoutError("lento"))
    storage.registra_errore(conn, ORA + 60_000, "verifica_treno", "9", ValueError("rotto"))
    storage.registra_errore(conn, ORA + 120_000, "verifica_treno", "10", ValueError("ancora"))
    conn.commit()
    conn.close()
    assert mostra_errori(str(db), 2) == 0
    out = capsys.readouterr().out
    assert "verifica_treno: 2" in out and "tabellone arrivi: 1" in out
    assert "Ultimi 2 errori" in out
    assert out.index("ancora") < out.index("rotto")  # dal piu' recente
    assert "lento" not in out  # il terzo non e' tra gli ultimi 2
    assert "2027-01-15 09:02:00" in out  # ORA = 08:00 UTC = 09:00 italiane, +2 minuti


def test_senza_errori_o_senza_tabella_non_fallisce(tmp_path, capsys):
    db = tmp_path / "e.db"
    storage.connect(db).close()
    assert mostra_errori(str(db), 5) == 0
    assert "Nessun errore" in capsys.readouterr().out
    import sqlite3

    vecchio = tmp_path / "vecchio.db"
    sqlite3.connect(vecchio).close()
    assert mostra_errori(str(vecchio), 5) == 0
    assert "Nessuna tabella" in capsys.readouterr().out


def test_db_inesistente_da_errore_e_non_lo_crea(tmp_path, capsys):
    assert mostra_errori(str(tmp_path / "no.db"), 5) == 2
    assert not (tmp_path / "no.db").exists()
    assert "DB non trovato" in capsys.readouterr().err


def test_il_comando_non_scrive_sul_db(tmp_path):
    db = tmp_path / "e.db"
    conn = storage.connect(db)
    storage.registra_errore(conn, ORA, "x", None, ValueError("a"))
    conn.commit()
    conn.close()
    prima = db.read_bytes()
    mostra_errori(str(db), 5)
    assert db.read_bytes() == prima


def test_la_cli_ha_il_sottocomando(tmp_path, capsys):
    db = tmp_path / "e.db"
    storage.connect(db).close()
    with pytest.raises(SystemExit) as e:
        main(["errori", "--db-path", str(db), "--ultimi", "3"])
    assert e.value.code == 0
