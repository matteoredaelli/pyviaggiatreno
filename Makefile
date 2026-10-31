.PHONY: help run pytest ruff-format ruff-check pyright lint build publish \
	crawler crawler-full crawler-tabelloni crawler-scan crawler-nazionale

# Parametri del crawler sovrascrivibili da riga di comando, es:
#   make crawler REGIONE=10 DB=data/lazio.db
REGIONE ?= 1
DB ?= data/treni.db
INTERVALLO_SCOPERTA ?= 300
INTERVALLO_VERIFICA ?= 900
INTERVALLO_TABELLONI ?= 600
INTERVALLO_SCAN ?= 1800
TABELLONI_MAX_STAZIONI ?= 50
SCAN_FINESTRA ?= 5
SCAN_MAX_CHIAMATE ?= 300
VERIFICA_CONCORRENZA ?= 5
VERIFICA_MAX_PER_GIRO ?= 0

# Default goal
help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Qualita' del codice:"
	@echo "  ruff-format   Formatta il codice con ruff"
	@echo "  ruff-check    Linta con ruff (aggiungi FIX=1 per --fix)"
	@echo "  pyright       Type checking con pyright"
	@echo "  lint          ruff-format + ruff-check + pyright"
	@echo "  pytest        Esegue i test"
	@echo ""
	@echo "Pacchetti:"
	@echo "  build         Build sdist + wheel con uv"
	@echo "  publish       Build e publish su PyPI (serve UV_PUBLISH_TOKEN)"
	@echo "  run           Avvia il server MCP (uv run viaggiatreno-mcp)"
	@echo ""
	@echo "Crawler (un solo comando, cicli concorrenti attivati dai flag):"
	@echo "  crawler            scoperta (elenco_tratte) + verifica (andamento_treno)"
	@echo "  crawler-tabelloni  i precedenti + scoperta via partenze/arrivi stazioni"
	@echo "  crawler-scan       i precedenti + tabelloni + scan-range numeri treno"
	@echo "  crawler-full       tutti e 4 i cicli attivi"
	@echo "  crawler-nazionale  come crawler-full ma su tutta Italia (REGIONE=0)"
	@echo ""
	@echo "  Parametri (var=valore): REGIONE DB INTERVALLO_SCOPERTA INTERVALLO_VERIFICA"
	@echo "    INTERVALLO_TABELLONI INTERVALLO_SCAN TABELLONI_MAX_STAZIONI SCAN_FINESTRA"
	@echo "    SCAN_MAX_CHIAMATE VERIFICA_CONCORRENZA VERIFICA_MAX_PER_GIRO."
	@echo "    Es: make crawler-full REGIONE=10 DB=data/lazio.db VERIFICA_CONCORRENZA=8"

# ---------------------------------------------------------------------------
# Qualita' del codice
# ---------------------------------------------------------------------------

addlicense:
	$$HOME/go/bin/addlicense -c "Matteo Redaelli" -l GPL-3.0-or-later  -s  ./**/*.py

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

lint: ruff-format ruff-check pyright

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
#   - tabelloni (partenze/arrivi delle stazioni)  opt-in
#   - scan      (cerca_numero_treno attorno ai noti) opt-in
# I target qui sotto sono solo combinazioni di flag dello stesso comando.
# ---------------------------------------------------------------------------

# Base: solo scoperta + verifica (tabelloni e scan spenti).
crawler:
	uv run viaggiatreno-crawler run \
		--regione $(REGIONE) --db-path $(DB) \
		--intervallo-scoperta $(INTERVALLO_SCOPERTA) \
		--intervallo-verifica $(INTERVALLO_VERIFICA) \
		--verifica-concorrenza $(VERIFICA_CONCORRENZA) \
		--verifica-max-per-giro $(VERIFICA_MAX_PER_GIRO) \
		--intervallo-tabelloni 0 --intervallo-scan 0

# + scoperta via tabelloni partenze/arrivi delle stazioni.
crawler-tabelloni:
	uv run viaggiatreno-crawler run \
		--regione $(REGIONE) --db-path $(DB) \
		--intervallo-scoperta $(INTERVALLO_SCOPERTA) \
		--intervallo-verifica $(INTERVALLO_VERIFICA) \
		--verifica-concorrenza $(VERIFICA_CONCORRENZA) \
		--verifica-max-per-giro $(VERIFICA_MAX_PER_GIRO) \
		--intervallo-tabelloni $(INTERVALLO_TABELLONI) \
		--tabelloni-max-stazioni $(TABELLONI_MAX_STAZIONI) \
		--intervallo-scan 0

# + scan-range dei numeri treno (include anche i tabelloni).
crawler-scan:
	uv run viaggiatreno-crawler run \
		--regione $(REGIONE) --db-path $(DB) \
		--intervallo-scoperta $(INTERVALLO_SCOPERTA) \
		--intervallo-verifica $(INTERVALLO_VERIFICA) \
		--verifica-concorrenza $(VERIFICA_CONCORRENZA) \
		--verifica-max-per-giro $(VERIFICA_MAX_PER_GIRO) \
		--intervallo-tabelloni $(INTERVALLO_TABELLONI) \
		--tabelloni-max-stazioni $(TABELLONI_MAX_STAZIONI) \
		--intervallo-scan $(INTERVALLO_SCAN) \
		--scan-finestra $(SCAN_FINESTRA) \
		--scan-max-chiamate $(SCAN_MAX_CHIAMATE)

# Tutti e 4 i cicli attivi.
crawler-full: crawler-scan

# Tutta Italia. Concorrenza di verifica più alta: con regione=0 i treni attivi
# sono di più (misurato: la verifica resta comunque pochi secondi a giro).
crawler-nazionale:
	$(MAKE) crawler-scan REGIONE=0 VERIFICA_CONCORRENZA=8
