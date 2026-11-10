# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fixtures e utility di test per ViaggiaTreno MCP."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from viaggiatreno import ViaggiaTrenoClient
from viaggiatreno_mcp.server import create_server

SAMPLES_DIR = Path(__file__).parent.parent / "samples"


def load_sample_content(name: str) -> str:
    """Carica il corpo effettivo di un file di test in samples/, ignorando le righe di commento."""
    matches = list(SAMPLES_DIR.glob(f"{name}.*"))
    if not matches:
        raise FileNotFoundError(f"Nessun file trovato per sample {name} in {SAMPLES_DIR}")
    lines = matches[0].read_text(encoding="utf-8").splitlines()
    body_lines = [l for l in lines if not l.startswith("#")]
    return "\n".join(body_lines).strip()


def load_sample_json(name: str) -> Any:
    """Carica e deserializza in JSON un file di test in samples/."""
    return json.loads(load_sample_content(name))


def make_mock_transport() -> httpx.MockTransport:
    """Crea un MockTransport httpx che risponde a tutti gli endpoint con i file da samples/."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "autocompletaStazioneNTS" in path:
            return httpx.Response(200, text=load_sample_content("autocompletaStazioneNTS"))
        elif "autocompletaStazioneImpostaViaggio" in path:
            return httpx.Response(
                200, text=load_sample_content("autocompletaStazioneImpostaViaggio")
            )
        elif "autocompletaStazione" in path:
            return httpx.Response(200, text=load_sample_content("autocompletaStazione"))
        elif "cercaStazione" in path:
            return httpx.Response(200, text=load_sample_content("cercaStazione"))
        elif "regione" in path:
            return httpx.Response(200, text=load_sample_content("regione"))
        elif "dettaglioStazione" in path:
            return httpx.Response(200, text=load_sample_content("dettaglioStazione"))
        elif "elencoStazioni" in path:
            return httpx.Response(200, text=load_sample_content("elencoStazioni"))
        elif "partenze" in path:
            return httpx.Response(200, text=load_sample_content("partenze"))
        elif "dettaglioViaggio" in path:
            return httpx.Response(200, text=load_sample_content("dettaglioViaggio"))
        elif "arrivi" in path:
            return httpx.Response(200, text=load_sample_content("arrivi"))
        elif "cercaNumeroTrenoTrenoAutocomplete" in path:
            return httpx.Response(
                200, text=load_sample_content("cercaNumeroTrenoTrenoAutocomplete")
            )
        elif "cercaNumeroTreno" in path:
            return httpx.Response(200, text=load_sample_content("cercaNumeroTreno"))
        elif "andamentoTreno" in path:
            return httpx.Response(200, text=load_sample_content("andamentoTreno"))
        elif "tratteCanvas" in path:
            return httpx.Response(200, text=load_sample_content("tratteCanvas"))
        elif "elencoTratte" in path:
            return httpx.Response(200, text=load_sample_content("elencoTratte"))
        elif "dettagliTratta" in path:
            return httpx.Response(200, text=load_sample_content("dettagliTratta"))
        elif "statistiche" in path:
            return httpx.Response(200, text=load_sample_content("statistiche"))
        elif "datimeteo" in path:
            # dati meteo sample è {}
            return httpx.Response(200, text=load_sample_content("datimeteo"))
        elif "infomobilitaRSSBox" in path:
            return httpx.Response(200, text=load_sample_content("infomobilitaRSSBox"))
        elif "infomobilitaRSS" in path:
            return httpx.Response(200, text=load_sample_content("infomobilitaRSS"))
        elif "infomobilitaTicker" in path:
            return httpx.Response(200, text=load_sample_content("infomobilitaTicker"))
        elif "language" in path:
            return httpx.Response(200, text=load_sample_content("language"))
        return httpx.Response(404, text="Not Found")

    return httpx.MockTransport(handler)


@pytest.fixture
def mock_client() -> ViaggiaTrenoClient:
    """Fixture che fornisce un ViaggiaTrenoClient collegato ai dati mock di samples/."""
    transport = make_mock_transport()
    async_client = httpx.AsyncClient(transport=transport)
    return ViaggiaTrenoClient(client=async_client)


@pytest.fixture
def mock_server(mock_client: ViaggiaTrenoClient):
    """Fixture che fornisce un server FastMCP collegato al mock_client."""
    return create_server(client=mock_client)
