# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parser per le risposte testuali e HTML delle API ViaggiaTreno."""

import html
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from viaggiatreno.models.service import (
    InfomobilitaNews,
    InfomobilitaNewsHeadline,
)
from viaggiatreno.models.station import (
    StationAutocompleteItem,
    StationNTSAutocompleteItem,
)
from viaggiatreno.models.train import TrainAutocompleteItem


def parse_station_autocomplete(text: str) -> list[StationAutocompleteItem]:
    """Parsa l'output testuale di autocompletaStazione / autocompletaStazioneImpostaViaggio.

    Formato atteso: NOME_STAZIONE|CODICE_STAZIONE (una riga per stazione).
    """
    results: list[StationAutocompleteItem] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            parts = line.split("|", 1)
            results.append(
                StationAutocompleteItem(
                    nome=parts[0].strip(),
                    codice=parts[1].strip(),
                )
            )
    return results


def parse_station_nts_autocomplete(text: str) -> list[StationNTSAutocompleteItem]:
    """Parsa l'output testuale di autocompletaStazioneNTS.

    Formato atteso: NOME_STAZIONE|CODICE_RICS_NTS.
    """
    results: list[StationNTSAutocompleteItem] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            parts = line.split("|", 1)
            results.append(
                StationNTSAutocompleteItem(
                    nome=parts[0].strip(),
                    codice_nts=parts[1].strip(),
                )
            )
    return results


def parse_train_autocomplete(text: str) -> list[TrainAutocompleteItem]:
    """Parsa l'output testuale di cercaNumeroTrenoTrenoAutocomplete.

    Supporta sia il formato attuale:
      9611 - TORINO PORTA NUOVA - 04/10/26|9611-S00219-1791064800000
    sia il formato storico:
      2107 - TORINO PORTA NUOVA|2107-S00219-1678230000000
    """
    results: list[TrainAutocompleteItem] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" not in line:
            continue
        left, right = line.split("|", 1)
        right_parts = right.strip().split("-")
        if len(right_parts) < 3:
            continue
        try:
            num = int(right_parts[0])
            cod_orig = right_parts[1]
            millis = int(right_parts[2])
        except ValueError:
            continue

        left_parts = [p.strip() for p in left.split(" - ")]
        stazione = left_parts[1] if len(left_parts) > 1 else ""
        data = left_parts[2] if len(left_parts) > 2 else None

        results.append(
            TrainAutocompleteItem(
                raw=line,
                numero_treno=num,
                stazione_origine=stazione,
                codice_stazione_origine=cod_orig,
                millis_data_partenza=millis,
                data=data,
            )
        )
    return results


def _clean_html_text(html_content: str) -> str:
    """Converte un frammento HTML in testo leggibile formattato."""
    text = re.sub(r"<br\s*/?>", "\n", html_content, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    # Rimuove spazi e a capo multipli
    lines = [line.strip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned.strip()


def parse_infomobilita_rss(html_text: str) -> list[InfomobilitaNews]:
    """Parsa il frammento HTML restituito da infomobilitaRSS."""
    items: list[InfomobilitaNews] = []
    # Trova tutti i blocchi <li>
    li_matches = re.findall(
        r'<li[^>]*class=["\'][^"\']*editModeCollapsibleElement[^"\']*["\'][^>]*>(.*?)</li>',
        html_text,
        re.DOTALL | re.IGNORECASE,
    )
    for li_content in li_matches:
        # Titolo e inEvidenza dal tag <a>
        a_match = re.search(
            r'<a[^>]*class=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            li_content,
            re.DOTALL | re.IGNORECASE,
        )
        if not a_match:
            continue
        a_class = a_match.group(1)
        titolo = _clean_html_text(a_match.group(2))
        in_evidenza = "inEvidenza" in a_class

        # Data da <h4>
        h4_match = re.search(r"<h4[^>]*>(.*?)</h4>", li_content, re.DOTALL | re.IGNORECASE)
        data = _clean_html_text(h4_match.group(1)) if h4_match else None

        # Testo da <div class="info-text...">
        body_match = re.search(
            r'<div[^>]*class=["\'][^"\']*info-text[^"\']*["\'][^>]*>(.*?)</div>',
            li_content,
            re.DOTALL | re.IGNORECASE,
        )
        body_html = body_match.group(1) if body_match else ""
        testo = _clean_html_text(body_html)

        # Cerca link treno se presente
        link_treno: dict[str, Any] | None = None
        treno_link_match = re.search(r'href=["\']([^"\']*cercaTreno\.jsp\?[^"\']+)["\']', body_html)
        if treno_link_match:
            raw_url = html.unescape(treno_link_match.group(1))
            parsed = urlparse(raw_url)
            qs = parse_qs(parsed.query)
            link_treno = {k: v[0] for k, v in qs.items()}

        items.append(
            InfomobilitaNews(
                titolo=titolo,
                data=data,
                testo=testo,
                inEvidenza=in_evidenza,
                link_treno=link_treno,
            )
        )
    return items


def parse_infomobilita_rss_box(html_text: str) -> list[InfomobilitaNewsHeadline]:
    """Parsa il frammento HTML sintetico restituito da infomobilitaRSSBox."""
    items: list[InfomobilitaNewsHeadline] = []
    a_matches = re.finditer(
        r'<a[^>]*class=["\']([^"\']*headingNewsAccordionBox[^"\']*)["\'][^>]*>(.*?)</a>',
        html_text,
        re.DOTALL | re.IGNORECASE,
    )
    for m in a_matches:
        classes = m.group(1)
        titolo = _clean_html_text(m.group(2))
        in_evidenza = "inEvidenza" in classes
        items.append(InfomobilitaNewsHeadline(titolo=titolo, inEvidenza=in_evidenza))
    return items


def parse_infomobilita_ticker(html_text: str) -> list[str]:
    """Parsa gli elementi del ticker scorrevole (infomobilitaTicker)."""
    items: list[str] = []
    for li_text in re.findall(r"<li[^>]*>(.*?)</li>", html_text, re.DOTALL | re.IGNORECASE):
        cleaned = _clean_html_text(li_text)
        if cleaned:
            items.append(cleaned)
    return items
