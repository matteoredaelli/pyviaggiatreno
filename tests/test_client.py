# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test unitari per ViaggiaTrenoClient."""

import pytest
from viaggiatreno import ViaggiaTrenoClient


@pytest.mark.asyncio
async def test_client_stazioni(mock_client: ViaggiaTrenoClient):
    # Autocompleta
    res = await mock_client.autocompleta_stazione("firenze")
    assert len(res) == 6
    assert res[0].codice == "S06421"

    # Cerca stazione
    cerca = await mock_client.cerca_stazione("apice")
    assert len(cerca) == 1
    assert cerca[0].id == "S09314"

    # Regione
    reg = await mock_client.regione("S01700")
    assert reg == 1

    # Dettaglio stazione
    dett = await mock_client.dettaglio_stazione("S01700", 1)
    assert dett is not None
    assert dett.codiceStazione == "S01700"
    assert dett.lat == 45.486347

    # Elenco stazioni
    elenco = await mock_client.elenco_stazioni(1)
    assert len(elenco) == 345


@pytest.mark.asyncio
async def test_client_partenze_arrivi(mock_client: ViaggiaTrenoClient):
    partenze = await mock_client.partenze("S01700")
    assert len(partenze) == 33
    assert partenze[0].numeroTreno == 9611

    arrivi = await mock_client.arrivi("S01700")
    assert len(arrivi) == 32
    assert arrivi[0].numeroTreno == 2452


@pytest.mark.asyncio
async def test_client_treni(mock_client: ViaggiaTrenoClient):
    # Cerca numero treno in JSON
    treno = await mock_client.cerca_numero_treno(9611)
    assert treno is not None
    assert treno.codLocOrig == "S00219"

    # Andamento treno
    andamento = await mock_client.andamento_treno("S00219", 9611, 1791064800000)
    assert andamento is not None
    assert andamento.numeroTreno == 9611
    assert len(andamento.fermate) == 6

    # Tratte canvas
    canvas = await mock_client.tratte_canvas("S00219", 9611, 1791064800000)
    assert len(canvas) == 6


@pytest.mark.asyncio
async def test_client_tratte(mock_client: ViaggiaTrenoClient):
    tratte = await mock_client.elenco_tratte()
    assert len(tratte) == 135

    dettagli = await mock_client.dettagli_tratta(510, 511)
    assert len(dettagli) == 2


@pytest.mark.asyncio
async def test_client_servizio(mock_client: ViaggiaTrenoClient):
    stats = await mock_client.statistiche()
    assert stats is not None
    assert stats.treniCircolanti == 579

    meteo = await mock_client.datimeteo(1)
    assert meteo == {}

    news = await mock_client.infomobilita_rss(False)
    assert len(news) == 4

    headlines = await mock_client.infomobilita_rss_box(False)
    assert len(headlines) == 4

    ticker = await mock_client.infomobilita_ticker()
    assert len(ticker) == 1

    lang = await mock_client.language("en")
    assert len(lang) > 100
