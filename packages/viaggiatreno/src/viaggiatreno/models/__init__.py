# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Package models per la libreria ViaggiaTreno."""

from viaggiatreno.models.common import (
    CLIENT_COMPANIES,
    REGIONS,
    TRAIN_STATUS_DESCRIPTIONS,
    ViaggiaTrenoBaseModel,
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
    Fermata,
    TrainAutocompleteItem,
    TrainBoardItem,
    TrainSearchResult,
    TrainStatus,
    TrattaCanvasItem,
)

__all__ = [
    "CLIENT_COMPANIES",
    "REGIONS",
    "TRAIN_STATUS_DESCRIPTIONS",
    "DettaglioTratta",
    "Fermata",
    "InfomobilitaNews",
    "InfomobilitaNewsHeadline",
    "StationAutocompleteItem",
    "StationDetail",
    "StationNTSAutocompleteItem",
    "StationSearchResult",
    "StationWeather",
    "Statistics",
    "TrainAutocompleteItem",
    "TrainBoardItem",
    "TrainSearchResult",
    "TrainStatus",
    "TrattaCanvasItem",
    "TrattaSegment",
    "ViaggiaTrenoBaseModel",
]
