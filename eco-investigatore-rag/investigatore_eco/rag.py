"""RAG di ECO: ricerca nell'archivio digitale del Giorno 3 (1005 file TXT, HTML, JSON, XML) e nei 500 registri
della rete secondaria (imprevisti del Giorno 3, «Documento: LX3-…»).

L'archivio è troppo grande per darlo tutto al modello. Il RAG lavora in due momenti.

UNA VOLTA SOLA, quando si carica l'archivio (prepara):
  FASE 1  LETTURA     ogni file, in qualunque dei 4 formati, diventa {id, titolo, testo, fonte, licenza}.
  FASE 2  SCANSIONE   ogni file riceve dei punti in base a quattro indizi (ID, fonte, licenza, contenuto) e
                      a un quinto (collegamenti con i file già riconosciuti). Esito:
                      "storia" (inerente all'indagine), "rumore" (copie enciclopediche) o "incerto".
                      I file della storia formano il CATALOGO, che il modello vede sempre: così sa quanti e
                      quali sono e non dice mai "non ce ne sono altri" dopo averne visto uno solo.
                      Ogni file riceve anche il TIPO DI PROVA (copia, misura diretta, derivata, sentito dire) e, se è
                      una copia, la FAMIGLIA della fonte copiata (es. B-317).
  FASE 3  BLOCCHI     i testi si dividono in blocchi di frasi intere, con il titolo davanti.
  FASE 4  INDICE      per ogni blocco: parole chiave (BM25, con i codici interi: M362-065 ≠ M362) e significato
                      (embedding, se disponibili).

A OGNI DOMANDA (Indice.cerca):
  FASE 5  RICERCA     a) ID o nomi di file scritti nella domanda: il file si prende direttamente;
                      b) ricerca IBRIDA (BM25 + embedding) sulla domanda e, per le domande brevi
                         ("e il settore?"), anche sulla domanda precedente;
                      b-bis) le domande doppie («quale ripetitore…? quante conferme…?») si cercano anche parte per parte;
                      c) PASSAGGI SUCCESSIVI: i codici e le parole rare dei primi risultati diventano nuove ricerche,
                         un salto alla volta (Ruggine → pratica M362 → lotto K391 → armadio), fino a RAG_PASSAGGI;
                      c-bis) se la domanda nomina un giorno operativo, i documenti di altri giorni scendono;
                      d) dai blocchi ai FILE: al modello passano solo i file della storia (o incerti); i file
                         rumore trovati vengono solo elencati come "scartati"; le COPIE della stessa fonte
                         (80 inoltri del bollettino B-317) diventano una voce sola con il conteggio; dei tipi molto
                         ripetuti (100 «Scheda di reparto») passano al massimo RAG_MAX_PER_TIPO file.
  FASE 6  MEMORIA     (in eco.py) i file emersi nelle domande precedenti restano nel prompt: il modello
                      non li dimentica quando la ricerca dopo ne trova altri.

Ogni scelta si accende e si spegne in config.py; valuta_rag.py misura quanto rende rispetto alla base del docente.
Senza embedding (niente sentence-transformers o niente internet) la ricerca va avanti con il solo BM25.
"""
import hashlib
import html
import json
import math
import random
import re
import threading
import time
import unicodedata
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

import config

FORMATI = {'.txt', '.html', '.htm', '.json', '.xml'}
STOP = set('''a ad al allo ai agli all agl alla alle con col coi da dal dallo dai dagli dall dagl dalla dalle di del dello dei
degli dell degl della delle in nel nello nei negli nell negl nella nelle su sul sullo sui sugli sull sugl sulla sulle per tra fra
il lo la i gli le l un uno una e ed o od ma se che chi cui non piu come dove quando quale quali quanto quanti quanta quante cosa
cos sono e era erano ha hanno ho hai abbiamo avete essere stato stata stati state questo questa questi queste quello quella
quelli quelle mi ti si ci vi ne lui lei loro noi voi io tu anche ancora gia poi solo molto tutto tutti tutta tutte suo sua suoi
sue mio mia tuo tua nostro nostra stesso stessa fa fatto ogni altro altra altri altre dopo prima sempre mai qui li la secondo
dimmi dammi sai sapere vorrei puoi file documento documenti archivio'''.split())
ID_NEL_TESTO = re.compile(r'\b([A-Z]{2,5}\d?)[-_ ]?(\d{3,5})\b', re.I)    # ARCH-5721, arch 5721, WIKI_1615, LX3-5593
FILE_NEL_TESTO = re.compile(r'\bdocumento[_ ]?(\d{1,4})\b', re.I)          # documento_0389(.xml)
RIGA_DOC = re.compile(r'^(?:Documento)\s*:?\s*([A-Z]{1,4}\d*[-_]\d{1,5})\s*$', re.I)   # «Documento: LX3-5593»
GIORNO_OP = re.compile(r'giorno\s+(?:operativo\s+)?0*(\d{1,2})\b', re.I)  # «giorno operativo 03», «giorno 3»
ORA_DOC = re.compile(r'\bore\s+(\d{1,2}[:.]\d{2})\b', re.I)

# Che tipo di prova è un documento (serve a distinguere copie e misure dirette; decide comunque il modello)
NATURA = [
    ('copia', re.compile(r"riproduzione senza verifica|copia del bollettino|\binoltra(?:no|to)?\b|catena di (?:inoltro|"
                         r"distribuzione)|ha copiato|copiat\w+ dal|trascritt\w* dal|senza controllare|"
                         r"non ha effettuato un sopralluogo|senza (?:alcun )?sopralluogo", re.I)),
    ('misura diretta', re.compile(r"misure eseguite direttamente|eseguit\w* direttamente sul posto|misurat\w* "
                                  r"(?:direttamente|sul posto)|esito firmato", re.I)),
    ('sentito dire', re.compile(r"ho sentito dire|si dice che|mi hanno detto|non ho visto", re.I)),
    ('derivata', re.compile(r"sostenut\w* da|basat\w* su[lg]|in base al (?:collaudo|registro|verbale)", re.I)),
]
ORIGINE = re.compile(r"\b(?:bollettino|rapporto|comunicato|circolare|avviso|secondo|dal|da)\s+([A-Z]{1,3}-\d{2,4})\b")
SPIEGA_NATURA = {
    'copia': 'copia o inoltro di un\'altra fonte, senza verifica propria',
    'misura diretta': 'misura fatta direttamente sul posto',
    'sentito dire': 'voce riferita, senza averla vista',
    'derivata': 'si basa su un altro documento',
}


# ================================ FASE 1 · LETTURA DEI 4 FORMATI =================================
def _campi_da_righe(testo):
    """Righe "chiave: valore" (TXT e HTML ripulito); le righe che non iniziano con una chiave continuano la precedente."""
    campi, ultimo = {}, None
    for riga in testo.splitlines():
        m = re.match(r'^\s*(id|title|text|source|license)\s*:\s*(.*)$', riga, re.I)
        if m:
            ultimo = m.group(1).lower()
            campi[ultimo] = m.group(2).strip()
        elif ultimo and riga.strip():
            campi[ultimo] += ' ' + riga.strip()
    return campi


def _campi_da_registro(testo):
    """Formato dei registri LAZZARO: «ARCHIVIO LAZZARO — Unità 3» / «Documento: LX3-5593» / titolo / testo."""
    righe = [r.strip() for r in testo.splitlines() if r.strip()]
    for k, r in enumerate(righe[:4]):
        m = RIGA_DOC.match(r)
        if m:
            return {'id': m.group(1).upper().replace('_', '-'), 'title': righe[k + 1] if len(righe) > k + 1 else '',
                    'text': ' '.join(righe[k + 2:]), 'source': ' · '.join(righe[:k])}
    return {}


def natura_di(testo):
    """('copia' | 'misura diretta' | 'sentito dire' | 'derivata' | '', origine): origine = la fonte copiata (es. B-317)."""
    for nome, regola in NATURA:
        if regola.search(testo):
            o = ORIGINE.search(testo) if nome == 'copia' else None
            return nome, (o.group(1) if o else '')
    return '', ''


def leggi_file(percorso):
    """Un file dell'archivio → {'id', 'titolo', 'testo', 'fonte', 'licenza', 'file', 'formato', 'giorno', 'ora', ...}.
    Va bene per TXT ("chiave: valore" o registro «Documento: LX3-…»), HTML (<p><b>chiave</b>: valore</p>), JSON e XML."""
    p = Path(percorso)
    grezzo = p.read_text(encoding='utf-8-sig', errors='replace')
    campi = {}
    try:
        if p.suffix.lower() == '.txt' and _campi_da_registro(grezzo):
            campi = _campi_da_registro(grezzo)
        elif p.suffix.lower() == '.json':
            dati = json.loads(grezzo)
            campi = {str(k).lower(): str(v) for k, v in dati.items()} if isinstance(dati, dict) else {}
        elif p.suffix.lower() == '.xml':
            radice = ET.fromstring(grezzo)
            campi = {e.tag.lower(): (e.text or '').strip() for e in radice}
        elif p.suffix.lower() in ('.html', '.htm'):
            pulito = re.sub(r'(?i)</p>|<br\s*/?>|</div>|</li>|</h\d>', '\n', grezzo)
            pulito = html.unescape(re.sub(r'<[^>]+>', '', pulito))
            campi = _campi_da_righe(pulito) or {'text': ' '.join(pulito.split())}
        else:
            campi = _campi_da_righe(grezzo)
    except Exception:
        campi = {}
    if not campi.get('text'):                       # file senza struttura: si prende tutto il testo
        campi['text'] = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', grezzo)).split())
    testo = ' '.join(campi['text'].split())
    titolo = campi.get('title', '').strip() or p.stem
    g = GIORNO_OP.search(titolo) or GIORNO_OP.search(testo[:200])
    ora = ORA_DOC.search(titolo)
    natura, origine = natura_di(testo)
    try:
        raccolta = p.resolve().relative_to(config.DATI.resolve()).parts[0]
    except ValueError:
        raccolta = p.parent.name
    return {'id': (campi.get('id') or p.stem).strip().upper(), 'titolo': titolo,
            'tipo': re.split(r'\s+[—–-]\s+', titolo)[0].strip(), 'giorno': int(g.group(1)) if g else None,
            'ora': ora.group(1).replace('.', ':') if ora else None, 'natura': natura, 'origine': origine,
            'testo': testo, 'fonte': campi.get('source', '').strip(), 'licenza': campi.get('license', '').strip(),
            'file': p.name, 'formato': p.suffix.lower().lstrip('.'), 'raccolta': raccolta,
            'sospetto': bool(_ordini_all_ai(testo))}


def _ordini_all_ai(testo):
    import archivio
    return config.SEGNALA_SOSPETTI and archivio.ORDINI_ALL_AI.search(testo)


def file_archivio():
    """I file da indicizzare: tutto ciò che sta in dati/archivio*/ (TXT, HTML, JSON, XML)."""
    return sorted(p for p in config.DATI.glob('archivio*/**/*') if p.is_file() and p.suffix.lower() in FORMATI)


# ================================ FASE 2 · SCANSIONE: STORIA O RUMORE? ===========================
def vocabolario_storia(documenti):
    """Parole tipiche dell'indagine: compaiono nel fascicolo (Giorno 1, Giorno 2, imprevisti)
    ma in pochissimi file dell'archivio (al massimo lo 0,5%). Esempi: rifugi, focolaio, sabotaggio, quarantena."""
    import archivio
    fascicolo = ' '.join(d['titolo'] + ' ' + d['testo'] for d in archivio.carica())
    candidate = {w for w in parole(fascicolo) if len(w) >= 6 and not w.isdigit()}
    df = {}
    for d in documenti:
        for w in set(parole(d['testo'])) & candidate:
            df[w] = df.get(w, 0) + 1
    limite = max(2, 0.005 * len(documenti))
    return {w for w in candidate if df.get(w, 0) <= limite}


def _codici_rari(testo):
    """Codici e nomi propri di un testo (RV596, B7, Cripta Nord, LUME): servono a riconoscere i collegamenti."""
    codici = {c.upper() for c in re.findall(r'\b[A-Z]{1,4}\d{2,5}\b', testo)}   # RV596, T347 (non A1: troppo comune)
    nomi = set(re.findall(r'\b([A-Z][a-zà-ù]+ [A-Z][a-zà-ù]+)\b', testo))
    maiuscole = {m for m in re.findall(r'\b[A-Z]{4,}\b', testo)}
    return codici | nomi | maiuscole


def classifica(d, vocabolario):
    """Punti e motivi per un file. Ogni indizio vale da -2 a +2; la somma decide la classe."""
    punti, motivi = 0, []
    prefisso = re.match(r'([A-Z]+\d*)[-_]', d['id'] or '') or re.match(r'([A-Z]+)', d['id'] or '')
    prefisso = prefisso.group(1) if prefisso else ''          # ARCH, WIKI, LX3
    # 1. ID: i documenti del dossier hanno ID ARCH-…, le copie enciclopediche WIKI-…
    if prefisso in config.SCANSIONE_PREFISSI_STORIA:
        punti += 2; motivi.append(f'ID {d["id"]}')
    elif prefisso in config.SCANSIONE_PREFISSI_RUMORE:
        punti -= 2; motivi.append(f'ID {d["id"]} (enciclopedia)')
    # 2. FONTE: "Dossier … LAZZARO" contro un indirizzo di Wikipedia
    f = d['fonte'].lower()
    if 'wikipedia' in f or 'http' in f:            # prima l'indirizzo web: ".../wiki/Lazzaro" resta Wikipedia
        punti -= 2; motivi.append('fonte Wikipedia' if 'wikipedia' in f else 'fonte: pagina web')
    elif any(x in f for x in ('dossier', 'lazzaro')):
        punti += 2; motivi.append(f'fonte «{d["fonte"][:45]}»')
    # 3. LICENZA: materiale originale contro licenza Creative Commons delle copie
    lic = d['licenza'].lower()
    if 'originale' in lic:
        punti += 1; motivi.append('materiale originale')
    elif 'cc by' in lic or 'creative' in lic:
        punti -= 1; motivi.append('licenza CC BY-SA')
    # 4. CONTENUTO: quante parole tipiche dell'indagine usa
    comuni = sorted(set(parole(d['testo'])) & vocabolario)
    if len(comuni) >= 3:
        punti += 2; motivi.append('parla dell\'indagine: ' + ', '.join(comuni[:5]))
    elif len(comuni) >= 2:
        punti += 1; motivi.append('alcune parole dell\'indagine: ' + ', '.join(comuni[:4]))
    return punti, motivi


def _classe(punti):
    return ('storia' if punti >= config.SCANSIONE_SOGLIA_STORIA else
            'rumore' if punti <= config.SCANSIONE_SOGLIA_RUMORE else 'incerto')


def scansiona(documenti):
    """Assegna a ogni documento 'classe' (storia / rumore / incerto), 'punti' e 'motivi'.
    Secondo giro: un file non ancora deciso che condivide un codice o un nome raro (RV596, Cripta Nord)
    con un file della storia riceve un punto in più (5° indizio: i collegamenti)."""
    voc = vocabolario_storia(documenti)
    for d in documenti:
        d['punti'], d['motivi'] = classifica(d, voc)
        d['classe'] = _classe(d['punti'])
    codici_storia = {}
    for d in documenti:
        if d['classe'] == 'storia':
            for c in _codici_rari(d['testo']):
                codici_storia.setdefault(c, set()).add(d['id'])
    for d in documenti:
        if d['classe'] == 'storia':
            continue
        legami = sorted({i for c in _codici_rari(d['testo']) for i in codici_storia.get(c, ()) if i != d['id']})
        if legami:
            d['punti'] += 1
            d['motivi'].append('collegato a ' + ', '.join(legami[:3]))
            d['classe'] = _classe(d['punti'])
    famiglie(documenti)
    return documenti


def famiglie(documenti):
    """Raggruppa le COPIE della stessa fonte: tutti i documenti che inoltrano «bollettino B-317» formano una famiglia,
    e così i testi identici. Una famiglia di 80 copie vale come UNA fonte, non come 80 conferme indipendenti."""
    for d in documenti:
        d.setdefault('natura', natura_di(d['testo'])[0])
        d.setdefault('origine', '')
        d['famiglia'] = d['origine'] if d['natura'] == 'copia' and d['origine'] else ''
    uguali = {}
    for d in documenti:
        if not d['famiglia'] and d['classe'] != 'rumore':
            chiave = hashlib.sha1(' '.join(parole(d['testo'])).encode()).hexdigest()[:10]
            uguali.setdefault(chiave, []).append(d)
    for chiave, lista in uguali.items():
        if len(lista) > 1:
            for d in lista:
                d['famiglia'] = f'testo uguale {chiave}'
    return documenti


# ================================ FASE 3 · BLOCCHI ===============================================
def dividi_frasi(testo):
    return [f for f in re.split(r'(?<=[.!?»])\s+(?=[A-ZÀ-Ý«"(0-9])', testo) if f.strip()]


def blocchi_documento(d, massimo=None, sovrapposizione=None):
    """Blocchi di frasi intere (al massimo `massimo` caratteri), con l'ultima frase ripetuta nel blocco dopo."""
    massimo = massimo or config.RAG_BLOCCO
    sovrapposizione = config.RAG_SOVRAPPOSIZIONE if sovrapposizione is None else sovrapposizione
    frasi, blocchi, corrente = dividi_frasi(d['testo']), [], []
    for f in frasi:
        while len(f) > massimo:                       # frase lunghissima: si taglia su uno spazio
            taglio = f.rfind(' ', 0, massimo)
            taglio = taglio if taglio > massimo // 2 else massimo
            if corrente:
                blocchi.append(' '.join(corrente))
                corrente = []
            blocchi.append(f[:taglio])
            f = f[taglio:].strip()
        if corrente and len(' '.join(corrente + [f])) > massimo:
            blocchi.append(' '.join(corrente))
            corrente = corrente[-sovrapposizione:] if sovrapposizione else []
            if len(' '.join(corrente + [f])) > massimo:
                corrente = []
        corrente.append(f)
    if corrente:
        blocchi.append(' '.join(corrente))
    return blocchi or [d['testo'][:massimo]]


# ================================ FASE 4 · INDICE: BM25 + EMBEDDING ==============================
def parole(testo):
    """Parole per la ricerca: minuscole, senza accenti, senza parole vuote; radice semplice (prime 6 lettere).
    I codici restano INTERI, trattino compreso: «M362-065» è un'altra pratica rispetto a «M362», e «B-317», «EV-341»,
    «CN-38» restano un'unica parola (prima il trattino li spezzava e M362-065 sembrava M362)."""
    t = unicodedata.normalize('NFD', testo.lower().replace('’', "'"))
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    out = []
    for gruppo in re.findall(r'[a-z0-9]+(?:-[a-z0-9]+)*', t):
        pezzi = [gruppo] if ('-' in gruppo and any(c.isdigit() for c in gruppo)) else gruppo.split('-')
        for w in pezzi:
            if w in STOP or (len(w) < 2 and not w.isdigit()):
                continue
            out.append(w if any(c.isdigit() for c in w) else w[:6])
    return out


def parole_intere(testo):
    """Parole intere (minuscole, senza accenti, senza parole vuote): per confrontare un titolo con la domanda.
    Le radici di 6 lettere qui sbagliano: «interno» e «Internet» hanno la stessa radice."""
    t = unicodedata.normalize('NFD', testo.lower().replace('’', "'"))
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    return [w for w in re.findall(r'[a-z0-9]+', t) if w not in STOP and (len(w) >= 2 or w.isdigit())]


def stessa_parola(a, b):
    """Uguali, o la stessa parola con un'altra vocale finale (romano/romani, mondiale/mondiali, cesare/cesari)."""
    if a == b:
        return True
    return (len(a) == len(b) >= 4 and a[:-1] == b[:-1] and a[-1] in 'aeiou' and b[-1] in 'aeiou')


class BM25:
    """Ricerca per parole chiave: premia le parole rare (codici, nomi) e i blocchi brevi che le contengono."""

    def __init__(self, testi, k1=1.4, b=0.75):
        self.k1, self.b = k1, b
        self.post, self.lung = {}, []
        for i, t in enumerate(testi):
            conta = {}
            for w in parole(t):
                conta[w] = conta.get(w, 0) + 1
            self.lung.append(sum(conta.values()))
            for w, c in conta.items():
                self.post.setdefault(w, []).append((i, c))
        self.n = len(testi)
        self.media = (sum(self.lung) / self.n) if self.n else 1
        self.idf = {w: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5)) for w, p in self.post.items()}

    def punteggi(self, query):
        s = np.zeros(self.n, dtype=np.float32)
        for w in set(parole(query)):
            for i, c in self.post.get(w, ()):
                s[i] += self.idf[w] * c * (self.k1 + 1) / (c + self.k1 * (1 - self.b + self.b * self.lung[i] / self.media))
        return s

    def df(self, w):
        return len(self.post.get(w, ()))


_emb = {'modello': None, 'errore': None}


def embedder():
    """Il modello di embedding (lo stesso della base del docente). None se non disponibile."""
    if _emb['modello'] is None and _emb['errore'] is None:
        try:
            from sentence_transformers import SentenceTransformer
            try:
                import torch
                dev = 'cuda' if torch.cuda.is_available() else 'cpu'
            except ImportError:
                dev = 'cpu'
            try:   # già scaricato: si carica dal disco senza chiedere a internet (su reti lente fa perdere decine di secondi)
                _emb['modello'] = SentenceTransformer(config.RAG_EMBEDDING, device=dev, local_files_only=True)
            except Exception:
                _emb['modello'] = SentenceTransformer(config.RAG_EMBEDDING, device=dev)
        except Exception as e:
            _emb['errore'] = f'{type(e).__name__}: {e}'[:200]
            print('RAG: embedding non disponibili, uso solo BM25 →', _emb['errore'])
    return _emb['modello']


def codifica(testi, mostra=False):
    m = embedder()
    if m is None:
        return None
    return np.asarray(m.encode(list(testi), normalize_embeddings=True, batch_size=64,
                               show_progress_bar=mostra, convert_to_numpy=True), dtype=np.float32)


def _rrf(classifiche, k=60):
    """Reciprocal Rank Fusion: unisce più classifiche (liste di blocchi) in un punteggio solo."""
    tot = {}
    for cl in classifiche:
        for r, i in enumerate(cl):
            tot[i] = tot.get(i, 0.0) + 1 / (k + r + 1)
    return tot


# ---- Richiesta esplicita dei file "rumore" (copie enciclopediche) --------------------------------
# Di norma il rumore non arriva al modello. Se chi scrive li chiede ("estrai 5 documenti di Wikipedia",
# "di cosa parlano i file rumore?", "mostrami WIKI-2124") il filtro si spegne e si cercano proprio quelli.
RICHIESTA_RUMORE = re.compile(
    r"wikipedia|\bwiki\b|enciclopedi|\brumore\b|\bscartat\w*|"
    r"(document\w*|file|copie|voci)\s+(\w+\s+)?(inutil\w*|non pertinent\w*|irrilevant\w*|che non c.entrano)", re.I)
NUMERI_PAROLE = {'un': 1, 'uno': 1, 'una': 1, 'due': 2, 'tre': 3, 'quattro': 4, 'cinque': 5, 'sei': 6, 'sette': 7,
                 'otto': 8, 'nove': 9, 'dieci': 10}
CONTO_RUMORE = re.compile(r"\b(\d{1,2}|" + '|'.join(NUMERI_PAROLE) + r")\s+(?:\w+\s+){0,2}?(?:document\w*|file|voci|voce|articol\w*|copie|pagine)\b", re.I)
NON_STORIA = re.compile(r"\b(che\s+)?non\s+(riguard\w*|c.entr\w*|ha\s+a\s+che\s+fare|fa\s+parte|appartien\w*|è\s+pertinente|sono\s+pertinenti)\s*(con\s+)?(la\s+|l.|alla\s+|all.|nella\s+|con\s+)?(storia|indagine|lazzaro|epidemia|dossier)?", re.I)
PAROLE_VUOTE = re.compile(
    r"\b(wikipedia|wiki|enciclopedi\w*|rumore|scartat\w*|inutil\w*|irrilevant\w*|pertinent\w*|document\w*|file|voci|voce|"
    r"articol\w*|copie|copia|pagine|estrai|estrarre|elenca\w*|dammi|dimmi|mostra\w*|trova\w*|cerca\w*|quali|quanti|"
    r"parlano|parla|cosa|come|sono|mi|puoi|vorrei|voglio|altri|altre|tutti|tutte|quegli|quelle|questi|queste|che|"
    r"\d+|" + '|'.join(NUMERI_PAROLE) + r")\b|[^\w\s]", re.I)


# ---- Capire con gli embedding che cosa chiede la domanda -----------------------------------------
# Richieste-tipo: la domanda viene confrontata (coseno) con queste frasi. Non conta la parola, conta il significato:
# "estrai un file che non riguarda la storia" è vicina a "dammi un documento che non c'entra con l'indagine".
PROTOTIPI = {
    'rumore': ["estrai un file che non riguarda la storia", "dammi un documento che non c'entra con l'indagine",
               "mostrami alcuni file non pertinenti", "voglio vedere dei documenti inutili dell'archivio",
               "estrai delle voci di Wikipedia", "elenca i file enciclopedici scartati",
               "di cosa parlano i documenti scartati come rumore",
               "dammi un articolo di cultura generale presente nell'archivio",
               "fammi vedere file che non hanno a che fare con l'epidemia"],
    'storia': ["cosa è successo nei rifugi", "chi ha aperto la pratica RV596", "dove si trova il materiale di recupero",
               "chi è Marta Riva", "quali file riguardano la storia", "estrai i documenti importanti dell'indagine",
               "mostrami i file del dossier LAZZARO", "qual è il deposito giusto", "c'è una prova contro la centrale",
               "riassumi cosa sappiamo finora"],
    'caso': ["scegli dei documenti a caso", "pescane alcuni a caso dall'archivio", "dammi un campione casuale di file",
             "estrai file a caso", "prendi un documento qualsiasi"],
}
NEGAZIONE = re.compile(r"\bnon\b|\bsenza\b|\bfuori\b|\balt[rv]\w*\b|\bestran\w*\b", re.I)   # "che NON riguarda": gli embedding sbagliano le negazioni
_proto = {'v': None}


def somiglianze(domanda):
    """{'rumore': x, 'storia': y, 'caso': z}: la somiglianza massima con le richieste-tipo. None senza embedding."""
    if _proto['v'] is None:
        voci = [(c, f) for c, lista in PROTOTIPI.items() for f in lista]
        v = codifica([f for _, f in voci])
        _proto['v'] = (v, [c for c, _ in voci]) if v is not None else False
    if not _proto['v']:
        return None
    v, classi = _proto['v']
    q = codifica([domanda])
    if q is None:
        return None
    s = v @ q[0]
    return {c: float(max(s[i] for i, cc in enumerate(classi) if cc == c)) for c in PROTOTIPI}


def capisci_richiesta(domanda):
    """Con gli embedding: la domanda chiede i file rumore? chiede file a caso? {'rumore', 'caso', 'sim'}"""
    out = {'rumore': False, 'caso': False, 'sim': None}
    if not config.RAG_INTENTO_EMBEDDING:
        return out
    try:
        sim = somiglianze(domanda)
    except Exception as e:
        print('RAG: intento non calcolato:', e)
        return out
    if not sim:
        return out
    out['sim'] = sim
    ru, st = sim['rumore'], sim['storia']
    out['rumore'] = ru >= config.RAG_SOGLIA_RUMORE and (ru - st >= config.RAG_MARGINE_RUMORE or bool(NEGAZIONE.search(domanda)))
    out['caso'] = sim['caso'] >= config.RAG_SOGLIA_CASO and sim['caso'] - st >= 0
    return out


RICHIESTA_CASO = re.compile(r"\ba caso\b|casual\w*|\brandom\b|\bcampione\b|\bqualsiasi\b", re.I)


def quanti(domanda):
    m = CONTO_RUMORE.search(domanda)
    if not m:
        return None
    v = m.group(1).lower()
    return int(v) if v.isdigit() else NUMERI_PAROLE[v]


def richiesta_rumore(domanda, forza=False):
    """None se la domanda non chiede i file rumore; altrimenti {'n': quanti (o None), 'tema': parole utili per cercarli}.
    forza=True: lo hanno già deciso gli embedding (capisci_richiesta), qui si leggono solo numero e argomento."""
    if not forza and not RICHIESTA_RUMORE.search(domanda):
        return None
    m = CONTO_RUMORE.search(domanda)
    n = None
    if m:
        v = m.group(1).lower()
        n = int(v) if v.isdigit() else NUMERI_PAROLE[v]
    domanda = NON_STORIA.sub(' ', domanda)     # "che non riguarda la storia" non è un argomento da cercare
    tema = ' '.join(w for w in PAROLE_VUOTE.sub(' ', ID_NEL_TESTO.sub(' ', domanda)).split() if len(w) > 2
                    and w.lower() not in ('per', 'con', 'del', 'dei', 'della', 'delle', 'sul', 'sui', 'nel', 'nei', 'gli', 'una', 'uno', 'da', 'di', 'il', 'la', 'le', 'lo'))
    return {'n': n, 'tema': tema}


class Indice:
    def __init__(self, documenti, blocco=None, con_titolo=True, embedding=True, mostra=True):
        self.documenti = scansiona(documenti) if 'classe' not in documenti[0] else documenti
        self.per_id = {d['id']: d for d in self.documenti}
        self.per_file = {d['file'].lower(): d for d in self.documenti}
        self.blocchi = []                      # (indice documento, testo del blocco)
        for i, d in enumerate(self.documenti):
            for b in blocchi_documento(d, blocco):
                self.blocchi.append((i, b))
        self.blocchi_di = {}                   # documento → i suoi blocchi, in ordine
        for n, (i, _) in enumerate(self.blocchi):
            self.blocchi_di.setdefault(i, []).append(n)
        self.cerca_testi = [(f'{self.documenti[i]["titolo"]}. {b}' if con_titolo else b) for i, b in self.blocchi]
        self.bm25 = BM25(self.cerca_testi)
        self.vettori = self._vettori_con_cache(mostra) if embedding else None
        if 'famiglia' not in self.documenti[0]:
            famiglie(self.documenti)
        self.famiglie = {}                     # 'bollettino B-317' → [ID delle copie]
        for d in self.documenti:
            if d.get('famiglia'):
                self.famiglie.setdefault(d['famiglia'], []).append(d['id'])
        self.raccolte = {}                     # cartella → documenti (archivio_g3, archivio_imprevisti_g3, ...)
        for d in self.documenti:
            self.raccolte.setdefault(d.get('raccolta') or 'archivio', []).append(d)

    def _vettori_con_cache(self, mostra):
        firma = hashlib.sha1((config.RAG_EMBEDDING + '\n'.join(self.cerca_testi)).encode('utf-8')).hexdigest()[:16]
        cache = config.CARTELLA / '.cache_rag' / f'vettori_{firma}.npy'
        if cache.exists():
            try:
                return np.load(cache)
            except Exception:
                pass
        t0 = time.time()
        v = codifica(self.cerca_testi, mostra)
        if v is not None:
            try:
                cache.parent.mkdir(exist_ok=True)
                np.save(cache, v)
            except OSError:
                pass
            print(f'RAG: {len(v)} blocchi codificati in {time.time() - t0:.0f} s')
        return v

    # --- catalogo prodotto dalla scansione ---
    def catalogo(self, classi=('storia', 'incerto')):
        return sorted((d for d in self.documenti if d['classe'] in classi), key=lambda d: (d['classe'], d['id']))

    def conteggi(self, documenti=None):
        c = {'storia': 0, 'incerto': 0, 'rumore': 0}
        for d in documenti or self.documenti:
            c[d['classe']] += 1
        return c

    def tipi_frequenti(self):
        """Tipi di documento ripetuti molte volte (es. 100 «Scheda di reparto»): nella ricerca ne passano pochi per tipo."""
        if not hasattr(self, '_tipi'):
            c = {}
            for d in self.documenti:
                if d['classe'] != 'rumore' and d.get('tipo'):
                    c[d['tipo']] = c.get(d['tipo'], 0) + 1
            self._tipi = {t for t, n in c.items() if n >= 10}
        return self._tipi

    def raccolta_piccola(self, nome):
        """True se i file della storia di questa raccolta stanno interi nel catalogo (es. i 5 file del dossier)."""
        docs = [d for d in self.raccolte.get(nome, []) if d['classe'] != 'rumore']
        return sum(len(d['testo']) for d in docs) <= config.CATALOGO_TESTO_MAX

    def nel_catalogo_intero(self, id_doc):
        d = self.per_id.get(id_doc)
        return bool(d and d['classe'] != 'rumore' and self.raccolta_piccola(d.get('raccolta') or 'archivio'))

    # ============================ FASE 5 · RICERCA ===============================================
    def trova_citati(self, testo):
        """a) File nominati esplicitamente: "ARCH-5721", "arch 5721", "documento_0389"."""
        trovati = []
        for pre, num in ID_NEL_TESTO.findall(testo):
            d = self.per_id.get(f'{pre.upper()}-{num}')
            if d and d not in trovati:
                trovati.append(d)
        for num in FILE_NEL_TESTO.findall(testo):
            for est in ('txt', 'html', 'json', 'xml'):
                d = self.per_file.get(f'documento_{int(num):04d}.{est}')
                if d and d not in trovati:
                    trovati.append(d)
        return trovati

    def _classifica_bm25(self, query, n=150):
        s = self.bm25.punteggi(query)
        idx = np.argsort(-s)[:n]
        return [int(i) for i in idx if s[i] > 0]

    def _classifica_emb(self, query, n=150):
        if self.vettori is None:
            return []
        q = codifica([query])
        if q is None:
            return []
        return [int(i) for i in np.argsort(-(self.vettori @ q[0]))[:n]]

    def _classifica(self, query, ibrida=True):
        """b) Ricerca ibrida: classifica per parole chiave + classifica per significato, unite con RRF."""
        cl = [self._classifica_bm25(query)]
        if ibrida and self.vettori is not None:
            cl.append(self._classifica_emb(query))
        return _rrf(cl)

    def _parole_rare(self, indici_blocchi, gia, quante=6):
        """c) Le parole più rare dei blocchi migliori (codici, nomi, luoghi) non ancora usate.
        Restituisce {parola: ID del documento da cui viene}: serve a mostrare la catena dei collegamenti."""
        scelte = {}
        per_blocco = max(2, quante // max(1, len(indici_blocchi)))   # ogni blocco porta le sue: nessuno resta senza
        for i in indici_blocchi:
            candidate = {}
            for w in parole(self.cerca_testi[i]):
                df = self.bm25.df(w)
                if w not in gia and w not in scelte and 2 <= df <= config.RAG_PAROLA_RARA and not w.isdigit():
                    candidate[w] = df
            # prima i codici (CN-38, M362, K391: collegano i documenti), poi le parole più rare
            for w in sorted(candidate, key=lambda w: (not any(c.isdigit() for c in w), candidate[w]))[:per_blocco]:
                scelte[w] = self.documenti[self.blocchi[i][0]]['id']
        return scelte

    def _semi(self, punti, filtro, giorno, quanti=5):
        """Da dove partono i salti: il blocco migliore dei primi `quanti` documenti diversi (niente rumore, niente
        documenti di un altro giorno operativo, un solo documento per tipo molto ripetuto)."""
        semi, docs, tipi = [], set(), set()
        frequenti = self.tipi_frequenti()
        for i, _ in sorted(punti.items(), key=lambda x: -x[1]):
            d = self.documenti[self.blocchi[i][0]]
            if d['id'] in docs or (filtro and d['classe'] == 'rumore'):
                continue
            if giorno is not None and d.get('giorno') is not None and d['giorno'] != giorno:
                continue
            if d.get('tipo') in frequenti:
                if d['tipo'] in tipi:
                    continue
                tipi.add(d['tipo'])
            docs.add(d['id'])
            semi.append(i)
            if len(semi) >= quanti:
                break
        return semi

    def collegamenti(self, risultati):
        """Coppie di file trovati che condividono un codice raro (M362, K391, CN-38, RV596): gli anelli della catena."""
        codici = {}
        for r in risultati:
            d = self.per_id.get(r['id'])
            if d:
                codici[r['id']] = {w for w in parole(d['titolo'] + ' ' + d['testo']) if any(c.isdigit() for c in w)
                                   and not w.replace('-', '').isdigit() and self.bm25.df(w) <= 2 * config.RAG_PAROLA_RARA}
        out, ids = [], [r['id'] for r in risultati]
        for n, a in enumerate(ids):
            for b in ids[n + 1:]:
                comuni = sorted(codici.get(a, set()) & codici.get(b, set()))
                if comuni:
                    out.append({'da': a, 'parola': ', '.join(self._testo_parola(w, a) for w in comuni), 'a': b})
        return out

    def voci_pertinenti(self, domanda, ordinati, storia_trovata, quante=2):
        """I file rumore di cui la domanda parla davvero (vedi cerca, passo c-ter). Lista di (indice, brani)."""
        q = parole_intere(domanda)
        presi = []

        def aggiungi(j, lista):
            if j not in [x for x, _ in presi] and len(presi) < quante:
                presi.append((j, lista))
        primo_rumore = None
        for n, (j, lista) in enumerate(ordinati[:40]):
            doc = self.documenti[j]
            if doc['classe'] != 'rumore':
                continue
            titolo = parole_intere(re.sub(r'\(.*?\)', ' ', doc['titolo']))
            uguali = [w for w in titolo if any(stessa_parola(w, x) for x in q)]
            if titolo and len(uguali) == len(titolo):
                aggiungi(j, lista)                                  # 1. il titolo intero è nella domanda
            elif n == 0 and (not storia_trovata or 2 * len(uguali) >= len(titolo)) and uguali:
                aggiungi(j, lista)          # 2. è il file più vicino di tutto l'archivio (prima della storia) e ha nel
                                            #    titolo almeno metà delle parole («fotosintesi» → «Fotosintesi clorofilliana»)
            if primo_rumore is None:
                primo_rumore = (j, lista)
        # 3. per significato: il blocco rumore più simile batte nettamente il miglior blocco della storia
        if len(presi) < quante and self.vettori is not None:
            v = codifica([domanda])
            if v is not None:
                sim = self.vettori @ v[0]
                rumore = np.array([self.documenti[j]['classe'] == 'rumore' for j, _ in self.blocchi])
                if rumore.any() and (~rumore).any():
                    i_r = int(np.argmax(np.where(rumore, sim, -1)))
                    s_r, s_s = float(sim[i_r]), float(np.max(np.where(rumore, -1, sim)))
                    if s_r >= config.RAG_SOGLIA_VOCE and s_r - s_s >= config.RAG_MARGINE_VOCE:
                        aggiungi(self.blocchi[i_r][0], [(s_r, i_r)])
        return presi

    def _testo_parola(self, w, id_doc):
        """La parola come è scritta nel documento (M362, non m362), per la vista dei collegamenti."""
        d = self.per_id.get(id_doc)
        m = re.search(r'(?i)\b' + re.escape(w) + r'[\wÀ-ÿ-]*', d['titolo'] + ' ' + d['testo']) if d else None
        return m.group(0) if m else w

    def cerca(self, domanda, precedenti=(), k=None, ibrida=None, secondo=None, contesto=None, filtro=None, per_doc=2):
        """Restituisce (risultati, scartati).
        risultati: i file da far leggere al modello (al massimo k, solo storia/incerti se filtro è attivo),
                   ciascuno con al massimo `per_doc` brani e il 'passaggio' che l'ha trovato (ID, 1, 2);
        scartati:  i file rumore più vicini alla domanda (solo titolo, non vanno al modello come prova)."""
        k = k or config.RAG_RISULTATI
        ibrida = config.RAG_IBRIDA if ibrida is None else ibrida
        secondo = config.RAG_SECONDO_PASSAGGIO if secondo is None else secondo
        contesto = config.RAG_CONTESTO_CHAT if contesto is None else contesto
        filtro = config.RAG_FILTRO_STORIA if filtro is None else filtro

        # a) file nominati nella domanda
        diretti = self.trova_citati(domanda)

        # a-bis) richiesta esplicita dei file rumore (copie enciclopediche): si cercano proprio quelli
        intento = capisci_richiesta(domanda)          # embedding: che cosa CHIEDE la domanda
        rumore = richiesta_rumore(domanda, forza=intento['rumore'])      # (le parole chiave restano come rinforzo)
        a_caso = bool(intento['caso'] or RICHIESTA_CASO.search(domanda)) and bool(quanti(domanda))   # "estrai 5 documenti a caso"
        if a_caso and not any(d['classe'] != 'rumore' for d in diretti):
            pool = [j for j, d in enumerate(self.documenti) if not rumore or d['classe'] == 'rumore']   # con "wikipedia" solo rumore
            scelti = random.sample(pool, min(quanti(domanda), 10, len(pool)))
            return [self._voce(self.documenti[j], [(0.0, i) for i, (jj, _) in enumerate(self.blocchi) if jj == j][:per_doc], 'a caso')
                    for j in scelti], []
        if rumore and not any(d['classe'] != 'rumore' for d in diretti):
            n = min(rumore['n'] or (len(diretti) if diretti else k), 10)   # "mostrami WIKI-2124" = solo quello
            migliore = {}
            if rumore['tema']:
                for i, s in self._classifica(rumore['tema'], ibrida).items():
                    j = self.blocchi[i][0]
                    if self.documenti[j]['classe'] == 'rumore':
                        migliore.setdefault(j, []).append((s, i))
            ordine = [self.documenti.index(d) for d in diretti] + \
                     [j for j, _ in sorted(migliore.items(), key=lambda x: -max(s for s, _ in x[1])) if self.documenti[j] not in diretti]
            altri = [j for j, d in enumerate(self.documenti) if d['classe'] == 'rumore' and j not in ordine]
            if not rumore['tema']:
                random.shuffle(altri)                  # nessun argomento: un campione diverso a ogni richiesta
            ordine += altri
            risultati = []
            for j in ordine[:n]:
                lista = sorted(migliore.get(j) or [(0.0, i) for i, (jj, _) in enumerate(self.blocchi) if jj == j], key=lambda x: -x[0])[:per_doc]
                risultati.append(self._voce(self.documenti[j], lista, 'richiesta'))
            return risultati, []

        # b) ricerca ibrida sulla domanda, su ogni sua parte (domande doppie: «quale ripetitore…? quante conferme…?»)
        #    e, per le domande brevi, insieme alla domanda precedente
        query, pesi = [domanda], [1.0]
        parti = [p for p in re.split(r'(?<=[?.!])\s+', domanda.strip()) if len(parole(p)) >= 2]
        if len(parti) >= 2:
            query += parti
            pesi += [0.8] * len(parti)
        if contesto and precedenti:
            query.append(precedenti[-1] + ' ' + domanda)       # "e il settore?" si capisce con la domanda di prima
            pesi.append(0.7)
        punti = {}
        for q, peso in zip(query, pesi):
            for i, s in self._classifica(q, ibrida).items():
                punti[i] = punti.get(i, 0) + s * peso
        passaggio = {i: 1 for i in punti}
        via = {}                                              # documento → (parola, documento da cui arriva)

        # c) passaggi successivi con le parole rare (codici, nomi) dei blocchi migliori: ogni passaggio fa un salto
        #    nella catena (Ruggine → pratica M362 → lotto K391 → armadio). Si cerca SOLO con le parole rare,
        #    così il salto trova davvero il documento collegato e non di nuovo quelli della domanda.
        giorno = next((int(m.group(1)) for q in query for m in [GIORNO_OP.search(q)] if m), None)
        if secondo and punti:
            usate = set(parole(' '.join(query)))
            semi = self._semi(punti, filtro, giorno)
            for salto in range(2, max(2, config.RAG_PASSAGGI) + 1):
                rare = self._parole_rare(semi, usate, quante=8)
                if not rare:
                    break
                usate |= set(rare)
                nuovi = {}
                for w, da in rare.items():
                    sw = self.bm25.punteggi(w)
                    for i in np.argsort(-sw)[:8]:
                        i = int(i)
                        j = self.blocchi[i][0]
                        if sw[i] <= 0 or self.documenti[j]['id'] == da or (filtro and self.documenti[j]['classe'] == 'rumore'):
                            continue
                        nuovi[i] = nuovi.get(i, 0) + float(sw[i])
                        via.setdefault(self.documenti[j]['id'], (self._testo_parola(w, da), da))
                if not nuovi:
                    break
                massimo = max(nuovi.values())
                peso = 0.6 ** (salto - 1) / 60                 # sulla scala dei punteggi RRF (~1/60 per il primo)
                for i, s in nuovi.items():
                    passaggio.setdefault(i, salto)
                    punti[i] = punti.get(i, 0) + peso * s / massimo
                semi = [i for i, _ in sorted(nuovi.items(), key=lambda x: -x[1])][:3]

        # c-bis) giorno operativo: se la domanda (o quella di prima) ne nomina uno, i documenti di altri giorni scendono

        # d) dai blocchi ai file; il filtro tiene da parte il rumore; le copie della stessa fonte diventano una voce sola
        per_documento = {}
        for i, s in sorted(punti.items(), key=lambda x: -x[1]):
            per_documento.setdefault(self.blocchi[i][0], []).append((s, i))
        if giorno is not None:
            for j, lista in per_documento.items():
                g = self.documenti[j].get('giorno')
                if g is not None and g != giorno:
                    per_documento[j] = [(s * config.RAG_PESO_ALTRO_GIORNO, i) for s, i in lista]
        ordinati = sorted(per_documento.items(), key=lambda x: -x[1][0][0])
        risultati, scartati, per_famiglia, per_tipo, riserva = [], [], {}, {}, []
        tipi_frequenti = self.tipi_frequenti()
        for d in diretti:
            risultati.append(self._voce(d, [(1.0, i) for i, (j, _) in enumerate(self.blocchi)
                                            if self.documenti[j] is d][:per_doc], 'ID'))
            if d.get('famiglia'):
                per_famiglia.setdefault(d['famiglia'], risultati[-1])
        presi = {r['id'] for r in risultati}
        for j, lista in ordinati:
            doc = self.documenti[j]
            if doc['id'] in presi:
                continue
            if filtro and doc['classe'] == 'rumore':
                if len(scartati) < config.RAG_SCARTATI_MOSTRATI:
                    scartati.append(self._voce(doc, lista[:1], min(passaggio[i] for _, i in lista[:1])))
                continue
            fam = doc.get('famiglia')
            if fam and fam in per_famiglia:                    # un'altra copia della stessa fonte: si conta, non si ripete
                per_famiglia[fam]['copie_trovate'].append(doc['id'])
                continue
            tipo = doc.get('tipo') if doc.get('tipo') in tipi_frequenti else None
            if tipo and per_tipo.get(tipo, 0) >= config.RAG_MAX_PER_TIPO:
                continue                                       # varietà: non 8 schede di reparto quasi uguali
            if len(risultati) < k:
                risultati.append(self._voce(doc, lista[:per_doc], min(passaggio[i] for _, i in lista[:per_doc]),
                                            via.get(doc['id'])))
                if fam:
                    per_famiglia[fam] = risultati[-1]
                if tipo:
                    per_tipo[tipo] = per_tipo.get(tipo, 0) + 1
            else:
                riserva.append((j, lista))
        # c-ter) VOCE PERTINENTE: se la domanda parla proprio dell'argomento di un file che non riguarda la storia
        #    («chi è Giulio Cesare?», «cos'è il disprosio?», «parlami di Catania»), quel file passa al modello con il
        #    suo testo e la classe RUMORE: il modello risponde con quello che c'è scritto e dice che non riguarda
        #    l'indagine. Tre modi per riconoscerlo (al massimo 2 file):
        #      1. tutte le parole del titolo sono nella domanda («Giulio Cesare (disambigua)» ← «chi è Giulio Cesare?»);
        #      2. è il file più vicino di tutto l'archivio e ha nel titolo parole della domanda;
        #      3. per significato (embedding): il file è molto più vicino alla domanda di qualsiasi file della storia.
        if filtro and config.RAG_RUMORE_PERTINENTE and ordinati and not diretti:
            pertinenti = self.voci_pertinenti(domanda, ordinati, bool(risultati))
            for j, lista in pertinenti:
                doc = self.documenti[j]
                scartati = [s for s in scartati if s['id'] != doc['id']]
                if len(risultati) >= k:
                    risultati.pop()
                # il modello deve poter rispondere: gli si dà il testo della voce dall'inizio (fino a RAG_TESTO_VOCE
                # caratteri), più il brano migliore se cade dopo
                scelti, lung = [], 0
                for i in self.blocchi_di.get(j, []):
                    if lung >= config.RAG_TESTO_VOCE:
                        break
                    scelti.append((1.0, i))
                    lung += len(self.blocchi[i][1])
                if lista and lista[0][1] not in [i for _, i in scelti]:
                    scelti.append(lista[0])
                risultati.append(self._voce(doc, scelti, 'voce pertinente'))
        # posti garantiti ai documenti COLLEGATI da un codice (M362, K391, CN-38): sono gli anelli della catena
        # e non devono restare fuori solo perché non somigliano alla domanda. Prendono il posto di un registro
        # ripetitivo (uno dei 100 dello stesso tipo), mai di un documento unico
        collegati = [(j, l) for j, l in riserva if via.get(self.documenti[j]['id'])
                     and any(c.isdigit() for c in via[self.documenti[j]['id']][0])][:config.RAG_POSTI_COLLEGATI]
        for j, lista in collegati:
            doc = self.documenti[j]
            sostituibile = next((n for n in range(len(risultati) - 1, -1, -1)
                                 if risultati[n]['passaggio'] != 'ID' and not risultati[n]['via']
                                 and not risultati[n]['natura'] and risultati[n]['tipo'] in tipi_frequenti), None)
            if sostituibile is None:
                break
            risultati[sostituibile] = self._voce(doc, lista[:per_doc], min(passaggio[i] for _, i in lista[:per_doc]),
                                                 via.get(doc['id']))
        return risultati, scartati

    def _voce(self, doc, lista, passaggio, via=None):
        scelti = sorted(lista, key=lambda x: x[1])
        fam = doc.get('famiglia') or ''
        return {'id': doc['id'], 'file': doc['file'], 'titolo': doc['titolo'], 'classe': doc['classe'],
                'formato': doc['formato'], 'sospetto': doc['sospetto'], 'brani': [self.blocchi[i][1] for _, i in scelti],
                'punteggio': round(max((s for s, _ in lista), default=0) * 100, 2), 'passaggio': passaggio,
                'giorno': doc.get('giorno'), 'ora': doc.get('ora'), 'natura': doc.get('natura') or '', 'tipo': doc.get('tipo'),
                'famiglia': fam, 'copie_totali': len(self.famiglie.get(fam, [])) if fam else 0, 'copie_trovate': [],
                'via': {'parola': via[0], 'da': via[1]} if via else None}


# ================================ INDICE GLOBALE DI ECO ==========================================
_stato = {'indice': None, 'firma': None, 'lock': threading.Lock()}


def prepara(mostra=True):
    """Fasi 1-4: legge, scansiona e indicizza l'archivio (solo se i file sono cambiati). None se non c'è archivio."""
    with _stato['lock']:
        files = file_archivio()
        firma = tuple((str(p), p.stat().st_mtime) for p in files)
        if not files:
            _stato.update(indice=None, firma=firma)
            return None
        if firma != _stato['firma'] or _stato['indice'] is None:
            t0 = time.time()
            docs = scansiona([leggi_file(p) for p in files])
            _stato['indice'] = Indice(docs, embedding=config.RAG_IBRIDA, mostra=mostra)
            _stato['firma'] = firma
            ind = _stato['indice']
            print(f'RAG: {len(docs)} file, {len(ind.blocchi)} blocchi, '
                  f'{"BM25 + embedding" if ind.vettori is not None else "solo BM25"} ({time.time() - t0:.0f} s)')
            scalda()
        return _stato['indice']


def scalda():
    """Carica SUBITO il modello di embedding e le richieste-tipo. Con i vettori già salvati su disco il modello non
    serviva all'avvio e si caricava alla prima domanda (su CPU anche 40 secondi): ora lo si fa prima di aprire la chat."""
    ind = _stato['indice']
    if ind is None or ind.vettori is None:
        return
    t0 = time.time()
    try:
        codifica(['prova'])
        if config.RAG_INTENTO_EMBEDDING:
            somiglianze('prova')
        if embedder() is not None:
            print(f'RAG: modello di embedding pronto ({time.time() - t0:.0f} s)')
    except Exception as e:
        print('RAG: embedding non caricato:', e)


def indice():
    return _stato['indice'] or prepara(mostra=False)


def cerca(domanda, precedenti=()):
    ind = indice()
    return ind.cerca(domanda, precedenti) if ind else ([], [])


def documento(id_doc):
    ind = _stato['indice']
    return ind.per_id.get(id_doc) if ind else None


def ids():
    ind = _stato['indice']
    return set(ind.per_id) if ind else set()


NOMI_RACCOLTE = {'archivio_g3': 'archivio digitale del Giorno 3 (dossier LAZZARO + copie enciclopediche)',
                 'archivio_imprevisti_g3': 'registri della rete secondaria (imprevisti del Giorno 3)'}


def nome_raccolta(nome):
    return NOMI_RACCOLTE.get(nome, nome.replace('_', ' '))


def descrizione():
    ind = _stato['indice']
    if not ind:
        return ''
    c = ind.conteggi()
    modo = 'parole chiave + significato' if ind.vettori is not None else 'parole chiave'
    copie = sum(len(v) for k, v in ind.famiglie.items() if not k.startswith('testo uguale'))
    return (f'{len(ind.documenti)} file: {c["storia"]} della storia, {c["rumore"]} rumore (enciclopedia), '
            f'{c["incerto"]} incerti' + (f' · {copie} copie di altre fonti raggruppate' if copie else '') +
            f' · {len(ind.blocchi)} blocchi · ricerca per {modo}')


def riassunto_raccolta(ind, nome):
    """Una raccolta grande (500 registri) raccontata per tipi: quanti documenti di ogni tipo e di quale giorno,
    i documenti unici nel loro tipo, le famiglie di copie, le misure dirette e i "sentito dire"."""
    docs = [d for d in ind.raccolte.get(nome, []) if d['classe'] != 'rumore']
    tipi = {}
    for d in docs:
        tipi.setdefault(d.get('tipo') or d['titolo'], []).append(d)
    comuni = sorted((t for t, l in tipi.items() if len(l) > 2), key=lambda t: -len(tipi[t]))
    righe = []
    for t in comuni:
        giorni = sorted({d['giorno'] for d in tipi[t] if d.get('giorno')})
        righe.append(f'  - {len(tipi[t])} × «{t}»' + (f' (giorno operativo {", ".join(f"{g:02d}" for g in giorni)})' if giorni else ''))
    unici = sorted((d for t, l in tipi.items() if len(l) <= 2 for d in l), key=lambda d: (d.get('ora') or '99', d['id']))
    if unici:
        righe.append('  Documenti unici nel loro tipo:')
        for d in unici:
            nota = f' — {d["natura"]}' + (f' di {d["famiglia"]}' if d.get('famiglia') and d['natura'] == 'copia' else '') if d.get('natura') else ''
            righe.append(f'  - {d["id"]} ({d["file"]}) «{d["titolo"]}»{nota}')
    for fam, ids in sorted(ind.famiglie.items(), key=lambda x: -len(x[1])):
        ids = [i for i in ids if ind.per_id[i].get('raccolta') == nome]
        if fam.startswith('testo uguale') or len(ids) < 2:
            continue
        righe.append(f'  Copie: {len(ids)} documenti riportano {fam} senza verifica propria (per esempio '
                     f'{", ".join(ids[:4])}…). Contano come UNA sola fonte, non come {len(ids)} conferme.')
    for nat in ('misura diretta', 'derivata', 'sentito dire'):
        ids = [d['id'] for d in docs if d.get('natura') == nat]
        if ids:
            righe.append(f'  {nat.capitalize()} ({SPIEGA_NATURA[nat]}): {", ".join(ids)}')
    return righe


def rag_righe(righe):
    return [('- ' + r.strip()) if not r.strip().startswith('-') else r.strip() for r in righe]


def rapporto_scansione(esempi_rumore=5):
    """Testo leggibile della scansione (per il notebook e per scansione_archivio.md)."""
    ind = indice()
    if not ind:
        return 'Nessun archivio digitale caricato.'
    c = ind.conteggi()
    righe = [f'# Scansione dell\'archivio digitale', '',
             f'{len(ind.documenti)} file letti → **{c["storia"]} della storia**, {c["incerto"]} incerti, '
             f'{c["rumore"]} rumore.', '', '| Classe | ID | File | Titolo | Punti | Motivi |', '|---|---|---|---|---|---|']
    for d in ind.catalogo():
        if not ind.raccolta_piccola(d.get('raccolta') or 'archivio'):
            continue
        righe.append(f'| {d["classe"]} | {d["id"]} | {d["file"]} | {d["titolo"]} | {d["punti"]:+d} | '
                     f'{"; ".join(d["motivi"])} |')
    for nome in ind.raccolte:
        if not ind.raccolta_piccola(nome):
            righe += ['', f'**{nome_raccolta(nome).capitalize()}** ({len(ind.raccolte[nome])} file, tutti con ID e fonte '
                      'del dossier):', ''] + rag_righe(riassunto_raccolta(ind, nome))
    rumore = [d for d in ind.documenti if d['classe'] == 'rumore']
    if rumore:
        righe += ['', f'Esempi di rumore (su {len(rumore)}):', '', '| ID | File | Titolo | Punti | Motivi |',
                  '|---|---|---|---|---|']
        vicini = sorted(rumore, key=lambda d: -d['punti'])[:esempi_rumore]     # i più "ingannevoli" per primi
        for d in vicini:
            righe.append(f'| {d["id"]} | {d["file"]} | {d["titolo"][:40]} | {d["punti"]:+d} | {"; ".join(d["motivi"])} |')
    return '\n'.join(righe)
