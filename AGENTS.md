# AGENTS.md

Guida sintetica del repo per agenti AI e contributori.

## Cos'è

Monorepo Python basato sulle API **non ufficiali** di ViaggiaTreno (treni in
Italia, dati real-time). Workspace `uv` con 4 pacchetti in `packages/`.

## Pacchetti

| Package (dir) | Nome dist | Ruolo | Entry point |
|---|---|---|---|
| `viaggiatreno` | `viaggiatreno` | Libreria client HTTP async (core, no MCP/SQLite) | — (import) |
| `viaggiatreno_mcp` | `viaggiatreno-mcp` | Server MCP (adattatore sottile sulla core) | `viaggiatreno-mcp` |
| `viaggiatreno_crawler` | `viaggiatreno-crawler` | Crawler a eventi (coda di lavori con scadenza) → dati storici in SQLite | `viaggiatreno-crawler eventi` |
| `viaggiatreno_sito` | `viaggiatreno-sito` | Generatore di un sito statico (una pagina per stazione) dal DB del crawler | `viaggiatreno-sito` |

Nessuna CLI generica separata: solo gli entry point sopra (`viaggiatreno-mcp`, `viaggiatreno-crawler`,
`viaggiatreno-sito`). `viaggiatreno-sito-hugo` (stesso pacchetto, `make sito-hugo`) scrive solo pagine markdown
delle stazioni in `content/<sezione>/` di un sito Hugo esistente, senza layout propri.

## Layout

- `packages/viaggiatreno/src/viaggiatreno/`
  - `api/client.py` — `ViaggiaTrenoClient` (httpx async)
  - `api/parsers.py` — parsing JSON/testo/HTML + quirk (204, date JS, orari >24h)
  - `models/` — modelli pydantic (`station`, `train`, `route`, `service`, `common`)
  - `heuristics/rotazione.py` — euristiche
  - `insights/` — analisi su dati già scaricati (nessun I/O): `corsa` (riga di tabellone normalizzata), `collegamento` (origine→destinazione di un verso), `itinerario` (fermate ordinate, indipendente dal verso), `stazione` (`ProfiloStazione`: binari, frequenza, ruolo, collegamenti), `treno` (`ProfiloTreno`: itinerario, fermate, archi da `andamentoTreno`), `linea` (`Linea`, `aggrega_archi`: raggruppamenti su più treni)
- `packages/viaggiatreno_mcp/src/viaggiatreno_mcp/`
  - `server.py` — avvio (transport stdio), `main`
  - `tools/` — tool MCP per dominio: `stations`, `trains`, `departures_arrivals`, `routes`, `service`
- `packages/viaggiatreno_crawler/src/viaggiatreno_crawler/`
  - `eventi.py` — `Motore`: i lavori `censisci_stazione`, `sonda_stazione`, `verifica_treno` (+ tratte/scan opz.)
  - `scheduler.py` — coda con scadenze + pool di worker
  - `rete.py` — trasporto resiliente (retry, pausa sul 403, proxy) + limitatore di richieste al secondo
  - `poller.py` — funzioni di scoperta/persistenza riusate dal motore
  - `storage.py` — schema e upsert SQLite (`regioni`, `stops`, `treni`, `fermate`, `tratte`, …)
  - `config.py` — `ConfigEventi`; `__main__.py` — CLI argparse (`eventi`, `manutenzione`)
- `data/eventi.db` — DB SQLite di output del crawler
- Docs (IT): `INDICE.md`, `VIAGGIATRENO.md`, `TRENORD.md`, `ENTITA.md`, `GLOSSARIO.md`, `COPERTURA_GEOGRAFICA.md`

## Stack

- Python >= 3.12, `uv` workspace, build `hatchling` + `hatch-vcs` (versione dai tag Git)
- Runtime: `httpx`, `pydantic` v2; MCP: `fastmcp`; crawler: `sqlite3` (stdlib)
- Lint/type/test: `ruff` (line-length 100), `pyright`, `pytest` (`asyncio_mode = auto`)

## Comandi

```bash
uv sync                    # installa workspace + dev deps (editable)
make lint                  # ruff format --check + ruff check + pyright
make pytest                # test (= uv run pytest)
make run                   # avvia il server MCP (= uv run viaggiatreno-mcp)
make crawler-eventi        # crawler a eventi (anche -tratte, -full; vedi make help)
make build                 # build di tutti i pacchetti (= uv build)
```

## Convenzioni

- La libreria `viaggiatreno` deve restare un client HTTP puro: niente dipendenze
  da MCP o SQLite. La logica applicativa va in `viaggiatreno_mcp`/`viaggiatreno_crawler`.
- Codice in inglese; commenti/documentazione spesso in italiano (coerenza col repo).
- Le API ViaggiaTreno sono fragili: gestire 204 No Content, Content-Type errato,
  date in ms, orari > 24:00. Non fare polling aggressivo.
- Versioni allineate dai tag Git (`vX.Y.Z`); i 3 pacchetti si pubblicano insieme
  via workflow `publish-pypi.yml` (Trusted Publishing / OIDC).

## Licenza

- `GPL-3.0-or-later` (testo in `LICENSE`, `license = "GPL-3.0-or-later"` nei `pyproject.toml`).
- Ogni `.py` tracciato ha l'intestazione SPDX: `make license-check` verifica, `make addlicense` aggiunge
  (google/addlicense). Nuovi file `.py` → lanciare `make addlicense`.
- Ogni pacchetto ha una copia reale di `LICENSE` (inclusa nei wheel); dopo modifiche a `LICENSE` lanciare `make license-sync`.

## CI (GitHub Actions)

- `tests.yml` — ruff + pyright + pytest (push/PR su `main`/`dev`)
- `test-build.yml` — build + test install wheel (su modifiche a `packages/`)
- `publish-pypi.yml` — build + publish su PyPI + GitHub Release (su tag push)

## Note / limiti

- API non ufficiali (reverse engineering), nessun rate limit documentato.
- Le API espongono solo lo "stato attuale"; lo storico esiste solo via crawler.
- `stops` del crawler è compatibile con `stops.txt` del GTFS Trenord; `treni`/
  `fermate` sono osservazioni real-time, non traducibili 1:1 in GTFS statico.
