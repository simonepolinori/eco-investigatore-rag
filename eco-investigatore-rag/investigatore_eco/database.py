"""Tool SQL di ECO (Giorno 4 · Operazione Varco): il «centralino» delle missioni con il database, SOLO IN LETTURA.

Il Giorno 4 ha due missioni con un database diverso:
  - «Il cancello nero»   (Squadra_3_2.zip) → accessi.sqlite, 3 tabelle            → sql_varco.py
  - «Il primo respiro»   (Squadra_3_3.zip) → archivio_recuperato.sqlite, 14 tabelle → sql_lete.py
Il resto di ECO (eco.py, web.py, istruzioni.py) usa solo le funzioni di questo file: qui si sceglie la missione.

Quale missione: quella scelta nell'interfaccia (🗄 Schema E/R), altrimenti config.MISSIONE_SQL, altrimenti la più
recente presente in dati/database/. Una domanda che parla chiaramente dell'altra missione (pratica RV596, Cripta Nord,
deposito... oppure varco V-38, terminale, abilitazioni...) va comunque al database giusto: così il vecchio test funziona
ancora anche dopo il cambio di missione.

Il collegamento è lo stesso del notebook Tool_SQL del docente: la domanda arriva all'assistente, il MODELLO propone la
query in JSON ({"sql": "SELECT ..."}), il CODICE la esegue in sola lettura, il risultato torna al modello che risponde;
poi il codice controlla che la risposta non inventi codici.
"""
import json
import re

import config
import sql_base
import sql_lete
import sql_varco

MISSIONI = {'lete': sql_lete, 'varco': sql_varco}
TITOLI = {'lete': 'Il primo respiro', 'varco': 'Il cancello nero'}
ZIP = {'lete': 'Squadra_3_3.zip', 'varco': 'Squadra_3_2.zip'}
_SCELTA = {'forzata': None}

_DI_VARCO = re.compile(r'\b(pratic\w*|deposit\w*|marta riva|cripta|darsena|settore\s+[a-z]\d|rv-?\d{2,4}|cancello nero|'
                       r'operator\w* id|operatori\.|depositi|accessi\.)\b', re.I)
_DI_LETE = re.compile(r'\b(lete|v-?38\w*|terminal\w*|sanitari\w*|addett\w* (?:alla )?sicurezza|abilitaz\w*|sospes\w*|'
                      r'sospension\w*|canal[ei]|finestr\w*|primo respiro|squadr\w* autorizzat\w*|[rem]\d{2}|'
                      r'operatori autorizzati|chiave del terminale|14 tabelle)\b', re.I)


def _file_scelta():
    return config.DATI / 'database' / 'missione_attiva.json'


def missioni():
    out = []
    for k, m in MISSIONI.items():
        p = m.percorso()
        out.append({'chiave': k, 'titolo': TITOLI[k], 'zip': ZIP[k], 'disponibile': p is not None, 'file': p.name if p else None})
    return out


def chiave_attiva():
    if _SCELTA['forzata'] in MISSIONI:
        return _SCELTA['forzata']
    try:
        k = json.loads(_file_scelta().read_text(encoding='utf-8')).get('missione')
        if k in MISSIONI and MISSIONI[k].disponibile():
            return k
    except (OSError, ValueError):
        pass
    k = getattr(config, 'MISSIONE_SQL', 'auto')
    if k in MISSIONI and MISSIONI[k].disponibile():
        return k
    return 'lete' if sql_lete.disponibile() else 'varco'


def usa(chiave, salva=False):
    """Sceglie la missione. salva=True la ricorda (file in dati/database/); altrimenti vale solo in questo processo."""
    if chiave not in MISSIONI:
        raise ValueError(f'missione sconosciuta: {chiave}')
    if salva:
        _file_scelta().parent.mkdir(parents=True, exist_ok=True)
        _file_scelta().write_text(json.dumps({'missione': chiave}), encoding='utf-8')
        _SCELTA['forzata'] = None
    else:
        _SCELTA['forzata'] = chiave
    return chiave


def attiva():
    return MISSIONI[chiave_attiva()]


def titolo():
    return TITOLI[chiave_attiva()]


def per(esito):
    """Il modulo della missione a cui appartiene un esito del tool."""
    return MISSIONI.get((esito or {}).get('missione') or 'varco', sql_varco)


def scegli_missione(domanda, cronologia=None):
    """Quale database interroga questa domanda: quella attiva, salvo che parli chiaramente dell'altra."""
    att = chiave_attiva()
    d = sql_base.norm(domanda)
    varco, lete = bool(_DI_VARCO.search(d)), bool(_DI_LETE.search(d))
    if varco and not lete and sql_varco.disponibile():
        return 'varco'
    if lete and not varco and sql_lete.disponibile():
        return 'lete'
    if not (varco or lete):     # domanda di seguito («e con la pratica RV000?»): la missione della domanda prima
        for m in reversed(cronologia or []):
            if isinstance(m, dict) and m.get('role') == 'user':
                p = sql_base.norm(str(m.get('content', '')))
                if _DI_VARCO.search(p) and not _DI_LETE.search(p) and sql_varco.disponibile():
                    return 'varco'
                if _DI_LETE.search(p) and not _DI_VARCO.search(p) and sql_lete.disponibile():
                    return 'lete'
                break
    return att


# ─────────────────────────── le funzioni usate dal resto di ECO ───────────────────────────
def disponibile():
    return any(m.disponibile() for m in MISSIONI.values())


def percorso():
    return attiva().percorso()


def data_missione():
    return attiva().data_missione()


def schema_testo():
    return attiva().schema_testo()


def impronta():
    return attiva().impronta()


def interroga_database(query, database=None):
    if database:
        return sql_base.interroga(query, database)
    return attiva().interroga_database(query)


def esempi(tabella, n=8):
    return attiva().esempi(tabella, n)


def serve(domanda, cronologia=None):
    """La domanda riguarda il database di una missione?"""
    if not disponibile():
        return False
    return MISSIONI[scegli_missione(domanda, cronologia)].serve(domanda, cronologia)


def _solo_della_missione(k, cronologia):
    """La conversazione senza le domande (e risposte) sull'altra missione: gli indizi non si mescolano."""
    altra = _DI_LETE if k == 'varco' else _DI_VARCO
    stessa = _DI_VARCO if k == 'varco' else _DI_LETE
    out, salta = [], False
    for m in cronologia or []:
        if not isinstance(m, dict):
            continue
        if m.get('role') == 'user':
            d = sql_base.norm(str(m.get('content', '')))
            salta = bool(altra.search(d)) and not stessa.search(d)
        if not salta:
            out.append(m)
    return out


def agente(domanda, cronologia=None, passo=None):
    k = scegli_missione(domanda, cronologia)
    esito = MISSIONI[k].agente(domanda, _solo_della_missione(k, cronologia), passo)
    esito['missione'] = k
    esito.setdefault('titolo_missione', TITOLI[k])
    return esito


def blocco_prompt(esito):
    return per(esito).blocco_prompt(esito)


def controlla_risposta(testo, esito):
    return per(esito).controlla_risposta(testo, esito)


def risposta_di_riserva(esito):
    return per(esito).risposta_di_riserva(esito)


def per_la_pagina(esito):
    out = per(esito).per_la_pagina(esito)
    if out is not None:
        k = (esito or {}).get('missione') or 'varco'
        out['missione'], out['titolo_missione'] = k, TITOLI.get(k)
    return out


def struttura(chiave=None):
    """Schema letto dal file, nello stesso formato per le due missioni (lo usa la pagina dello schema E/R)."""
    k = chiave if chiave in MISSIONI else chiave_attiva()
    if k == 'lete':
        s = sql_lete.struttura()
    else:
        s = _struttura_varco()
    s['missione'], s['titolo_missione'] = k, TITOLI[k]
    s['missioni'] = missioni()
    return s


ENTITA_VARCO = {'operatori': 'OPERATORE', 'depositi': 'DEPOSITO', 'accessi': 'ACCESSO'}


def _struttura_varco():
    s = sql_varco.struttura()
    if not s.get('disponibile'):
        return s
    for t in s['tabelle']:
        t['entita'] = ENTITA_VARCO.get(t['nome'], t['nome'].upper())
        t.setdefault('perche', '')
        t.setdefault('storica', False)
    for r in s['relazioni']:
        r.update(lato_padre=r.get('lato_entita'), lato_figlio=r.get('lato_accesso'), senza_figli=r.get('senza_accessi'),
                 verificata=not r.get('orfani'), copertura=100.0 if not r.get('orfani') else None, altre_tabelle=[],
                 prova=f"{r['chiave']} → {r['riferisce']}: " + (f"{r['orfani']} orfani" if r.get('orfani') else 'nessun orfano'))
    s.update(titolo='Giorno 4 · Il cancello nero', layout={'operatori': [190, 380], 'accessi': [600, 380], 'depositi': [1010, 380]},
             riferimenti_non_mappati=[], regole='Persona, deposito, settore e pratica devono corrispondere tutti; il permesso '
             'deve essere attivo e valido_fino almeno pari alla data della missione.')
    return s


def esempi_console(chiave=None):
    k = chiave if chiave in MISSIONI else chiave_attiva()
    if k == 'lete':
        return sql_lete.esempi_console()
    d = sql_varco.data_missione()
    return [
        ['Il permesso della missione (dossier)', "SELECT a.id, o.nome AS operatore, d.nome AS deposito, d.settore, a.pratica, "
         "a.codice, a.stato, a.valido_fino\nFROM accessi a\nJOIN operatori o ON o.id = a.operatore_id\nJOIN depositi d ON "
         f"d.id = a.deposito_id\nWHERE o.nome = 'Marta Riva'\n  AND d.nome = 'Cripta Nord'\n  AND d.settore = 'B7'\n  AND "
         f"a.pratica = 'RV596'\n  AND a.stato = 'attivo'\n  AND a.valido_fino >= '{d}'"],
        ['Tutti i permessi di Marta Riva', "SELECT a.id, d.nome AS deposito, d.settore, a.pratica, a.codice, a.stato, "
         "a.valido_fino\nFROM accessi a\nJOIN operatori o ON o.id = a.operatore_id\nJOIN depositi d ON d.id = a.deposito_id\n"
         "WHERE o.nome = 'Marta Riva'\nORDER BY a.id"],
        ['Permessi per stato', 'SELECT stato, COUNT(*) AS permessi\nFROM accessi\nGROUP BY stato'],
        ['Validi alla data della missione', f"SELECT COUNT(*) AS validi\nFROM accessi\nWHERE stato = 'attivo' AND valido_fino >= '{d}'"],
        ['Codici che iniziano con zero', "SELECT id, pratica, codice\nFROM accessi\nWHERE codice LIKE '0%'\nLIMIT 10"],
        ['Prova: cancellare (viene bloccata)', "DELETE FROM accessi WHERE stato = 'revocato'"],
        ['Prova: leggere sqlite_master (bloccata)', 'SELECT name, sql FROM sqlite_master'],
    ]


def __getattr__(nome):
    """Compatibilità: le altre funzioni (indizi, verifica, valori, query_riserva...) sono quelle della prima missione."""
    return getattr(sql_varco, nome)
