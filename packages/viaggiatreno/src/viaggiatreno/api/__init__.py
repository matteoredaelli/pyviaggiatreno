# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Package API per la libreria ViaggiaTreno."""

from viaggiatreno.api.client import ViaggiaTrenoClient, format_viaggiatreno_datetime
from viaggiatreno.api.parsers import (
    parse_infomobilita_rss,
    parse_infomobilita_rss_box,
    parse_infomobilita_ticker,
    parse_station_autocomplete,
    parse_station_nts_autocomplete,
    parse_train_autocomplete,
)

__all__ = [
    "ViaggiaTrenoClient",
    "format_viaggiatreno_datetime",
    "parse_infomobilita_rss",
    "parse_infomobilita_rss_box",
    "parse_infomobilita_ticker",
    "parse_station_autocomplete",
    "parse_station_nts_autocomplete",
    "parse_train_autocomplete",
]
