"""Client asincrono per le API di ViaggiaTreno."""

import time
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from urllib.parse import quote

import httpx

from viaggiatreno.api.parsers import (
    parse_infomobilita_rss,
    parse_infomobilita_rss_box,
    parse_infomobilita_ticker,
    parse_station_autocomplete,
    parse_station_nts_autocomplete,
    parse_train_autocomplete,
)
from viaggiatreno.models.route import DettaglioTratta, TrattaSegment
from viaggiatreno.models.service import (
    InfomobilitaNews,
    InfomobilitaNewsHeadline,
    StationWeather,
    Statistics,
)
from viaggiatreno.models.station import (
    StationAutocompleteItem,
    StationDetail,
    StationNTSAutocompleteItem,
    StationSearchResult,
)
from viaggiatreno.models.train import (
    TrainAutocompleteItem,
    TrainBoardItem,
    TrainSearchResult,
    TrainStatus,
    TrattaCanvasItem,
)

DEFAULT_BASE_URL = "http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def format_viaggiatreno_datetime(dt: datetime | str | None = None) -> str:
    """Formatta la data/ora nel formato atteso dagli endpoint partenze/arrivi.

    Esempio formato ViaggiaTreno: Sun Oct 04 2026 08:12:27 GMT+0200 (URL-encoded).
    """
    if dt is None:
        now = datetime.now(UTC).astimezone()
        formatted = now.strftime("%a %b %d %Y %H:%M:%S GMT%z")
    elif isinstance(dt, datetime):
        formatted = dt.strftime("%a %b %d %Y %H:%M:%S GMT%z")
    else:
        # Se è già stringa
        formatted = dt

    return quote(formatted)


class ViaggiaTrenoClient:
    """Client asincrono per tutte le chiamate REST di ViaggiaTreno."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._external_client = client
        self._client: httpx.AsyncClient | None = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"User-Agent": DEFAULT_USER_AGENT},
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._external_client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        await self._get_client()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def _request(self, path: str) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        client = await self._get_client()
        response = await client.get(url)
        return response

    # -------------------------------------------------------------------------
    # STAZIONI
    # -------------------------------------------------------------------------

    async def autocompleta_stazione(self, prefisso: str) -> list[StationAutocompleteItem]:
        """Suggerimenti stazioni per prefisso (GET /autocompletaStazione/{prefisso})."""
        r = await self._request(f"autocompletaStazione/{quote(prefisso)}")
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        return parse_station_autocomplete(r.text)

    async def autocompleta_stazione_imposta_viaggio(
        self, prefisso: str
    ) -> list[StationAutocompleteItem]:
        """Suggerimenti stazioni per imposta viaggio (GET /autocompletaStazioneImpostaViaggio/{prefisso})."""
        r = await self._request(f"autocompletaStazioneImpostaViaggio/{quote(prefisso)}")
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        return parse_station_autocomplete(r.text)

    async def autocompleta_stazione_nts(self, prefisso: str) -> list[StationNTSAutocompleteItem]:
        """Suggerimenti stazioni e posti tecnici con codice NTS RICS (GET /autocompletaStazioneNTS/{prefisso})."""
        r = await self._request(f"autocompletaStazioneNTS/{quote(prefisso)}")
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        return parse_station_nts_autocomplete(r.text)

    async def cerca_stazione(self, prefisso: str) -> list[StationSearchResult]:
        """Ricerca stazioni con risposta JSON strutturata (GET /cercaStazione/{prefisso})."""
        r = await self._request(f"cercaStazione/{quote(prefisso)}")
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        data = r.json()
        return [StationSearchResult.model_validate(item) for item in data]

    async def regione(self, codice_stazione: str) -> int | None:
        """Codice regione numerico di una stazione (GET /regione/{codiceStazione})."""
        r = await self._request(f"regione/{quote(codice_stazione)}")
        if r.status_code == 204 or not r.text.strip():
            return None
        r.raise_for_status()
        try:
            return int(r.text.strip())
        except ValueError:
            return None

    async def dettaglio_stazione(
        self, codice_stazione: str, codice_regione: int
    ) -> StationDetail | None:
        """Dettagli e coordinate di una stazione (GET /dettaglioStazione/{codiceStazione}/{codiceRegione})."""
        r = await self._request(f"dettaglioStazione/{quote(codice_stazione)}/{codice_regione}")
        if r.status_code == 204 or not r.text.strip():
            return None
        r.raise_for_status()
        data = r.json()
        return StationDetail.model_validate(data)

    async def elenco_stazioni(self, codice_regione: int) -> list[StationDetail]:
        """Elenco completo stazioni di una regione (GET /elencoStazioni/{codiceRegione})."""
        r = await self._request(f"elencoStazioni/{codice_regione}")
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        data = r.json()
        return [StationDetail.model_validate(item) for item in data]

    # -------------------------------------------------------------------------
    # PARTENZE E ARRIVI
    # -------------------------------------------------------------------------

    async def partenze(
        self,
        codice_stazione: str,
        data_ora: datetime | str | None = None,
    ) -> list[TrainBoardItem]:
        """Tabellone partenze da una stazione (GET /partenze/{codiceStazione}/{dataOra})."""
        encoded_date = format_viaggiatreno_datetime(data_ora)
        r = await self._request(f"partenze/{quote(codice_stazione)}/{encoded_date}")
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        data = r.json()
        return [TrainBoardItem.model_validate(item) for item in data]

    async def arrivi(
        self,
        codice_stazione: str,
        data_ora: datetime | str | None = None,
    ) -> list[TrainBoardItem]:
        """Tabellone arrivi in una stazione (GET /arrivi/{codiceStazione}/{dataOra})."""
        encoded_date = format_viaggiatreno_datetime(data_ora)
        r = await self._request(f"arrivi/{quote(codice_stazione)}/{encoded_date}")
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        data = r.json()
        return [TrainBoardItem.model_validate(item) for item in data]

    async def dettaglio_viaggio(
        self,
        id_stazione_da: str,
        id_stazione_a: str,
    ) -> list[TrainBoardItem]:
        """Treni diretti (senza cambi) tra due stazioni nella giornata corrente.

        GET /dettaglioViaggio/{idStazioneDa}/{idStazioneA}

        Endpoint non documentato in nessuna delle fonti note ([DLT], [MB], [GT],
        [TM]), trovato nello script ufficiale del sito (``rest-jsapi``) e
        verificato dal vivo. Di fatto sostituisce il dismesso
        ``soluzioniViaggioNew`` (ora 404) per il solo caso dei treni diretti:
        non gestisce percorsi con interscambio.
        """
        r = await self._request(
            f"dettaglioViaggio/{quote(id_stazione_da)}/{quote(id_stazione_a)}"
        )
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        data = r.json()
        return [TrainBoardItem.model_validate(item) for item in data]

    # -------------------------------------------------------------------------
    # TRENI
    # -------------------------------------------------------------------------

    async def cerca_numero_treno_autocomplete(
        self, numero_treno: int | str
    ) -> list[TrainAutocompleteItem]:
        """Corse attive per un numero treno (GET /cercaNumeroTrenoTrenoAutocomplete/{numeroTreno})."""
        r = await self._request(f"cercaNumeroTrenoTrenoAutocomplete/{numero_treno}")
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        return parse_train_autocomplete(r.text)

    async def cerca_numero_treno(self, numero_treno: int | str) -> TrainSearchResult | None:
        """Identificativi corsa corrente per un treno in JSON (GET /cercaNumeroTreno/{numeroTreno})."""
        r = await self._request(f"cercaNumeroTreno/{numero_treno}")
        if r.status_code == 204 or not r.text.strip():
            return None
        r.raise_for_status()
        data = r.json()
        return TrainSearchResult.model_validate(data)

    async def andamento_treno(
        self,
        codice_stazione_origine: str,
        numero_treno: int | str,
        data_partenza: int | str,
    ) -> TrainStatus | None:
        """Stato dettagliato treno e fermate (GET /andamentoTreno/{codiceStazioneOrigine}/{numeroTreno}/{dataPartenza})."""
        r = await self._request(
            f"andamentoTreno/{quote(codice_stazione_origine)}/{numero_treno}/{data_partenza}"
        )
        if r.status_code == 204 or not r.text.strip():
            return None
        r.raise_for_status()
        data = r.json()
        return TrainStatus.model_validate(data)

    async def tratte_canvas(
        self,
        codice_stazione_origine: str,
        numero_treno: int | str,
        data_partenza: int | str,
    ) -> list[TrattaCanvasItem]:
        """Itinerario visuale ad albero (GET /tratteCanvas/{codiceStazioneOrigine}/{numeroTreno}/{dataPartenza})."""
        r = await self._request(
            f"tratteCanvas/{quote(codice_stazione_origine)}/{numero_treno}/{data_partenza}"
        )
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        data = r.json()
        return [TrattaCanvasItem.model_validate(item) for item in data]

    # -------------------------------------------------------------------------
    # TRATTE E RETE
    # -------------------------------------------------------------------------

    async def elenco_tratte(
        self,
        categorie: str = "ES*,IC,EXP,EC,EN,REG",
        id_regione: int = 0,
        zoomlevel: int = 6,
        timestamp: int | None = None,
    ) -> list[TrattaSegment]:
        """Segmenti della rete e occupazione da treni.

        GET /elencoTratte/{idRegione}/{zoomlevel}/{categorie}/{catAV}/{timestamp}

        Nomi dei parametri confermati dalla segnatura reale dell'endpoint (vedi
        VIAGGIATRENO.md). Note verificate dal vivo:

        - ``id_regione``: 0 = tutta Italia, 1-22 = singola regione (stesso
          codice di ``elenco_stazioni``/``regione``). Filtra i *segmenti* per
          posizione geografica, non i treni: un segmento di confine può
          restituire treni di lunga percorrenza estranei alla regione.
        - ``zoomlevel``: livello di zoom della mappa, non una finestra
          temporale. Fuori dal range 6-11 il conteggio dei segmenti
          ``occupata`` risulta sensibilmente più basso. Il default ``6`` è
          quello verificato come più completo.
        - ``catAV`` (quarto segmento del path) non è esposto come parametro:
          va lasciato sempre ``null``, qualsiasi altro valore numerico azzera
          silenziosamente tutti i flag ``occupata``.

        Gli ID ``trattaAB``/``trattaBA`` restituiti sono numerati **per
        regione**: vanno passati a :meth:`dettagli_tratta` insieme allo stesso
        ``id_regione`` usato qui, altrimenti si ottengono treni di un segmento
        fisicamente diverso senza nessun errore.
        """
        ts = timestamp if timestamp is not None else int(time.time() * 1000)
        r = await self._request(
            f"elencoTratte/{id_regione}/{zoomlevel}/{quote(categorie)}/null/{ts}"
        )
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        data = r.json()
        return [TrattaSegment.model_validate(item) for item in data]

    async def dettagli_tratta(
        self,
        tratta_ab: int,
        tratta_ba: int,
        categorie: str = "ES*,IC,EXP,EC,EN,REG",
        id_regione: int = 0,
    ) -> list[DettaglioTratta]:
        """Treni presenti su un segmento.

        GET /dettagliTratta/{idRegione}/{trattaAB}/{trattaBA}/{categorie}/{catAV}

        ``id_regione`` **deve essere lo stesso** usato nella chiamata a
        :meth:`elenco_tratte` che ha prodotto ``tratta_ab``/``tratta_ba``: gli
        ID non sono identificativi globali della rete ma sono numerati per
        regione. Usare un ``id_regione`` diverso restituisce (senza errore)
        i treni di un segmento fisicamente diverso, verificato dal vivo (es.
        ``trattaAB=10, trattaBA=92`` con regione 0 è Pisa-Grosseto, con
        regione 1 è Milano-Piacenza).
        """
        r = await self._request(
            f"dettagliTratta/{id_regione}/{tratta_ab}/{tratta_ba}/{quote(categorie)}/null"
        )
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        data = r.json()
        return [DettaglioTratta.model_validate(item) for item in data]

    # -------------------------------------------------------------------------
    # INFORMAZIONI DI SERVIZIO
    # -------------------------------------------------------------------------

    async def statistiche(self, timestamp: int | None = None) -> Statistics | None:
        """Statistiche treni circolanti e programmati (GET /statistiche/{timestamp})."""
        ts = timestamp if timestamp is not None else int(time.time() * 1000)
        r = await self._request(f"statistiche/{ts}")
        if r.status_code == 204 or not r.text.strip():
            return None
        r.raise_for_status()
        data = r.json()
        return Statistics.model_validate(data)

    async def datimeteo(self, codice_regione: int) -> dict[str, StationWeather]:
        """Previsioni meteo per stazioni di una regione (GET /datimeteo/{codiceRegione})."""
        r = await self._request(f"datimeteo/{codice_regione}")
        if r.status_code == 204 or not r.text.strip():
            return {}
        r.raise_for_status()
        data = r.json()
        results: dict[str, StationWeather] = {}
        for station_id, weather_dict in data.items():
            results[station_id] = StationWeather.model_validate(weather_dict)
        return results

    async def infomobilita_rss(self, is_info_lavori: bool = False) -> list[InfomobilitaNews]:
        """Notizie circolazione o lavori programmati (GET /infomobilitaRSS/{isInfoLavori})."""
        param = "true" if is_info_lavori else "false"
        r = await self._request(f"infomobilitaRSS/{param}")
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        return parse_infomobilita_rss(r.text)

    async def infomobilita_rss_box(
        self, is_info_lavori: bool = False
    ) -> list[InfomobilitaNewsHeadline]:
        """Titoli sintetici delle notizie di infomobilità (GET /infomobilitaRSSBox/{isInfoLavori})."""
        param = "true" if is_info_lavori else "false"
        r = await self._request(f"infomobilitaRSSBox/{param}")
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        return parse_infomobilita_rss_box(r.text)

    async def infomobilita_ticker(self) -> list[str]:
        """Avvisi brevi del ticker scorrevole (GET /infomobilitaTicker)."""
        r = await self._request("infomobilitaTicker")
        if r.status_code == 204 or not r.text.strip():
            return []
        r.raise_for_status()
        return parse_infomobilita_ticker(r.text)

    async def language(self, id_lingua: str = "it") -> dict[str, str]:
        """Dizionario di traduzione dell'interfaccia (GET /language/{idLingua})."""
        r = await self._request(f"language/{quote(id_lingua)}")
        if r.status_code == 204 or not r.text.strip():
            return {}
        r.raise_for_status()
        return r.json()
