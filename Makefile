.PHONY: help run pytest ruff-format ruff-check pyright lint build publish \
	addlicense license-check license-sync \
	crawler-eventi crawler-orario crawler-eventi-tratte crawler-eventi-full crawler-manutenzione stazioni tratte viste errors sito sito-hugo

# Parametri del crawler sovrascrivibili da riga di comando, es:
#   make crawler-eventi REGIONE=10 DB=data/lazio.db RICHIESTE_AL_SECONDO=0.5
REGIONE ?= 1
DB ?= data/eventi.db
RICHIESTE_AL_SECONDO ?= 1
WORKERS ?= 4
INTERVALLO_TRATTE ?= 300
INTERVALLO_SCAN ?= 1800
SCAN_FINESTRA ?= 5
SCAN_MAX_CHIAMATE ?= 300
GIORNI_AVVISTAMENTI ?= 7
N ?= 20

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
	@echo "Crawler (coda di lavori con scadenza, un solo processo):"
	@echo "  crawler-eventi         stazioni + capolinea + treni (il caso normale)"
	@echo "  tratte                 carica una tantum la rete (segmenti di elencoTratte, regioni 0-22)"
	@echo "  sito                   genera il sito statico (stazioni e linee) in SITO_OUT da una copia del DB"
	@echo "  sito-hugo              aggiunge le pagine delle stazioni a un sito Hugo esistente (HUGO_CONTENT=.../content)"
	@echo "  errors                 ultimi N errori del crawler (N=20; sola lettura, anche a crawler acceso)"
	@echo "  crawler-orario         estrae l'orario programmato di tutti i treni (6-14 giorni di validita')"
	@echo "  crawler-eventi-tratte  + scoperta per segmenti (tratte, tratte_osservazioni, avvistamenti_tratta)"
	@echo "  crawler-eventi-full    + scan dei numeri treno attorno ai noti"
	@echo "  viste                  (ri)crea le viste SQL per dashboard e wiki (anche a crawler acceso)"
	@echo "  stazioni               carica una tantum le stazioni di tutta Italia (elencoStazioni, regioni 1-22)"
	@echo "  crawler-manutenzione   pulizia/compattazione del DB (FERMARE prima il crawler)"
	@echo ""
	@echo "  Parametri (var=valore): REGIONE DB RICHIESTE_AL_SECONDO WORKERS INTERVALLO_TRATTE"
	@echo "    INTERVALLO_SCAN SCAN_FINESTRA SCAN_MAX_CHIAMATE GIORNI_AVVISTAMENTI."
	@echo "    Es: make crawler-eventi-tratte REGIONE=10 DB=data/lazio.db RICHIESTE_AL_SECONDO=0.5"
	@echo ""
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
LICENSE_PACKAGES = viaggiatreno viaggiatreno_mcp viaggiatreno_crawler viaggiatreno_sito

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
# Un solo comando, `viaggiatreno-crawler eventi`: una coda di lavori con scadenza
# (censimento stazioni, sonda dei capolinea, verifica dei treni) in un unico processo.
# I target qui sotto sono solo combinazioni di flag dello stesso comando: se ne lancia
# uno solo alla volta.
# ---------------------------------------------------------------------------

# Alias per avviare il crawler: equivale a `make crawler` (stessi parametri).
# Manutenzione una tantum del DB: va lanciata a crawler FERMO (il VACUUM riscrive
# il file e SQLite non ammette due scrittori). Fa un backup prima di toccare nulla.
#   - valorizza treni.orario_partenza dai dati gia' presenti
#   - cancella gli avvistamenti_tratta piu' vecchi di GIORNI_AVVISTAMENTI giorni
#   - toglie le fermate dal raw_json dei treni regolari arrivati (restano in `fermate`)
#   - VACUUM per restituire lo spazio
crawler-manutenzione:
	@if pgrep -f "viaggiatreno-crawler (run|eventi)" >/dev/null; then \
		echo "Il crawler e' in esecuzione: fermalo prima (Ctrl-C) e rilancia."; exit 1; fi
	cp $(DB) $(DB).pre-manutenzione
	@echo "Backup: $(DB).pre-manutenzione (cancellalo quando hai verificato)"
	uv run viaggiatreno-crawler manutenzione --db-path $(DB) \
		--ricava-destinazione --ricava-orario-partenza \
		--pulisci-avvistamenti $(GIORNI_AVVISTAMENTI) \
		--compatta-raw-json --vacuum

# Crawler a eventi: coda di lavori con scadenza (censimento stazioni, sonda dei
# capolinea, verifica dei treni). Il ritmo verso il sito e' limitato da
# RICHIESTE_AL_SECONDO, il parallelismo da WORKERS.
crawler-eventi:
	uv run viaggiatreno-crawler eventi \
		--regione $(REGIONE) --db-path $(DB) \
		--richieste-al-secondo $(RICHIESTE_AL_SECONDO) \
		--workers $(WORKERS)

# Estrae l'orario programmato (itinerario, tempi, fermate) invece delle statistiche: un treno per
# (numero, origine, tipo di giorno), record valido 6-14 giorni. Tutta Italia: REGIONE=0.
crawler-orario:
	uv run viaggiatreno-crawler eventi --modalita orario \
		--regione $(REGIONE) --db-path $(DB) \
		--richieste-al-secondo $(RICHIESTE_AL_SECONDO) \
		--workers $(WORKERS)

# + scoperta per segmenti (elencoTratte/dettagliTratta): alimenta tratte,
# tratte_osservazioni e avvistamenti_tratta, e trova treni in circolazione.
crawler-eventi-tratte:
	uv run viaggiatreno-crawler eventi \
		--regione $(REGIONE) --db-path $(DB) \
		--richieste-al-secondo $(RICHIESTE_AL_SECONDO) \
		--workers $(WORKERS) \
		--intervallo-tratte $(INTERVALLO_TRATTE)

# + scan dei numeri treno attorno ai noti (cercaNumeroTreno).
crawler-eventi-full:
	uv run viaggiatreno-crawler eventi \
		--regione $(REGIONE) --db-path $(DB) \
		--richieste-al-secondo $(RICHIESTE_AL_SECONDO) \
		--workers $(WORKERS) \
		--intervallo-tratte $(INTERVALLO_TRATTE) \
		--intervallo-scan $(INTERVALLO_SCAN) \
		--scan-finestra $(SCAN_FINESTRA) \
		--scan-max-chiamate $(SCAN_MAX_CHIAMATE)

# Carica una tantum le stazioni di tutta Italia (22 chiamate a elencoStazioni, regioni 1-22)
# nella tabella `stops`. Si puo' lanciare anche a crawler acceso: scrive per regione, a
# pezzi brevi. Per una sola regione: make stazioni REGIONI_STAZIONI="--regione 1".
REGIONI_STAZIONI ?=
stazioni:
	uv run viaggiatreno-crawler stazioni --db-path $(DB) \
		--richieste-al-secondo $(RICHIESTE_AL_SECONDO) $(REGIONI_STAZIONI)

# Sito statico (stazioni e linee). Legge una COPIA del DB (sola lettura, anche a crawler acceso).
# Es: make sito STAZIONE=S01322 (solo Monza) · make sito DB=data/orario.db SITO_OUT=/tmp/sito
SITO_OUT ?= sito
STAZIONE ?=
sito:
	uv run viaggiatreno-sito --db-path $(DB) --out $(SITO_OUT) $(if $(STAZIONE),--stazione $(STAZIONE),)

# Pagine markdown delle stazioni in <HUGO_CONTENT>/<HUGO_SEZIONE>/ di un sito Hugo esistente
# (la cartella della sezione e' gestita dallo script: viene riscritta a ogni esecuzione).
# Es: make sito-hugo HUGO_CONTENT=~/siti/miosito/content
HUGO_CONTENT ?=
HUGO_SEZIONE ?= trains
sito-hugo:
	@test -n "$(HUGO_CONTENT)" || { echo "uso: make sito-hugo HUGO_CONTENT=<sito-hugo>/content"; exit 2; }
	uv run viaggiatreno-sito-hugo --db-path $(DB) --content-dir $(HUGO_CONTENT) --sezione $(HUGO_SEZIONE) $(if $(STAZIONE),--stazione $(STAZIONE),)

# Segmenti della rete da elencoTratte, una tantum o raramente (23 chiamate, regioni 0-22; la 0 e la
# 1 sono grafi diversi). Non scarica i treni. Per una regione: make tratte REGIONI_TRATTE="--regione 1".
REGIONI_TRATTE ?=
tratte:
	uv run viaggiatreno-crawler tratte --db-path $(DB) \
		--richieste-al-secondo $(RICHIESTE_AL_SECONDO) $(REGIONI_TRATTE)

# Ultimi N errori registrati dal crawler (tabelloni e lavori falliti), es: make errors N=50
# Non include i blocchi 403/429: quelli stanno solo nel log.
errors:
	uv run viaggiatreno-crawler errori --db-path $(DB) --ultimi $(N)

# Viste SQL riassuntive (v_stops, v_treno, ...). Il crawler le crea da solo all'avvio: questo
# serve per un DB gia' esistente o dopo un cambio delle definizioni. Non scrive dati.
viste:
	uv run viaggiatreno-crawler viste --db-path $(DB)
