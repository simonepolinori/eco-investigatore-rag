"""Tool SQL di ECO · Giorno 4 · missione «Il cancello nero» (Squadra_3_2.zip): accessi.sqlite, SOLO IN LETTURA.

È il codice del primo tool SQL (operatori, depositi, accessi): resta uguale, così il «vecchio test» funziona ancora.
La missione «Il primo respiro» (14 tabelle) è in sql_lete.py; database.py sceglie quale delle due usare.

Come funziona il collegamento (lo stesso schema del notebook Tool_SQL del docente, ma dentro ECO):
  1. la domanda in linguaggio naturale arriva all'assistente;
  2. il MODELLO (Gemini o Qwen, motori.py) propone UNA query SQL di lettura, in JSON: {"sql": "SELECT ..."};
  3. il CODICE la controlla e la esegue con interroga_database() (sola lettura, tre protezioni);
  4. il risultato (colonne e righe) torna al modello, che scrive la risposta con le fonti;
  5. il codice controlla la risposta: nessun codice inventato, zeri iniziali conservati.
La query e le righe usate si vedono in chat (pannello «🗄 Query SQL») e nel diagramma E/R interattivo.

Le tre protezioni della sola lettura (nessuna modifica possibile al database):
  - il file si apre in modalità read-only (mode=ro) con PRAGMA query_only;
  - un "authorizer" di SQLite permette solo SELECT sulle tre tabelle e un elenco chiuso di funzioni;
  - prima di eseguire, il codice rifiuta tutto ciò che non è una sola SELECT (DELETE, UPDATE, DROP, ATTACH, PRAGMA...).
Un limite di istruzioni ferma le query troppo pesanti; al modello arrivano al massimo 50 righe.

Se il modello non è disponibile o propone due volte una query sbagliata, il codice costruisce una query di riserva
con gli indizi trovati nella domanda, nella conversazione e nel dossier (e lo dice chiaramente: origine = «riserva»).
"""
import hashlib
import json
import re
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path

import config

# ─────────────────────────── schema (dal notebook Tool_SQL del docente) ───────────────────────────
SCHEMA = '''operatori(id, nome)
depositi(id, nome, settore)
accessi(id, operatore_id, deposito_id, pratica, codice, stato, valido_fino)
accessi.operatore_id collega operatori.id; accessi.deposito_id collega depositi.id.
Il codice è testo: conserva eventuali zeri iniziali.
Data della missione: {data}. stato deve essere attivo, valido_fino almeno pari a questa data.
I dati richiesti per la ricerca arrivano dai dossier. Se mancano, chiedili all'utente.'''

TABELLE = ('operatori', 'depositi', 'accessi')
# funzioni ammesse nelle query (tutte di sola lettura). LIKE e GLOB sono funzioni per SQLite: servono a cercare i nomi.
FUNZIONI = {'count', 'min', 'max', 'lower', 'upper', 'length', 'coalesce', 'sum', 'avg', 'like', 'glob', 'substr',
            'substring', 'trim', 'ltrim', 'rtrim', 'ifnull', 'instr', 'replace', 'round', 'abs', 'group_concat',
            'date', 'datetime', 'julianday', 'strftime', 'nullif', 'iif', 'typeof'}
MAX_RIGHE = 50
LIMITE_PASSI = 1000            # x 1000 istruzioni della macchina virtuale di SQLite: poi la query si ferma

DESCRIZIONI = {   # per il diagramma E/R e per il prompt
    'operatori': 'Le persone che possono ricevere un permesso.',
    'depositi': 'I depositi e il loro settore.',
    'accessi': 'I permessi: chi (operatore) può entrare dove (deposito), con quale pratica e codice, stato e scadenza.',
    'operatori.id': 'chiave primaria', 'operatori.nome': 'nome dell\'operatore',
    'depositi.id': 'chiave primaria', 'depositi.nome': 'nome del deposito', 'depositi.settore': 'settore del deposito',
    'accessi.id': 'chiave primaria', 'accessi.operatore_id': 'chiave esterna → operatori.id',
    'accessi.deposito_id': 'chiave esterna → depositi.id', 'accessi.pratica': 'pratica che autorizza il permesso',
    'accessi.codice': 'codice di accesso (TESTO: può iniziare con zero)', 'accessi.stato': 'attivo oppure revocato',
    'accessi.valido_fino': 'scadenza del permesso (AAAA-MM-GG hh:mm)',
}

_cache = {'percorso': None, 'firma': None, 'valori': None, 'impronta': None}
_LOCK = threading.Lock()


def data_missione():
    return getattr(config, 'DATA_MISSIONE', '2031-10-12 06:00')


def schema_testo():
    return SCHEMA.format(data=data_missione())


# ─────────────────────────── dove sta il database ───────────────────────────
def percorso():
    """accessi.sqlite: in dati/database/ (dove lo mette il caricamento dello ZIP), oppure accanto al programma."""
    nome = getattr(config, 'DATABASE_NOME', 'accessi.sqlite')
    for c in (config.DATI / 'database' / nome, config.CARTELLA / nome, config.DATI / nome, Path.cwd() / nome):
        if c.is_file():
            return c
    # solo il database di QUESTA missione (nella stessa cartella può esserci archivio_recuperato.sqlite dell'altra)
    trovati = sorted(config.DATI.glob('**/accessi*.sqlite')) + sorted(config.DATI.glob('**/accessi*.db'))
    return trovati[0] if trovati else None


def disponibile():
    return percorso() is not None


def _impronta(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def impronta():
    """SHA-256 del file: la stessa prima e dopo ogni query = il database non è cambiato."""
    p = percorso()
    return _impronta(p) if p else None


# ─────────────────────────── il tool: interroga_database ───────────────────────────
_SCRITTURA = re.compile(r'\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|'
                        r'analyze|truncate|grant|revoke|begin|commit|rollback|savepoint|release)\b', re.I)


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


def interroga_database(query, database=None):
    """Esegue UNA query di lettura. Restituisce {'colonne', 'righe', 'altre_righe', 'ms', 'letture'} oppure
    {'errore', 'bloccata'}. Le righe sono liste; il codice resta testo (zeri iniziali conservati)."""
    motivo = controlla_query(query)
    if motivo:
        return {'errore': motivo, 'bloccata': True}
    p = Path(database).resolve() if database else percorso()
    if not p or not p.is_file():
        return {'errore': 'Carica il database della tua squadra (accessi.sqlite, ZIP del giorno 4).', 'bloccata': False}
    con = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True, check_same_thread=False)
    letture = []                               # (tabella, colonna) lette dalla query: servono al diagramma E/R
    try:
        con.execute('PRAGMA query_only=ON')

        def autorizza(azione, a1, a2, db, trigger):
            if azione == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if azione == sqlite3.SQLITE_READ:
                if a1 in TABELLE:
                    letture.append((a1, a2))
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY
            if azione == sqlite3.SQLITE_FUNCTION:
                return sqlite3.SQLITE_OK if (a2 or '').lower() in FUNZIONI else sqlite3.SQLITE_DENY
            if azione == getattr(sqlite3, 'SQLITE_RECURSIVE', -99):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_DENY
        con.set_authorizer(autorizza)
        passi = [0]

        def limite():
            passi[0] += 1
            return 1 if passi[0] > LIMITE_PASSI else 0
        con.set_progress_handler(limite, 1000)
        t0 = time.perf_counter()
        cur = con.execute(query)
        righe = cur.fetchmany(MAX_RIGHE + 1)
        colonne = [x[0] for x in cur.description] if cur.description else []
        return {'colonne': colonne, 'righe': [[_valore(v) for v in r] for r in righe[:MAX_RIGHE]],
                'altre_righe': len(righe) > MAX_RIGHE, 'ms': round(1000 * (time.perf_counter() - t0), 2),
                'letture': sorted({f'{t}.{c}' for t, c in letture if c})}
    except sqlite3.Error as e:
        testo = str(e)
        if 'interrupted' in testo:
            testo = 'Query troppo pesante: fermata dal limite di istruzioni.'
        elif 'not authorized' in testo or 'prohibited' in testo:
            testo = ('Non autorizzato: il tool legge solo le tabelle operatori, depositi e accessi, con funzioni '
                     'di lettura (' + testo + ').')
        return {'errore': testo, 'bloccata': 'autorizzato' in testo.lower()}
    finally:
        con.close()


def _valore(v):
    return v if v is None or isinstance(v, (int, float, str)) else str(v)


# ─────────────────────────── struttura e valori (per il diagramma E/R e per gli indizi) ───────────────────────────
def struttura():
    """Schema reale letto dal file (colonne, tipi, chiavi), righe per tabella e cardinalità calcolate sui dati."""
    p = percorso()
    if not p:
        return {'disponibile': False}
    con = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True)
    try:
        tabelle = []
        for t in TABELLE:
            col = con.execute(f'PRAGMA table_info({t})').fetchall()
            fk = {r[3]: (r[2], r[4]) for r in con.execute(f'PRAGMA foreign_key_list({t})').fetchall()}
            if t == 'accessi':   # se il file non dichiara le chiavi esterne, valgono quelle dello schema del docente
                fk.setdefault('operatore_id', ('operatori', 'id'))
                fk.setdefault('deposito_id', ('depositi', 'id'))
            tabelle.append({'nome': t, 'righe': con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0],
                            'descrizione': DESCRIZIONI.get(t, ''),
                            'colonne': [{'nome': c[1], 'tipo': c[2] or 'TEXT', 'pk': bool(c[5]), 'notnull': bool(c[3]),
                                         'fk': (f'{fk[c[1]][0]}.{fk[c[1]][1]}' if c[1] in fk else None),
                                         'descrizione': DESCRIZIONI.get(f'{t}.{c[1]}', '')} for c in col]})

        def card(fk_col, tab):
            senza = con.execute(f'SELECT COUNT(*) FROM {tab} t WHERE NOT EXISTS '
                                f'(SELECT 1 FROM accessi a WHERE a.{fk_col}=t.id)').fetchone()[0]
            mx = con.execute(f'SELECT MAX(n) FROM (SELECT COUNT(*) n FROM accessi GROUP BY {fk_col})').fetchone()[0] or 0
            nulli = con.execute(f'SELECT COUNT(*) FROM accessi WHERE {fk_col} IS NULL').fetchone()[0]
            orfani = con.execute(f'SELECT COUNT(*) FROM accessi a WHERE a.{fk_col} IS NOT NULL AND NOT EXISTS '
                                 f'(SELECT 1 FROM {tab} t WHERE t.id=a.{fk_col})').fetchone()[0]
            return {'lato_entita': f'({0 if senza else 1},N)', 'lato_accesso': f'({0 if nulli else 1},1)',
                    'senza_accessi': senza, 'massimo': mx, 'nulli': nulli, 'orfani': orfani}
        relazioni = [
            {'nome': 'possiede', 'da': 'operatori', 'a': 'accessi', 'chiave': 'accessi.operatore_id', 'riferisce': 'operatori.id',
             'join': 'accessi.operatore_id = operatori.id', **card('operatore_id', 'operatori')},
            {'nome': 'riguarda', 'da': 'depositi', 'a': 'accessi', 'chiave': 'accessi.deposito_id', 'riferisce': 'depositi.id',
             'join': 'accessi.deposito_id = depositi.id', **card('deposito_id', 'depositi')},
        ]
        stati = dict(con.execute('SELECT stato, COUNT(*) FROM accessi GROUP BY stato').fetchall())
        scadenze = dict(con.execute('SELECT valido_fino, COUNT(*) FROM accessi GROUP BY valido_fino').fetchall())
        return {'disponibile': True, 'file': p.name, 'tabelle': tabelle, 'relazioni': relazioni, 'stati': stati,
                'scadenze': scadenze, 'data_missione': data_missione(), 'schema': schema_testo(),
                'impronta': _impronta(p)[:16]}
    finally:
        con.close()


def esempi(tabella, n=8):
    if tabella not in TABELLE:
        return {'errore': 'tabella sconosciuta'}
    return interroga_database(f'SELECT * FROM {tabella} LIMIT {int(n)}')


def valori():
    """Nomi di operatori e depositi, settori e pratiche presenti nel database (per riconoscere gli indizi)."""
    p = percorso()
    if not p:
        return None
    firma = (str(p), p.stat().st_mtime, p.stat().st_size)
    with _LOCK:
        if _cache['firma'] != firma:
            con = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True)
            try:
                _cache['valori'] = {
                    'operatori': [r[0] for r in con.execute('SELECT DISTINCT nome FROM operatori')],
                    'depositi': [r[0] for r in con.execute('SELECT DISTINCT nome FROM depositi')],
                    'settori': [r[0] for r in con.execute('SELECT DISTINCT settore FROM depositi')],
                    'pratiche': [r[0] for r in con.execute('SELECT DISTINCT pratica FROM accessi WHERE pratica IS NOT NULL')],
                    'codici': {r[0] for r in con.execute('SELECT codice FROM accessi WHERE codice IS NOT NULL')},
                }
            finally:
                con.close()
            _cache['firma'] = firma
        return _cache['valori']


def settori_di(deposito):
    r = interroga_database(f'SELECT settore FROM depositi WHERE nome = {_sql_str(deposito)}')
    return [x[0] for x in r.get('righe') or []]


def _norm(s):
    s = unicodedata.normalize('NFKD', (s or '').lower().replace('’', "'"))
    return ''.join(c for c in s if not unicodedata.combining(c))


def _cerca_valore(valore, testo_norm):
    return re.search(r'(?<![\w])' + re.escape(_norm(valore)) + r'(?![\w])', testo_norm) is not None


def indizi(testo):
    """Persona, deposito, settore e pratica che compaiono nel testo E nel database (niente valori inventati)."""
    v = valori()
    if not v:
        return {}
    t = _norm(testo)
    out = {}
    for chiave, lista in (('persona', v['operatori']), ('deposito', v['depositi'])):
        trovati = [x for x in lista if _cerca_valore(x, t)]
        if trovati:
            out[chiave] = max(trovati, key=len)          # «Marta Riva», non un nome contenuto in un altro
    sett = [x for x in v['settori'] if re.search(r'(?<![\w-])' + re.escape(x) + r'(?![\w-])', testo)]
    if sett:   # se c'è il deposito, prima il suo settore (il dossier nomina anche il settore della pista falsa)
        suo = settori_di(out['deposito']) if out.get('deposito') else []
        out['settore'] = next((x for x in sett if x in suo), sett[0])
    prat = [x for x in v['pratiche'] if re.search(r'(?<![\w-])' + re.escape(x) + r'(?![\w-])', testo, re.I)]
    if prat:
        out['pratica'] = prat[0]
    # valori scritti nella domanda che NON esistono nel database (prove «pratica inesistente», «Darsena Vuota»...):
    # restano negli indizi, così la query li cerca davvero e non trova niente (nessun codice inventato)
    inesistenti = []
    if 'pratica' not in out:
        m = re.search(r'\bpratic\w*\s+(?:n\.?\s*)?([A-Z]{1,4}-?\d{2,5})\b', testo, re.I) or \
            re.search(r'\b((?:RV|PX)-?\d{2,5})\b', testo, re.I)
        if m:
            out['pratica'] = m.group(1).upper()
            inesistenti.append('pratica')
    if 'settore' not in out:
        m = re.search(r'\bsettore\s+([A-Z]{1,2}\d{1,3})\b', testo)
        if m:
            out['settore'] = m.group(1)
            inesistenti.append('settore')
    if 'deposito' not in out:
        m = re.search(r"\b(?:deposito|magazzino)\s+(?:di\s+|del\s+|della\s+)?([A-ZÀ-Ý][\wà-ÿ']+(?:\s+[A-ZÀ-Ý][\wà-ÿ']+)?)", testo) \
            or re.search(r"\b(Darsena\s+Vuota)\b", testo, re.I)
        if m and m.group(1).split()[0].lower() not in ('il', 'la', 'lo', 'un', 'una'):
            out['deposito'] = m.group(1).strip()
            inesistenti.append('deposito')
    if 'persona' not in out:
        m = re.search(r"\b(?:operatore|operatrice|persona|di|per|a|ad)\s+([A-ZÀ-Ý][a-zà-ÿ']+\s+[A-ZÀ-Ý][a-zà-ÿ']+)\b", testo)
        if m and not ({w for w in m.group(1).split()} & _NON_PERSONE):
            out['persona'] = m.group(1)
            inesistenti.append('persona')
    if inesistenti:
        out['inesistenti'] = inesistenti
    return out


_NON_PERSONE = set('Cripta Nord Darsena Vuota San Leone Pietro Ripetitore Ferro Velo Roma Giorno Operazione Varco Deposito '
                   'Settore Protocollo Lazzaro LAZZARO Database Marta'.split())


def chiavi_note(ind):
    """Le chiavi degli indizi (persona, deposito, settore, pratica) già fissate, esistenti o no."""
    return [k for k in ('persona', 'deposito', 'settore', 'pratica') if ind.get(k)]


def _sql_str(s):
    return "'" + str(s).replace("'", "''") + "'"


_SELECT_COMPLETO = ('SELECT a.id, o.nome AS operatore, d.nome AS deposito, d.settore, a.pratica, a.codice, a.stato, '
                    'a.valido_fino\nFROM accessi a\nJOIN operatori o ON o.id = a.operatore_id\n'
                    'JOIN depositi d ON d.id = a.deposito_id')


def query_riserva(ind):
    """Query costruita dal codice con gli indizi (quando il modello non c'è o sbaglia due volte)."""
    cond = []
    if ind.get('persona'):
        cond.append(f"o.nome = {_sql_str(ind['persona'])}")
    if ind.get('deposito'):
        cond.append(f"d.nome = {_sql_str(ind['deposito'])}")
    if ind.get('settore'):
        cond.append(f"d.settore = {_sql_str(ind['settore'])}")
    if ind.get('pratica'):
        cond.append(f"a.pratica = {_sql_str(ind['pratica'])}")
    if not cond:
        return None
    cond += ["a.stato = 'attivo'", f"a.valido_fino >= {_sql_str(data_missione())}"]
    return _SELECT_COMPLETO + '\nWHERE ' + '\n  AND '.join(cond) + '\nORDER BY a.valido_fino DESC'


def verifica(ind):
    """Controllo fatto dal codice: tutti i permessi della persona o della pratica, e per ognuno quali condizioni
    passano (persona, deposito, settore, pratica, attivo, non scaduto). Mostra perché gli altri sono scartati."""
    cond = []
    if ind.get('persona'):
        cond.append(f"o.nome = {_sql_str(ind['persona'])}")
    p = ind.get('pratica')
    if p:
        cond.append(f"a.pratica = {_sql_str(p)}")
    if not cond:
        if ind.get('deposito'):
            cond.append(f"d.nome = {_sql_str(ind['deposito'])}")
        else:
            return None
    q = _SELECT_COMPLETO + '\nWHERE ' + ' OR '.join(cond) + '\nORDER BY a.id'
    r = interroga_database(q)
    if 'errore' in r:
        return {'query': q, 'errore': r['errore']}
    cols = r['colonne']
    out = []
    for riga in r['righe']:
        x = dict(zip(cols, riga))
        controlli = {
            'persona': None if not ind.get('persona') else x['operatore'] == ind['persona'],
            'deposito': None if not ind.get('deposito') else x['deposito'] == ind['deposito'],
            'settore': None if not ind.get('settore') else x['settore'] == ind['settore'],
            'pratica': None if not p else x['pratica'] == p,
            'attivo': x['stato'] == 'attivo',
            'non scaduto': (x['valido_fino'] or '') >= data_missione(),
        }
        motivi = []
        if controlli['attivo'] is False:
            motivi.append('revocato')
        if controlli['non scaduto'] is False:
            motivi.append(f"scaduto il {x['valido_fino']}")
        for k in ('persona', 'deposito', 'settore', 'pratica'):
            if controlli[k] is False:
                motivi.append(f'{k} diversa' if k in ('persona', 'pratica') else f'{k} diverso')
        out.append({**x, 'controlli': controlli, 'valido': not motivi, 'motivi': motivi})
    return {'query': q, 'righe': out, 'validi': [x for x in out if x['valido']]}


# ─────────────────────────── richieste di modifica: il tool non le esegue mai ───────────────────────────
# un ORDINE di modificare (verbo all'imperativo/infinito a inizio frase o dopo «puoi», «per favore»...), non un nome:
# «la modifica al programma» o «cosa cambia se...» non sono richieste di scrittura
_VERBI_MODIFICA = (r'(?:cancella|cancellate|cancellare|elimina|eliminate|eliminare|rimuovi|rimuovete|rimuovere|svuota|'
                   r'svuotate|svuotare|distruggi|distruggere|modifica|modificate|modificare|aggiorna|aggiornate|aggiornare|'
                   r'inserisci|inserite|inserire|sostituisci|sostituire|riattiva|riattivate|riattivare|revoca|revocate|'
                   r'revocare|prolunga|prolungate|prolungare|estendi|estendere|azzera|azzerare|resetta|resettare|'
                   r'cambia|cambiate|cambiare)')
_MODIFICA = re.compile(r'(?:^|[.!?,;:]\s*|\b(?:puoi|potete|potresti|devi|dovresti|voglio|vorrei|fammi|per favore|ora|adesso|'
                       r'allora|subito|eco|tu|che tu)\s+(?:\w+\s+)?)' + _VERBI_MODIFICA + r'\b', re.I)
_OGGETTO_DB = re.compile(r'\b(database|db|dati|tabell\w*|righ\w*|permess\w*|access\w*|codic\w*|autorizzaz\w*|'
                         r'operator\w*|deposit\w*|record|sql|pratica|pratiche|scadenz\w*|stato)\b', re.I)
_SQL_SCRITTURA = re.compile(r'\b(delete\s+from|drop\s+(table|database|index|view)|update\s+\w+\s+set|insert\s+into|'
                            r'alter\s+table|truncate\s+table|attach\s+database|replace\s+into)\b', re.I)


def richiesta_di_modifica(domanda):
    """«Cancella i permessi revocati», «aggiorna la scadenza», «DROP TABLE accessi»: il tool è di sola lettura."""
    d = _norm(domanda).strip()
    return bool(_MODIFICA.search(d) and _OGGETTO_DB.search(d)) or bool(_SQL_SCRITTURA.search(domanda))


_PAROLE_DB = re.compile(
    r'\b(autorizzaz\w*|permess\w*|accessi|database|db|sql|query|tabell\w*|varco|cancello|revocat\w*|scadut\w*|'
    r'operatori|codice di accesso|codice d accesso|codice per entrare|entrare nel deposito|aprire il deposito)\b', re.I)
# «codice» da solo è ambiguo (codici rari, bollettini, lotti): vale solo se non si parla di quelli
_CODICE = re.compile(r'\bcodic[ei]\b', re.I)
_ALTRI_CODICI = re.compile(r'\b(bollettin\w*|lott\w*|segnal\w*|ripetitor\w*|circuit\w*|rar[oi]|programma|python|'
                           r'tesserin\w*)\b', re.I)


def serve(domanda, cronologia=None):
    """La domanda riguarda il database degli accessi? (parole del database o seguito di una domanda SQL)."""
    if not disponibile():
        return False
    d = _norm(domanda)
    if _PAROLE_DB.search(d) or richiesta_di_modifica(domanda):
        return True
    if _CODICE.search(d) and not _ALTRI_CODICI.search(d):
        return True
    # seguito della conversazione: «e con la pratica RV000?», «e Darsena Vuota?» dopo una domanda sul database
    precedenti = [m for m in (cronologia or []) if isinstance(m, dict) and m.get('role') == 'user']
    if precedenti and len(d.split()) <= 14:
        prima = _norm(str(precedenti[-1].get('content', '')))
        if (_PAROLE_DB.search(prima) or (_CODICE.search(prima) and not _ALTRI_CODICI.search(prima))) and \
                (indizi(domanda) or re.search(r'\b(e se|e con|e invece|invece|e per|e la|e il|e nel|e a)\b', d)):
            return True
    return False


# ─────────────────────────── l'agente: domanda → SQL del modello → tool → risultato ───────────────────────────
PROMPT_SQL = """Sei il generatore di query SQL dell'investigatore {nome}. Rispondi SOLO con un oggetto JSON, senza altro testo:
- {{"sql": "SELECT ..."}} con UNA sola query di lettura (SQLite) che risponde alla domanda;
- {{"sql": null, "chiedi": "..."}} se mancano gli indizi necessari e non li trovi né nella conversazione né nel dossier;
- {{"sql": null, "motivo": "..."}} se la domanda chiede di modificare, cancellare o inserire dati (il tool è di sola \
lettura) oppure non riguarda il database degli accessi.

SCHEMA DEL DATABASE
{schema}

REGOLE
- Usa i JOIN: accessi.operatore_id = operatori.id e accessi.deposito_id = depositi.id. Mostra nelle colonne operatore \
(o.nome), deposito (d.nome), d.settore, a.pratica, a.codice, a.stato, a.valido_fino, così si vede la riga usata.
- Persona, deposito, settore e pratica devono corrispondere TUTTI agli indizi; per un permesso valido: \
a.stato = 'attivo' AND a.valido_fino >= '{data}'.
- Scrivi i valori esattamente come negli indizi (stesse maiuscole). Il codice è testo: non trasformarlo in numero.
- Non usare tabelle diverse da operatori, depositi, accessi. Niente PRAGMA, niente sqlite_master.
- Se la domanda non dice persona, deposito, settore o pratica, prendili dagli indizi del dossier qui sotto \
(la missione: il permesso della squadra per il deposito) e dalla conversazione.

INDIZI DAL DOSSIER (documenti dell'indagine)
{dossier}

CONVERSAZIONE RECENTE
{conversazione}"""


def _testo_dossier():
    """I file della storia dell'archivio (dossier LAZZARO: persona, pratica, deposito, settore) più il fascicolo G2."""
    righe = []
    try:
        import rag
        ind = rag.indice() if rag.file_archivio() else None
        if ind:
            for d in ind.catalogo():
                if ind.raccolta_piccola(d.get('raccolta') or 'archivio') and d.get('classe') != 'rumore':
                    righe.append(f'[{d["id"]}] {d["titolo"]}: {d["testo"]}')
    except Exception:
        pass
    return '\n'.join(righe)[:6000] or '(nessun dossier caricato)'


def _conversazione(cronologia, n=6):
    out = []
    for m in (cronologia or [])[-n:]:
        if isinstance(m, dict) and m.get('role') in ('user', 'assistant'):
            testo = str(m.get('content', '')).strip().splitlines()
            testo = ' '.join(r for r in testo if not r.startswith(('⏱', '📂', '_⏱', '_📂')))[:600]
            out.append(f'{"Utente" if m["role"] == "user" else "ECO"}: {testo}')
    return '\n'.join(out) or '(prima domanda)'


def leggi_json(testo):
    """Il JSON proposto dal modello, anche dentro ```json ... ``` o con testo intorno. None se non c'è."""
    if not testo:
        return None
    t = testo.strip()
    t = re.sub(r'^```(?:json|sql)?\s*|\s*```$', '', t, flags=re.I).strip()
    for prova in (t, (re.search(r'\{.*\}', t, re.S) or [None])[0] if re.search(r'\{.*\}', t, re.S) else None):
        if not prova:
            continue
        try:
            x = json.loads(prova)
            if isinstance(x, dict) and 'sql' in x:
                return x
        except ValueError:
            continue
    m = re.search(r'(?is)\b(select\b.+?)(?:;|```|$)', t)    # il modello ha scritto solo la query, senza JSON
    if m and len(m.group(1)) < 2000:
        return {'sql': m.group(1).strip()}
    return None


def genera(messaggi, max_tokens=300, temperatura=0.1):
    """Come la funzione genera() del notebook del docente: lista di messaggi (system + user) → testo del modello.
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


def agente(domanda, cronologia=None, passo=None):
    """Domanda in linguaggio naturale → il modello propone l'SQL → il codice lo esegue → esito per il prompt e la pagina.
    passo(testo) riceve le azioni da mostrare (facoltativo)."""
    passo = passo or (lambda t: None)
    t0 = time.perf_counter()
    impronta_prima = impronta()
    esito = {'domanda': domanda, 'tentativi': [], 'origine': None, 'query': None, 'data_missione': data_missione(),
             'file': percorso().name if percorso() else None}
    # indizi: prima la domanda, poi le domande precedenti della conversazione, poi il dossier (solo i valori mancanti)
    ind = indizi(domanda)
    fonte_indizi = 'domanda' if chiavi_note(ind) else None
    precedenti = [str(m.get('content', '')) for m in (cronologia or [])[-6:] if isinstance(m, dict) and m.get('role') == 'user']
    for testo in reversed(precedenti):
        da_prima = indizi(testo)
        nuovi = [k for k in chiavi_note(da_prima) if k not in ind]
        for k in nuovi:
            ind[k] = da_prima[k]
            if k in (da_prima.get('inesistenti') or []):
                ind.setdefault('inesistenti', []).append(k)
        if nuovi:
            fonte_indizi = (fonte_indizi + ' + conversazione') if fonte_indizi else 'conversazione'
    if len(chiavi_note(ind)) < 4:      # i valori mancanti arrivano dal dossier (mai sopra quelli scritti nella domanda)
        dal_dossier = {k: v for k, v in indizi(_testo_dossier()).items() if k != 'inesistenti' and k not in ind}
        ind.update(dal_dossier)
        if dal_dossier:
            fonte_indizi = (fonte_indizi + ' + dossier') if fonte_indizi else 'dossier'
    esito['indizi'], esito['fonte_indizi'] = ind, fonte_indizi
    dossier = {k: v for k, v in indizi(_testo_dossier()).items() if k != 'inesistenti'}
    esito['dossier'] = dossier
    esito['diverso_dal_dossier'] = {k: {'chiesto': ind[k], 'dossier': dossier[k]} for k in chiavi_note(ind)
                                    if k in dossier and ind[k] != dossier[k] and k not in (ind.get('inesistenti') or [])}

    if richiesta_di_modifica(domanda):           # prova «cancellare dati»: niente SQL di scrittura, mai
        esito.update(origine='bloccata', bloccata=True,
                     errore='Richiesta di modifica rifiutata: il tool SQL è di sola lettura (file aperto in read-only, '
                            'solo SELECT autorizzate). Nessuna query di scrittura è stata eseguita.')
        passo('⛔ Richiesta di modificare il database: rifiutata, il tool è di sola lettura')
        # dimostrazione: anche se qualcuno provasse, il tool la blocca
        prova = interroga_database('DELETE FROM accessi WHERE stato = \'revocato\'')
        esito['prova_blocco'] = {'query': "DELETE FROM accessi WHERE stato = 'revocato'", 'esito': prova.get('errore')}
        passo(f'🛡 Prova di sicurezza: DELETE inviato al tool → bloccato («{prova.get("errore", "")[:60]}»)')
    else:
        sistema = PROMPT_SQL.format(nome=config.NOME, schema=schema_testo(), data=data_missione(),
                                    dossier=_testo_dossier(), conversazione=_conversazione(cronologia))
        messaggi = [{'role': 'system', 'content': sistema}, {'role': 'user', 'content': domanda}]
        passo('🗄 Tool SQL: il modello legge lo schema del database e propone una query')
        for n in range(2):                        # un secondo tentativo con l'errore del primo
            try:
                risposta = genera(messaggi, max_tokens=320)
            except Exception as e:
                risposta = ''
                esito['tentativi'].append({'proposta': '', 'errore': f'{type(e).__name__}: {e}'[:200]})
                break
            if not risposta:
                esito['tentativi'].append({'proposta': '', 'errore': 'nessun modello disponibile'})
                break
            proposta = leggi_json(risposta)
            if proposta is None:
                esito['tentativi'].append({'proposta': risposta[:400], 'errore': 'il modello non ha prodotto JSON valido'})
                messaggi += [{'role': 'assistant', 'content': risposta},
                             {'role': 'user', 'content': 'Rispondi solo con il JSON {"sql": "SELECT ..."}.'}]
                continue
            if not proposta.get('sql'):
                esito['tentativi'].append({'proposta': json.dumps(proposta, ensure_ascii=False)[:400],
                                           'errore': None, 'nessuna_query': True})
                esito['chiedi'] = proposta.get('chiedi')
                esito['motivo'] = proposta.get('motivo')
                passo('🗄 Il modello non propone query: ' + (proposta.get('chiedi') or proposta.get('motivo') or '—')[:120])
                break
            q = str(proposta['sql']).strip()
            passo('🧾 Query proposta dal modello: ' + re.sub(r'\s+', ' ', q)[:160])
            r = interroga_database(q)
            esito['tentativi'].append({'proposta': q, 'errore': r.get('errore')})
            if 'errore' in r:
                passo(('⛔ Bloccata: ' if r.get('bloccata') else '⚠ Errore SQL: ') + r['errore'][:140])
                messaggi += [{'role': 'assistant', 'content': risposta},
                             {'role': 'user', 'content': f'La query ha dato errore: {r["errore"]}. Correggila e rispondi '
                                                         'solo con il JSON {"sql": "SELECT ..."}.'}]
                continue
            esito.update(origine='modello', query=q, **r)
            break
        if esito['origine'] is None and not esito.get('motivo') and not esito.get('chiedi'):
            q = query_riserva(ind)
            if q:
                r = interroga_database(q)
                esito.update(origine='riserva', query=q, **r)
                passo('🧩 Query di riserva costruita dal codice con gli indizi (' + (fonte_indizi or '—') + ')')
            elif not esito['tentativi'] or esito['tentativi'][-1].get('errore'):
                esito['chiedi'] = ('Per cercare il permesso servono gli indizi: persona, deposito, settore e pratica '
                                   '(li trovate nel dossier del Giorno 3).')
        if esito.get('query') and 'errore' not in esito:
            passo(f'▶ Eseguita in sola lettura: {len(esito["righe"])} rig{"a" if len(esito["righe"]) == 1 else "he"} '
                  f'in {esito["ms"]} ms')
    # controllo del codice sui candidati (perché gli altri permessi sono scartati)
    esito['verifica'] = verifica(ind) if ind and not esito.get('bloccata') else None
    if esito['verifica'] and esito['verifica'].get('righe') is not None:
        v = esito['verifica']
        passo(f'🔍 Verifica del codice: {len(v["righe"])} permessi candidati, {len(v["validi"])} valid'
              f'{"o" if len(v["validi"]) == 1 else "i"} alla data della missione ({data_missione()})')
    dopo = impronta()
    esito['integro'] = impronta_prima == dopo
    esito['impronta'] = (dopo or '')[:16]
    esito['secondi'] = time.perf_counter() - t0
    esito['codici'] = codici_validi(esito)
    return esito


def codici_validi(esito):
    """I codici che la risposta può citare: quelli delle righe restituite e dei candidati verificati."""
    out = set()
    if esito.get('colonne') and 'codice' in esito['colonne']:
        k = esito['colonne'].index('codice')
        out |= {str(r[k]) for r in esito.get('righe') or [] if r[k] is not None}
    for r in ((esito.get('verifica') or {}).get('righe') or []):
        out.add(str(r['codice']))
    return sorted(out)


def controlla_risposta(testo, esito):
    """Dopo la risposta del modello: segnala codici che non esistono nel risultato o con gli zeri iniziali persi."""
    if not esito or not testo:
        return []
    validi = set(codici_validi(esito))
    tutti = (valori() or {}).get('codici', set())
    problemi = []
    for c in dict.fromkeys(re.findall(r'(?<![\w-])\d{4,8}(?![\w-])', testo)):
        if c in validi or c in ('2031',):
            continue
        perso = [v for v in validi if v.lstrip('0') == c and v != c]
        if perso:
            problemi.append(f'il codice {c} ha perso gli zeri iniziali: quello giusto è {perso[0]}')
        elif c in tutti or len(c) == 6:
            problemi.append(f'il codice {c} non è tra le righe restituite dal database per questa domanda')
    return problemi


# ─────────────────────────── per il prompt della risposta ───────────────────────────
def blocco_prompt(esito):
    """La sezione del prompt con il risultato del tool: il modello risponde da qui (non inventa righe o codici)."""
    if not esito:
        return ''
    righe = ['DATABASE DEGLI ACCESSI — RISULTATO DEL TOOL SQL (sola lettura)',
             f'Data della missione: {esito["data_missione"]}. Un permesso è valido se stato = attivo e valido_fino '
             f'è almeno la data della missione; persona, deposito, settore e pratica devono corrispondere tutti.']
    if esito.get('bloccata'):
        righe.append(f'RICHIESTA BLOCCATA: {esito.get("errore")}')
        righe.append('Spiega che il database si può solo leggere: nessun dato è stato cancellato o modificato '
                     f'(impronta del file uguale prima e dopo: {"sì" if esito.get("integro") else "NO"}).')
    elif esito.get('chiedi'):
        righe.append(f'MANCANO INDIZI: {esito["chiedi"]} Chiedili a chi scrive, senza inventare valori.')
    elif esito.get('motivo') and not esito.get('query'):
        righe.append(f'NESSUNA QUERY: {esito["motivo"]}')
    if esito.get('query'):
        righe.append(f'Query eseguita ({"proposta dal modello" if esito["origine"] == "modello" else "di riserva, costruita dal codice"}):')
        righe.append(esito['query'])
        if esito.get('errore'):
            righe.append(f'Errore: {esito["errore"]}')
        else:
            righe.append('Risultato (JSON): ' + json.dumps({'colonne': esito['colonne'], 'righe': esito['righe'],
                                                            'altre_righe': esito['altre_righe']}, ensure_ascii=False))
            if not esito['righe']:
                righe.append('NESSUNA RIGA: nel database non c\'è un permesso che soddisfa la richiesta. Dillo chiaramente '
                             'e NON inventare un codice.')
    v = esito.get('verifica')
    if v and v.get('righe') is not None:
        righe.append('Verifica del codice sui permessi candidati (tutti i permessi della persona o della pratica):')
        for r in v['righe']:
            righe.append(f'- riga id {r["id"]}: {r["operatore"]}, {r["deposito"]} settore {r["settore"]}, pratica '
                         f'{r["pratica"]}, codice {r["codice"]}, {r["stato"]}, valido fino {r["valido_fino"]} → '
                         + ('VALIDO' if r['valido'] else 'scartato: ' + ', '.join(r['motivi'])))
        for k, d in (esito.get('diverso_dal_dossier') or {}).items():
            righe.append(f'ATTENZIONE: la domanda usa {k} «{d["chiesto"]}», ma il dossier indica «{d["dossier"]}»: '
                         'una riga con un valore diverso dal dossier non è l\'autorizzazione della squadra. Fallo notare.')
        for k in esito['indizi'].get('inesistenti') or []:
            righe.append(f'{k.capitalize()} «{esito["indizi"][k]}»: NON esiste nel database.')
    f = fonti_indizi(esito.get('indizi') or {})
    if f:
        righe.append('Dove sono gli indizi nel dossier: ' + '; '.join(f'{k} «{esito["indizi"][k]}» in {", ".join(ids)}' for k, ids in f.items()))
    righe.append('Come rispondere: dai il codice (se c\'è) ESATTAMENTE come nella riga, con gli zeri iniziali; di\' quale '
                 'riga (id) e quali condizioni hai controllato; spiega perché gli altri permessi sono scartati (revocato, '
                 'scaduto, pratica diversa). Collega gli indizi ai documenti del dossier citando i loro ID tra parentesi quadre '
                 '(quelli indicati qui sopra). Non citare il database tra '
                 'parentesi quadre: scrivi «database degli accessi, riga id N».')
    return '\n'.join(righe)


def fonti_indizi(ind):
    """In quali documenti del dossier compare ogni indizio (per citarli): {'persona': ['ARCH-3097'], ...}."""
    out = {}
    try:
        import rag
        ind_rag = rag.indice() if rag.file_archivio() else None
        docs = [d for d in ind_rag.catalogo() if ind_rag.raccolta_piccola(d.get('raccolta') or 'archivio')
                and d.get('classe') != 'rumore'] if ind_rag else []
    except Exception:
        docs = []
    for k in chiavi_note(ind):
        if k in (ind.get('inesistenti') or []):
            continue
        ids = [d['id'] for d in docs if _cerca_valore(ind[k], _norm(d['titolo'] + ' ' + d['testo']))]
        if ids:
            out[k] = ids
    return out


def risposta_di_riserva(esito):
    """Se nessun modello può scrivere, la risposta la compone il codice dal risultato (senza inventare)."""
    if esito.get('bloccata'):
        return ('Non posso farlo: il database degli accessi si può solo leggere. La richiesta di modifica è stata '
                'rifiutata e nessun dato è cambiato' + (' (impronta del file identica prima e dopo).' if esito.get('integro') else '.'))
    if esito.get('chiedi') and not esito.get('query'):
        return esito['chiedi']
    if esito.get('errore'):
        return f'La query non è andata a buon fine: {esito["errore"]}'
    if not esito.get('query'):
        return 'Non ho eseguito nessuna query sul database degli accessi.'
    cols, righe = esito.get('colonne') or [], esito.get('righe') or []
    if not righe:
        ines = esito['indizi'].get('inesistenti') or []
        return ('Nel database degli accessi non risulta nessun permesso valido per questa richiesta'
                + (': ' + ', '.join(f'{k} «{esito["indizi"][k]}» non esiste nel database' for k in ines) if ines else '')
                + '. Non c\'è nessun codice da dare.')
    x = [dict(zip(cols, r)) for r in righe]
    pezzi = []
    for r in x[:5]:
        pezzi.append(', '.join(f'{k} {v}' for k, v in r.items()))
    testo = (f'Il database degli accessi restituisce {len(x)} rig{"a" if len(x) == 1 else "he"}: ' + ' | '.join(pezzi) + '.')
    diversi = esito.get('diverso_dal_dossier') or {}
    if len(x) == 1 and 'codice' in x[0]:
        testo = ((f'Il codice dell\'autorizzazione è {x[0]["codice"]}' if not diversi else
                  f'Con questi dati il database ha un permesso con codice {x[0]["codice"]}')
                 + (f' (riga id {x[0]["id"]})' if 'id' in x[0] else '') + '. ' + testo)
    if diversi:
        testo += (' Attenzione: non corrisponde al dossier (' + '; '.join(
            f'{k} {d["chiesto"]} invece di {d["dossier"]}' for k, d in diversi.items()) + '), quindi non è la nostra autorizzazione.')
    v = esito.get('verifica')
    if v and v.get('righe'):
        scartati = [r for r in v['righe'] if not r['valido']]
        if scartati:
            testo += ' Scartati: ' + '; '.join(f'codice {r["codice"]} ({", ".join(r["motivi"])})' for r in scartati[:6]) + '.'
    f = fonti_indizi(esito.get('indizi') or {})
    if f:
        testo += ' Indizi dal dossier: ' + '; '.join(f'{k} {esito["indizi"][k]} [{", ".join(ids)}]' for k, ids in f.items()) + '.'
    return testo


def per_la_pagina(esito):
    """Versione compatta dell'esito per l'interfaccia (pannello «🗄 Query SQL» e diagramma E/R)."""
    if not esito:
        return None
    chiavi = ('domanda', 'origine', 'query', 'colonne', 'righe', 'altre_righe', 'ms', 'letture', 'errore', 'bloccata',
              'chiedi', 'motivo', 'indizi', 'fonte_indizi', 'tentativi', 'verifica', 'integro', 'impronta', 'secondi',
              'data_missione', 'prova_blocco', 'file', 'dossier', 'diverso_dal_dossier')
    return {k: esito.get(k) for k in chiavi}
