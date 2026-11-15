# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regione dalle stazioni vicine e coordinate non valide."""

from viaggiatreno_sito.geo import coordinate_valide, regioni_geografiche


def test_coordinate_fuori_dall_italia_non_sono_valide():
    assert coordinate_valide(45.5, 9.2)
    assert not coordinate_valide(-9.0, 4.5) and not coordinate_valide(None, 9.0)


def test_una_stazione_con_regione_incoerente_prende_quella_dei_vicini():
    st = {f"L{i}": (41.9 + i * 0.01, 12.5, 5) for i in range(8)}
    st["X"] = (41.95, 12.5, 19)  # in mezzo a Roma, ma con il codice dell'Abruzzo
    assert regioni_geografiche(st)["X"] == 5


def test_una_stazione_di_confine_non_viene_spostata():
    st = {f"L{i}": (41.9 + i * 0.01, 12.5, 5) for i in range(4)}
    st |= {f"M{i}": (42.0 + i * 0.01, 12.5, 19) for i in range(4)}
    st["X"] = (41.96, 12.5, 19)
    assert regioni_geografiche(st)["X"] == 19


def test_senza_coordinate_resta_il_codice_originale():
    assert regioni_geografiche({"A": (None, None, 7), "B": (0.0, 0.0, 3)}) == {"A": 7, "B": 3}
