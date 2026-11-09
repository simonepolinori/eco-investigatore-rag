"""Base comune del tool SQL di ECO (Giorno 4): SOLA LETTURA su qualsiasi database SQLite della missione.

Lo usano le missioni del Giorno 4 (sql_varco.py «Il cancello nero», sql_lete.py «Il primo respiro").
Le tre protezioni della sola lettura sono le stesse del notebook Tool_SQL del docente:
  - il file si apre in modalità read-only (mode=ro) con PRAGMA query_only;
  - un "authorizer" di SQLite permette solo SELECT sulle tabelle del file e un elenco chiuso di funzioni;
  - prima di eseguire, il codice rifiuta tutto ciò che non è UNA sola SELECT (DELETE, UPDATE, DROP, ATTACH, PRAGMA...).
Un limite di istruzioni ferma le query troppo pesanti; al modello arrivano al massimo 50 righe.
"""
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

# funzioni ammesse nelle query (tutte di sola lettura). LIKE e GLOB sono funzioni per SQLite: servono a cercare i nomi.
FUNZIONI = {'count', 'min', 'max', 'lower', 'upper', 'length', 'coalesce', 'sum', 'avg', 'like', 'glob', 'substr',
            'substring', 'trim', 'ltrim', 'rtrim', 'ifnull', 'instr', 'replace', 'round', 'abs', 'group_concat',
            'date', 'datetime', 'julianday', 'strftime', 'nullif', 'iif', 'typeof', 'total'}
MAX_RIGHE = 50
LIMITE_PASSI = 2000            # x 1000 istruzioni della macchina virtuale di SQLite: poi la query si ferma

_SCRITTURA = re.compile(r'\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|'
                        r'analyze|truncate|grant|revoke|begin|commit|rollback|savepoint|release)\b', re.I)


def norm(s):
    """minuscole e senza accenti (per confrontare i testi)"""
    s = unicodedata.normalize('NFKD', (s or '').lower().replace('’', "'"))
    return ''.join(c for c in s if not unicodedata.combining(c))


def sql_str(s):
    """un valore come stringa SQL sicura: 'Archivio Lete' (gli apici dentro raddoppiati)"""
    return "'" + str(s).replace("'", "''") + "'"


def impronta(p):
    """SHA-256 del file: la stessa prima e dopo ogni query = il database non è cambiato."""
    return hashlib.sha256(Path(p).read_bytes()).hexdigest() if p and Path(p).is_file() else None


def _togli_commenti_e_stringhe(q):
    q = re.sub(r'--[^\n]*', ' ', q)
    q = re.sub(r'/\*.*?\*/', ' ', q, flags=re.S)
    return re.sub(r"'(?:[^']|'')*'", "''", q)


def controlla_query(query):
    """Controllo prima di eseguire: None se va bene, altrimenti il motivo del rifiuto (nessuna esecuzione)."""
    if not isinstance(query, str) or not query.strip():
        return 'Scrivi una query SQL.'
    nuda = _togli_commenti_e_stringhe(query).strip().rstrip(';').strip()
    if ';' in nuda:
        return 'Una sola istruzione per volta.'
    if not re.match(r'(?is)^\s*(select|with)\b', nuda):
        return 'Il tool è di sola lettura: sono ammesse solo query SELECT.'
    m = _SCRITTURA.search(nuda)
    if m:
        return f'Il tool è di sola lettura: «{m.group(1).upper()}» non è ammesso.'
    return None


def tabelle_del_file(p):
    """Le tabelle vere del file (niente sqlite_master, niente tabelle interne di SQLite)."""
    con = sqlite3.connect(Path(p).as_uri() + '?mode=ro', uri=True)
    try:
        return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                                          "ORDER BY name")]
    finally:
        con.close()


def _valore(v):
    return v if v is None or isinstance(v, (int, float, str)) else str(v)


def interroga(query, p, tabelle=None, max_righe=MAX_RIGHE):
    """Esegue UNA query di lettura sul file p. Restituisce {'colonne', 'righe', 'altre_righe', 'ms', 'letture'} oppure
    {'errore', 'bloccata'}. Le righe sono liste; i codici restano testo (zeri iniziali conservati).
    tabelle = le tabelle che si possono leggere (di solito tutte quelle del file)."""
    motivo = controlla_query(query)
    if motivo:
        return {'errore': motivo, 'bloccata': True}
    if not p or not Path(p).is_file():
        return {'errore': 'Carica il database della missione (dall\'Archivio: lo ZIP del Giorno 4).', 'bloccata': False}
    ammesse = set(tabelle or tabelle_del_file(p))
    con = sqlite3.connect(Path(p).as_uri() + '?mode=ro', uri=True, check_same_thread=False)
    letture = []                               # (tabella, colonna) lette dalla query: servono al diagramma E/R
    try:
        con.execute('PRAGMA query_only=ON')

        def autorizza(azione, a1, a2, db, trigger):
            if azione == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if azione == sqlite3.SQLITE_READ:
                if a1 in ammesse:
                    letture.append((a1, a2))
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY
            if azione == sqlite3.SQLITE_FUNCTION:
                return sqlite3.SQLITE_OK if (a2 or '').lower() in FUNZIONI else sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_DENY          # anche le CTE ricorsive (SQLITE_RECURSIVE) e tutto il resto
        con.set_authorizer(autorizza)
        passi = [0]

        def limite():
            passi[0] += 1
            return 1 if passi[0] > LIMITE_PASSI else 0
        con.set_progress_handler(limite, 1000)
        t0 = time.perf_counter()
        cur = con.execute(query)
        righe = cur.fetchmany(max_righe + 1)
        colonne = [x[0] for x in cur.description] if cur.description else []
        return {'colonne': colonne, 'righe': [[_valore(v) for v in r] for r in righe[:max_righe]],
                'altre_righe': len(righe) > max_righe, 'ms': round(1000 * (time.perf_counter() - t0), 2),
                'letture': sorted({f'{t}.{c}' for t, c in letture if c})}
    except sqlite3.Error as e:
        testo = str(e)
        if 'interrupted' in testo:
            testo = 'Query troppo pesante: fermata dal limite di istruzioni.'
        elif 'not authorized' in testo or 'prohibited' in testo:
            testo = ('Non autorizzato: il tool legge solo le tabelle del database della missione, con funzioni '
                     'di lettura (' + testo + ').')
        return {'errore': testo, 'bloccata': 'autorizzato' in testo.lower()}
    finally:
        con.close()


# ─────────────────────────── il formato delle risposte del modello ───────────────────────────
def leggi_json(testo):
    """Il JSON proposto dal modello, anche dentro ```json ... ``` o con testo intorno. None se non c'è."""
    if not testo:
        return None
    t = re.sub(r'^```(?:json|sql)?\s*|\s*```$', '', testo.strip(), flags=re.I).strip()
    m = re.search(r'\{.*\}', t, re.S)
    for prova in (t, m.group(0) if m else None):
        if not prova:
            continue
        try:
            x = json.loads(prova)
            if isinstance(x, dict) and ('sql' in x or 'fine' in x):
                return x
        except ValueError:
            continue
    m = re.search(r'(?is)\b((?:select|with)\b.+?)(?:;|```|$)', t)    # il modello ha scritto solo la query, senza JSON
    if m and len(m.group(1)) < 4000:
        return {'sql': m.group(1).strip()}
    return None


def genera(messaggi, max_tokens=400, temperatura=0.1):
    """Come la funzione genera() del notebook del docente: lista di messaggi (system + user + ...) → testo del modello.
    Usa i motori di ECO (Gemini, con Qwen di riserva). Restituisce '' se nessun modello è disponibile."""
    import motori
    sistema = '\n'.join(m['content'] for m in messaggi if m['role'] == 'system')
    altri = [m for m in messaggi if m['role'] != 'system'] or [{'role': 'user', 'content': '...'}]
    testo, info = '', None
    for testo, info in motori.rispondi(sistema, altri, max_tokens=max_tokens, temperatura=temperatura):
        pass
    if not info or info.get('motore') == 'nessuno':
        return ''
    return testo


def conversazione(cronologia, n=6):
    """Le ultime battute della chat, in breve (per il prompt del generatore di query)."""
    out = []
    for m in (cronologia or [])[-n:]:
        if isinstance(m, dict) and m.get('role') in ('user', 'assistant'):
            righe = str(m.get('content', '')).strip().splitlines()
            testo = ' '.join(r for r in righe if not r.startswith(('⏱', '📂', '_⏱', '_📂', '🗄')))[:600]
            out.append(f'{"Utente" if m["role"] == "user" else "ECO"}: {testo}')
    return '\n'.join(out) or '(prima domanda)'


# ─────────────────────────── richieste di modifica: il tool non le esegue mai ───────────────────────────
_VERBI_MODIFICA = (r'(?:cancella|cancellate|cancellare|elimina|eliminate|eliminare|rimuovi|rimuovete|rimuovere|svuota|'
                   r'svuotate|svuotare|distruggi|distruggere|modifica|modificate|modificare|aggiorna|aggiornate|aggiornare|'
                   r'inserisci|inserite|inserire|aggiungi|aggiungete|aggiungere|sostituisci|sostituire|riattiva|riattivate|'
                   r'riattivare|revoca|revocate|revocare|prolunga|prolungate|prolungare|estendi|estendere|azzera|azzerare|'
                   r'resetta|resettare|cambia|cambiate|cambiare|sblocca|sbloccate|sbloccare|togli|togliete|togliere|'
                   r'annulla|annullate|annullare|sospendi|sospendere)')
_MODIFICA = re.compile(r'(?:^|[.!?,;:]\s*|\b(?:puoi|potete|potresti|devi|dovresti|voglio|vorrei|fammi|per favore|ora|adesso|'
                       r'allora|subito|eco|tu|che tu)\s+(?:\w+\s+)?)' + _VERBI_MODIFICA + r'\b', re.I)
_OGGETTO_DB = re.compile(r'\b(database|db|dati|tabell\w*|righ\w*|permess\w*|access\w*|codic\w*|autorizzaz\w*|'
                         r'operator\w*|deposit\w*|record|sql|pratica|pratiche|scadenz\w*|stato|revoc\w*|sospension\w*|'
                         r'abilitazion\w*|terminal\w*|chiav\w*|varc\w*|squadr\w*|finestr\w*|blocc\w*)\b', re.I)
_SQL_SCRITTURA = re.compile(r'\b(delete\s+from|drop\s+(table|database|index|view)|update\s+\w+\s+set|insert\s+into|'
                            r'alter\s+table|truncate\s+table|attach\s+database|replace\s+into)\b', re.I)


def richiesta_di_modifica(domanda):
    """«Cancella i permessi revocati», «togli la sospensione», «DROP TABLE r08»: il tool è di sola lettura."""
    d = norm(domanda).strip()
    return bool(_MODIFICA.search(d) and _OGGETTO_DB.search(d)) or bool(_SQL_SCRITTURA.search(domanda))
