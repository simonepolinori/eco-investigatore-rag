"""Tool SQL di ECO · Giorno 4 · missione «Il primo respiro» (Squadra_3_3.zip): archivio_recuperato.sqlite, SOLA LETTURA.

Il database è stato recuperato da un terminale danneggiato: 14 tabelle con nomi in codice (r02, r07, m12...), colonne
k0, k1, v1, ts_a... e NESSUN vincolo di relazione. Qui ci sono:
  1. la MAPPA delle 14 tabelle (significato ipotizzato) con le PROVE calcolate su tutti i dati: righe, valori distinti,
     NULL, campioni e il controllo dei riferimenti (ogni chiave esterna punta davvero a una sola tabella, nessun orfano);
  2. la VERIFICA del codice: tutte le regole della missione (foglio «Regole») come query SQL eseguite dal tool, passo per
     passo, con il motivo di ogni candidato escluso e l'informazione che manca (da chiedere alla centrale);
  3. i PARAMETRI della missione (istante, varco, sito, canale del lettore del veicolo): la centrale può aggiornarli
     (pannello 🗄 Schema E/R o «la centrale comunica: ...» in chat); i controlli si ripetono e lo storico dice cosa cambia;
  4. l'AGENTE: il modello propone le query (JSON {"sql": ...}), il codice le esegue, il risultato torna al modello.
Gli intervalli includono l'inizio ed escludono la fine; una fine NULL = nessuna scadenza; la revoca vale dal suo istante.
"""
import json
import re
import sqlite3
import threading
import time
from pathlib import Path

import config
import sql_base as base
from sql_base import sql_str

NOME_MISSIONE = 'Il primo respiro'
CHIAVE = 'lete'
RUOLI = ('SANITARIO', 'SICUREZZA')

# ─────────────────────────── la mappa delle 14 tabelle (ricostruita da noi, verificata sui dati) ───────────────────────────
# tabella: (entità, significato, {colonna: significato}, perché lo pensiamo)
MAPPA = {
    'r02': ('SITO', 'I siti (archivi) della zona: nome e sigla.',
            {'k0': 'chiave primaria', 'v1': 'nome del sito (es. «Archivio Lete»)', 'v2': 'sigla del sito (AR-3-xx, AC-374)'},
            '24 righe, nomi tutti diversi «Archivio …»: c\'è anche «Archivio Lete», la nostra destinazione; r07.k1 punta qui.'),
    'r07': ('VARCO', 'I varchi d\'ingresso di ogni sito.',
            {'k0': 'chiave primaria', 'k1': 'sito → r02.k0', 'v1': 'codice del varco (V-38, V-38-B, P-3-xx)'},
            'v1 contiene «V-38» (il varco della missione) e il simile «V-38-B»; k1 punta a r02 su tutte le righe.'),
    'r09': ('TERMINALE', 'I terminali che controllano un varco: canale e stato.',
            {'k0': 'chiave primaria', 'k1': 'varco controllato → r07.k0', 'v1': 'canale del terminale (Canale …)',
             'v2': 'stato: OPERATIVO / FUORI_SERVIZIO'},
            'v2 ha solo OPERATIVO e FUORI_SERVIZIO (la regola «Terminale»); v1 sono canali; k1 punta a r07.'),
    'm05': ('FINESTRA', 'Le finestre di apertura di ogni terminale.',
            {'k0': 'chiave primaria', 'k1': 'terminale → r09.k0', 'ts_a': 'inizio (incluso)', 'ts_b': 'fine (esclusa)'},
            'Solo un terminale e un intervallo di tempo (3 per terminale): la regola «Finestra di apertura».'),
    'r13': ('CHIAVE', 'Le versioni della chiave di ogni terminale (codice e validità).',
            {'k0': 'chiave primaria', 'k1': 'terminale → r09.k0', 'v1': 'codice della chiave (TESTO, 6 cifre)',
             'ts_a': 'valida dal (incluso)', 'ts_b': 'valida fino a (escluso)'},
            'v1 sono codici di 6 cifre, tutti diversi; un terminale ne ha diverse, in periodi diversi: «versione della chiave».'),
    'r03': ('PERSONA', 'Le persone: nome e badge.',
            {'k0': 'chiave primaria', 'v1': 'nome e cognome', 'v2': 'badge (PX-…)'},
            '265 righe con nomi di persona e un identificativo PX-…; m12, r06, e04 e r15 puntano qui.'),
    'r11': ('SQUADRA', 'Le squadre (Unità / Nucleo).',
            {'k0': 'chiave primaria', 'v1': 'nome della squadra (Unità 3-…, Nucleo 3-…)'},
            '74 nomi «Unità …» e «Nucleo …»; i permessi (r08) e le appartenenze (m12) puntano qui.'),
    'm12': ('APPARTENENZA', 'Chi fa parte di quale squadra e da quando a quando.',
            {'k0': 'chiave primaria', 'k1': 'persona → r03.k0', 'k2': 'squadra → r11.k0', 'ts_a': 'dal (incluso)',
             'ts_b': 'al (escluso; NULL = ancora membro)'},
            'Collega persone e squadre nel tempo (regola «Stessa squadra»); alcune persone hanno registrazioni doppie.'),
    'r06': ('ABILITAZIONE', 'Le abilitazioni di una persona a un ruolo.',
            {'k0': 'chiave primaria', 'k1': 'persona → r03.k0', 'v1': 'ruolo: SANITARIO / SICUREZZA',
             'ts_a': 'valida dal (incluso)', 'ts_b': 'fino a (escluso; NULL = senza scadenza)'},
            'v1 ha solo SANITARIO e SICUREZZA (i due ruoli); k1 punta a r03; ci sono rinnovi sovrapposti.'),
    'e04': ('SOSPENSIONE', 'Le sospensioni delle persone.',
            {'k0': 'chiave primaria', 'k1': 'persona → r03.k0', 'ts_a': 'dal (incluso)', 'ts_b': 'al (escluso; NULL = senza fine)',
             'v1': 'motivo (controllo ordinario, ritiro idoneità…)'},
            'Pochi casi (23), motivi da sospensione e un intervallo; una ha inizio nel futuro (regola «Sospensioni»).'),
    'r08': ('PERMESSO', 'Il permesso di una squadra su un varco, per un ruolo.',
            {'k0': 'chiave primaria', 'k1': 'squadra → r11.k0', 'k2': 'varco → r07.k0', 'v1': 'ruolo: SANITARIO / SICUREZZA',
             'ts_a': 'valido dal (incluso)', 'ts_b': 'fino a (escluso; NULL = senza scadenza)', 'v2': 'stato: ATTIVO / BLOCCATO'},
            'Squadra + varco + ruolo + periodo + stato ATTIVO/BLOCCATO: esattamente la regola «Permessi».'),
    'e10': ('REVOCA', 'Le revoche dei permessi (con l\'istante da cui valgono).',
            {'k0': 'chiave primaria', 'k1': 'permesso revocato → r08.k0', 'ts_a': 'istante di effetto', 'v1': 'motivo'},
            'k1 punta a r08; motivi «revoca direzione», «cambio turno»; un solo istante: quello da cui la revoca vale.'),
    'r14': ('COPIA REGISTRO', 'Copia del registro dei permessi fatta nel turno precedente: FONTE STORICA.',
            {'k0': 'chiave primaria', 'k1': 'permesso copiato → r08.k0', 'k2': 'squadra → r11.k0', 'k3': 'varco → r07.k0',
             'v1': 'ruolo', 'ts_a': 'dal', 'ts_b': 'al', 'v2': 'stato copiato', 'ts_c': 'data della copia',
             'v3': 'provenienza (REPLICA_TURNO_PRECEDENTE)'},
            'Una riga per ogni permesso (k1 → r08, tutti diversi), con provenienza e data della copia (3/11 18:00): '
            'aiuta a capire i dati ma non prova autorizzazioni correnti.'),
    'r15': ('ACCESSO PASSATO', 'Gli accessi registrati il giorno prima (3/11): FONTE STORICA.',
            {'k0': 'chiave primaria', 'k1': 'terminale → r09.k0', 'k2': 'persona → r03.k0', 'ts_a': 'quando',
             'v1': 'esito: OK / NEGATO', 'v2': 'codice della chiave usata'},
            'Tutti del 3/11, esito OK/NEGATO e la chiave usata: è un registro di accessi passati, non un\'autorizzazione.'),
}
STORICHE = ('r14', 'r15')
# relazioni (chiavi esterne): (tabella figlia, colonna, tabella padre, nome della relazione nel diagramma E/R)
RELAZIONI = [
    ('r07', 'k1', 'r02', 'si trova in'), ('r09', 'k1', 'r07', 'controlla'), ('m05', 'k1', 'r09', 'apre in'),
    ('r13', 'k1', 'r09', 'versione di'), ('m12', 'k1', 'r03', 'membro'), ('m12', 'k2', 'r11', 'di squadra'),
    ('r06', 'k1', 'r03', 'abilita'), ('e04', 'k1', 'r03', 'sospende'), ('r08', 'k1', 'r11', 'concesso a'),
    ('r08', 'k2', 'r07', 'per varco'), ('e10', 'k1', 'r08', 'revoca'), ('r14', 'k1', 'r08', 'copia di'),
    ('r14', 'k2', 'r11', 'copia squadra'), ('r14', 'k3', 'r07', 'copia varco'), ('r15', 'k1', 'r09', 'registrato da'),
    ('r15', 'k2', 'r03', 'eseguito da'),
]
# posizione dei blocchi nel diagramma (gruppi: persone a sinistra, squadre e permessi al centro, luoghi a destra)
LAYOUT = {
    'r06': [260, 260], 'r03': [260, 720], 'e04': [260, 1160],
    'm12': [700, 720], 'r11': [1120, 720], 'r08': [1120, 300], 'e10': [700, 80], 'r14': [1560, 80],
    'r07': [1560, 520], 'r02': [2000, 520], 'r09': [1560, 1000], 'm05': [2000, 860], 'r13': [2000, 1220],
    'r15': [960, 1220],
}
LAYOUT_REL = {'r14.k2': [1300, 225], 'r14.k1': [1340, 150]}   # rombi spostati perché non si sovrappongano

REGOLE = """1. Due persone: un SANITARIO e un addetto SICUREZZA, con identificativi diversi (la stessa persona con due \
abilitazioni non basta).
2. Stessa squadra: entrambe membri della stessa squadra nell'istante richiesto (m12; una vecchia appartenenza non vale).
3. Abilitazioni: ognuna con un'abilitazione valida per il proprio ruolo (r06; rinnovi sovrapposti = stessa persona).
4. Sospensioni: nessuna delle due sospesa nell'istante richiesto (e04; una sospensione futura non è ancora attiva).
5. Permessi: la squadra ha, per il varco richiesto, un permesso ATTIVO e valido nel tempo per ciascuno dei due ruoli (r08).
6. Revoche: un permesso è escluso se una revoca è già efficace (e10.ts_a <= istante); conta l'istante, non la presenza.
7. Terminale: controlla il varco richiesto, è OPERATIVO e usa il canale compatibile con il lettore del veicolo (r09).
8. Finestra e chiave: almeno una finestra di apertura valida (m05) e una versione della chiave valida (r13) per quel \
terminale. Non scegliere il codice ordinando gli identificativi.
9. Date AAAA-MM-GG HH:MM: ogni intervallo include l'inizio ed esclude la fine; fine NULL = nessuna scadenza.
10. Fonti storiche (r14 copia del registro, r15 accessi passati): aiutano a capire, non provano autorizzazioni correnti.
11. I codici sono testo. Non si cambiano dati o permessi. Se non c'è un accesso valido, si dichiara."""

_cache = {'firma': None, 'struttura': None}
_LOCK = threading.Lock()


# ─────────────────────────── dove sta il database ───────────────────────────
def percorso():
    nome = getattr(config, 'DATABASE_LETE', 'archivio_recuperato.sqlite')
    for c in (config.DATI / 'database' / nome, config.CARTELLA / nome, config.DATI / nome, Path.cwd() / nome):
        if c.is_file():
            return c
    trovati = sorted(config.DATI.glob('**/archivio_recuperato*.sqlite')) + sorted(config.DATI.glob('**/archivio_recuperato*.db'))
    return trovati[0] if trovati else None


def disponibile():
    return percorso() is not None


def impronta():
    return base.impronta(percorso())


def tabelle():
    p = percorso()
    return base.tabelle_del_file(p) if p else []


def interroga_database(query, max_righe=base.MAX_RIGHE):
    """Il tool: UNA query di lettura su archivio_recuperato.sqlite (le tre protezioni sono in sql_base.interroga)."""
    return base.interroga(query, percorso(), max_righe=max_righe)


def esempi(tabella, n=8):
    if tabella not in tabelle():
        return {'errore': 'tabella sconosciuta'}
    return interroga_database(f'SELECT * FROM {tabella} LIMIT {int(n)}')


# ─────────────────────────── i parametri della missione (la centrale li può aggiornare) ───────────────────────────
FILE_PARAMETRI = 'missione_lete.json'
FILE_STORICO = 'storico_controlli.jsonl'


def _file(nome):
    return config.DATI / 'database' / nome


def parametri_iniziali():
    return dict({'istante': '2026-11-04 12:30', 'varco': 'V-38', 'sito': 'Archivio Lete', 'canale': 'Canale Kappa'},
                **getattr(config, 'PARAMETRI_LETE', {}))


def parametri():
    """I parametri in uso: quelli della scheda (config.PARAMETRI_LETE), aggiornati da quelli salvati dalla centrale."""
    p = parametri_iniziali()
    try:
        salvati = json.loads(_file(FILE_PARAMETRI).read_text(encoding='utf-8'))
        p.update({k: salvati[k] for k in ('istante', 'varco', 'sito', 'canale') if k in salvati})
        p['origine'], p['aggiornato'] = salvati.get('origine', ''), salvati.get('aggiornato', '')
    except (OSError, ValueError):
        p['origine'], p['aggiornato'] = 'scheda della missione', ''
    return p


def data_missione():
    return parametri()['istante']


def valida_parametri(p):
    """Controlla e pulisce i parametri. ValueError con il motivo se qualcosa non va."""
    out = {}
    ist = str(p.get('istante', '')).strip().replace('T', ' ')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}', ist):
        raise ValueError('L\'istante va scritto AAAA-MM-GG HH:MM (es. 2026-11-04 12:00).')
    out['istante'] = ist
    v = str(p.get('varco', '')).strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{0,19}', v):
        raise ValueError('Il varco va scritto come nel database (es. V-38).')
    out['varco'] = v
    out['sito'] = re.sub(r'\s+', ' ', str(p.get('sito', '') or '')).strip()[:60]
    c = re.sub(r'\s+', ' ', str(p.get('canale', '') or '')).strip()[:40]
    if c and not c.lower().startswith('canale'):
        c = 'Canale ' + c
    out['canale'] = c[:1].upper() + c[1:] if c else ''
    return out


def salva_parametri(nuovi, origine='pannello'):
    """La centrale aggiorna i parametri: si salvano (con lo storico degli aggiornamenti) e si restituiscono."""
    vecchi = parametri()
    p = valida_parametri({**vecchi, **{k: v for k, v in nuovi.items() if v is not None}})
    try:
        prima = json.loads(_file(FILE_PARAMETRI).read_text(encoding='utf-8')).get('aggiornamenti', [])
    except (OSError, ValueError):
        prima = []
    cambi = {k: [vecchi.get(k, ''), p[k]] for k in p if vecchi.get(k, '') != p[k]}
    dati = dict(p, origine=origine, aggiornato=time.strftime('%Y-%m-%d %H:%M:%S'),
                aggiornamenti=(prima + [{'quando': time.strftime('%Y-%m-%d %H:%M:%S'), 'origine': origine, 'cambi': cambi}])[-50:])
    _file(FILE_PARAMETRI).parent.mkdir(parents=True, exist_ok=True)
    _file(FILE_PARAMETRI).write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding='utf-8')
    return parametri(), cambi


def ripristina_parametri():
    try:
        _file(FILE_PARAMETRI).unlink()
    except OSError:
        pass
    return parametri()


def canali():
    r = interroga_database('SELECT DISTINCT v1 FROM r09 ORDER BY v1', max_righe=200)
    return [x[0] for x in r.get('righe') or []]


def varchi():
    r = interroga_database('SELECT v.v1, s.v1 FROM r07 v JOIN r02 s ON s.k0 = v.k1 ORDER BY v.v1', max_righe=500)
    return [{'varco': x[0], 'sito': x[1]} for x in r.get('righe') or []]


# ─────────────────────────── STRUTTURA: la mappa con le prove calcolate sui dati ───────────────────────────
def struttura():
    """Tabelle, colonne (tipo, distinti, NULL, campioni, intervallo), relazioni verificate su tutte le righe
    (copertura, orfani, unicità del bersaglio, cardinalità) e riferimenti scoperti in automatico."""
    p = percorso()
    if not p:
        return {'disponibile': False, 'missione': CHIAVE}
    firma = (str(p), p.stat().st_mtime, p.stat().st_size)
    with _LOCK:
        if _cache['firma'] == firma and _cache['struttura']:
            s = dict(_cache['struttura'])
            s.update(data_missione=data_missione(), parametri=parametri(), schema=schema_testo())
            return s
    con = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True)
    try:
        nomi = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        pk = {}
        for t in nomi:
            col = con.execute(f'PRAGMA table_info({t})').fetchall()
            chiave = [c[1] for c in col if c[5]]
            pk[t] = chiave[0] if chiave else None
        insiemi = {t: {r[0] for r in con.execute(f'SELECT {pk[t]} FROM {t}')} for t in nomi if pk[t]}
        dich = {(f, c): (pa, nome) for f, c, pa, nome in RELAZIONI}
        tab_out = []
        ordine = list(MAPPA)
        for t in sorted(nomi, key=lambda x: (ordine.index(x) if x in ordine else 99, x)):
            n = con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            info = MAPPA.get(t, (t.upper(), '', {}, ''))
            colonne = []
            for c in con.execute(f'PRAGMA table_info({t})').fetchall():
                nome = c[1]
                dist, nulli = con.execute(f'SELECT COUNT(DISTINCT {nome}), SUM({nome} IS NULL) FROM {t}').fetchone()
                x = {'nome': nome, 'tipo': c[2] or 'TEXT', 'pk': bool(c[5]), 'notnull': bool(c[3]),
                     'fk': f'{dich[(t, nome)][0]}.{pk[dich[(t, nome)][0]]}' if (t, nome) in dich else None,
                     'descrizione': info[2].get(nome, ''), 'distinti': dist, 'nulli': nulli or 0}
                if nome.startswith('ts'):
                    x['min'], x['max'] = con.execute(f'SELECT MIN({nome}), MAX({nome}) FROM {t}').fetchone()
                if dist <= 8 and not c[5] and (t, nome) not in dich:
                    x['valori'] = [[v, k] for v, k in con.execute(
                        f'SELECT {nome}, COUNT(*) FROM {t} GROUP BY {nome} ORDER BY COUNT(*) DESC, {nome}')]
                else:
                    x['esempi'] = [r[0] for r in con.execute(f'SELECT DISTINCT {nome} FROM {t} WHERE {nome} IS NOT NULL LIMIT 3')]
                colonne.append(x)
            tab_out.append({'nome': t, 'entita': info[0], 'descrizione': info[1], 'perche': info[3], 'righe': n,
                            'storica': t in STORICHE, 'colonne': colonne})
        rel_out = []
        for figlia, col, padre, nome in RELAZIONI:
            if figlia not in nomi or padre not in nomi:
                continue
            valori = [r[0] for r in con.execute(f'SELECT {col} FROM {figlia}')]
            pieni = [v for v in valori if v is not None]
            orfani = sum(1 for v in pieni if v not in insiemi[padre])
            altre = [u for u in nomi if u != padre and pk.get(u) and pieni and all(v in insiemi[u] for v in pieni)]
            conta = con.execute(f'SELECT {col}, COUNT(*) FROM {figlia} WHERE {col} IS NOT NULL GROUP BY {col}').fetchall()
            massimo = max((k for _, k in conta), default=0)
            senza = len(insiemi[padre] - {v for v, _ in conta})
            nulli = len(valori) - len(pieni)
            rel_out.append({
                'nome': nome, 'da': padre, 'a': figlia, 'chiave': f'{figlia}.{col}', 'riferisce': f'{padre}.{pk[padre]}',
                'join': f'{figlia}.{col} = {padre}.{pk[padre]}',
                'lato_padre': f'({0 if senza else 1},{"N" if massimo > 1 else 1})',
                'lato_figlio': f'({0 if nulli else 1},1)',
                'righe': len(valori), 'distinti': len(set(pieni)), 'nulli': nulli, 'orfani': orfani,
                'senza_figli': senza, 'massimo': massimo, 'altre_tabelle': altre,
                'copertura': round(100 * (len(pieni) - orfani) / len(pieni), 1) if pieni else 0.0,
                'verificata': bool(pieni) and orfani == 0 and not altre,
                'prova': (f'{len(pieni)} valori di {figlia}.{col} ({len(set(pieni))} distinti): '
                          f'{len(pieni) - orfani} si trovano in {padre}.{pk[padre]}'
                          + (f', {orfani} orfani' if orfani else ', nessun orfano')
                          + ('; nessun\'altra tabella li contiene tutti' if not altre else f'; li contiene anche {", ".join(altre)}'))})
        # riferimenti trovati in automatico che la mappa non dichiara (di solito nessuno: tutto è già spiegato)
        nuovi = []
        for t in nomi:
            for c in con.execute(f'PRAGMA table_info({t})').fetchall():
                if c[5] or (t, c[1]) in dich or (c[2] or '').upper() != 'INTEGER':
                    continue
                pieni = [r[0] for r in con.execute(f'SELECT {c[1]} FROM {t} WHERE {c[1]} IS NOT NULL')]
                bersagli = [u for u in nomi if pk.get(u) and pieni and all(v in insiemi[u] for v in pieni)]
                if bersagli:
                    nuovi.append({'chiave': f'{t}.{c[1]}', 'bersagli': bersagli})
        doppie = con.execute('SELECT COUNT(*) FROM (SELECT k1, k2 FROM m12 GROUP BY k1, k2 HAVING COUNT(*) > 1)').fetchone()[0] \
            if 'm12' in nomi else 0
        s = {'disponibile': True, 'missione': CHIAVE, 'titolo': f'Giorno 4 · {NOME_MISSIONE}', 'file': p.name,
             'tabelle': tab_out, 'relazioni': rel_out, 'riferimenti_non_mappati': nuovi, 'layout': LAYOUT, 'layout_rel': LAYOUT_REL,
             'impronta': base.impronta(p)[:16], 'note': {'appartenenze_doppie': doppie},
             'regole': REGOLE, 'stati': {}, 'scadenze': {}}
    finally:
        con.close()
    with _LOCK:
        _cache['firma'], _cache['struttura'] = firma, s
    s = dict(s)
    s.update(data_missione=data_missione(), parametri=parametri(), schema=schema_testo())
    return s


def schema_testo(breve=False):
    """Lo schema per il prompt: tabelle in codice + la nostra mappa (entità, colonne) + le chiavi esterne."""
    righe = []
    for t, (ent, descr, col, _) in MAPPA.items():
        cols = ', '.join(f'{c}={d}' for c, d in col.items()) if not breve else ', '.join(col)
        righe.append(f'{t} = {ent}{" (fonte storica)" if t in STORICHE else ""}: {descr} Colonne: {cols}')
    righe.append('Chiavi esterne (verificate su tutte le righe, nessun orfano): ' +
                 '; '.join(f'{f}.{c} → {pa}.k0' for f, c, pa, _ in RELAZIONI))
    righe.append('I codici delle chiavi (r13.v1) sono TESTO. Date nel formato AAAA-MM-GG HH:MM (testo: il confronto tra testi '
                 'funziona). Intervallo valido all\'istante T: ts_a <= T AND (ts_b IS NULL OR T < ts_b).')
    return '\n'.join(righe)


def mappa_testo():
    """La mappa con le prove, in breve (per il prompt quando la domanda chiede la mappa delle tabelle)."""
    s = struttura()
    if not s.get('disponibile'):
        return ''
    out = []
    for t in s['tabelle']:
        cols = []
        for c in t['colonne']:
            extra = (f" valori {', '.join(f'{v}×{k}' for v, k in c['valori'])}" if c.get('valori') else
                     f" {c['distinti']} distinti" + (f", {c['nulli']} NULL" if c['nulli'] else '') +
                     (f", da {c['min']} a {c['max']}" if c.get('min') else ''))
            cols.append(f"{c['nome']}{' PK' if c['pk'] else ''}{' FK→' + c['fk'] if c['fk'] else ''} ({c['descrizione']};{extra})")
        out.append(f"- {t['nome']} = {t['entita']}{' [fonte storica]' if t['storica'] else ''} · {t['righe']} righe · "
                   f"{t['descrizione']} Prove: {t['perche']} Colonne: " + '; '.join(cols))
    out.append('Relazioni verificate: ' + '; '.join(f"{r['chiave']} → {r['riferisce']} «{r['nome']}» "
                                                    f"{r['lato_padre']}:{r['lato_figlio']} ({r['prova']})" for r in s['relazioni']))
    return '\n'.join(out)


# ─────────────────────────── VERIFICA: tutte le regole, in SQL, passo per passo ───────────────────────────
def _val(alias, T):
    """[ts_a, ts_b): l'inizio è incluso, la fine esclusa, NULL = nessuna fine"""
    return f'{alias}.ts_a <= {T} AND ({alias}.ts_b IS NULL OR {T} < {alias}.ts_b)'


def _lista(ids):
    return ', '.join(str(int(i)) for i in ids) or 'NULL'


def verifica(par=None):
    """Controllo completo fatto dal codice per i parametri dati (o quelli della missione).
    Ogni passo è una query SQL eseguita dal tool di sola lettura; il risultato dice soluzioni, esclusi e cosa manca."""
    par = valida_parametri(par or parametri())
    t0 = time.perf_counter()
    T, V = sql_str(par['istante']), par['varco']
    out = {'parametri': par, 'passi': [], 'soluzioni': [], 'esclusi': [], 'mancante': None, 'stato': 'nessuna',
           'squadre': [], 'persone': [], 'coppie': [], 'terminali': [], 'varchi': []}

    def passo(chiave, titolo, spiegazione, q, max_righe=500):
        r = interroga_database(q, max_righe=max_righe)
        out['passi'].append({'id': chiave, 'titolo': titolo, 'spiegazione': spiegazione, 'query': q, **r})
        if 'errore' in r:
            raise RuntimeError(f'{titolo}: {r["errore"]}')
        return [dict(zip(r['colonne'], x)) for x in r['righe']]

    def escludi(tipo, chi, motivo, regola):
        out['esclusi'].append({'tipo': tipo, 'chi': chi, 'motivo': motivo, 'regola': regola})

    try:
        # 1 · il varco richiesto (e quelli con un codice simile, che NON vanno usati)
        cond_sito = f' AND s.v1 = {sql_str(par["sito"])}' if par['sito'] else ''
        righe = passo('varco', '1 · Il varco richiesto', f'Varco {V}' + (f' del sito «{par["sito"]}»' if par['sito'] else '') +
                      ': r07 (varchi) collegato a r02 (siti). I codici simili sono mostrati e scartati.',
                      f"""SELECT v.k0 AS varco_id, v.v1 AS varco, s.v1 AS sito, s.v2 AS sigla,
  CASE WHEN v.v1 = {sql_str(V)}{cond_sito} THEN 'varco richiesto'
       WHEN v.v1 = {sql_str(V)} THEN 'stesso codice ma in un altro sito: escluso'
       ELSE 'codice simile: NON è il varco richiesto' END AS esito
FROM r07 v
JOIN r02 s ON s.k0 = v.k1
WHERE v.v1 = {sql_str(V)} OR v.v1 LIKE {sql_str(V + '-%')}
ORDER BY v.v1""")
        out['varchi'] = righe
        vids = [r['varco_id'] for r in righe if r['esito'] == 'varco richiesto']
        for r in righe:
            if r['esito'] != 'varco richiesto':
                escludi('varco', f"{r['varco']} ({r['sito']})", r['esito'], 'Terminale: deve controllare il varco richiesto')
        if not vids:
            out['mancante'] = (f'Il varco {V}' + (f' del sito «{par["sito"]}»' if par['sito'] else '') +
                               ' non esiste nel database: controllate il codice con la centrale.')
            return _chiudi(out, t0)

        # 2 · i permessi delle squadre su quel varco, con stato, periodo e revoche
        righe = passo('permessi', '2 · Permessi sul varco (r08) e revoche (e10)',
                      'Per ogni squadra e ruolo: ATTIVO, valido all\'istante (inizio incluso, fine esclusa, NULL = senza '
                      'scadenza) e senza una revoca già efficace (conta l\'istante di effetto).',
                      f"""SELECT p.k0 AS permesso, p.k1 AS squadra_id, q.v1 AS squadra, p.v1 AS ruolo, p.v2 AS stato,
  p.ts_a AS dal, p.ts_b AS al, (SELECT MIN(r.ts_a) FROM e10 r WHERE r.k1 = p.k0) AS revoca_dal,
  CASE WHEN p.v2 <> 'ATTIVO' THEN 'escluso: stato ' || p.v2
       WHEN p.ts_a > {T} THEN 'escluso: vale solo dal ' || p.ts_a
       WHEN p.ts_b IS NOT NULL AND p.ts_b <= {T} THEN 'escluso: scaduto (fine ' || p.ts_b || ', esclusa)'
       WHEN EXISTS (SELECT 1 FROM e10 r WHERE r.k1 = p.k0 AND r.ts_a <= {T})
         THEN 'escluso: revocato dal ' || (SELECT MIN(r.ts_a) FROM e10 r WHERE r.k1 = p.k0 AND r.ts_a <= {T})
       WHEN EXISTS (SELECT 1 FROM e10 r WHERE r.k1 = p.k0)
         THEN 'valido (revoca dal ' || (SELECT MIN(r.ts_a) FROM e10 r WHERE r.k1 = p.k0) || ': non ancora efficace)'
       ELSE 'valido' END AS esito
FROM r08 p
JOIN r11 q ON q.k0 = p.k1
WHERE p.k2 IN ({_lista(vids)})
ORDER BY q.v1, p.v1""")
        squadre = {}
        for r in righe:
            s = squadre.setdefault(r['squadra_id'], {'id': r['squadra_id'], 'nome': r['squadra'], 'ruoli': {}})
            s['ruoli'].setdefault(r['ruolo'], []).append({'permesso': r['permesso'], 'esito': r['esito']})
        valide = []
        for s in squadre.values():
            motivi = []
            for ruolo in RUOLI:
                lista = s['ruoli'].get(ruolo, [])
                if not lista:
                    motivi.append(f'nessun permesso {ruolo} sul varco')
                elif not any(x['esito'].startswith('valido') for x in lista):
                    motivi.append(f'permesso {ruolo} ' + '; '.join(x['esito'].replace('escluso: ', '') for x in lista))
            s['valida'], s['motivo'] = not motivi, '; '.join(motivi)
            out['squadre'].append(s)
            if motivi:
                escludi('squadra', s['nome'], s['motivo'], 'Permessi / Revoche')
            else:
                valide.append(s['id'])

        # 3 · le squadre che hanno entrambi i permessi validi (la stessa regola, in una query)
        passo('squadre', '3 · Squadre con un permesso valido per ENTRAMBI i ruoli',
              'La regola dei permessi in una sola query: GROUP BY squadra, servono 2 ruoli validi.',
              f"""SELECT q.v1 AS squadra, p.k1 AS squadra_id, GROUP_CONCAT(DISTINCT p.v1) AS ruoli_validi
FROM r08 p
JOIN r11 q ON q.k0 = p.k1
WHERE p.k2 IN ({_lista(vids)})
  AND p.v2 = 'ATTIVO'
  AND {_val('p', T)}
  AND NOT EXISTS (SELECT 1 FROM e10 r WHERE r.k1 = p.k0 AND r.ts_a <= {T})
GROUP BY p.k1
HAVING COUNT(DISTINCT p.v1) = 2
ORDER BY q.v1""")
        if not valide:
            out['mancante'] = None
            return _chiudi(out, t0)

        # 4 · chi è membro di quelle squadre nell'istante richiesto (registrazioni doppie = stessa persona)
        membri = passo('membri', '4 · Membri delle squadre candidate (m12) nell\'istante richiesto',
                       'Una vecchia appartenenza non vale; più registrazioni della stessa persona contano una volta.',
                       f"""SELECT q.v1 AS squadra, m.k2 AS squadra_id, pe.k0 AS persona_id, pe.v1 AS persona, pe.v2 AS badge,
  COUNT(*) AS registrazioni, MIN(m.ts_a) AS dal,
  CASE WHEN SUM(m.ts_b IS NULL) > 0 THEN NULL ELSE MAX(m.ts_b) END AS al,
  MAX(CASE WHEN {_val('m', T)} THEN 1 ELSE 0 END) AS membro_ora
FROM m12 m
JOIN r03 pe ON pe.k0 = m.k1
JOIN r11 q ON q.k0 = m.k2
WHERE m.k2 IN ({_lista(valide)})
GROUP BY m.k2, pe.k0
ORDER BY q.v1, pe.v1""")
        pids = sorted({r['persona_id'] for r in membri})
        # 5 · abilitazioni e 6 · sospensioni di quelle persone
        abil = passo('abilitazioni', '5 · Abilitazioni dei membri (r06)',
                     'Ruolo valido all\'istante; i rinnovi sovrapposti non sono persone diverse.',
                     f"""SELECT pe.v1 AS persona, a.k1 AS persona_id, a.v1 AS ruolo, a.ts_a AS dal, a.ts_b AS al,
  CASE WHEN a.ts_a > {T} THEN 'non ancora valida'
       WHEN a.ts_b IS NOT NULL AND a.ts_b <= {T} THEN 'scaduta'
       ELSE 'valida' END AS esito
FROM r06 a
JOIN r03 pe ON pe.k0 = a.k1
WHERE a.k1 IN ({_lista(pids)})
ORDER BY pe.v1, a.v1, a.ts_a""")
        sosp = passo('sospensioni', '6 · Sospensioni dei membri (e04)',
                     'Esclude chi è sospeso all\'istante; una sospensione futura non è ancora attiva.',
                     f"""SELECT pe.v1 AS persona, s.k1 AS persona_id, s.v1 AS motivo, s.ts_a AS dal, s.ts_b AS al,
  CASE WHEN s.ts_a > {T} THEN 'futura: non ancora attiva'
       WHEN s.ts_b IS NOT NULL AND s.ts_b <= {T} THEN 'finita'
       ELSE 'ATTIVA' END AS esito
FROM e04 s
JOIN r03 pe ON pe.k0 = s.k1
WHERE s.k1 IN ({_lista(pids)})
ORDER BY pe.v1""")
        # analisi persona per persona (nel codice, dalle righe qui sopra)
        ruoli_validi = {}
        for a in abil:
            if a['esito'] == 'valida':
                ruoli_validi.setdefault(a['persona_id'], set()).add(a['ruolo'])
        sospese = {}
        for s in sosp:
            if s['esito'] == 'ATTIVA':
                sospese[s['persona_id']] = f"sospesa dal {s['dal']}" + (f" al {s['al']}" if s['al'] else ' (senza fine)') + f" ({s['motivo']})"
        coppie_codice = []
        for sid in valide:
            nome_sq = next(s['nome'] for s in out['squadre'] if s['id'] == sid)
            utili = {r: [] for r in RUOLI}
            for m in [x for x in membri if x['squadra_id'] == sid]:
                pid, chi = m['persona_id'], f"{m['persona']} ({m['badge']})"
                rv = sorted(ruoli_validi.get(pid, set()))
                info = {'squadra': nome_sq, 'persona_id': pid, 'persona': m['persona'], 'badge': m['badge'],
                        'membro': bool(m['membro_ora']), 'registrazioni': m['registrazioni'], 'ruoli': rv,
                        'sospensione': sospese.get(pid), 'ok': False}
                if not m['membro_ora']:
                    info['motivo'] = f"appartenenza a {nome_sq} " + (f"finita il {m['al']}" if m['al'] and m['al'] <= par['istante']
                                                                     else f"non ancora iniziata (dal {m['dal']})")
                    escludi('persona', chi, info['motivo'], 'Stessa squadra: conta l\'istante richiesto')
                elif pid in sospese:
                    info['motivo'] = sospese[pid]
                    escludi('persona', chi, f'{nome_sq}: {sospese[pid]}', 'Sospensioni')
                elif not rv:
                    tutte = [a for a in abil if a['persona_id'] == pid]
                    info['motivo'] = ('nessuna abilitazione' if not tutte else 'abilitazione ' + '; '.join(
                        f"{a['ruolo']} {a['esito']} ({a['dal']}–{a['al'] or '…'})" for a in tutte))
                    escludi('persona', chi, f'{nome_sq}: {info["motivo"]}', 'Abilitazioni')
                else:
                    info['ok'] = True
                    info['motivo'] = 'utilizzabile come ' + ' o '.join(rv) + (
                        f" (ha {m['registrazioni']} registrazioni nella squadra: è sempre una persona)" if m['registrazioni'] > 1 else '')
                    for r in rv:
                        utili[r].append(info)
                out['persone'].append(info)
            trovate = [(a, b) for a in utili['SANITARIO'] for b in utili['SICUREZZA'] if a['persona_id'] != b['persona_id']]
            if not trovate:
                usabili = {x['persona_id'] for r in RUOLI for x in utili[r]}
                if len(usabili) == 1 and all(utili[r] for r in RUOLI):
                    unico = utili['SANITARIO'][0]
                    motivo = (f"una sola persona utilizzabile ({unico['persona']}) con entrambe le abilitazioni: "
                              'servono due persone diverse')
                    escludi('persona', f"{unico['persona']} ({unico['badge']})", f'{nome_sq}: {motivo}', 'Due persone')
                else:
                    manca = [r for r in RUOLI if not utili[r]]
                    motivo = 'nessun membro utilizzabile come ' + ' né come '.join(manca) if manca else 'nessuna coppia di persone diverse'
                escludi('squadra', nome_sq, f'permessi validi, ma {motivo}', 'Due persone / Stessa squadra')
                for s in out['squadre']:
                    if s['id'] == sid:
                        s['valida'], s['motivo'] = False, f'permessi validi, ma {motivo}'
            for a, b in trovate:
                coppie_codice.append((sid, a['persona_id'], b['persona_id']))

        # 7 · le coppie valide in UNA query (tutte le regole sulle persone e sui permessi insieme)
        cte = f"""WITH membri AS (SELECT DISTINCT m.k2 AS squadra, m.k1 AS persona FROM m12 m WHERE {_val('m', T)}),
abilitati AS (SELECT DISTINCT a.k1 AS persona, a.v1 AS ruolo FROM r06 a WHERE {_val('a', T)}),
sospesi AS (SELECT DISTINCT s.k1 AS persona FROM e04 s WHERE {_val('s', T)}),
permessi AS (SELECT DISTINCT p.k1 AS squadra, p.v1 AS ruolo FROM r08 p
  WHERE p.k2 IN ({_lista(vids)}) AND p.v2 = 'ATTIVO' AND {_val('p', T)}
    AND NOT EXISTS (SELECT 1 FROM e10 r WHERE r.k1 = p.k0 AND r.ts_a <= {T})),
coppie AS (SELECT m1.squadra, m1.persona AS sanitario, m2.persona AS sicurezza
  FROM membri m1
  JOIN membri m2 ON m2.squadra = m1.squadra AND m2.persona <> m1.persona
  JOIN abilitati a1 ON a1.persona = m1.persona AND a1.ruolo = 'SANITARIO'
  JOIN abilitati a2 ON a2.persona = m2.persona AND a2.ruolo = 'SICUREZZA'
  JOIN permessi p1 ON p1.squadra = m1.squadra AND p1.ruolo = 'SANITARIO'
  JOIN permessi p2 ON p2.squadra = m1.squadra AND p2.ruolo = 'SICUREZZA'
  WHERE m1.persona NOT IN (SELECT persona FROM sospesi) AND m2.persona NOT IN (SELECT persona FROM sospesi))"""
        coppie = passo('coppie', '7 · Coppie valide (SANITARIO + SICUREZZA): tutte le regole sulle persone',
                       'Stessa squadra nell\'istante, persone diverse, abilitazioni valide, nessuna sospensione attiva, '
                       'permessi validi della squadra per i due ruoli.',
                       cte + """
SELECT q.v1 AS squadra, c.squadra AS squadra_id, s1.v1 AS sanitario, s1.v2 AS badge_sanitario, c.sanitario AS sanitario_id,
  s2.v1 AS sicurezza, s2.v2 AS badge_sicurezza, c.sicurezza AS sicurezza_id
FROM coppie c
JOIN r11 q ON q.k0 = c.squadra
JOIN r03 s1 ON s1.k0 = c.sanitario
JOIN r03 s2 ON s2.k0 = c.sicurezza
ORDER BY q.v1, s1.v1, s2.v1""")
        out['coppie'] = coppie
        if sorted((c['squadra_id'], c['sanitario_id'], c['sicurezza_id']) for c in coppie) != sorted(coppie_codice):
            out['incoerenza'] = 'la query delle coppie e il controllo riga per riga non coincidono: ricontrollate i dati'

        # 8 · i terminali del varco: stato, canale, finestre e chiave valide all'istante
        C = par['canale']
        cond_canale = (f"\n       WHEN LOWER(t.v1) <> LOWER({sql_str(C)}) THEN 'escluso: canale diverso da quello del lettore "
                       f"del veicolo ({C})'") if C else ''
        terminali = passo('terminali', '8 · Terminali del varco (r09) con finestra (m05) e chiave (r13) valide',
                          'OPERATIVO, canale compatibile con il lettore del veicolo' +
                          (f' ({C})' if C else ' (canale non comunicato: tutti i canali restano possibili)') +
                          ', almeno una finestra di apertura e una versione della chiave valide all\'istante.',
                          f"""SELECT t.k0 AS terminale, t.v1 AS canale, t.v2 AS stato,
  (SELECT COUNT(*) FROM m05 f WHERE f.k1 = t.k0 AND {_val('f', T)}) AS finestre_valide,
  (SELECT GROUP_CONCAT(c.v1, ' / ') FROM r13 c WHERE c.k1 = t.k0 AND {_val('c', T)}) AS codice,
  CASE WHEN t.v2 <> 'OPERATIVO' THEN 'escluso: ' || t.v2{cond_canale}
       WHEN (SELECT COUNT(*) FROM m05 f WHERE f.k1 = t.k0 AND {_val('f', T)}) = 0 THEN 'escluso: nessuna finestra di apertura valida'
       WHEN (SELECT COUNT(*) FROM r13 c WHERE c.k1 = t.k0 AND {_val('c', T)}) = 0 THEN 'escluso: nessuna chiave valida'
       ELSE 'valido' END AS esito
FROM r09 t
WHERE t.k1 IN ({_lista(vids)})
ORDER BY t.v1""")
        out['terminali'] = terminali
        for t in terminali:
            if t['esito'] != 'valido':
                escludi('terminale', f"{t['canale']} (terminale {t['terminale']})", t['esito'].replace('escluso: ', ''),
                        'Terminale / Finestra e chiave')
        # 9 · finestre e chiavi nel dettaglio (perché un terminale passa o no)
        passo('finestre_chiavi', '9 · Finestre di apertura e versioni della chiave dei terminali',
              'Il dettaglio dei periodi: valida = l\'istante è dentro [dal, al).',
              f"""SELECT t.v1 AS canale, 'finestra' AS tipo, NULL AS codice, f.ts_a AS dal, f.ts_b AS al,
  CASE WHEN {_val('f', T)} THEN 'valida' WHEN f.ts_a > {T} THEN 'futura' ELSE 'finita' END AS esito
FROM m05 f JOIN r09 t ON t.k0 = f.k1
WHERE t.k1 IN ({_lista(vids)})
UNION ALL
SELECT t.v1, 'chiave', c.v1, c.ts_a, c.ts_b,
  CASE WHEN {_val('c', T)} THEN 'valida' WHEN c.ts_a > {T} THEN 'futura' ELSE 'finita' END
FROM r13 c JOIN r09 t ON t.k0 = c.k1
WHERE t.k1 IN ({_lista(vids)})
ORDER BY canale, tipo, dal""")

        # 10 · LA SOLUZIONE: coppie valide × terminali validi (una sola query con tutte le regole)
        cond_c = f' AND LOWER(t.v1) = LOWER({sql_str(C)})' if C else ''
        soluzioni = passo('soluzione', '10 · Soluzione: due operatori autorizzati, terminale e chiave',
                          'Tutte le regole insieme. Nessun ordinamento per identificativo: se le righe sono più di una, '
                          'i dati lasciano più possibilità.',
                          cte + f""",
terminali AS (SELECT t.k0 AS terminale, t.v1 AS canale, c.v1 AS chiave, c.ts_a AS chiave_dal, c.ts_b AS chiave_al
  FROM r09 t
  JOIN r13 c ON c.k1 = t.k0 AND {_val('c', T)}
  WHERE t.k1 IN ({_lista(vids)}) AND t.v2 = 'OPERATIVO'{cond_c}
    AND EXISTS (SELECT 1 FROM m05 f WHERE f.k1 = t.k0 AND {_val('f', T)}))
SELECT q.v1 AS squadra, s1.v1 AS sanitario, s1.v2 AS badge_sanitario, s2.v1 AS sicurezza, s2.v2 AS badge_sicurezza,
  te.canale, te.terminale, te.chiave AS codice, te.chiave_dal, te.chiave_al
FROM coppie c
JOIN r11 q ON q.k0 = c.squadra
JOIN r03 s1 ON s1.k0 = c.sanitario
JOIN r03 s2 ON s2.k0 = c.sicurezza
CROSS JOIN terminali te
ORDER BY q.v1, te.canale""")
        out['soluzioni'] = soluzioni
        validi = [t for t in terminali if t['esito'] == 'valido']
        if len(soluzioni) > 1:
            pezzi = []
            if len(validi) > 1 and not C:
                pezzi.append('il CANALE del lettore del veicolo: nel database non c\'è e restano ' + str(len(validi)) +
                             ' terminali validi (' + ', '.join(f"{t['canale']} con chiave {t['codice']}" for t in validi) + ')')
            if len({(c['sanitario_id'], c['sicurezza_id']) for c in coppie}) > 1:
                pezzi.append('quale coppia parte: le coppie valide sono ' + str(len(coppie)) + ' (' +
                             '; '.join(f"{c['squadra']}: {c['sanitario']} + {c['sicurezza']}" for c in coppie) + ')')
            out['mancante'] = ('Manca ' + ' e '.join(pezzi) + '. Va chiesto alla centrale: non si sceglie una riga '
                               'perché compare per prima.') if pezzi else None
            out['manca'] = ' e '.join(x.split(':')[0] for x in pezzi).replace('il CANALE', 'il canale') or 'un dato per scegliere'
        elif not soluzioni:
            if coppie and not validi:
                out['mancante'] = ('Nessun terminale del varco è utilizzabile' +
                                   (f' con il {C}' if C else '') + ' in questo istante: nessun accesso valido.')
    except RuntimeError as e:
        out['errore'] = str(e)
    return _chiudi(out, t0)


def _chiudi(out, t0):
    n = len(out['soluzioni'])
    out['stato'] = 'unica' if n == 1 else 'ambigua' if n > 1 else 'nessuna'
    out['secondi'] = round(time.perf_counter() - t0, 3)
    out['codici'] = sorted({str(s['codice']) for s in out['soluzioni']} |
                           {str(c) for t in out['terminali'] for c in str(t.get('codice') or '').split(' / ') if c})
    out['sintesi'] = sintesi(out)
    return out


def sintesi(v):
    """Una frase con l'esito della verifica."""
    p = v['parametri']
    dove = f"varco {p['varco']}" + (f" ({p['sito']})" if p['sito'] else '') + f", {p['istante']}"
    if v.get('errore'):
        return f'Verifica non riuscita ({dove}): {v["errore"]}'
    if v['stato'] == 'unica':
        s = v['soluzioni'][0]
        return (f"{dove}: autorizzati {s['sanitario']} (SANITARIO) e {s['sicurezza']} (SICUREZZA) della {s['squadra']}, "
                f"terminale {s['canale']}, chiave {s['codice']}.")
    if v['stato'] == 'ambigua':
        s0 = v['soluzioni'][0]
        stessa = len({(s['sanitario'], s['sicurezza']) for s in v['soluzioni']}) == 1
        return (f"{dove}: {len(v['soluzioni'])} possibilità valide"
                + (f" (sempre {s0['sanitario']} + {s0['sicurezza']} della {s0['squadra']}, cambia il terminale)" if stessa else '')
                + f"; manca {v.get('manca') or 'un dato'}: va chiesto alla centrale.")
    return f"{dove}: nessun accesso valido." + (f" {v['mancante']}" if v.get('mancante') else '')


def confronta(prima, dopo):
    """Cosa cambia tra due verifiche (prova finale: la centrale aggiorna i parametri, si ripetono i controlli)."""
    cambi = []
    pp, pd = prima['parametri'], dopo['parametri']
    for k, nome in (('istante', 'istante'), ('varco', 'varco'), ('sito', 'sito'), ('canale', 'canale del veicolo')):
        if pp.get(k) != pd.get(k):
            cambi.append(f'{nome}: {pp.get(k) or "—"} → {pd.get(k) or "—"}')
    chiave = lambda s: f"{s['squadra']}: {s['sanitario']} + {s['sicurezza']}, {s['canale']} chiave {s['codice']}"
    a, b = {chiave(s) for s in prima['soluzioni']}, {chiave(s) for s in dopo['soluzioni']}
    sq = lambda v: {s['nome'] for s in v['squadre'] if s.get('valida')}
    te = lambda v: {f"{t['canale']} ({t['codice']})" for t in v['terminali'] if t['esito'] == 'valido'}
    risultati = []
    if sq(prima) != sq(dopo):
        risultati.append(f"squadre valide: {', '.join(sorted(sq(prima))) or 'nessuna'} → {', '.join(sorted(sq(dopo))) or 'nessuna'}")
    if te(prima) != te(dopo):
        risultati.append(f"terminali validi: {', '.join(sorted(te(prima))) or 'nessuno'} → {', '.join(sorted(te(dopo))) or 'nessuno'}")
    if a != b:
        risultati.append(f"soluzioni: {'; '.join(sorted(a)) or 'nessuna'} → {'; '.join(sorted(b)) or 'nessuna'}")
    if prima['stato'] != dopo['stato']:
        risultati.append(f"esito: {prima['stato']} → {dopo['stato']}")
    return {'parametri': cambi, 'risultati': risultati or ['nessuna differenza nei risultati'],
            'prima': prima['sintesi'], 'dopo': dopo['sintesi']}


# ─────────────────────────── storico dei controlli («registrate cosa cambia») ───────────────────────────
def registra(v, origine):
    try:
        _file(FILE_STORICO).parent.mkdir(parents=True, exist_ok=True)
        riga = {'quando': time.strftime('%Y-%m-%d %H:%M:%S'), 'origine': origine, 'parametri': v['parametri'],
                'stato': v['stato'], 'sintesi': v['sintesi'],
                'soluzioni': [{k: s[k] for k in ('squadra', 'sanitario', 'sicurezza', 'canale', 'codice')} for s in v['soluzioni']],
                'esclusi': len(v['esclusi'])}
        with open(_file(FILE_STORICO), 'a', encoding='utf-8') as f:
            f.write(json.dumps(riga, ensure_ascii=False) + '\n')
    except OSError:
        pass


def storico(n=30):
    try:
        righe = [json.loads(r) for r in _file(FILE_STORICO).read_text(encoding='utf-8').splitlines() if r.strip()]
    except (OSError, ValueError):
        righe = []
    righe = righe[-n:]
    for i, r in enumerate(righe):   # per ogni controllo: cosa cambia rispetto a quello prima con parametri diversi
        prec = next((x for x in reversed(righe[:i]) if x['parametri'] != r['parametri']), None)
        if prec:
            r['rispetto_a'] = {'quando': prec['quando'], 'sintesi': prec['sintesi'],
                               'parametri': {k: [prec['parametri'].get(k), r['parametri'].get(k)] for k in r['parametri']
                                             if prec['parametri'].get(k) != r['parametri'].get(k)}}
    return righe[::-1]


# ─────────────────────────── quando la domanda riguarda questo database ───────────────────────────
_PAROLE = re.compile(
    r'\b(autorizzat\w*|autorizzaz\w*|operatori|terminal\w*|chiav[ei]|varc\w*|v-?\d{2}\w*|lete|permess\w*|abilitaz\w*|'
    r'sospes\w*|sospension\w*|revoc\w*|canal[ei]|finestr\w*|database|db|sql|query|tabell\w*|dizionario|'
    r'[rem]\d{2}|sanitari\w*|sicurezza|candidat\w*|esclus\w*|parametr\w*|soluzion\w*|primo respiro|codice di accesso|'
    r'codice per entrare|entrare|accessi passati|copia del registro|chi puo entrare)\b', re.I)
_ALTRI = re.compile(r'\b(focolai\w*|rifugi\w*|bollettin\w*|ripetitor\w*|cabina|tesserin\w*|malevol\w*|imprevist\w*|'
                    r'mappa di roma|programma|python)\b', re.I)
_SEGUITO = re.compile(r'\b(e se|e con|e invece|invece|e per|e alle|e al|e nel|e a|se arriviamo|se arrivassimo|ripeti|rifai|'
                      r'di nuovo|ancora)\b', re.I)


def serve(domanda, cronologia=None):
    if not disponibile():
        return False
    d = base.norm(domanda)
    if _ALTRI.search(d) and not re.search(r'\b(database|sql|query|tabell\w*)\b', d):
        return False
    if _PAROLE.search(d) or base.richiesta_di_modifica(domanda):
        return True
    precedenti = [m for m in (cronologia or []) if isinstance(m, dict) and m.get('role') == 'user']
    if precedenti and len(d.split()) <= 16:
        prima = base.norm(str(precedenti[-1].get('content', '')))
        if _PAROLE.search(prima) and (_SEGUITO.search(d) or parametri_dalla_domanda(domanda)[0]):
            return True
    return False


_MESI = {'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4, 'maggio': 5, 'giugno': 6, 'luglio': 7, 'agosto': 8,
         'settembre': 9, 'ottobre': 10, 'novembre': 11, 'dicembre': 12}


def parametri_dalla_domanda(domanda, base_par=None):
    """Parametri scritti nella domanda: «alle 12:30», «il 5 novembre», «varco V-38-B», «canale Lambda»...
    Restituisce (cambi, note). Solo quelli diversi dai parametri in uso."""
    base_par = base_par or parametri()
    d = domanda
    cambi, note = {}, []
    data = base_par['istante'][:10]
    m = re.search(r'\b(20\d{2})-(\d{2})-(\d{2})\b', d)
    if m:
        data = m.group(0)
    else:
        m = re.search(r'\b(\d{1,2})\s+(' + '|'.join(_MESI) + r')(?:\s+(20\d{2}))?', d, re.I)
        if m:
            data = f"{m.group(3) or base_par['istante'][:4]}-{_MESI[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    ora = base_par['istante'][11:]
    m = re.search(r'(?<![\d-])([01]?\d|2[0-3])[:.]([0-5]\d)(?![\d])', d)
    if m:
        ora = f'{int(m.group(1)):02d}:{m.group(2)}'
    else:
        m = re.search(r'\balle\s+(?:ore\s+)?([01]?\d|2[0-3])\b(?![:.\d])', d, re.I)
        if m:
            ora = f'{int(m.group(1)):02d}:00'
    ist = f'{data} {ora}'
    if ist != base_par['istante']:
        cambi['istante'] = ist
    m = re.search(r'\b([A-Z]-\d{1,3}(?:-[A-Z0-9]+)?)\b', d, re.I)
    if m and m.group(1).upper() != base_par['varco'] and re.search(r'varc|^\s*e\b|\bV-', d, re.I):
        cambi['varco'] = m.group(1).upper()
    m = re.search(r'\bcanale\s+([A-Za-zÀ-ÿ]+)', d, re.I)
    if m and m.group(1).lower() not in ('del', 'dello', 'della', 'compatibile', 'giusto', 'corretto', 'non', 'di', 'e', 'che',
                                        'usato', 'usa', 'serve', 'manca', 'mancante'):
        c = 'Canale ' + m.group(1)[:1].upper() + m.group(1)[1:].lower()
        noti = {x.lower(): x for x in canali()}
        c = noti.get(c.lower(), c)
        if c.lower() not in noti:
            note.append(f'il {c} non esiste nel database')
        if c != base_par['canale']:
            cambi['canale'] = c
    m = re.search(r'\b(Archivio\s+(?:Distretto\s+)?[A-Z0-9][\w-]*)', d)
    if m and m.group(1) != base_par['sito']:
        cambi['sito'] = m.group(1)
    return cambi, note


_DA_CENTRALE = re.compile(r'\b(la\s+centrale|centrale\s+(?:comunica|aggiorna|dice|ha)|nuovi\s+parametri|parametri\s+'
                          r'aggiornati|aggiornamento\s+della\s+centrale|ufficiale)\b', re.I)
_IPOTESI = re.compile(r'\b(e se|se arriv\w*|supponi\w*|ipotesi|ipotizz\w*|cosa succede se|cosa cambia se)\b', re.I)
_MAPPA = re.compile(r'\b(mappa|dizionario|significat\w*|struttur\w*|schema|relazion\w*|tabell\w*|colonn\w*|'
                    r'chiavi? (?:primari\w*|estern\w*)|[rem]\d{2})\b', re.I)
_SOLUZIONE = re.compile(r'\b(autorizzat\w*|autorizzaz\w*|operatori|terminal\w*|chiav[ei]|varc\w*|entrare|candidat\w*|'
                        r'esclus\w*|soluzion\w*|lete|permess\w*|abilitaz\w*|sospes\w*|revoc\w*|canal\w*|finestr\w*|'
                        r'parametr\w*|centrale|controll\w*|codice|chi (?:puo|può|deve))\b', re.I)


def tipo_domanda(domanda, cambi):
    d = base.norm(domanda)
    mappa = bool(_MAPPA.search(d)) and not re.search(r'mappa di roma', d)
    soluzione = bool(_SOLUZIONE.search(d)) or bool(cambi)
    return {'mappa': mappa, 'soluzione': soluzione or not mappa}


# ─────────────────────────── l'agente: domanda → SQL del modello → tool → risultato ───────────────────────────
PROMPT_SQL = """Sei il generatore di query SQL dell'investigatore {nome} (missione «{missione}», Giorno 4). Rispondi SOLO \
con un oggetto JSON, senza altro testo:
- {{"sql": "SELECT ...", "perche": "a cosa serve", "ultima": true/false}}: UNA query di lettura (SQLite). "ultima": true \
se con questa hai i dati per rispondere;
- {{"fine": true}} se le query già eseguite bastano;
- {{"sql": null, "chiedi": "..."}} se serve un dato che il database non contiene (va chiesto alla centrale);
- {{"sql": null, "motivo": "..."}} se la domanda chiede di modificare, cancellare o inserire dati (il tool è di sola \
lettura) oppure non riguarda il database.
Puoi fare al massimo {passi} query; dopo ognuna ricevi il risultato.

DATABASE archivio_recuperato.sqlite (nomi in codice, nessun vincolo recuperato: la mappa qui sotto è la nostra \
ricostruzione, verificata sui dati)
{schema}

REGOLE DI ACCESSO (foglio «Regole» della missione)
{regole}

PARAMETRI DELLA MISSIONE IN USO: istante {istante} · varco {varco} · sito {sito} · canale del lettore del veicolo: {canale}

COME SCRIVERE LE QUERY
- Usa i JOIN sulle chiavi della mappa e mostra colonne leggibili con alias chiari (r03.v1 AS persona, r11.v1 AS squadra, \
r07.v1 AS varco, r09.v1 AS canale, r13.v1 AS codice, ...).
- Validità all'istante T: x.ts_a <= 'T' AND (x.ts_b IS NULL OR 'T' < x.ts_b). Revoca efficace: e10.ts_a <= 'T'.
- Per esplorare usa campioni (LIMIT), COUNT, COUNT(DISTINCT ...), GROUP BY e controlli dei riferimenti \
(NOT EXISTS / LEFT JOIN ... IS NULL). Al massimo 50 righe arrivano a te.
- Non scegliere mai una riga ordinando gli identificativi. r14 e r15 sono fonti storiche: non provano autorizzazioni.
- Solo SELECT (o WITH ... SELECT non ricorsiva). Niente PRAGMA, niente sqlite_master.

CONVERSAZIONE RECENTE
{conversazione}"""


def agente(domanda, cronologia=None, passo=None):
    """Domanda → il modello propone le query (anche più d'una) → il codice le esegue → verifica del codice → esito."""
    passo = passo or (lambda t: None)
    t0 = time.perf_counter()
    prima = impronta()
    par_uso = parametri()
    cambi, note = parametri_dalla_domanda(domanda, par_uso)
    esito = {'missione': CHIAVE, 'titolo_missione': NOME_MISSIONE, 'domanda': domanda, 'tentativi': [], 'query_modello': [],
             'origine': None, 'query': None, 'file': percorso().name if percorso() else None, 'note_parametri': note}
    d = base.norm(domanda)
    if cambi and _DA_CENTRALE.search(d) and not _IPOTESI.search(d):    # aggiornamento ufficiale: diventa il nuovo parametro
        vecchi = par_uso
        par_uso, salvati = salva_parametri(cambi, origine='centrale (chat)')
        esito['aggiornati'] = salvati
        passo('📡 La centrale aggiorna i parametri: ' + ', '.join(f'{k} {a or "—"} → {b}' for k, (a, b) in salvati.items()))
        cambi = {}
        esito['parametri_prima'] = {k: vecchi.get(k, '') for k in ('istante', 'varco', 'sito', 'canale')}
    par = valida_parametri({**par_uso, **cambi})
    esito.update(parametri=par, parametri_missione={k: par_uso.get(k, '') for k in ('istante', 'varco', 'sito', 'canale')},
                 cambiati=cambi, data_missione=par['istante'])
    tipo = tipo_domanda(domanda, cambi)
    esito['tipo'] = tipo

    if base.richiesta_di_modifica(domanda):           # «cancella», «togli la sospensione», «DROP TABLE»: mai
        esito.update(origine='bloccata', bloccata=True,
                     errore='Richiesta di modifica rifiutata: il tool SQL è di sola lettura (file aperto in read-only, solo '
                            'SELECT autorizzate). Non si cambiano dati o permessi per rendere valida una soluzione.')
        passo('⛔ Richiesta di modificare il database: rifiutata, il tool è di sola lettura')
        prova = interroga_database("DELETE FROM e04 WHERE ts_b IS NULL")
        esito['prova_blocco'] = {'query': 'DELETE FROM e04 WHERE ts_b IS NULL', 'esito': prova.get('errore')}
        passo(f'🛡 Prova di sicurezza: DELETE inviato al tool → bloccato («{(prova.get("errore") or "")[:60]}»)')
    else:
        passi_max = max(1, int(getattr(config, 'SQL_PASSI', 3)))
        sistema = PROMPT_SQL.format(nome=config.NOME, missione=NOME_MISSIONE, passi=passi_max, schema=schema_testo(),
                                    regole=REGOLE, istante=par['istante'], varco=par['varco'], sito=par['sito'] or '—',
                                    canale=par['canale'] or 'NON COMUNICATO (non è nel database)',
                                    conversazione=base.conversazione(cronologia))
        messaggi = [{'role': 'system', 'content': sistema}, {'role': 'user', 'content': domanda}]
        passo('🗄 Tool SQL: il modello legge la mappa delle 14 tabelle e le regole e propone le query')
        eseguite, errori = 0, 0
        for _ in range(passi_max + 2):
            if eseguite >= passi_max:
                break
            try:
                risposta = base.genera(messaggi, max_tokens=500)
            except Exception as e:
                esito['tentativi'].append({'proposta': '', 'errore': f'{type(e).__name__}: {e}'[:200]})
                break
            if not risposta:
                esito['tentativi'].append({'proposta': '', 'errore': 'nessun modello disponibile'})
                break
            prop = base.leggi_json(risposta)
            if prop is None:
                esito['tentativi'].append({'proposta': risposta[:400], 'errore': 'il modello non ha prodotto JSON valido'})
                errori += 1
                if errori > 1:
                    break
                messaggi += [{'role': 'assistant', 'content': risposta},
                             {'role': 'user', 'content': 'Rispondi solo con il JSON {"sql": "SELECT ...", "ultima": true/false}.'}]
                continue
            if prop.get('fine') and not prop.get('sql'):
                break
            if not prop.get('sql'):
                esito['chiedi'], esito['motivo'] = prop.get('chiedi'), prop.get('motivo')
                esito['tentativi'].append({'proposta': json.dumps(prop, ensure_ascii=False)[:400], 'errore': None, 'nessuna_query': True})
                passo('🗄 Il modello non propone query: ' + (prop.get('chiedi') or prop.get('motivo') or '—')[:120])
                break
            q = str(prop['sql']).strip()
            passo(f'🧾 Query {eseguite + 1} proposta dal modello: ' + re.sub(r'\s+', ' ', q)[:160])
            r = interroga_database(q)
            esito['tentativi'].append({'proposta': q, 'errore': r.get('errore')})
            if 'errore' in r:
                errori += 1
                passo(('⛔ Bloccata: ' if r.get('bloccata') else '⚠ Errore SQL: ') + r['errore'][:140])
                if errori > 2:
                    break
                messaggi += [{'role': 'assistant', 'content': risposta},
                             {'role': 'user', 'content': f'La query ha dato errore: {r["errore"]}. Correggila e rispondi solo '
                                                         'con il JSON {"sql": "SELECT ...", "ultima": true/false}.'}]
                continue
            eseguite += 1
            esito['query_modello'].append({'n': eseguite, 'perche': str(prop.get('perche') or '')[:200], 'query': q, **r})
            passo(f'▶ Eseguita in sola lettura: {len(r["righe"])} rig{"a" if len(r["righe"]) == 1 else "he"} in {r["ms"]} ms'
                  + (' (prime 50)' if r['altre_righe'] else ''))
            if prop.get('ultima') or eseguite >= passi_max:
                break
            messaggi += [{'role': 'assistant', 'content': risposta},
                         {'role': 'user', 'content': f'RISULTATO della query {eseguite} (JSON): ' + json.dumps(
                             {'colonne': r['colonne'], 'righe': r['righe'], 'altre_righe': r['altre_righe']},
                             ensure_ascii=False)[:6000] + f'\nSe ti serve un\'altra query (ne restano {passi_max - eseguite}) '
                             'rispondi con un altro JSON {"sql": ...}; se hai i dati rispondi {"fine": true}.'}]
        if esito['query_modello']:
            ultima = esito['query_modello'][-1]
            esito.update(origine='modello', query=ultima['query'], colonne=ultima['colonne'], righe=ultima['righe'],
                         altre_righe=ultima['altre_righe'], ms=ultima['ms'], letture=ultima.get('letture'))

        # la verifica del codice (sempre, per le domande sull'accesso; è anche la «query di riserva» senza modello)
        if tipo['soluzione']:
            v = verifica(par)
            esito['verifica'] = v
            registra(v, 'chat')
            passo(f'🔍 Verifica del codice ({len(v["passi"])} query, tutte le regole): ' + v['sintesi'][:180])
            if v['esclusi']:
                passo(f'🚫 Esclusi con il motivo: {len(v["esclusi"])} (squadre, persone, terminali, varchi simili)')
            if v.get('mancante'):
                passo('❔ Informazione mancante: ' + v['mancante'][:160])
            if cambi or esito.get('aggiornati'):
                prima_par = esito.get('parametri_prima') or esito['parametri_missione']
                vb = verifica(prima_par)
                esito['confronto'] = confronta(vb, v)
                passo('↔ Confronto con i parametri ' + ('precedenti' if esito.get('aggiornati') else 'della missione') + ': '
                      + '; '.join(esito['confronto']['risultati'])[:180])
            if not esito['query'] and v['passi']:
                fin = v['passi'][-1]
                esito.update(origine='riserva', query=fin['query'], colonne=fin.get('colonne'), righe=fin.get('righe'),
                             altre_righe=fin.get('altre_righe'), ms=fin.get('ms'), letture=fin.get('letture'))
                passo('🧩 Nessuna query del modello: uso le query della verifica del codice')
        if tipo['mappa']:
            esito['mappa'] = True
            if not esito['origine']:
                esito['origine'] = 'riserva'      # la mappa la calcola il codice (struttura) anche senza modello
            passo('🗺 Mappa delle 14 tabelle con le prove (righe, distinti, riferimenti verificati su tutti i dati)')
    dopo = impronta()
    esito['integro'] = prima == dopo
    esito['impronta'] = (dopo or '')[:16]
    esito['secondi'] = time.perf_counter() - t0
    esito['codici'] = codici_validi(esito)
    return esito


def codici_validi(esito):
    """I codici che la risposta può citare: quelli delle righe restituite (query del modello e verifica)."""
    out = set()
    for q in esito.get('query_modello') or []:
        for i, c in enumerate(q.get('colonne') or []):
            for r in q.get('righe') or []:
                if r[i] is not None and re.fullmatch(r'\d{4,8}', str(r[i])):
                    out.add(str(r[i]))
    v = esito.get('verifica') or {}
    out |= set(v.get('codici') or [])
    for p in v.get('passi') or []:
        for i, c in enumerate(p.get('colonne') or []):
            if c in ('codice', 'chiave'):
                for r in p.get('righe') or []:
                    if r[i] is not None:
                        out |= set(str(r[i]).split(' / '))
    return sorted(out)


def controlla_risposta(testo, esito):
    """Dopo la risposta del modello: codici che non sono tra le righe restituite, o con gli zeri persi."""
    if not esito or not testo:
        return []
    validi = set(codici_validi(esito))
    problemi = []
    for c in dict.fromkeys(re.findall(r'(?<![\w:.-])\d{5,8}(?![\w:-]|[.,]\d)', testo)):
        if c in validi or c.startswith('20') and len(c) == 4:
            continue
        perso = [v for v in validi if v.lstrip('0') == c and v != c]
        if perso:
            problemi.append(f'il codice {c} ha perso gli zeri iniziali: quello giusto è {perso[0]}')
        elif len(c) == 6:
            problemi.append(f'il codice {c} non è tra le righe restituite dal database per questa domanda')
    v = esito.get('verifica')
    if v and v['stato'] == 'unica' and v.get('soluzioni'):
        sol = v['soluzioni'][0]
        if sol['codice'] not in testo:      # soluzione unica: la risposta deve dare QUELLA chiave (non un'altra versione)
            problemi.append(f'la soluzione è unica: chiave {sol["codice"]} ({sol["canale"]}, {sol["sanitario"]} + '
                            f'{sol["sicurezza"]}); la risposta deve citarla esattamente')
    if v and v['stato'] == 'ambigua' and v.get('mancante') and not re.search(
            r'manca|non (?:sappiamo|si sa|è possibile|posso)|centrale|ambigu|più (?:possibilit|terminal|coppi)|due terminali|'
            r'entrambi|oppure|dipende', base.norm(testo)):
        problemi.append('i dati lasciano più possibilità: la risposta deve dire cosa manca e che va chiesto alla centrale')
    return problemi


# ─────────────────────────── per il prompt della risposta ───────────────────────────
def _tabella_testo(colonne, righe, n=50):
    return json.dumps({'colonne': colonne, 'righe': righe[:n]}, ensure_ascii=False)


def blocco_prompt(esito):
    if not esito:
        return ''
    p = esito['parametri']
    out = [f'DATABASE DELLA MISSIONE «{NOME_MISSIONE}» (archivio_recuperato.sqlite) — RISULTATO DEL TOOL SQL (sola lettura)',
           f"Parametri usati: istante {p['istante']} · varco {p['varco']} · sito {p['sito'] or '—'} · canale del lettore del "
           f"veicolo: {p['canale'] or 'NON COMUNICATO (il database non lo contiene)'}."]
    if esito.get('aggiornati'):
        out.append('La centrale ha AGGIORNATO i parametri: ' + ', '.join(f'{k} {a or "—"} → {b}' for k, (a, b) in esito['aggiornati'].items()))
    if esito.get('cambiati'):
        m = esito['parametri_missione']
        out.append('ATTENZIONE: la domanda usa parametri diversi da quelli della missione (' + ', '.join(
            f'{k} {m.get(k) or "—"} → {v}' for k, v in esito['cambiati'].items()) + '): è un\'ipotesi, i parametri ufficiali '
            'non cambiano finché la centrale non li aggiorna.')
    for n in esito.get('note_parametri') or []:
        out.append(f'Nota: {n}.')
    if esito.get('bloccata'):
        out.append(f'RICHIESTA BLOCCATA: {esito.get("errore")}')
        out.append('Spiega che il database si può solo leggere: nessun dato è stato cancellato o modificato '
                   f'(impronta del file uguale prima e dopo: {"sì" if esito.get("integro") else "NO"}).')
    if esito.get('chiedi'):
        out.append(f'IL GENERATORE DI QUERY CHIEDE: {esito["chiedi"]}')
    for q in esito.get('query_modello') or []:
        out.append(f'Query {q["n"]} proposta dal modello ed eseguita dal tool' + (f' ({q["perche"]})' if q.get('perche') else '') + ':')
        out.append(q['query'])
        out.append('Risultato: ' + _tabella_testo(q['colonne'], q['righe']) + (' (prime 50 righe)' if q['altre_righe'] else ''))
    v = esito.get('verifica')
    if v:
        out.append('VERIFICA DEL CODICE (tutte le regole, su tutti i dati, con query SQL di sola lettura):')
        if v.get('errore'):
            out.append(f'- errore: {v["errore"]}')
        vr = [f"{x['varco']} ({x['sito']}): {x['esito']}" for x in v['varchi']]
        out.append('- Varchi: ' + ('; '.join(vr) or 'nessuno'))
        out.append('- Squadre con permessi sul varco: ' + '; '.join(
            f"{s['nome']} → {'VALIDA' if s.get('valida') else 'esclusa: ' + s['motivo']}" for s in v['squadre']))
        if v['persone']:
            out.append('- Membri delle squadre candidate: ' + '; '.join(
                f"{x['persona']} ({x['badge']}, {x['squadra']}): {'OK, ' if x['ok'] else 'escluso, '}{x['motivo']}" for x in v['persone']))
        out.append('- Coppie valide: ' + ('; '.join(f"{c['squadra']}: {c['sanitario']} ({c['badge_sanitario']}, SANITARIO) + "
                                                   f"{c['sicurezza']} ({c['badge_sicurezza']}, SICUREZZA)" for c in v['coppie']) or 'nessuna'))
        out.append('- Terminali del varco: ' + '; '.join(
            f"{t['canale']} (terminale {t['terminale']}, {t['stato']}, finestre valide {t['finestre_valide']}, chiave valida "
            f"{t['codice'] or 'nessuna'}) → {t['esito']}" for t in v['terminali']))
        out.append(f"- ESITO: {v['stato'].upper()} — {v['sintesi']}")
        for s in v['soluzioni']:
            out.append(f"  · {s['squadra']}: {s['sanitario']} ({s['badge_sanitario']}) + {s['sicurezza']} ({s['badge_sicurezza']}), "
                       f"terminale {s['canale']} ({s['terminale']}), chiave {s['codice']} (valida {s['chiave_dal']} – {s['chiave_al'] or '…'})")
        if v.get('mancante'):
            out.append(f'- INFORMAZIONE MANCANTE: {v["mancante"]}')
        out.append(f'- Esclusi ({len(v["esclusi"])}): ' + '; '.join(f"{e['tipo']} {e['chi']}: {e['motivo']}" for e in v['esclusi'][:20]))
        out.append('- Fonti storiche r14 (copia del registro, 3/11 18:00) e r15 (accessi del 3/11): non usate come prova.')
        if v.get('incoerenza'):
            out.append('- ATTENZIONE: ' + v['incoerenza'])
    if esito.get('confronto'):
        c = esito['confronto']
        out.append('COSA CAMBIA rispetto ai parametri ' + ('precedenti' if esito.get('aggiornati') else 'della missione') + ': '
                   + '; '.join(c['parametri']) + ' → ' + '; '.join(c['risultati']) + f'. Prima: {c["prima"]} Dopo: {c["dopo"]}')
    if esito.get('mappa'):
        out.append('MAPPA DELLE 14 TABELLE (ricostruita e verificata dal codice su tutti i dati):')
        out.append(mappa_testo())
    out.append('Come rispondere: usa SOLO queste righe e questa verifica. Se l\'esito è UNICA, la PRIMA frase dice la chiave '
               '(es. «Il codice per il varco V-38 è 108958, terminale Canale Kappa»); poi i due operatori (nome e badge), '
               'la squadra, il terminale (canale) e la chiave ESATTAMENTE come nelle righe. Se è AMBIGUA non scegliere: elenca '
               'le possibilità, di\' cosa manca e che va chiesto alla centrale. Se è NESSUNA dichiaralo. Spiega almeno tre '
               'candidati esclusi con il motivo e la regola. Cita le tabelle (es. «r08, permesso 9992717»), non tra parentesi '
               'quadre. Le fonti storiche non provano autorizzazioni. Se c\'è il confronto, di\' cosa cambia. Per la mappa: '
               'tabella, significato, chiavi, relazioni e prove.')
    return '\n'.join(out)


def data_italiana(ist):
    """'2026-11-04 12:30' → 'il 4 novembre 2026 alle 12:30'"""
    m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2})', ist or '')
    if not m:
        return f'il {ist}'
    mesi = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre', 'ottobre',
            'novembre', 'dicembre']
    return f'il {int(m.group(3))} {mesi[int(m.group(2)) - 1]} {m.group(1)} alle {m.group(4)}'


def risposta_di_riserva(esito):
    """Senza modello: la risposta la compone il codice dal risultato (senza inventare)."""
    if esito.get('bloccata'):
        return ('Non posso farlo: il database si può solo leggere. La richiesta è stata rifiutata e nessun dato è cambiato'
                + (' (impronta del file identica prima e dopo).' if esito.get('integro') else '.'))
    pezzi = []
    v = esito.get('verifica')
    if v and v['stato'] == 'unica' and not esito.get('mappa'):      # la risposta che serve: chiara, in tre righe
        s, p = v['soluzioni'][0], v['parametri']
        badge = lambda b: f' ({b})' if b else ''
        ipotesi = 'Ipotesi (i parametri ufficiali non cambiano): ' if esito.get('cambiati') else ''
        righe = [ipotesi + f"Il codice per il varco {p['varco']}" + (f" ({p['sito']})" if p['sito'] else '') +
                 f" è **{s['codice']}**, sul terminale {s['canale']}.",
                 f"Entrano {s['sanitario']}{badge(s.get('badge_sanitario'))} come SANITARIO e {s['sicurezza']}"
                 f"{badge(s.get('badge_sicurezza'))} come SICUREZZA, della {s['squadra']}, {data_italiana(p['istante'])}."]
        if v['esclusi']:
            righe.append(f"Ho escluso {len(v['esclusi'])} candidati, per esempio: " +
                         '; '.join(f"{e['chi']} ({e['motivo']})" for e in v['esclusi'][:3]) + '.')
        if esito.get('confronto'):
            righe.append('Cosa cambia: ' + '; '.join(esito['confronto']['risultati']) + '.')
        righe.append('Query, righe ed esclusi completi sono nel pannello 🗄 Query SQL qui sotto.')
        return '\n'.join(righe)
    if v:
        pezzi.append(v['sintesi'])
        if v['stato'] == 'ambigua':
            pezzi.append(v.get('mancante') or '')
            pezzi.append('Possibilità: ' + '; '.join(f"{s['squadra']} con {s['sanitario']} e {s['sicurezza']}, {s['canale']} "
                                                       f"chiave {s['codice']}" for s in v['soluzioni']) + '.')
        if v['esclusi']:
            pezzi.append('Esclusi: ' + '; '.join(f"{e['chi']} ({e['motivo']})" for e in v['esclusi'][:6]) + '.')
    if esito.get('confronto'):
        pezzi.append('Cosa cambia: ' + '; '.join(esito['confronto']['risultati']) + '.')
    if esito.get('mappa'):
        s = struttura()
        pezzi.append('Mappa delle tabelle: ' + '; '.join(f"{t['nome']} = {t['entita']} ({t['righe']} righe)" for t in s.get('tabelle', [])) + '.')
    if not pezzi and esito.get('query_modello'):
        q = esito['query_modello'][-1]
        pezzi.append(f"La query restituisce {len(q['righe'])} righe: " + ' | '.join(
            ', '.join(f'{k} {x}' for k, x in zip(q['colonne'], r)) for r in q['righe'][:5]) + '.')
    return ' '.join(pezzi) or 'Non ho eseguito nessuna query sul database.'


def per_la_pagina(esito):
    """L'esito per l'interfaccia (pannello «🗄 Query SQL» e pagina dello schema E/R)."""
    if not esito:
        return None
    chiavi = ('missione', 'titolo_missione', 'domanda', 'origine', 'query', 'colonne', 'righe', 'altre_righe', 'ms', 'letture',
              'errore', 'bloccata', 'chiedi', 'motivo', 'tentativi', 'query_modello', 'verifica', 'confronto', 'parametri',
              'parametri_missione', 'cambiati', 'aggiornati', 'note_parametri', 'integro', 'impronta', 'secondi',
              'data_missione', 'prova_blocco', 'file', 'tipo', 'mappa')
    out = {k: esito.get(k) for k in chiavi}
    letture = set(out.get('letture') or [])
    for q in esito.get('query_modello') or []:
        letture |= set(q.get('letture') or [])
    for p in (esito.get('verifica') or {}).get('passi') or []:
        letture |= set(p.get('letture') or [])
    out['letture'] = sorted(letture)
    return out


# ─────────────────────────── esempi per la console della pagina dello schema ───────────────────────────
def esempi_console():
    p = parametri()
    T, V = sql_str(p['istante']), sql_str(p['varco'])
    return [
        ['Campione di una tabella (r08)', 'SELECT *\nFROM r08\nLIMIT 10'],
        ['Conteggi e distinti (r06)', 'SELECT COUNT(*) AS righe, COUNT(DISTINCT k1) AS persone, COUNT(DISTINCT v1) AS ruoli\nFROM r06'],
        ['Valori distinti di una colonna (r08.v2)', 'SELECT v2 AS stato, COUNT(*) AS righe\nFROM r08\nGROUP BY v2'],
        ['Controllo dei riferimenti: r08.k2 → r07', 'SELECT COUNT(*) AS righe,\n  SUM(NOT EXISTS (SELECT 1 FROM r07 v WHERE v.k0 = p.k2)) AS orfani\nFROM r08 p'],
        ['Appartenenze doppie (m12)', 'SELECT k1 AS persona, k2 AS squadra, COUNT(*) AS registrazioni\nFROM m12\nGROUP BY k1, k2\nHAVING COUNT(*) > 1\nLIMIT 20'],
        ['Il varco della missione', f'SELECT v.k0, v.v1 AS varco, s.v1 AS sito\nFROM r07 v JOIN r02 s ON s.k0 = v.k1\nWHERE v.v1 LIKE {sql_str(p["varco"] + "%")}'],
        ['Permessi sul varco all\'istante', f"""SELECT q.v1 AS squadra, p.v1 AS ruolo, p.v2 AS stato, p.ts_a, p.ts_b,
  (SELECT MIN(r.ts_a) FROM e10 r WHERE r.k1 = p.k0) AS revoca
FROM r08 p
JOIN r11 q ON q.k0 = p.k1
JOIN r07 v ON v.k0 = p.k2
WHERE v.v1 = {V}
ORDER BY q.v1, p.v1"""],
        ['Terminali del varco, finestre e chiavi', f"""SELECT t.v1 AS canale, t.v2 AS stato,
  (SELECT COUNT(*) FROM m05 f WHERE f.k1 = t.k0 AND {_val('f', T)}) AS finestre_valide,
  (SELECT GROUP_CONCAT(c.v1) FROM r13 c WHERE c.k1 = t.k0 AND {_val('c', T)}) AS codice
FROM r09 t
JOIN r07 v ON v.k0 = t.k1
WHERE v.v1 = {V}"""],
        ['Sospensioni attive all\'istante', f"SELECT pe.v1 AS persona, s.v1 AS motivo, s.ts_a, s.ts_b\nFROM e04 s\nJOIN r03 pe ON pe.k0 = s.k1\nWHERE {_val('s', T)}"],
        ['Prova: cancellare (viene bloccata)', "DELETE FROM e10"],
        ['Prova: leggere sqlite_master (bloccata)', 'SELECT name, sql FROM sqlite_master'],
    ]
