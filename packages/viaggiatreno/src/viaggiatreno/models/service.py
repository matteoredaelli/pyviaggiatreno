# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modelli Pydantic per statistiche, infomobilità, meteo e lingua."""

from typing import Any

from pydantic import Field

from viaggiatreno.models.common import ViaggiaTrenoBaseModel


class Statistics(ViaggiaTrenoBaseModel):
    """Statistiche aggregate della rete ferroviaria nazionale in tempo reale."""

    treniGiorno: int = Field(..., description="Totale treni previsti nella giornata corrente")
    ultimoAggiornamento: int = Field(
        ..., description="Timestamp dell'ultimo aggiornamento delle statistiche in ms"
    )
    treniCircolanti: int = Field(
        ..., description="Numero di treni attualmente in circolazione sulla rete"
    )


class StationWeather(ViaggiaTrenoBaseModel):
    """Dati meteo previsti per una stazione (datimeteo)."""

    codStazione: str = Field(..., description="Codice stazione")
    oggiTemperatura: int | None = Field(None, description="Temperatura media prevista oggi (°C)")
    oggiTemperaturaMattino: int | None = Field(None, description="Temperatura mattino oggi (°C)")
    oggiTemperaturaPomeriggio: int | None = Field(
        None, description="Temperatura pomeriggio oggi (°C)"
    )
    oggiTemperaturaSera: int | None = Field(None, description="Temperatura sera oggi (°C)")
    oggiTempo: int | None = Field(None, description="Codice meteo oggi")
    oggiTempoMattino: int | None = Field(None, description="Codice meteo mattino oggi")
    oggiTempoPomeriggio: int | None = Field(None, description="Codice meteo pomeriggio oggi")
    oggiTempoSera: int | None = Field(None, description="Codice meteo sera oggi")
    domaniTemperatura: int | None = Field(
        None, description="Temperatura media prevista domani (°C)"
    )
    domaniTemperaturaMattino: int | None = Field(
        None, description="Temperatura mattino domani (°C)"
    )
    domaniTemperaturaPomeriggio: int | None = Field(
        None, description="Temperatura pomeriggio domani (°C)"
    )
    domaniTemperaturaSera: int | None = Field(None, description="Temperatura sera domani (°C)")
    domaniTempo: int | None = Field(None, description="Codice meteo domani")
    domaniTempoMattino: int | None = Field(None, description="Codice meteo mattino domani")
    domaniTempoPomeriggio: int | None = Field(None, description="Codice meteo pomeriggio domani")
    domaniTempoSera: int | None = Field(None, description="Codice meteo sera domani")


class InfomobilitaNews(ViaggiaTrenoBaseModel):
    """Notizia o avviso completo di infomobilità / lavori."""

    titolo: str = Field(..., description="Titolo della notizia o dell'avviso")
    data: str | None = Field(None, description="Data di pubblicazione dell'avviso")
    testo: str = Field(..., description="Corpo testuale della notizia (senza markup HTML)")
    inEvidenza: bool = Field(
        default=False,
        description="True se la notizia è contrassegnata come 'in evidenza'",
    )
    link_treno: dict[str, Any] | None = Field(
        default=None,
        description="Eventuali parametri di treno citato estratti dal link (treno, origine, datapartenza)",
    )


class InfomobilitaNewsHeadline(ViaggiaTrenoBaseModel):
    """Titolo sintetico di un avviso di infomobilità (infomobilitaRSSBox)."""

    titolo: str = Field(..., description="Titolo dell'avviso")
    inEvidenza: bool = Field(default=False, description="True se l'avviso è in evidenza")
