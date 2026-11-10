# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test unitari per i parser di testo e HTML di ViaggiaTreno."""

from viaggiatreno import (
    parse_infomobilita_rss,
    parse_infomobilita_rss_box,
    parse_infomobilita_ticker,
    parse_station_autocomplete,
    parse_station_nts_autocomplete,
    parse_train_autocomplete,
)

from tests.conftest import load_sample_content


def test_parse_station_autocomplete():
    content = load_sample_content("autocompletaStazione")
    items = parse_station_autocomplete(content)
    assert len(items) == 6
    assert items[0].nome == "FIRENZE SANTA MARIA NOVELLA"
    assert items[0].codice == "S06421"
    assert items[1].nome == "FIRENZE CAMPO MARTE"
    assert items[1].codice == "S06900"


def test_parse_station_autocomplete_imposta_viaggio():
    content = load_sample_content("autocompletaStazioneImpostaViaggio")
    items = parse_station_autocomplete(content)
    assert len(items) == 6
    assert items[0].codice == "S06421"


def test_parse_station_nts_autocomplete():
    content = load_sample_content("autocompletaStazioneNTS")
    items = parse_station_nts_autocomplete(content)
    assert len(items) == 12
    assert items[0].nome == "FIRENZE BINARIO S.MARCO VECCHIO"
    assert items[0].codice_nts == "830006950"


def test_parse_train_autocomplete():
    content = load_sample_content("cercaNumeroTrenoTrenoAutocomplete")
    items = parse_train_autocomplete(content)
    assert len(items) == 1
    assert items[0].numero_treno == 9611
    assert items[0].stazione_origine == "TORINO PORTA NUOVA"
    assert items[0].codice_stazione_origine == "S00219"
    assert items[0].millis_data_partenza == 1791064800000
    assert items[0].data == "04/10/26"


def test_parse_train_autocomplete_legacy_format():
    legacy_text = "2107 - TORINO PORTA NUOVA|2107-S00219-1678230000000\n"
    items = parse_train_autocomplete(legacy_text)
    assert len(items) == 1
    assert items[0].numero_treno == 2107
    assert items[0].stazione_origine == "TORINO PORTA NUOVA"
    assert items[0].codice_stazione_origine == "S00219"
    assert items[0].millis_data_partenza == 1678230000000
    assert items[0].data is None


def test_parse_infomobilita_rss():
    content = load_sample_content("infomobilitaRSS")
    news = parse_infomobilita_rss(content)
    assert len(news) == 4
    # Prima notizia in evidenza
    assert news[0].titolo == "CIRCOLAZIONE REGOLARE"
    assert news[0].inEvidenza is True
    assert "circolazione si svolge regolarmente" in news[0].testo
    assert news[0].data == "04.10.2026"
    # Seconda notizia con link a treno
    assert news[1].titolo == "INFOTRENI INTERCITY - EUROCITY"
    assert news[1].inEvidenza is False
    assert news[1].link_treno is not None
    assert news[1].link_treno["treno"] == "1963"
    assert news[1].link_treno["origine"] == "S01700"


def test_parse_infomobilita_rss_box():
    content = load_sample_content("infomobilitaRSSBox")
    headlines = parse_infomobilita_rss_box(content)
    assert len(headlines) == 4
    assert headlines[0].titolo == "CIRCOLAZIONE REGOLARE"
    assert headlines[0].inEvidenza is True
    assert headlines[1].titolo == "INFOTRENI INTERCITY - EUROCITY"
    assert headlines[1].inEvidenza is False


def test_parse_infomobilita_ticker():
    content = load_sample_content("infomobilitaTicker")
    tickers = parse_infomobilita_ticker(content)
    assert len(tickers) == 1
    assert tickers[0] == "CIRCOLAZIONE REGOLARE"
