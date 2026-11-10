# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modelli Pydantic per le stazioni ferroviarie."""

from typing import Any

from pydantic import Field

from viaggiatreno.models.common import REGIONS, ViaggiaTrenoBaseModel


class StationAutocompleteItem(ViaggiaTrenoBaseModel):
    """Elemento restituito dall'autocompletamento delle stazioni (formato NOME|CODICE)."""

    nome: str = Field(..., description="Nome della stazione (es. FIRENZE SANTA MARIA NOVELLA)")
    codice: str = Field(..., description="Codice stazione ViaggiaTreno (es. S06421)")


class StationNTSAutocompleteItem(ViaggiaTrenoBaseModel):
    """Elemento restituito dall'autocompletamento tecnico NTS con codice RICS."""

    nome: str = Field(..., description="Nome della località o stazione tecnica")
    codice_nts: str = Field(..., description="Codice numerico RICS a 9-11 cifre (es. 830006900)")


class StationSearchResult(ViaggiaTrenoBaseModel):
    """Risultato strutturato della ricerca stazione."""

    id: str = Field(..., description="Codice stazione (es. S09314)")
    nomeLungo: str = Field(..., description="Nome completo della stazione")
    nomeBreve: str | None = Field(None, description="Nome breve o abbreviato")
    label: str | None = Field(None, description="Etichetta o comune")


class StationDetail(ViaggiaTrenoBaseModel):
    """Dettaglio anagrafico e geografico di una stazione."""

    codiceStazione: str = Field(..., description="Codice stazione (es. S01700)")
    codReg: int | None = Field(None, description="Codice numerico della regione (1-22)")
    nomeRegione: str | None = Field(None, description="Nome testuale della regione")
    lat: float | None = Field(None, description="Latitudine WGS84")
    lon: float | None = Field(None, description="Longitudine WGS84")
    nomeCitta: str | None = Field(None, description="Nome della città o comune")
    tipoStazione: int | None = Field(
        None, description="Tipo stazione (1 principale, 3 regolare, ecc.)"
    )
    localita: StationSearchResult | None = Field(None, description="Dati anagrafici località")
    key: str | None = Field(None, description="Chiave composita codice_regione")
    esterno: bool | None = Field(None, description="Flag stazione esterna")
    dettZoomStaz: list[dict[str, Any]] | None = Field(
        default=None, description="Livelli di zoom per mappa"
    )

    def model_post_init(self, context: Any, /) -> None:
        if self.codReg is not None and self.nomeRegione is None:
            self.nomeRegione = REGIONS.get(self.codReg)
