# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Le pagine markdown per un sito Hugo esistente."""

import pytest
from test_modello import Db
from viaggiatreno_sito.hugo import MARCATORE, render_hugo
from viaggiatreno_sito.modello import costruisci_modello


@pytest.fixture
def db(tmp_path):
    return Db(tmp_path)


def _scrivi(db, tmp_path, **kw):
    content = tmp_path / "content"
    return render_hugo(costruisci_modello(db.conn), content, **kw), content / "trains"


def test_una_pagina_per_stazione_con_url_stabile_e_solo_markdown(db, tmp_path):
    db.treno(["A", "B", "C"])
    esito, sez = _scrivi(db, tmp_path)
    assert esito.n_stazioni == 3 and (sez / "_index.md").exists() and (sez / MARCATORE).exists()
    pagine = [p for p in sez.rglob("*.md") if p.name != "_index.md"]
    assert len(pagine) == 3
    b = next(p for p in pagine if p.name == "b.md").read_text(encoding="utf-8")
    assert b.startswith("---\n") and 'url: "/trains/stations/b/"' in b
    assert "## Lines" in b and "[" in b and "<" not in b.split("---\n", 2)[2]
    assert not list(sez.rglob("*.html")) and not list(sez.rglob("*.css"))


def test_i_link_tra_stazioni_puntano_alle_pagine_esistenti(db, tmp_path):
    db.treno(["A", "B", "C"])
    _, sez = _scrivi(db, tmp_path, solo={"A", "B"})
    b = next(sez.rglob("b.md")).read_text(encoding="utf-8")
    assert "(/trains/stations/a/)" in b and "(/trains/stations/c/)" not in b


def test_i_nomi_sono_escapati(db, tmp_path):
    db.treno(["A", "B"])
    db.conn.execute(
        "UPDATE stops SET stop_name = ? WHERE stop_id = 'A'", ("<b>x</b> | *y* L'Aquila",)
    )
    db.conn.commit()
    _, sez = _scrivi(db, tmp_path)
    corpo = next(sez.rglob("b.md")).read_text(encoding="utf-8")
    assert "<b>" not in corpo.split("---\n", 2)[2] and "\\|" in corpo


def test_rigenerare_sostituisce_e_non_tocca_cartelle_altrui(db, tmp_path):
    db.treno(["A", "B"])
    _, sez = _scrivi(db, tmp_path)
    (sez / "vecchia.md").write_text("x")
    _scrivi(db, tmp_path)
    assert not (sez / "vecchia.md").exists()

    altrui = tmp_path / "content2" / "trains"
    altrui.mkdir(parents=True)
    (altrui / "mio.md").write_text("mio")
    with pytest.raises(SystemExit):
        render_hugo(costruisci_modello(db.conn), tmp_path / "content2")
    assert (altrui / "mio.md").read_text() == "mio"
