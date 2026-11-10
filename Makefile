.PHONY: help run pytest ruff-format ruff-check pyright lint build publish \
	addlicense license-check license-sync \
	run-crawler crawler crawler-full crawler-tabelloni crawler-nazionale \
	crawler-manutenzione

# Parametri del crawler sovrascrivibili da riga di comando, es:
#   make crawler REGIONE=10 DB=data/lazio.db
REGIONE ?= 1
DB ?= data/treni.db
INTERVALLO_SCOPERTA ?= 300
INTERVALLO_VERIFICA ?= 900
INTERVALLO_TABELLONI ?= 800
INTERVALLO_SCAN ?= 1800
TABELLONI_MAX_STAZIONI ?= 50
TABELLONI_RARE_PER_GIRO ?= 10
SCAN_FINESTRA ?= 5
SCAN_MAX_CHIAMATE ?= 300
VERIFICA_CONCORRENZA ?= 5
VERIFICA_MAX_PER_GIRO ?= 0
VERIFICA_ANTICIPO ?= 900
VERIFICA_MIN_INTERVALLO ?= 300
TABELLONE_MIN_INTERVALLO ?= 1800
GIORNI_AVVISTAMENTI ?= 7

# Default goal
help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Qualita' del codice:"
	@echo "  ruff-format   Formatta il codice con ruff"
	@echo "  ruff-check    Linta con ruff (aggiungi FIX=1 per --fix)"
	@echo "  pyright       Type checking con pyright"
	@echo "  lint          ruff-format + ruff-check + pyright + license-check"
	@echo "  license-check Verifica le intestazioni GPL-3.0-or-later (addlicense -check)"
	@echo "  addlicense    Aggiunge le intestazioni mancanti ai .py tracciati"
	@echo "  license-sync  Copia LICENSE nei pacchetti (serve per includerlo nei wheel)"
	@echo "  pytest        Esegue i test"
	@echo ""
	@echo "Pacchetti:"
	@echo "  build         Build sdist + wheel con uv"
	@echo "  publish       Build e publish su PyPI (serve UV_PUBLISH_TOKEN)"
	@echo "  run           Avvia il server MCP (uv run viaggiatreno-mcp)"
	@echo ""
	@echo "Crawler (un solo comando, cicli concorrenti attivati dai flag):"
	@echo "  run-crawler        alias di crawler (avvio base: scoperta + verifica)"
	@echo "  crawler            scoperta (elenco_tratte) + verifica (andamento_treno)"
	@echo "  crawler-tabelloni  i precedenti + scoperta via partenze delle stazioni"
	@echo "  crawler-full       tutti e 4 i cicli: i precedenti + scan-range numeri treno"
	@echo "  crawler-nazionale  come crawler-full ma su tutta Italia (REGIONE=0)"
	@echo "  crawler-manutenzione  pulizia/compattazione del DB (FERMARE prima il crawler)"
	@echo ""
	@echo "  Parametri (var=valore): REGIONE DB INTERVALLO_SCOPERTA INTERVALLO_VERIFICA"
	@echo "    INTERVALLO_TABELLONI INTERVALLO_SCAN TABELLONI_MAX_STAZIONI TABELLONI_RARE_PER_GIRO SCAN_FINESTRA"
	@echo "    SCAN_MAX_CHIAMATE VERIFICA_CONCORRENZA VERIFICA_MAX_PER_GIRO VERIFICA_ANTICIPO"
	@echo "    VERIFICA_MIN_INTERVALLO TABELLONE_MIN_INTERVALLO GIORNI_AVVISTAMENTI."
	@echo "    Es: make crawler-full REGIONE=10 DB=data/lazio.db VERIFICA_CONCORRENZA=8"

# ---------------------------------------------------------------------------
# Qualita' del codice
# ---------------------------------------------------------------------------

# Intestazioni di licenza (GPL-3.0-or-later, SPDX) con google/addlicense.
# Opera solo sui .py tracciati da git: esclude .venv e i _version.py generati.
# `./**/*.py` non andava bene: senza globstar la shell non scende nei sottopacchetti.
ADDLICENSE ?= $(HOME)/go/bin/addlicense
ADDLICENSE_ARGS = -c "Matteo Redaelli" -l GPL-3.0-or-later -s

addlicense:
	git ls-files '*.py' | xargs $(ADDLICENSE) $(ADDLICENSE_ARGS)

# Ogni pacchetto ha una copia reale di LICENSE: hatchling la include in wheel e
# sdist (dist-info/licenses/). Un symlink verso ../../LICENSE non funziona,
# `uv build` rifiuta i link che escono dalla root del pacchetto.
LICENSE_PACKAGES = viaggiatreno viaggiatreno_mcp viaggiatreno_crawler

license-sync:
	@for p in $(LICENSE_PACKAGES); do cp LICENSE packages/$$p/LICENSE; done

license-check:
	git ls-files '*.py' | xargs $(ADDLICENSE) -check $(ADDLICENSE_ARGS)
	@for p in $(LICENSE_PACKAGES); do \
		cmp -s LICENSE packages/$$p/LICENSE || { echo "packages/$$p/LICENSE non allineato: make license-sync"; exit 1; }; \
	done

pytest:
	uv run pytest

ruff-format:
	uv run ruff format .

ruff-check:
ifdef FIX
	uv run ruff check --fix .
else
	uv run ruff check .
endif

pyright:
	uv run pyright

lint: ruff-format ruff-check pyright license-check

# ---------------------------------------------------------------------------
# Pacchetti
# ---------------------------------------------------------------------------

build:
	uv build

publish: build
	uv publish

run:
	uv run viaggiatreno-mcp

# ---------------------------------------------------------------------------
# Crawler
#
# NON ci sono script separati: c'e' un unico comando `viaggiatreno-crawler run`
# che avvia piu' cicli concorrenti nello stesso processo. Ogni ciclo si attiva
# col proprio intervallo in secondi; intervallo 0 = ciclo spento.
#   - scoperta  (elenco_tratte/dettagli_tratta)  sempre attivo
#   - verifica  (andamento_treno sui treni noti)  sempre attivo
#   - tabelloni (partenze delle stazioni)         opt-in
#   - scan      (cerca_numero_treno attorno ai noti) opt-in
# I target qui sotto sono solo combinazioni di flag dello stesso comando.
# ---------------------------------------------------------------------------

# Alias per avviare il crawler: equivale a `make crawler` (stessi parametri).
run-crawler: crawler

# Base: solo scoperta + verifica (tabelloni e scan spenti).
crawler:
	uv run viaggiatreno-crawler run \
		--regione $(REGIONE) --db-path $(DB) \
		--intervallo-scoperta $(INTERVALLO_SCOPERTA) \
		--intervallo-verifica $(INTERVALLO_VERIFICA) \
		--verifica-concorrenza $(VERIFICA_CONCORRENZA) \
		--verifica-max-per-giro $(VERIFICA_MAX_PER_GIRO) \
		--verifica-anticipo $(VERIFICA_ANTICIPO) \
		--verifica-min-intervallo $(VERIFICA_MIN_INTERVALLO) \
		--tabellone-min-intervallo $(TABELLONE_MIN_INTERVALLO) \
		--intervallo-tabelloni 0 --intervallo-scan 0

# + scoperta via tabelloni delle partenze delle stazioni (arrivi: --tabelloni-arrivi).
crawler-tabelloni:
	uv run viaggiatreno-crawler run \
		--regione $(REGIONE) --db-path $(DB) \
		--intervallo-scoperta $(INTERVALLO_SCOPERTA) \
		--intervallo-verifica $(INTERVALLO_VERIFICA) \
		--verifica-concorrenza $(VERIFICA_CONCORRENZA) \
		--verifica-max-per-giro $(VERIFICA_MAX_PER_GIRO) \
		--verifica-anticipo $(VERIFICA_ANTICIPO) \
		--verifica-min-intervallo $(VERIFICA_MIN_INTERVALLO) \
		--tabellone-min-intervallo $(TABELLONE_MIN_INTERVALLO) \
		--intervallo-tabelloni $(INTERVALLO_TABELLONI) \
		--tabelloni-max-stazioni $(TABELLONI_MAX_STAZIONI) \
		--tabelloni-rare-per-giro $(TABELLONI_RARE_PER_GIRO) \
		--intervallo-scan 0

# Tutti e 4 i cicli attivi: scoperta + verifica + tabelloni + scan-range
# dei numeri treno.
crawler-full:
	uv run viaggiatreno-crawler run \
		--regione $(REGIONE) --db-path $(DB) \
		--intervallo-scoperta $(INTERVALLO_SCOPERTA) \
		--intervallo-verifica $(INTERVALLO_VERIFICA) \
		--verifica-concorrenza $(VERIFICA_CONCORRENZA) \
		--verifica-max-per-giro $(VERIFICA_MAX_PER_GIRO) \
		--verifica-anticipo $(VERIFICA_ANTICIPO) \
		--verifica-min-intervallo $(VERIFICA_MIN_INTERVALLO) \
		--tabellone-min-intervallo $(TABELLONE_MIN_INTERVALLO) \
		--intervallo-tabelloni $(INTERVALLO_TABELLONI) \
		--tabelloni-max-stazioni $(TABELLONI_MAX_STAZIONI) \
		--tabelloni-rare-per-giro $(TABELLONI_RARE_PER_GIRO) \
		--intervallo-scan $(INTERVALLO_SCAN) \
		--scan-finestra $(SCAN_FINESTRA) \
		--scan-max-chiamate $(SCAN_MAX_CHIAMATE)

# Tutta Italia. Concorrenza di verifica più alta: con regione=0 i treni attivi
# sono di più (misurato: la verifica resta comunque pochi secondi a giro).
crawler-nazionale:
	$(MAKE) crawler-full REGIONE=0 VERIFICA_CONCORRENZA=8

# Manutenzione una tantum del DB: va lanciata a crawler FERMO (il VACUUM riscrive
# il file e SQLite non ammette due scrittori). Fa un backup prima di toccare nulla.
#   - valorizza treni.orario_partenza dai dati gia' presenti
#   - cancella gli avvistamenti_tratta piu' vecchi di GIORNI_AVVISTAMENTI giorni
#   - toglie le fermate dal raw_json dei treni regolari arrivati (restano in `fermate`)
#   - VACUUM per restituire lo spazio
crawler-manutenzione:
	@if pgrep -f "viaggiatreno-crawler run" >/dev/null; then \
		echo "Il crawler e' in esecuzione: fermalo prima (Ctrl-C) e rilancia."; exit 1; fi
	cp $(DB) $(DB).pre-manutenzione
	@echo "Backup: $(DB).pre-manutenzione (cancellalo quando hai verificato)"
	uv run viaggiatreno-crawler manutenzione --db-path $(DB) \
		--ricava-orario-partenza \
		--pulisci-avvistamenti $(GIORNI_AVVISTAMENTI) \
		--compatta-raw-json --vacuum

