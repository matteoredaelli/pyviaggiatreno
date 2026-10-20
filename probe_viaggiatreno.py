#!/usr/bin/env python3
"""Chiama tutti gli endpoint documentati in VIAGGIATRENO.md e salva le risposte
reali in ./samples/ (status, content-type e corpo). Richiede: pip install httpx"""

import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import httpx

BASE = "http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno"
OUT = Path("samples")
OUT.mkdir(exist_ok=True)

STAZIONE = "S01700"  # Milano Centrale
now = datetime.now(UTC).astimezone()
data_ora = quote(now.strftime("%a %b %d %Y %H:%M:%S GMT%z"))
now_ms = int(time.time() * 1000)

client = httpx.Client(timeout=20, headers={"User-Agent": "Mozilla/5.0"})


def get(name: str, path: str) -> httpx.Response | None:
    url = f"{BASE}/{path}"
    try:
        r = client.get(url)
    except httpx.HTTPError as e:
        print(f"{name:42} ERRORE {e}")
        return None
    ctype = r.headers.get("content-type", "")
    print(f"{name:42} {r.status_code} {ctype} {len(r.content)} B")
    ext = "json" if r.text.lstrip()[:1] in "[{" else "txt"
    (OUT / f"{name}.{ext}").write_text(
        f"# {url}\n# status={r.status_code} content-type={ctype}\n{r.text}\n",
        encoding="utf-8",
    )
    time.sleep(0.5)  # richieste moderate
    return r


# Stazioni
get("autocompletaStazione", "autocompletaStazione/firenze")
get("autocompletaStazioneImpostaViaggio", "autocompletaStazioneImpostaViaggio/firenze")
get("autocompletaStazioneNTS", "autocompletaStazioneNTS/firenze")
get("cercaStazione", "cercaStazione/apice")
reg = get("regione", f"regione/{STAZIONE}")
codreg = reg.text.strip() if reg is not None and reg.status_code == 200 else "1"
get("dettaglioStazione", f"dettaglioStazione/{STAZIONE}/{codreg}")
get("elencoStazioni", f"elencoStazioni/{codreg}")

# Partenze / arrivi
get("partenze", f"partenze/{STAZIONE}/{data_ora}")
get("arrivi", f"arrivi/{STAZIONE}/{data_ora}")

# Treni: prendo un numero dalle partenze reali
numero = None
r = client.get(f"{BASE}/partenze/{STAZIONE}/{data_ora}")
if r.status_code == 200 and r.text.strip():
    try:
        numero = r.json()[0]["numeroTreno"]
    except (ValueError, IndexError, KeyError):
        pass
numero = numero or 9685
get("cercaNumeroTrenoTrenoAutocomplete", f"cercaNumeroTrenoTrenoAutocomplete/{numero}")
ct = get("cercaNumeroTreno", f"cercaNumeroTreno/{numero}")
if ct is not None and ct.status_code == 200 and ct.text.strip():
    d = ct.json()
    args = f"{d['codLocOrig']}/{d['numeroTreno']}/{d['millisDataPartenza']}"
    get("andamentoTreno", f"andamentoTreno/{args}")
    get("tratteCanvas", f"tratteCanvas/{args}")

# Dettaglio viaggio: treni diretti tra due stazioni (endpoint non documentato
# in nessuna fonte nota, trovato in rest-jsapi)
get("dettaglioViaggio", f"dettaglioViaggio/{STAZIONE}/S06421")

# Tratte
cat = "ES*,IC,EXP,EC,EN,REG"
et = get("elencoTratte", f"elencoTratte/0/6/{cat}/null/{now_ms}")
if et is not None and et.status_code == 200:
    try:
        seg = next(s for s in et.json() if s.get("occupata"))
        get(
            "dettagliTratta",
            f"dettagliTratta/0/{seg['trattaAB']}/{seg['trattaBA']}/{cat}/null",
        )
    except (StopIteration, ValueError):
        print("nessuna tratta occupata: dettagliTratta saltato")

# Servizio
get("statistiche", f"statistiche/{now_ms}")
get("datimeteo", "datimeteo/1")
get("infomobilitaRSS", "infomobilitaRSS/false")
get("infomobilitaRSSBox", "infomobilitaRSSBox/false")
get("infomobilitaTicker", "infomobilitaTicker")
get("language", "language/en")

print(f"\nRisposte salvate in {OUT.resolve()}")
