# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modello dati del sito: per ogni stazione, tutto cio' che la pagina mostra, senza HTML.

Il modello e' separato dal rendering: si puo' provare senza guardare le pagine, scrivere in JSON
(per la ricerca, una mappa, un altro generatore) e rigenerare le pagine senza rileggere il DB.

Cosa conta come cosa (stesse definizioni della libreria e delle viste SQL):

- **origine/destinazione effettive**: prima e ultima fermata *non soppressa* del treno;
- **capolinea**: almeno un treno vi nasce o vi finisce; **transito**: almeno un treno vi passa. Le
  due cose possono valere insieme;
- un treno e' *parziale* se ha almeno una fermata soppressa: dove nasce e finisce e' incerto, quindi
  conta in `n_incerti` (non in `n_nascono`/`n_finiscono`); se vi passa conta comunque come "passa".

Sono le definizioni delle viste SQL del crawler (`v_stops`), non quelle di `StatoTreno` (che
chiama parziale anche un treno PP/SI/SF senza fermate soppresse): sul DB reale i due conteggi
devono coincidere, ed e' provato in `test_modello.py`.

I tipi di giorno sono quelli di `viaggiatreno.insights.calendario`. Una corsa e' (numero, origine,
giorno); i conteggi per tipo di giorno sono *medie per giorno* su quanti giorni di quel tipo hanno
dati. Un giorno con meno di `SOGLIA_GIORNO_COMPLETO` (50%) delle corse del giorno piu' ricco e'
considerato parziale (il crawler e' partito o stato fermo a meta') e non entra nelle medie.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime

from viaggiatreno.insights import (
    Linea,
    ProfiloTreno,
    TipoGiorno,
    aggrega_archi,
    costruisci_linee,
    offset_italia_ms,
    tipo_giorno,
)
from viaggiatreno.insights.itinerario import Itinerario

from viaggiatreno_sito import db
from viaggiatreno_sito.geo import coordinate_valide, regioni_geografiche

SOGLIA_GIORNO_COMPLETO = 0.5
TIPI_GIORNO = tuple(t.value for t in TipoGiorno)


@dataclass
class GiorniDati:
    """Quali giorni hanno dati, per tipo, e quali sono stati scartati perche' parziali."""

    completi: dict[str, list[str]] = field(default_factory=dict)  # tipo -> date ISO
    parziali: list[str] = field(default_factory=list)


@dataclass
class LineaDellaStazione:
    chiave: str  # `A|B`, stabile e indipendente dal verso
    nome: str  # "ORIGINE - DESTINAZIONE"
    estremo_a: str
    estremo_b: str
    n_treni: int  # treni (corse) della linea che passano di qui
    ruolo: str  # "capolinea" | "intermedia" | "solo in alcune varianti"
    n_fermate: int  # fermate della variante piu' completa


@dataclass
class Vicino:
    codice: str
    nome: str | None
    n_treni: int
    durata_minuti: float | None  # mediana programmata; None se non nota
    distanza_km: float | None


@dataclass
class Tratta:
    regione_codice: int
    tratta_ab: int
    tratta_ba: int
    altro_nodo: str
    altro_nome: str | None


@dataclass
class Frequenza:
    """Corse medie per giorno e profilo orario, per un tipo di giorno."""

    tipo_giorno: str
    n_giorni: int
    corse_per_giorno: float | None  # None se non ci sono giorni di quel tipo
    per_ora: list[float]  # 24 valori: passaggi medi in quell'ora locale


@dataclass
class Stazione:
    codice: str
    nome: str | None
    citta: str | None
    regione_codice: int | None
    regione_nome: str | None
    lat: float | None
    lon: float | None
    # ruolo (da profili regolari; vedi la docstring del modulo)
    capolinea: bool
    transito: bool
    n_corse: int  # corse osservate che toccano la stazione
    n_nascono: int
    n_finiscono: int
    n_passano: int
    n_incerti: int
    binari: list[str]  # unione di programmati ed effettivi, ordine naturale
    destinazioni: list[str]  # nomi, dei treni che vi nascono
    origini: list[str]  # nomi, dei treni che vi finiscono
    collegamenti: list[str]  # unione di destinazioni e origini, per frequenza complessiva
    frequenze: list[Frequenza]
    linee: list[LineaDellaStazione]
    vicini: list[Vicino]
    tratte: list[Tratta]

    @property
    def ha_dati(self) -> bool:
        return self.n_corse > 0

    def a_dict(self) -> dict:
        return asdict(self)


@dataclass
class Modello:
    stazioni: dict[str, Stazione]
    giorni: GiorniDati
    n_linee: int
    n_corse: int

    def indice(self) -> list[dict]:
        """Riga per stazione per la ricerca e le mappe, senza i dettagli."""
        return [
            {
                "codice": s.codice,
                "nome": s.nome,
                "citta": s.citta,
                "regione": s.regione_nome,
                "lat": s.lat,
                "lon": s.lon,
                "capolinea": s.capolinea,
                "transito": s.transito,
                "n_linee": len(s.linee),
                "n_corse": s.n_corse,
            }
            for s in sorted(self.stazioni.values(), key=lambda x: (x.nome or x.codice, x.codice))
        ]


# ---------------------------------------------------------------------------- calcolo


def _ordine_naturale(binario: str) -> tuple:
    return (0, int(binario), "") if binario.isdigit() else (1, 0, binario)


def _giorno(p: ProfiloTreno) -> date | None:
    try:
        return date.fromisoformat(p.data) if p.data else None
    except ValueError:
        return None


def _ora_locale(ms: int) -> int:
    return datetime.fromtimestamp((ms + offset_italia_ms(ms)) / 1000, UTC).hour


def _orario_fermata(f) -> int | None:
    for v in (f.arrivo_teorico, f.partenza_teorica, f.programmata):
        if v is not None:
            return v
    return None


def giorni_completi(profili: list[ProfiloTreno], soglia: float) -> GiorniDati:
    per_giorno: Counter[date] = Counter()
    for p in profili:
        g = _giorno(p)
        if g is not None:
            per_giorno[g] += 1
    if not per_giorno:
        return GiorniDati()
    massimo = max(per_giorno.values())
    out = GiorniDati()
    for g, n in sorted(per_giorno.items()):
        if n >= soglia * massimo:
            out.completi.setdefault(tipo_giorno(g).value, []).append(g.isoformat())
        else:
            out.parziali.append(g.isoformat())
    return out


def _ruolo_in_linea(linea: Linea, codice: str) -> str:
    if codice in (linea.estremo_a, linea.estremo_b):
        return "capolinea"
    if codice in linea.stazioni:
        return "intermedia"
    return "solo in alcune varianti"


def costruisci_modello(
    conn: sqlite3.Connection,
    *,
    soglia_giorno: float = SOGLIA_GIORNO_COMPLETO,
    solo: set[str] | None = None,
) -> Modello:
    """Il modello di tutte le stazioni (o solo quelle in `solo`) dal DB del crawler."""
    coordinate = db.coordinate_stazioni(conn)
    profili = db.carica_profili(conn, coordinate=coordinate)
    giorni = giorni_completi(profili, soglia_giorno)
    completi = {g for lista in giorni.completi.values() for g in lista}

    # una sola passata sui profili: ruolo, binari, frequenza
    n_corse: Counter[str] = Counter()
    nascono: Counter[str] = Counter()
    finiscono: Counter[str] = Counter()
    passano: Counter[str] = Counter()
    incerti: Counter[str] = Counter()
    binari: dict[str, set[str]] = defaultdict(set)
    dest: dict[str, Counter[str]] = defaultdict(Counter)
    orig: dict[str, Counter[str]] = defaultdict(Counter)
    conta_giorno: dict[tuple[str, str], int] = defaultdict(int)  # (stazione, tipo) -> corse
    conta_ora: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * 24)

    for p in profili:
        if p.itinerario is None:
            continue
        g = _giorno(p)
        valide = p.fermate_valide
        if not valide:
            continue
        parziale = any(f.soppressa for f in p.fermate)
        prima, ultima = valide[0], valide[-1]
        for s in {f.codice for f in valide}:  # una corsa conta una volta per stazione
            n_corse[s] += 1
        for f in valide:
            binari[f.codice].update(f.binari)
        if parziale:
            incerti[prima.codice] += 1
            if ultima.codice != prima.codice:
                incerti[ultima.codice] += 1
        else:
            nascono[prima.codice] += 1
            dest[prima.codice][ultima.nome] += 1
            if ultima.codice != prima.codice:
                finiscono[ultima.codice] += 1
                orig[ultima.codice][prima.nome] += 1
        for s in {f.codice for f in valide} - {prima.codice, ultima.codice}:
            passano[s] += 1
        for f in valide:
            s = f.codice
            if g is not None and g.isoformat() in completi:
                tipo = tipo_giorno(g).value
                conta_giorno[(s, tipo)] += 1
                ms = _orario_fermata(f)
                if ms is not None:
                    conta_ora[(s, tipo)][_ora_locale(ms)] += 1

    linee = costruisci_linee(profili)
    linee_di: dict[str, list[tuple[Linea, int]]] = defaultdict(list)
    for linea in linee:
        visti: Counter[str] = Counter()
        for v in linea.varianti:
            for cod in set(v.itinerario.codici):
                visti[cod] += v.n_treni
        for cod, n in visti.items():
            linee_di[cod].append((linea, n))

    vicini_di: dict[str, list[Vicino]] = defaultdict(list)
    for a in aggrega_archi(profili):
        x, y = a.coppia
        vicini_di[x].append(
            Vicino(y, a.nome_b, a.n_treni, a.durata_programmata_mediana, a.distanza_km)
        )
        vicini_di[y].append(
            Vicino(x, a.nome_a, a.n_treni, a.durata_programmata_mediana, a.distanza_km)
        )

    tratte_di: dict[str, list[Tratta]] = defaultdict(list)
    nomi = {
        r["stop_id"]: r["stop_name"] for r in conn.execute("SELECT stop_id, stop_name FROM stops")
    }
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='tratte'").fetchone():
        for r in conn.execute("SELECT * FROM tratte"):
            for mio, altro in ((r["nodo_a"], r["nodo_b"]), (r["nodo_b"], r["nodo_a"])):
                tratte_di[mio].append(
                    Tratta(
                        r["regione_codice"], r["tratta_ab"], r["tratta_ba"], altro, nomi.get(altro)
                    )
                )

    regioni = (
        {r["codice"]: r["nome"] for r in conn.execute("SELECT * FROM regioni")}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='regioni'").fetchone()
        else {}
    )

    righe = conn.execute("SELECT * FROM stops").fetchall()
    regione_di = regioni_geografiche(
        {r["stop_id"]: (r["stop_lat"], r["stop_lon"], r["regione_codice"]) for r in righe}
    )

    stazioni: dict[str, Stazione] = {}
    for r in righe:
        cod = r["stop_id"]
        valide = coordinate_valide(r["stop_lat"], r["stop_lon"])
        if solo is not None and cod not in solo:
            continue
        frequenze = []
        for tipo in TIPI_GIORNO:
            n_g = len(giorni.completi.get(tipo, []))
            if n_g:
                tot = conta_giorno.get((cod, tipo), 0)
                per_ora = [round(x / n_g, 2) for x in conta_ora.get((cod, tipo), [0] * 24)]
                frequenze.append(Frequenza(tipo, n_g, round(tot / n_g, 1), per_ora))
            else:
                frequenze.append(Frequenza(tipo, 0, None, [0.0] * 24))
        stazioni[cod] = Stazione(
            codice=cod,
            nome=r["stop_name"],
            citta=r["citta"],
            regione_codice=regione_di[cod],
            regione_nome=regioni.get(regione_di[cod]),
            lat=r["stop_lat"] if valide else None,
            lon=r["stop_lon"] if valide else None,
            capolinea=nascono[cod] + finiscono[cod] > 0,
            transito=passano[cod] > 0,
            n_corse=n_corse[cod],
            n_nascono=nascono[cod],
            n_finiscono=finiscono[cod],
            n_passano=passano[cod],
            n_incerti=incerti[cod],
            binari=sorted(binari.get(cod, ()), key=_ordine_naturale),
            destinazioni=[n for n, _ in dest[cod].most_common()],
            origini=[n for n, _ in orig[cod].most_common()],
            collegamenti=[n for n, _ in (dest[cod] + orig[cod]).most_common()],
            frequenze=frequenze,
            linee=[
                LineaDellaStazione(
                    chiave=linea.chiave,
                    nome=linea.nome,
                    estremo_a=linea.estremo_a,
                    estremo_b=linea.estremo_b,
                    n_treni=n,
                    ruolo=_ruolo_in_linea(linea, cod),
                    n_fermate=linea.completa.itinerario.n_fermate,
                )
                for linea, n in sorted(linee_di.get(cod, []), key=lambda x: (-x[1], x[0].chiave))
            ],
            vicini=sorted(vicini_di.get(cod, []), key=lambda v: (-v.n_treni, v.codice)),
            tratte=tratte_di.get(cod, []),
        )
    return Modello(stazioni, giorni, len(linee), len(profili))


__all__ = ["Itinerario", "Modello", "Stazione", "costruisci_modello", "giorni_completi"]
