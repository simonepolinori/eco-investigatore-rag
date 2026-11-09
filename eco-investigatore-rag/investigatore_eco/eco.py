"""Il cervello di ECO: prompt + fascicolo + RAG + memoria + conversazione → motore (Gemini o Qwen) → controllo delle fonti.

Il codice non scrive risposte e non smista le domande: capisce e decide tutto il modello.
Il codice gli prepara che cosa leggere:
  - il FASCICOLO (Giorno 1, Giorno 2, imprevisti), sempre intero;
  - il CATALOGO dell'archivio digitale, prodotto dalla scansione (rag.py, fase 2): quali file sono della storia;
  - la MEMORIA: i file dell'archivio già emersi nella conversazione (citati, trovati o nominati);
  - i RISULTATI DELLA RICERCA per l'ultima domanda (rag.py, fase 5);
  - la CRONOLOGIA della chat (gli ultimi config.MEMORIA_TURNI scambi).
  - dal Giorno 4, il RISULTATO DEL TOOL SQL (database.py) quando la domanda riguarda il database della missione
    («Il cancello nero» o «Il primo respiro»): il modello propone le query, il codice le esegue in sola lettura, il
    risultato (con la verifica del codice sulle regole) torna al modello.
Reti di sicurezza: se la risposta cita un ID che non esiste, il modello la riscrive una volta; se cita un codice di
accesso che il database non ha restituito (o perde gli zeri iniziali), il modello la riscrive una volta.
"""
import json
import re
import time

import archivio
import config
import database
import istruzioni
import motori
import rag

CITAZIONE = re.compile(r'\[([^\[\]]{2,80})\]')
FORMA_ID = re.compile(r'^[A-Z]{1,4}\d*[-_ ]\d{1,5}$', re.I)
SEGNO_DETTAGLI = '⏱'
SEGNO_FILE = '📂'
SEGNO_SQL = '🗄'


def _lettere(i):
    m = re.match(r'[A-Z]+', i)
    return m.group(0) if m else ''


def fonti_citate(testo):
    """Gli ID tra parentesi quadre, nell'ordine in cui compaiono (senza doppioni).
    Contano solo i codici con la forma di un documento (G…, LX…, ARCH, WIKI): [B-317], [EV-341] o [M362-065] sono
    bollettini, segnali e pratiche, non documenti, e non vanno segnalati come fonti inventate."""
    prefissi = {_lettere(i) for i in archivio.ids() | rag.ids()}
    trovati = []
    for gruppo in CITAZIONE.findall(testo):
        for pezzo in re.split(r'[,;/]|\be\b', gruppo):
            pezzo = pezzo.strip()
            if FORMA_ID.match(pezzo):
                i = archivio.normalizza_id(pezzo)
                if i not in trovati and _lettere(i) in prefissi:
                    trovati.append(i)
    return trovati


def _pulisci(testo):
    """Toglie le righe dei dettagli dalle risposte precedenti prima di ridarle al modello."""
    righe = testo.splitlines()
    fine = next((i for i, r in enumerate(righe) if r.startswith(SEGNO_SQL + ' ')), len(righe))   # blocco SQL: sempre in fondo
    return '\n'.join(r for r in righe[:fine] if SEGNO_DETTAGLI not in r and SEGNO_FILE not in r).strip()


def _testo(contenuto):
    """Gradio può passare il contenuto come stringa, dizionario o lista di parti."""
    if isinstance(contenuto, str):
        return contenuto
    if isinstance(contenuto, dict):
        return contenuto.get('text') or contenuto.get('content') or ''
    if isinstance(contenuto, (list, tuple)):
        return ' '.join(_testo(c) for c in contenuto)
    return ''


def _messaggi_grezzi(cronologia):
    """La cronologia di Gradio (o della console) come lista di (ruolo, testo completo)."""
    out = []
    for m in cronologia or []:
        if isinstance(m, dict):
            if m.get('role') in ('user', 'assistant'):
                out.append((m['role'], _testo(m.get('content'))))
        elif isinstance(m, (list, tuple)) and len(m) == 2:          # vecchio formato [domanda, risposta]
            if m[0]:
                out.append(('user', _testo(m[0])))
            if m[1]:
                out.append(('assistant', _testo(m[1])))
    return [(r, t) for r, t in out if t.strip()]


def prepara_cronologia(cronologia):
    """Ultimi scambi della chat nel formato [{'role': 'user'|'assistant', 'content': str}] da dare al modello."""
    msg = [{'role': r, 'content': _pulisci(t) if r == 'assistant' else t} for r, t in _messaggi_grezzi(cronologia)]
    msg = [m for m in msg if m['content'] and not m['content'].startswith(('⚠', '⏳'))]
    unite = []                                                       # due messaggi di fila dello stesso ruolo → uno
    for m in msg:
        if unite and unite[-1]['role'] == m['role']:
            unite[-1] = {'role': m['role'], 'content': unite[-1]['content'] + '\n' + m['content']}
        else:
            unite.append(m)
    msg = unite[-2 * config.MEMORIA_TURNI:]
    while msg and msg[0]['role'] != 'user':                          # la conversazione deve iniziare dall'utente
        msg.pop(0)
    return msg


# ================================ FASE 6 · MEMORIA DEI FILE ======================================
def memoria_file(cronologia):
    """I file dell'archivio digitale emersi finora nella conversazione, dal più vecchio al più recente.
    Si leggono dalla cronologia stessa: ID citati nelle risposte, file nominati nelle domande,
    riga 📂 dei file recuperati. Così la memoria segue la chat (nuova chat = memoria vuota) e
    il modello ritrova ogni volta il testo dei file anche se l'ultima ricerca ne ha trovati altri."""
    ind = rag.indice()
    if not ind:
        return []
    memoria, turno = {}, 0
    for ruolo, testo in _messaggi_grezzi(cronologia):
        if ruolo == 'user':
            turno += 1
        citati = set(fonti_citate(_pulisci(testo))) if ruolo == 'assistant' else set()
        for d in ind.trova_citati(testo):
            voce = memoria.setdefault(d['id'], {'id': d['id'], 'file': d['file'], 'titolo': d['titolo'],
                                                 'classe': d['classe'], 'testo': d['testo'], 'prima': turno,
                                                 'citato': False, 'nominato': False})
            voce['ultima'] = turno
            voce['citato'] |= d['id'] in citati
            voce['nominato'] |= ruolo == 'user'
    # restano SEMPRE i file citati nelle risposte o nominati da chi scrive; quelli solo "trovati dalla ricerca"
    # restano solo per la domanda dopo (con 1500 file la ricerca ne porta tanti: non devono riempire la memoria).
    # Delle copie della stessa fonte (80 inoltri di B-317) ne resta una sola.
    for v in memoria.values():
        v['famiglia'] = (ind.per_id.get(v['id']) or {}).get('famiglia') or ''
    voci, famiglie = [], set()
    for v in sorted(memoria.values(), key=lambda v: (not (v['citato'] or v['nominato']), -v['ultima'])):
        if not (v['citato'] or v['nominato']) and v['ultima'] < turno:
            continue
        if v['famiglia'] and v['famiglia'] in famiglie:
            continue
        famiglie.add(v['famiglia'])
        voci.append(v)
    voci = voci[:config.MEMORIA_FILE]
    return sorted(voci, key=lambda v: (v['prima'], v['id']))


# ================================ RISPOSTA =======================================================
# ================================ CHIACCHIERE: NIENTE RICERCA =====================================
# Saluti, ringraziamenti, «chi sei?», «cosa sai fare?»: tutte le parole del messaggio sono parole da conversazione.
# Per questi messaggi non si cerca nell'archivio e il prompt è corto: la risposta arriva in uno o due secondi.
PAROLE_CHIACCHIERA = set("""ciao salve buongiorno buonasera buonanotte hey ehi ei hola hello hi ehila eccomi
grazie mille tante tantissime ok okay okk perfetto bene benissimo ottimo va vabbe vabene bravo bravissimo super
chi sei tu come ti chiami stai va cosa che sai fare puoi fai fa aiutarmi aiuto aiutare mi ci può e eco investigatore
assistente piacere arrivederci addio a presto dopo domani buona buon giornata serata notte lavoro si sì no capito
d accordo daccordo il tuo nome sono io siamo noi squadra 3 tre di della bello forte grande top gentilissimo
tutto apposto posto okay ah oh beh allora quindi dunque""".split())


ANCORE_CHIACCHIERA = set("""ciao salve buongiorno buonasera buonanotte hey ehi ei hola hello hi ehila eccomi grazie
arrivederci addio piacere bravo bravissimo gentilissimo""".split())
FRASI_CHIACCHIERA = re.compile(r"\bchi sei\b|\bcome ti chiami\b|\bcome stai\b|\b(cosa|che) (sai|puoi) fare\b|"
                               r"\b(cosa|che) fai\b|\bchi e eco\b|\bil tuo nome\b")


def chiacchiera(domanda):
    """True se il messaggio è solo conversazione (nessuna parola dell'indagine, nessun ID o codice)."""
    import unicodedata
    t = unicodedata.normalize('NFD', (domanda or '').lower().replace('’', "'"))
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    parole = re.findall(r"[a-z0-9]+", t)
    if not parole or len(parole) > 8 or re.search(r'\d{2,}|[a-z]+-\d', t):
        return False
    if not all(w in PAROLE_CHIACCHIERA for w in parole):
        return False
    # serve almeno un saluto, un grazie o una domanda su ECO: «sì», «ok», «e quindi?» sono risposte nel discorso
    # dell'indagine e devono passare dalla ricerca con tutto il contesto
    return bool(ANCORE_CHIACCHIERA & set(parole)) or bool(FRASI_CHIACCHIERA.search(' '.join(parole)))


def ricerca(domanda, cronologia):
    """RAG: cerca nell'archivio digitale i file per questa domanda. (None, []) se non c'è archivio."""
    if not rag.file_archivio():
        return None, []
    precedenti = [m['content'] for m in prepara_cronologia(cronologia) if m['role'] == 'user']
    try:
        return rag.cerca(domanda, precedenti)
    except Exception as e:
        print('RAG: ricerca non riuscita:', e)
        return [], []


_CALCOLA = object()


def sql_per(domanda, cronologia, passo=None):
    """Tool SQL (Giorno 4): esito del database per questa domanda, oppure None se la domanda non lo riguarda."""
    try:
        if not database.serve(domanda, prepara_cronologia(cronologia)):
            return None
        return database.agente(domanda, prepara_cronologia(cronologia), passo)
    except Exception as e:
        print('Tool SQL: non riuscito:', e)
        return {'domanda': domanda, 'errore': f'tool SQL non riuscito ({type(e).__name__}: {e})'[:200], 'origine': None,
                'query': None, 'tentativi': [], 'indizi': {}, 'data_missione': database.data_missione()}


def _breve(r):
    return {k: r[k] for k in ('id', 'file', 'titolo', 'classe', 'punteggio', 'passaggio') if k in r}


def rispondi_stream(domanda, cronologia=None, motore=None, ricerca_fatta=None, sql_fatto=_CALCOLA):
    """Generatore di (testo da mostrare, info). L'ultimo elemento ha info completo (motore, secondi, fonti, ...).
    ricerca_fatta = (risultati, scartati) già calcolati (l'interfaccia con la mappa li mostra prima nei passi).
    sql_fatto = esito del tool SQL già calcolato (None = la domanda non riguarda il database)."""
    t0 = time.perf_counter()
    breve = config.CHIACCHIERE_VELOCI and chiacchiera(domanda)
    sql = None
    if breve:                                    # «ciao», «grazie», «chi sei?»: niente RAG, prompt corto
        risultati, scartati, memoria = [], [], []
        sistema = istruzioni.sistema_breve()
    else:
        risultati, scartati = ricerca_fatta if ricerca_fatta is not None else ricerca(domanda, cronologia)
        sql = sql_per(domanda, cronologia) if sql_fatto is _CALCOLA else sql_fatto
        memoria = memoria_file(cronologia)
        precedenti = [m['content'] for m in prepara_cronologia(cronologia) if m['role'] == 'user'][-2:]
        sistema = istruzioni.sistema(risultati, scartati, memoria, sql=sql, domanda=domanda, precedenti=precedenti)
    t_ricerca = time.perf_counter() - t0
    messaggi = prepara_cronologia(cronologia) + [{'role': 'user', 'content': domanda.strip()}]
    validi = archivio.ids() | rag.ids()
    testo, info = '', None
    for testo, info in motori.rispondi(sistema, messaggi, motore, max_tokens=200 if breve else None):
        if info is None:
            yield testo, None
    citati = fonti_citate(testo)
    sbagliati = [i for i in citati if i not in validi]
    corretta = False
    if sbagliati and config.CONTROLLO_FONTI and info['motore'] != 'nessuno':
        nota = istruzioni.CORREZIONE_FONTI.format(sbagliati=', '.join(sbagliati))
        rifai = messaggi + [{'role': 'assistant', 'content': testo}, {'role': 'user', 'content': nota}]
        nuovo_motore = 'locale' if info['motore'] == 'Qwen locale' else motore
        for testo2, info2 in motori.rispondi(sistema, rifai, nuovo_motore):
            if info2 is None:
                yield testo2, None
        if info2['motore'] != 'nessuno':
            testo, info, corretta = testo2, info2, True
            citati = fonti_citate(testo)
            sbagliati = [i for i in citati if i not in validi]
    # tool SQL: nessun codice inventato, zeri iniziali conservati (una riscrittura, poi l'avviso)
    problemi_sql = database.controlla_risposta(testo, sql) if sql and info['motore'] != 'nessuno' else []
    if problemi_sql and config.CONTROLLO_FONTI:
        nota = ('Nota per te: ' + '; '.join(problemi_sql) + '. Riscrivi la risposta usando solo i codici delle righe '
                'restituite dal database, identici (con gli zeri iniziali).')
        rifai = messaggi + [{'role': 'assistant', 'content': testo}, {'role': 'user', 'content': nota}]
        nuovo_motore = 'locale' if info['motore'] == 'Qwen locale' else motore
        for testo2, info2 in motori.rispondi(sistema, rifai, nuovo_motore):
            if info2 is None:
                yield testo2, None
        if info2['motore'] != 'nessuno':
            testo, info, corretta = testo2, info2, True
            citati = fonti_citate(testo)
            sbagliati = [i for i in citati if i not in validi]
            problemi_sql = database.controlla_risposta(testo, sql)
    if sql and info['motore'] == 'nessuno':      # nessun modello: NESSUNA risposta preimpostata, solo l'avviso
        testo = (testo.strip() + '\nIl tool SQL ha comunque eseguito le query in sola lettura: righe e verifica sono nel '
                 'pannello 🗄 qui sotto. La risposta la scrive solo il modello: riprovate tra poco.')
    info = dict(info, secondi=time.perf_counter() - t0, fonti=citati, fonti_inesistenti=sbagliati, riscritta=corretta,
                sql=database.per_la_pagina(sql), problemi_sql=problemi_sql,
                recuperati=None if risultati is None else [_breve(r) for r in risultati],
                scartati=[_breve(r) for r in scartati], memoria=[_breve(m) for m in memoria],
                secondi_ricerca=t_ricerca, domanda=domanda)
    mostra = testo.strip()
    if problemi_sql:
        mostra += '\n\n⚠ Controllo del codice: ' + '; '.join(problemi_sql) + '.'
    if sbagliati:
        mostra += f'\n\n⚠ Attenzione: {", ".join(sbagliati)} non esiste né nel fascicolo né nell\'archivio.'
    if config.MOSTRA_DETTAGLI:
        mostra += dettagli(info, citati)
    # memoria aggiornata con questa domanda e questa risposta (per il pannello e il diario)
    dopo = list(cronologia or []) + [{'role': 'user', 'content': domanda},
                                     {'role': 'assistant', 'content': testo + dettagli(info, citati)}]
    info['memoria'] = [_breve(m) for m in memoria_file(dopo)]
    _diario(domanda, testo, info)
    yield mostra, info


def rispondi(domanda, cronologia=None, motore=None):
    """Versione senza streaming: (testo, info)."""
    testo, info = '', None
    for testo, info in rispondi_stream(domanda, cronologia, motore):
        pass
    return testo, info


# ================================ COSA VEDE LA SQUADRA ===========================================
def dettagli(info, citati):
    """Riga sotto la risposta. La riga 📂 serve anche alla memoria: elenca i file trovati per questa domanda."""
    if not info or info['motore'] == 'nessuno':
        return ''
    riga = f'{SEGNO_DETTAGLI} {info["secondi"]:.1f} s'
    if config.MOSTRA_MOTORE:
        riga += f' · {info["motore"]}'
        if info['motore'] == 'Gemini':
            riga += f' (richieste oggi: {motori.richieste_gemini_oggi()})'
    riga += ' · fonti: ' + (', '.join(citati) if citati else '—')
    if info.get('avviso') and config.MOSTRA_MOTORE:
        riga += f' · riserva usata perché: {info["avviso"]}'
    testo = f'\n\n_{riga}_'
    rec = info.get('recuperati')
    if rec:
        voci = [f'{"**" if r["id"] in citati else ""}{r["file"]}{"**" if r["id"] in citati else ""} ({r["id"]})'
                for r in rec]
        testo += f'\n\n_{SEGNO_FILE} file recuperati dalla ricerca: ' + ' · '.join(voci) + '_'
    q = info.get('sql') or {}
    if q.get('query'):          # «show query»: la query eseguita dal tool SQL e quante righe ha restituito
        esito = q.get('errore') or f'{len(q.get("righe") or [])} righe'
        testo += (f'\n\n{SEGNO_SQL} Query SQL ({"proposta dal modello" if q.get("origine") == "modello" else "di riserva"}, '
                  f'sola lettura) → {esito}:\n```sql\n{q["query"]}\n```')
        if q.get('righe'):
            testo += '\n' + SEGNO_SQL + ' Righe: ' + ' · '.join(
                '(' + ', '.join(f'{c}={v}' for c, v in zip(q['colonne'], r)) + ')' for r in q['righe'][:5])
    elif q.get('bloccata'):
        testo += f'\n\n{SEGNO_SQL} Tool SQL: {q.get("errore")}'
    v = q.get('verifica')
    if v and v.get('sintesi'):   # missione «Il primo respiro»: l'esito della verifica del codice su tutte le regole
        testo += f'\n{SEGNO_SQL} Verifica del codice ({len(v.get("passi") or [])} query, {len(v.get("esclusi") or [])} esclusi): {v["sintesi"]}'
    return testo


def tabella_recuperati(info):
    """Pannello della chat: file trovati per l'ultima domanda, memoria della conversazione, catalogo della scansione."""
    info = info or {}
    rec = info.get('recuperati')
    if rec is None:
        return 'Nessun archivio digitale caricato.'
    citati = set(info.get('fonti') or [])
    righe = [f'**Domanda:** «{info.get("domanda", "")}»', '', '#### 🔎 Trovati dalla ricerca']
    if rec:
        righe += ['| ID | File | Titolo | Passo | Usato |', '|---|---|---|---|---|']
        for r in rec:
            titolo = r['titolo'][:34] + (' _(incerto)_' if r['classe'] == 'incerto' else '')
            righe.append(f'| {r["id"]} | {r["file"]} | {titolo} | {r["passaggio"]} | {"✅" if r["id"] in citati else ""} |')
    else:
        righe.append('_Nessun file della storia vicino a questa domanda._')
    if info.get('scartati'):
        righe += ['', '_Scartati (rumore, non passati al modello): ' +
                  ' · '.join(f'{r["id"]} «{r["titolo"][:30]}»' for r in info['scartati']) + '_']
    righe += ['', '#### 🧠 Memoria della conversazione (file emersi finora)']
    mem = info.get('memoria') or []
    righe.append(' · '.join(f'{m["id"]} ({m["titolo"][:30]})' for m in mem) if mem else
                 '_Ancora nessun file emerso: la memoria si riempie domanda dopo domanda._')
    ind = rag._stato['indice']
    if ind:
        righe += ['', '#### 🗂 Catalogo della scansione', f'_{rag.descrizione()}_', '']
        righe += [f'- {"✅ " if d["id"] in citati else ""}{d["id"]} · {d["file"]} · {d["titolo"]}'
                  + (' _(incerto)_' if d['classe'] == 'incerto' else '') for d in ind.catalogo()]
    righe += ['', '_Passo: ID = nominato nella domanda, 1 = ricerca, 2 = seconda ricerca (parole rare). '
                  'Usato = citato nella risposta._']
    return '\n'.join(righe)


def _diario(domanda, risposta, info):
    """Registro per la squadra (ECO non lo rilegge mai)."""
    try:
        with open(config.DIARIO, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ora': time.strftime('%Y-%m-%d %H:%M:%S'), 'domanda': domanda, 'risposta': risposta,
                                'motore': info.get('motore'), 'secondi': round(info.get('secondi', 0), 2),
                                'fonti': info.get('fonti'), 'avviso': info.get('avviso'),
                                'file_recuperati': [f'{r["file"]} ({r["id"]})' for r in info.get('recuperati') or []],
                                'memoria': [m['id'] for m in info.get('memoria') or []],
                                'sql': (info.get('sql') or {}).get('query'),
                                'sql_righe': (info.get('sql') or {}).get('righe')},
                               ensure_ascii=False) + '\n')
    except OSError:
        pass


class Conversazione:
    """Una chat che ricorda gli scambi precedenti (per la console e per le prove)."""

    def __init__(self, motore=None):
        self.motore, self.storia = motore, []

    def chiedi(self, domanda):
        testo, info = rispondi(domanda, self.storia, self.motore)
        self.storia += [{'role': 'user', 'content': domanda}, {'role': 'assistant', 'content': testo}]
        return testo, info
