# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Viste SQL riassuntive per dashboard e wiki: stazioni, binari, treni, giorni.

Le viste leggono solo `treni`, `fermate`, `stops` e `regioni`. Non scrivono nulla e non hanno
stato: si ricreano da zero (`DROP` + `CREATE`) quando cambia il loro testo. La versione e' un
hash dell'SQL, salvato in `crawler_stato`: `aggiorna_viste` non fa niente se e' invariata.

Le definizioni sono **le stesse della libreria** (`viaggiatreno.insights`), perche' dashboard e
tool MCP devono dare la stessa risposta. Dove differiscono e' scritto qui sotto:

- **ordine delle fermate**: `fermate.id` (l'ordine dell'API), mai `progressivo`, che in alcuni
  treni e' ripetuto o non crescente;
- **origine/destinazione effettive**: prima e ultima fermata *non soppressa* del treno;
- **corsa di una stazione**: un treno distinto con una fermata *non soppressa* li';
- **binari**: l'*unione* di programmato ed effettivo, sulle fermate non soppresse;
- **capolinea**: almeno un treno vi nasce o vi finisce, senza contare i treni parzialmente
  soppressi (finiscono in `n_incerti`); **transito**: almeno un treno vi passa. Possono valere
  entrambi. A differenza della libreria non c'e' la "deduzione" dei terminali: qui la
  destinazione e' dichiarata (viene da `andamentoTreno`, non da un tabellone);
- **giorno**: la data locale di `data_partenza_treno` (mezzanotte locale in ms). Si calcola con
  +12 ore e `date()` in UTC, che da' il giorno giusto in orario solare e legale senza dipendere
  dal fuso del processo.

Limiti:

- Le viste vedono solo i treni **verificati** (con `fermate`): una corsa solo scoperta dai
  tabelloni conta in `v_treno` ma non in `v_fermata` e quindi non nelle stazioni.
- Un giorno incompleto (il primo e l'ultimo dei dati) falsa i confronti: usare `v_stops_giorno`
  e non sommare giorni diversi per "treni al giorno".
- Sono viste, non tabelle: ogni interrogazione ricalcola. Su ~240.000 fermate la piu' pesante
  (`v_stops`) impiega circa 1-2 secondi; se non basta si materializza in una tabella.
"""

from __future__ import annotations

import hashlib
import sqlite3

_CHIAVE_VERSIONE = "viste_versione"

# L'ordine conta: ogni vista puo' usare solo quelle che la precedono.
VISTE: dict[str, str] = {
    # ------------------------------------------------------------------ una riga per corsa
    "v_treno": """
CREATE VIEW v_treno AS
SELECT
    t.id AS treno_id,
    t.numero_treno,
    t.cod_origine,
    t.data_partenza_treno,
    date((t.data_partenza_treno + 43200000) / 1000, 'unixepoch') AS giorno,
    t.categoria,
    t.codice_cliente,
    t.stato,
    t.chiusura_motivo,
    t.ritardo_corrente,
    t.ritardo_finale,
    COALESCE(a.n_fermate, 0) AS n_fermate,
    COALESCE(a.n_soppresse, 0) AS n_soppresse,
    COALESCE(a.n_soppresse, 0) > 0 AS parziale,
    fo.stop_id AS origine_effettiva,
    fd.stop_id AS destinazione_effettiva
FROM treni t
LEFT JOIN (
    SELECT treno_id,
           COUNT(*) AS n_fermate,
           SUM(COALESCE(actual_fermata_type, -1) = 3) AS n_soppresse,
           MIN(CASE WHEN COALESCE(actual_fermata_type, -1) != 3 THEN id END) AS id_prima,
           MAX(CASE WHEN COALESCE(actual_fermata_type, -1) != 3 THEN id END) AS id_ultima
    FROM fermate GROUP BY treno_id
) a ON a.treno_id = t.id
LEFT JOIN fermate fo ON fo.id = a.id_prima
LEFT JOIN fermate fd ON fd.id = a.id_ultima
""",
    # ------------------------------------------------------------------ una riga per fermata
    "v_fermata": """
CREATE VIEW v_fermata AS
SELECT
    f.id AS fermata_id,
    f.treno_id,
    f.stop_id,
    t.numero_treno,
    t.giorno,
    t.categoria,
    t.codice_cliente,
    (COALESCE(f.actual_fermata_type, -1) = 3) AS soppressa,
    t.parziale AS treno_parziale,
    t.origine_effettiva,
    t.destinazione_effettiva,
    CASE
        WHEN COALESCE(f.actual_fermata_type, -1) = 3 THEN 'soppressa'
        WHEN f.stop_id = t.origine_effettiva THEN 'origina'
        WHEN f.stop_id = t.destinazione_effettiva THEN 'termina'
        ELSE 'passa'
    END AS ruolo,
    f.binario_programmato,
    f.binario_effettivo,
    (f.binario_programmato IS NOT NULL AND f.binario_effettivo IS NOT NULL
        AND f.binario_programmato != f.binario_effettivo) AS binario_cambiato,
    f.ritardo
FROM fermate f
JOIN v_treno t ON t.treno_id = f.treno_id
""",
    # ------------------------------------------------------------------ binari usati (interna)
    "v_fermata_binario": """
CREATE VIEW v_fermata_binario AS
SELECT stop_id, binario_programmato AS binario, 'p' AS tipo, treno_id, giorno, binario_cambiato
FROM v_fermata WHERE NOT soppressa AND binario_programmato IS NOT NULL
UNION ALL
SELECT stop_id, binario_effettivo, 'e', treno_id, giorno, binario_cambiato
FROM v_fermata WHERE NOT soppressa AND binario_effettivo IS NOT NULL
""",
    # ------------------------------------------------------------------ una riga per stazione
    "v_stops": """
CREATE VIEW v_stops AS
SELECT
    s.stop_id,
    s.stop_name,
    s.citta,
    s.regione_codice,
    r.nome AS regione_nome,
    s.stop_lat,
    s.stop_lon,
    s.fonte,
    COALESCE(a.n_corse, 0) AS n_corse,
    COALESCE(a.n_numeri, 0) AS n_numeri,
    COALESCE(a.n_giorni, 0) AS n_giorni,
    a.primo_giorno,
    a.ultimo_giorno,
    COALESCE(a.n_nascono, 0) AS n_nascono,
    COALESCE(a.n_finiscono, 0) AS n_finiscono,
    COALESCE(a.n_passano, 0) AS n_passano,
    COALESCE(a.n_incerti, 0) AS n_incerti,
    COALESCE(a.n_nascono, 0) + COALESCE(a.n_finiscono, 0) > 0 AS capolinea,
    COALESCE(a.n_passano, 0) > 0 AS transito,
    COALESCE(a.n_destinazioni, 0) AS n_destinazioni,
    COALESCE(a.n_origini, 0) AS n_origini,
    COALESCE(b.n_binari, 0) AS n_binari,
    COALESCE(b.n_programmati, 0) AS n_binari_programmati,
    COALESCE(b.n_effettivi, 0) AS n_binari_effettivi,
    COALESCE(a.n_corse_soppresse, 0) AS n_corse_soppresse,
    COALESCE(a.n_cambi_binario, 0) AS n_cambi_binario
FROM stops s
LEFT JOIN regioni r ON r.codice = s.regione_codice
LEFT JOIN (
    SELECT stop_id,
        COUNT(DISTINCT CASE WHEN NOT soppressa THEN treno_id END) AS n_corse,
        COUNT(DISTINCT CASE WHEN NOT soppressa THEN numero_treno END) AS n_numeri,
        COUNT(DISTINCT CASE WHEN NOT soppressa THEN giorno END) AS n_giorni,
        MIN(CASE WHEN NOT soppressa THEN giorno END) AS primo_giorno,
        MAX(CASE WHEN NOT soppressa THEN giorno END) AS ultimo_giorno,
        COUNT(DISTINCT CASE WHEN ruolo = 'origina' AND NOT treno_parziale THEN treno_id END)
            AS n_nascono,
        COUNT(DISTINCT CASE WHEN ruolo = 'termina' AND NOT treno_parziale THEN treno_id END)
            AS n_finiscono,
        COUNT(DISTINCT CASE WHEN ruolo = 'passa' THEN treno_id END) AS n_passano,
        COUNT(DISTINCT CASE WHEN ruolo IN ('origina', 'termina') AND treno_parziale
                            THEN treno_id END) AS n_incerti,
        COUNT(DISTINCT CASE WHEN NOT soppressa AND destinazione_effettiva != stop_id
                            THEN destinazione_effettiva END) AS n_destinazioni,
        COUNT(DISTINCT CASE WHEN NOT soppressa AND origine_effettiva != stop_id
                            THEN origine_effettiva END) AS n_origini,
        COUNT(DISTINCT CASE WHEN soppressa THEN treno_id END) AS n_corse_soppresse,
        COUNT(DISTINCT CASE WHEN NOT soppressa AND binario_cambiato THEN treno_id END)
            AS n_cambi_binario
    FROM v_fermata GROUP BY stop_id
) a ON a.stop_id = s.stop_id
LEFT JOIN (
    SELECT stop_id,
        COUNT(DISTINCT binario) AS n_binari,
        COUNT(DISTINCT CASE WHEN tipo = 'p' THEN binario END) AS n_programmati,
        COUNT(DISTINCT CASE WHEN tipo = 'e' THEN binario END) AS n_effettivi
    FROM v_fermata_binario GROUP BY stop_id
) b ON b.stop_id = s.stop_id
""",
    # ------------------------------------------------------------------ stazione x giorno
    "v_stops_giorno": """
CREATE VIEW v_stops_giorno AS
SELECT
    a.stop_id,
    s.stop_name,
    a.giorno,
    a.n_corse,
    a.n_nascono,
    a.n_finiscono,
    a.n_passano,
    a.n_destinazioni,
    COALESCE(b.n_binari, 0) AS n_binari
FROM (
    SELECT stop_id, giorno,
        COUNT(DISTINCT treno_id) AS n_corse,
        COUNT(DISTINCT CASE WHEN ruolo = 'origina' AND NOT treno_parziale THEN treno_id END)
            AS n_nascono,
        COUNT(DISTINCT CASE WHEN ruolo = 'termina' AND NOT treno_parziale THEN treno_id END)
            AS n_finiscono,
        COUNT(DISTINCT CASE WHEN ruolo = 'passa' THEN treno_id END) AS n_passano,
        COUNT(DISTINCT CASE WHEN destinazione_effettiva != stop_id
                            THEN destinazione_effettiva END) AS n_destinazioni
    FROM v_fermata WHERE NOT soppressa GROUP BY stop_id, giorno
) a
JOIN stops s ON s.stop_id = a.stop_id
LEFT JOIN (
    SELECT stop_id, giorno, COUNT(DISTINCT binario) AS n_binari
    FROM v_fermata_binario GROUP BY stop_id, giorno
) b ON b.stop_id = a.stop_id AND b.giorno = a.giorno
""",
    # ------------------------------------------------------------------ stazione x binario
    "v_stop_binari": """
CREATE VIEW v_stop_binari AS
SELECT
    b.stop_id,
    s.stop_name,
    b.binario,
    COUNT(DISTINCT b.treno_id) AS n_corse,
    COUNT(DISTINCT CASE WHEN b.tipo = 'p' THEN b.treno_id END) AS n_programmato,
    COUNT(DISTINCT CASE WHEN b.tipo = 'e' THEN b.treno_id END) AS n_reale,
    COUNT(DISTINCT CASE WHEN b.binario_cambiato THEN b.treno_id END) AS n_cambiati,
    COUNT(DISTINCT b.giorno) AS n_giorni
FROM v_fermata_binario b
JOIN stops s ON s.stop_id = b.stop_id
GROUP BY b.stop_id, b.binario
""",
}


def versione() -> str:
    """Hash dell'SQL delle viste: cambia solo se cambia una definizione."""
    h = hashlib.sha256()
    for nome, sql in VISTE.items():
        h.update(nome.encode())
        h.update(sql.encode())
    return h.hexdigest()[:16]


def _versione_salvata(conn: sqlite3.Connection) -> str | None:
    try:
        r = conn.execute(
            "SELECT valore FROM crawler_stato WHERE chiave = ?", (_CHIAVE_VERSIONE,)
        ).fetchone()
    except sqlite3.OperationalError:  # tabella non ancora creata
        return None
    return None if r is None else str(r[0])


def crea_viste(conn: sqlite3.Connection) -> None:
    """(Ri)crea tutte le viste in una sola transazione e salva la versione.

    Se una vista fallisce non resta niente a meta': la transazione viene annullata. Salva prima
    eventuali scritture in sospeso del chiamante: `BEGIN` non puo' stare dentro un'altra
    transazione, e nel motore la connessione puo' averne una aperta.
    """
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for nome in reversed(VISTE):
            conn.execute(f"DROP VIEW IF EXISTS {nome}")
        for sql in VISTE.values():
            conn.execute(sql)
        conn.execute(
            "INSERT INTO crawler_stato (chiave, valore) VALUES (?, ?) "
            "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore",
            (_CHIAVE_VERSIONE, versione()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def aggiorna_viste(conn: sqlite3.Connection, *, forza: bool = False) -> bool:
    """Ricrea le viste solo se la versione salvata differisce. Restituisce `True` se le ha scritte.

    Se tutte le viste esistono gia' ed e' la stessa versione non scrive niente, cosi' un secondo
    processo che apre il DB mentre il crawler lavora non prende il lock di scrittura.
    """
    if not forza and _versione_salvata(conn) == versione():
        esistenti = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'")
        }
        if set(VISTE) <= esistenti:
            return False
    crea_viste(conn)
    return True
