# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Le pagine generate: contenuto, escape, link relativi e casi limite."""

import json
import os
import re
import sys

import pytest
from test_modello import Db
from viaggiatreno_sito.__main__ import main
from viaggiatreno_sito.modello import costruisci_modello
from viaggiatreno_sito.render import render_sito


@pytest.fixture
def db(tmp_path):
    return Db(tmp_path)


def _sito(db, tmp_path, **kw):
    out = tmp_path / "sito"
    modello = costruisci_modello(db.conn)
    return render_sito(modello, out, **kw), out


def _pagina(out, codice):
    return (out / "stazioni" / f"{codice}.html").read_text(encoding="utf-8")


def test_una_pagina_per_stazione_anche_senza_treni(db, tmp_path):
    db.treno(["A", "B", "C"])
    db.stazione("Z", "ZETA")
    esito, out = _sito(db, tmp_path)
    assert esito.n_stazioni == 4
    assert {p.name for p in (out / "stazioni").iterdir()} == {f"{c}.html" for c in "ABCZ"}
    z = _pagina(out, "Z")
    assert "no trains observed" in z and "Lines (" not in z and "Nearby stations" not in z


def test_la_pagina_mostra_ruolo_linee_binari_e_vicini(db, tmp_path):
    db.treno(["A", "B", "C"], binari={"B": "4"})
    db.treno(["B", "C"])
    _, out = _sito(db, tmp_path)
    b = _pagina(out, "B")
    assert (
        '<span class="badge">terminus</span>' in b
        and '<span class="badge">through station</span>' in b
    )
    assert "Lines (2)" in b and "A - C" in b and "B - C" in b
    assert "<h2>Platforms</h2>" in b and '<span class="chip binario">4</span>' in b
    assert 'href="A.html"' in b and 'href="C.html"' in b  # vicini cliccabili


def test_i_nomi_sono_escapati(db, tmp_path):
    db.treno(["A", "B"])
    db.conn.execute(
        "UPDATE stops SET stop_name = ? WHERE stop_id = 'A'", ("<script>x()</script> & L'Aquila",)
    )
    db.conn.commit()
    _, out = _sito(db, tmp_path)
    for pagina in (
        _pagina(out, "A"),
        _pagina(out, "B"),
        (out / "index.html").read_text(encoding="utf-8"),
    ):
        assert "<script>x()" not in pagina.replace("<script>\nconst campo", "")
    assert "&lt;script&gt;x()&lt;/script&gt; &amp; L&#39;Aquila" in _pagina(out, "A")


def test_i_link_sono_relativi_e_non_rotti(db, tmp_path):
    db.treno(["A", "B", "C"])
    _, out = _sito(db, tmp_path)
    for f in out.rglob("*.html"):
        for h in re.findall(r'href="([^"#?]+)"', f.read_text(encoding="utf-8")):
            if h.startswith("http"):
                continue
            assert not h.startswith("/"), (f.name, h)
            assert os.path.exists(os.path.normpath(os.path.join(f.parent, h))), (f.name, h)


def test_con_solo_i_link_a_stazioni_assenti_non_sono_link(db, tmp_path):
    db.treno(["A", "B", "C"])
    _, out = _sito(db, tmp_path, solo={"B"})
    b = _pagina(out, "B")
    assert 'href="A.html"' not in b and 'href="C.html"' not in b  # non esistono: niente link rotti
    assert ">A<" in b or "A</td>" in b  # ma il nome resta visibile
    assert [p.name for p in (out / "stazioni").iterdir()] == ["B.html"]


def test_il_tipo_di_giorno_senza_dati_lo_dice(db, tmp_path):
    db.treno(["A", "B"])
    _, out = _sito(db, tmp_path)
    a = _pagina(out, "A")
    assert "Weekday (Mon–Fri)" in a and "Saturday" in a and "Sunday and holidays" in a
    assert a.count("No data for this day type") == 2


def test_il_grafico_orario_ha_24_barre_e_la_barra_piu_alta_e_il_100(db, tmp_path):
    db.treno(["A", "B"], ora=8)
    _, out = _sito(db, tmp_path)
    barre = re.findall(r'<i(?: class="picco")? style="height:(\d+)%"', _pagina(out, "A"))
    assert len(barre) == 24 and barre[8] == "100" and barre.count("0") == 23


def test_senza_nessun_treno_le_barre_non_dividono_per_zero(db, tmp_path):
    db.stazione("Z", "ZETA")
    _, out = _sito(db, tmp_path)
    assert "ZETA" in _pagina(out, "Z")


def test_l_indice_raggruppa_per_regione_e_il_json_ha_le_stazioni(db, tmp_path):
    db.treno(["A", "B"])
    _, out = _sito(db, tmp_path)
    idx = (out / "index.html").read_text(encoding="utf-8")
    assert "2 stations (2 with observed trains)" in idx and 'href="stazioni/A.html"' in idx
    dati = json.loads((out / "dati" / "stazioni.json").read_text(encoding="utf-8"))
    assert [r["codice"] for r in dati] == ["A", "B"] and dati[0]["capolinea"] is True


def test_riscrivere_il_sito_e_idempotente(db, tmp_path):
    db.treno(["A", "B", "C"])
    _, out = _sito(db, tmp_path)
    prima = {p.name: p.read_bytes() for p in out.rglob("*.html")}
    _sito(db, tmp_path)
    assert {p.name: p.read_bytes() for p in out.rglob("*.html")} == prima


def test_la_cli_genera_il_sito_e_non_modifica_il_db(db, tmp_path, capsys, monkeypatch):
    db.treno(["A", "B", "C"])
    db.conn.commit()
    db.conn.close()
    path = tmp_path / "e.db"
    prima = path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["viaggiatreno-sito"])
    main(["--db-path", str(path), "--out", str(tmp_path / "o"), "--stazione", "B"])
    assert (tmp_path / "o" / "stazioni" / "B.html").exists()
    assert "1 stazioni (1 con treni)" in capsys.readouterr().out
    assert path.read_bytes() == prima


def test_la_cli_segnala_db_e_stazioni_inesistenti(db, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        main(["--db-path", str(tmp_path / "no.db")])
    assert e.value.code == 2 and "DB non trovato" in capsys.readouterr().err
    assert not (tmp_path / "no.db").exists()
    db.treno(["A", "B"])
    db.conn.close()
    with pytest.raises(SystemExit) as e:
        main(
            [
                "--db-path",
                str(tmp_path / "e.db"),
                "--out",
                str(tmp_path / "o"),
                "--stazione",
                "NOPE",
            ]
        )
    assert e.value.code == 2 and "NOPE" in capsys.readouterr().err


def test_le_barre_sono_proporzionali_al_massimo(db, tmp_path):
    for _ in range(4):
        db.treno(["A", "B"], ora=8)
    for _ in range(2):
        db.treno(["A", "B"], ora=9)
    _, out = _sito(db, tmp_path)
    barre = [
        int(x)
        for x in re.findall(r'<i(?: class="picco")? style="height:(\d+)%"', _pagina(out, "A"))
    ]
    assert barre[8] == 100 and barre[9] == 50 and sum(barre) == 150


def test_l_avviso_sui_giorni_parziali_compare_solo_se_ce_ne_sono(db, tmp_path):
    for _ in range(10):
        db.treno(["A", "B"], giorno=(2026, 11, 11))
    _, out = _sito(db, tmp_path)
    assert "Days with incomplete data" not in _pagina(out, "A")
    db.treno(["A", "B"], giorno=(2026, 11, 12))  # 1 corsa su 10: parziale
    _, out = _sito(db, tmp_path)
    assert "Days with incomplete data, excluded from the averages: 2026-11-12" in _pagina(out, "A")


def test_la_mappa_incorpora_stazioni_e_archi(db, tmp_path):
    db.treno(["A", "B"])
    _, out = _sito(db, tmp_path)
    m = (out / "mappa.html").read_text(encoding="utf-8")
    assert "leaflet" in m and '"s":' in m and '"t":' in m
