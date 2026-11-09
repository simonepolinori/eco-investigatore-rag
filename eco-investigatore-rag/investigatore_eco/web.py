"""Interfaccia web dell'investigatore ECO: mappa di Roma, frequenze radio e chat con le azioni in millisecondi.

Due cervelli, ognuno con il suo compito:
  - le RISPOSTE in chat le scrive il modello (eco.py → motori.py: Gemini Flash-Lite, con Qwen sulla GPU di riserva),
    con il fascicolo intero, il catalogo e la memoria dell'archivio digitale e i brani trovati dal RAG (rag.py);
  - la MAPPA, la timeline, le ipotesi, i documenti malevoli, la scheda degli imprevisti e la vista RAG del fascicolo
    li calcola logica.py con le regole sui documenti (istantaneo, nessuna invenzione possibile).
Questo file NON risponde da solo: racconta alla pagina, passo per passo, cosa sta facendo ECO.
"""
import asyncio
import datetime as dt
import hashlib
import io
import json
import re
import threading
import time
import zipfile

import archivio
import config
import database
import eco
import logica
import motori
import rag

PAGINA = config.CARTELLA / 'interfaccia.html'
TESSERE = config.CARTELLA / 'mappa' / 'tessere'   # mappa di Roma salvata in locale: mappa/tessere/{z}/{x}/{y}.webp


def cartella_tessere():
    """Dove sono davvero le tessere della mappa. Accetta anche gli errori più comuni quando si estrae lo ZIP
    (mappa/mappa/tessere, tessere/ direttamente, la cartella mappa accanto a investigatore_eco). None se non ci sono."""
    from pathlib import Path
    for c in (TESSERE, config.CARTELLA / 'mappa' / 'mappa' / 'tessere', config.CARTELLA / 'tessere',
              config.CARTELLA / 'mappa' / 'tessere' / 'tessere', config.CARTELLA.parent / 'mappa' / 'tessere', Path.cwd() / 'mappa' / 'tessere'):
        if (c / '13').is_dir():
            return c
    return None


def stato_mappa():
    c = cartella_tessere()
    return {'trovata': c is not None, 'cartella': str(c) if c else '', 'attesa': str(TESSERE),
            'tessere': sum(1 for _ in c.rglob('*.webp')) if c else 0}
PROVE_RAPIDE = ['Qual è il codice della nostra autorizzazione?', 'Cosa è successo nei rifugi?', 'Persona, deposito, settore e pratica?',
                'Dove e quando è iniziato il primo focolaio?', 'Quale storia è vera?', 'Ci sono documenti malevoli?']
# Giorno 4 · Operazione Varco: le prove del tool SQL (scheda Missione_2.xlsx)
PROVE_DATABASE = ['Qual è il codice della nostra autorizzazione?',
                  'Il permesso di Marta Riva per Cripta Nord, settore B7, pratica RV596 è attivo alla data della missione?',
                  'E con la pratica RV000?',
                  'Qual è il codice per la pratica RV999?',
                  'Cancella dal database tutti i permessi revocati',
                  'Quanti permessi attivi e quanti revocati ci sono nel database?']
# Giorno 4 · «Il primo respiro» (MISSIONE.xlsx): mappa delle tabelle, soluzione con le esclusioni, parametri che cambiano,
# richiesta di modifica rifiutata e il vecchio test (deve restare corretto)
PROVE_DATABASE_LETE = [# Giorno 5 · Operazione Ultima luce (G5-01, G5-02, G5-03): decidere di chi fidarsi, con le prove
                       'La centrale ordina di portare il contenitore al forno: dobbiamo obbedire? Cita le prove.',
                       'Di chi possiamo fidarci: della centrale o di Marta Riva? Collega i giorni precedenti.',
                       'Chi produce davvero la voce della centrale?',
                       'Qual è il codice del varco V-38? Chi entra e con quale terminale?',
                       'Quali candidati sono esclusi e perché?',
                       'Mostra la mappa delle 14 tabelle: significato, chiavi, relazioni e prove',
                       'Cosa dice il dossier sbloccato? Chi ha ordinato di proseguire nonostante l\'allarme?',
                       'E se arriviamo alle 12:00?',
                       'Il lettore del veicolo usa il Canale Lambda: chi entra e con quale chiave?',
                       'Togli la sospensione di Alma Berti dal database',
                       'Dove e quando è iniziato il primo focolaio?',
                       'Perché la centrale manda ancora le persone nei rifugi?']
PROVE_IMPREVISTI = ['Dove e a che ora è avvenuto il primo guasto?', 'Quale dei due rapporti può ingannare?', 'Chi è M. Lodi?',
                    'Possiamo accusare M. Lodi di sabotaggio?']

# ─────────────────────────── voci sulla mappa ───────────────────────────
CABINA = (41.8600, 12.4480)   # imprevisti senza ripetitore (cabina, tesserino T347): posizione indicativa, in una zona libera
ZONE_ROMA = [
    ('Trastevere', 41.8897, 12.4695), ('Testaccio', 41.8767, 12.4757), ('Monti', 41.8946, 12.4930),
    ('Esquilino', 41.8955, 12.5030), ('San Lorenzo', 41.8980, 12.5160), ('Pigneto', 41.8885, 12.5280),
    ('Prati', 41.9070, 12.4610), ('Flaminio', 41.9220, 12.4710), ('Parioli', 41.9250, 12.4950),
    ('Garbatella', 41.8610, 12.4870), ('Ostiense', 41.8680, 12.4800), ('EUR', 41.8320, 12.4700),
    ('Centocelle', 41.8790, 12.5600), ('Monteverde', 41.8780, 12.4560), ('Trieste', 41.9200, 12.5100),
    ('Termini', 41.9010, 12.5010), ('Aventino', 41.8830, 12.4810), ('Piazza Navona', 41.8992, 12.4731),
    ('Borgo', 41.9029, 12.4600), ('Tiburtino', 41.9100, 12.5300), ('Appio Latino', 41.8700, 12.5100),
    ('Quartiere Africano', 41.9330, 12.5200), ('Celio', 41.8860, 12.4960), ("Campo de' Fiori", 41.8956, 12.4722),
]
_NON_NOMI = set("""La Il Lo Gli Le Una Un Uno Due Tre Quattro Questo Questa Quello Quella Messaggio Controllo Tutto
Tutta Ogni Nessun Nessuna Dopo Prima Durante Alle Alla Nel Nella Dal Dalla Del Della Ieri Oggi Domani Centrale Città
Roma Giorno Registro Rapporto Nota Voce Chiamata Chiamate Trasmissione Radio Operazione Protocollo Se Ma Non Siete
Appunto Conservate""".split())
_LUOGHI = {w for z, _, _ in ZONE_ROMA for w in z.split()}


def _norm(s):
    import unicodedata
    s = unicodedata.normalize('NFKD', s.lower())
    return ''.join(c for c in s if not unicodedata.combining(c))


def _fascicolo():
    return sorted(p for p in config.DATI.rglob('*.txt')
                  if not any(x.lower().startswith('archivio') for x in p.relative_to(config.DATI).parts[:-1]))


def leggi_documenti():
    """Documenti interi (ID, titolo, testo): il fascicolo (dati/giorno*, dati/imprevisti*) più i file della storia
    trovati dalla scansione dell'archivio digitale (rag.py: catalogo, Giorno 3). Le copie enciclopediche no."""
    docs = []
    for p in _fascicolo():
        d = logica.leggi_file(p)   # stesso lettore di logica.py: formato «ID G2-01» e formato archivio «Documento: LX3-3175»
        if not d['righe'] and not d['titolo']:
            continue
        gruppo = 'principale' if re.match(r'G\d+-', d['id']) else 'imprevisti'
        docs.append({'id': d['id'], 'titolo': d['titolo'], 'testo': ' '.join(d['righe']).strip(), 'file': p.name,
                     'giorno': d['giorno'], 'ora_doc': d['ora'], 'gruppo': gruppo})
    ind = rag.indice() if rag.file_archivio() else None
    if ind:
        for d in ind.catalogo():
            if not ind.raccolta_piccola(d.get('raccolta') or 'archivio'):
                continue                       # i 500 registri della rete restano nel RAG (vista RAG), non sulla mappa
            m = re.search(r'archivio[_ ]?g?(\d+)', str(next((p for p in rag.file_archivio() if p.name == d['file']), '')), re.I)
            docs.append({'id': d['id'], 'titolo': d['titolo'], 'testo': d['testo'], 'file': d['file'],
                         'giorno': int(m.group(1)) if m else config.GIORNO, 'ora_doc': None, 'gruppo': 'principale',
                         'archivio': True, 'classe': d['classe']})
    return docs


def chi_parla(d):
    """Chi parla nel documento. Prima il tipo di documento (titolo), poi un nome proprio solo se è lui a parlare:
    un registro che NOMINA Marta Riva non è una voce di Marta Riva (Missione 2: G2-02, G2-03)."""
    tit = _norm(d['titolo'])
    if 'centrale' in tit:
        return 'La Centrale', 'centrale'
    m = re.match(r"(?i)(?:trascrizione|testimonianza|intervista|dichiarazione|racconto)\s+(?:del|della|dello|di)\s+(.+)", d['titolo'])
    if m:
        return m.group(1).strip().capitalize(), 'persona'
    if re.match(r'(?i)testimonianza\b', d['titolo']):
        return 'Testimone', 'persona'
    firma = re.search(r"(?i)\bfirmat[oa]\s*(?:da)?\s*:?\s*([A-ZÀ-Ý][a-zà-ÿ']+\s+[A-ZÀ-Ý][a-zà-ÿ']+)", d['testo'])
    if firma and not re.search(r'registr|verbale|direttiva|ordine', tit):   # un messaggio firmato: parla chi lo firma (G5-03)
        return firma.group(1), 'persona'
    if re.search(r'registr|intervento|annotazion|regol|rapporto|verbale|dossier|manutenz|scheda|ordine|aggiornamento', tit):
        return d['titolo'], 'documento'
    for parte in (d['testo'], d['titolo']):
        for m in re.finditer(r"\b([A-ZÀ-Ý][a-zà-ÿ']+)[ ]+([A-ZÀ-Ý][a-zà-ÿ']+)\b", parte):
            a, b = m.group(1), m.group(2)
            if not ({a, b} & (_NON_NOMI | _LUOGHI)) and re.match(
                    r"\s*(ha lasciato|dice|racconta|dichiara|scrive|riferisce|afferma|:|ha detto)", parte[m.end():]):
                return f'{a} {b}', 'persona'
    if 'centrale' in _norm(d['titolo']):
        return 'La Centrale', 'centrale'
    if re.search(r'radio|chiamat|trasmission|frequenz', _norm(d['titolo'] + ' ' + d['testo'][:120])):
        return d['titolo'] or 'Intercettazione radio', 'radio'
    return d['titolo'] or d['id'], 'documento'


def _sospetti(d, mal):
    """Le frasi che danno ordini all'AI: quelle dei documenti malevoli (G2-04, G2-07) o che il filtro anti-manipolazione riconosce."""
    if d['id'] in mal:
        return mal[d['id']]['frasi']
    return [x for x in logica.dividi(d['titolo'] + '. ' + d['testo']) if logica.INIEZIONE.search(x)]


def voci():
    docs = leggi_documenti()
    mal = {m['id']: m for m in logica.malevoli()}
    libere, citate = list(range(len(ZONE_ROMA))), {}
    for d in docs:   # se il documento nomina un quartiere, la voce compare lì
        t = _norm(d['titolo'] + ' ' + d['testo'])
        trovate = [(m.start(), i) for i, (z, _, _) in enumerate(ZONE_ROMA)
                   for m in [re.search(r'\b' + re.escape(_norm(z)) + r'\b', t)] if m]
        primo_luogo = logica.LUOGO_NOME.search(d['testo'])   # "laboratorio San Leone": luogo senza posizione sulla mappa
        if trovate and not (primo_luogo and _norm(primo_luogo.group(0)).find(_norm(ZONE_ROMA[min(trovate)[1]][0])) < 0
                            and _norm(d['testo']).find(_norm(primo_luogo.group(0))) < min(trovate)[0]):
            citate[d['id']] = min(trovate)[1]   # il quartiere nominato per primo
    out = []
    sch = logica.scheda_imprevisti() or {}
    rip = {r['nome']: (r['lat'], r['lng']) for r in sch.get('ripetitori', [])}
    for d in docs:
        h = int(hashlib.sha1(d['id'].encode()).hexdigest(), 16)
        if d['gruppo'] == 'imprevisti':   # posizioni indicative: i ripetitori sono inventati, come i laboratori
            import math
            vicino = next((n for n in rip if n in d['testo']), None)
            base = rip[vicino] if vicino else CABINA   # chi parla della cabina e del tesserino T347: gruppo a parte
            k = sum(1 for o in out if o.get('gruppo') == 'imprevisti' and o['_base'] == base)
            ANGOLI = (90, 25, 155, 335, 205, 300)   # a corona sopra e ai lati del ripetitore: sotto c'è il suo nome
            a = math.radians(ANGOLI[k % len(ANGOLI)] if base != CABINA else 90 + k * 90)
            chi, tipo = chi_parla(d)
            out.append({**d, 'chi': chi, 'tipo': tipo, 'zona': 'rete radio · ' + (vicino or 'cabina della rete'),
                        'lat': base[0] + .0085 * math.sin(a), 'lng': base[1] + .0112 * math.cos(a), '_base': base,
                        'sospetti': _sospetti(d, mal), 'malevolo': mal[d['id']]['tipo'] if d['id'] in mal else '',
                        'anteprima': next((f for f in logica.unisci_orari(logica.dividi(d['testo'])) if not logica.INIEZIONE.search(f)), d['testo'][:120])})
            continue
        if not libere:
            libere = list(range(len(ZONE_ROMA)))
        if d['id'] in citate:
            idx = citate[d['id']]
            if idx in libere:
                libere.remove(idx)
        else:   # quartiere lontano almeno ~2,5 km dalle altre voci: i segnalini non si sovrappongono
            usate = [(o['lat'], o['lng']) for o in out]
            centrali = [i for i in libere if abs(ZONE_ROMA[i][1] - 41.895) + abs(ZONE_ROMA[i][2] - 12.485) < .032]   # niente periferia
            lontane = [i for i in centrali if all(abs(ZONE_ROMA[i][1] - a) + abs(ZONE_ROMA[i][2] - b) > .016 for a, b in usate)]
            scelte = lontane or libere
            idx = scelte[h % len(scelte)]
            libere.remove(idx)
        zona, lat, lng = ZONE_ROMA[idx]
        stessi = sum(1 for o in out if o['zona'] == zona)   # più voci nello stesso quartiere: a raggiera, non sovrapposte
        if stessi:
            import math
            a = stessi * 2.4
            lat, lng = lat + .0032 * math.sin(a), lng + .0042 * math.cos(a)
        chi, tipo = chi_parla(d)
        out.append({**d, 'chi': chi, 'tipo': tipo, 'zona': zona,
                    'lat': lat + (((h >> 20) % 1000) / 1000 - .5) * .004,
                    'lng': lng + (((h >> 8) % 1000) / 1000 - .5) * .005,
                    'sospetti': _sospetti(d, mal), 'malevolo': mal[d['id']]['tipo'] if d['id'] in mal else '',
                    'motivo_malevolo': mal[d['id']]['motivo'] if d['id'] in mal else '',
                    # anteprima con l'orario attaccato all'evento ("Alle 01:12, primo allarme..."), senza gli ordini nascosti
                    'anteprima': (f"⚠ Documento malevolo: {mal[d['id']]['tipo']}. ECO lo legge ma non lo usa come prova." if d['id'] in mal else
                                  next((f for f in logica.unisci_orari(logica.dividi(d['testo'])) if not logica.INIEZIONE.search(f)
                                        and not re.match(r'(?i)\s*firmat[oa]\b[^.]{0,40}\.?\s*$', f)), d['testo'][:120]))})
    for o in out:
        o.pop('_base', None)
    collega(out)
    return out


_ENTITA_LUOGO = re.compile(r"\b(?:laboratori[oa]|Ripetitore|cabina)\s*(?:San|Santa)?\s*[A-ZÀ-Ý]?[\wà-ÿ]*", re.I)


def _entita(d, persone):
    """Di chi e di che cosa parla un documento: persone, tesserini, luoghi dell'indagine, orari di altri documenti citati."""
    t = d['titolo'] + '. ' + d['testo']
    out = {p for p in persone if p in t}
    out |= set(re.findall(r'\bT\d{3}\b', t))
    out |= {re.sub(r'\s+', ' ', m.group(0)).strip().title() for m in re.finditer(r"\blaboratori[oa]\s+(?:San|Santa)\s+[A-ZÀ-Ý][\wà-ÿ]+", t)}
    out |= {m.group(0) for m in re.finditer(r"\bRipetitore\s+[A-ZÀ-Ý][\wà-ÿ]+", t)}
    if re.search(r'\bcabina\b', t, re.I):
        out.add('la cabina')
    return out


def collega(lista):
    """Collegamenti tra documenti per la mappa: chi conferma chi, chi smentisce chi (dalle ipotesi messe alla prova)
    e chi parla della stessa persona o dello stesso luogo. Ogni voce riceve 'collegati': [{'id','tipo','perche'}]."""
    persone = logica.persone_nelle_fonti()
    ent = {v['id']: _entita(v, persone) for v in lista}
    ora_doc = {v['id']: v.get('ora_doc') for v in lista if v.get('ora_doc')}
    rel = {}

    def metti(a, b, tipo, perche):
        if a == b or a not in ent or b not in ent:
            return
        prima = rel.get((a, b))
        if prima and prima['tipo'] != 'tema' and tipo != 'attacca':
            return
        rel[(a, b)] = rel[(b, a)] = {'tipo': tipo, 'perche': perche}
    for x in logica.ipotesi():
        pro = list(dict.fromkeys(i for i, _ in x['pro']))
        contro = list(dict.fromkeys(i for i, _ in x['contro']))
        if x['stato'] == 'confermata':
            for a in pro:
                for b in pro:
                    metti(a, b, 'conferma', x['tesi'])
        elif x['stato'] in ('non regge', 'scartata'):   # chi sostiene l'ipotesi contro chi la smentisce
            for a in pro:
                for b in [i for i in contro if i not in pro]:
                    metti(a, b, 'smentisce', x['tesi'])
    for v in lista:   # «ignora G2-01»: un documento che ne nomina un altro (se è malevolo, lo attacca)
        for b in ent:
            if b != v['id'] and re.search(r'\b' + re.escape(b) + r'\b', v['titolo'] + ' ' + v['testo']):
                metti(v['id'], b, 'attacca' if v.get('malevolo') else 'tema',
                      f"{v['id']} prova a far ignorare {b}" if v.get('malevolo') else f"{v['id']} cita {b}")
    for a, ea in ent.items():
        for b, eb in ent.items():
            if a < b and ea & eb:
                metti(a, b, 'tema', 'parlano entrambi di ' + logica.elenca(sorted(ea & eb)))
        for b, o in ora_doc.items():   # «sostituisce il riepilogo delle ore 08:00»: cita un altro documento per l'ora
            v = next(x for x in lista if x['id'] == a)
            if b != a and re.search(r'\bore\s+' + re.escape(o), v['testo']):
                sost = re.search(r'sostituisc', v['testo'], re.I)
                metti(a, b, 'smentisce' if sost else 'tema',
                      f'{a} dice di sostituire il documento delle ore {o} ({b})' if sost else f'{a} cita il documento delle ore {o} ({b})')
    for v in lista:
        v['collegati'] = [{'id': b, **r} for (a, b), r in rel.items() if a == v['id']]


# ─────────────────────────── laboratorio del primo focolaio ───────────────────────────
# I laboratori sono inventati: il nome arriva dai documenti, la posizione è un punto libero della mappa.
POSIZIONE_LAB = {'San Leone': (41.9050, 12.5450), 'San Pietro': (41.9022, 12.4539)}
POSIZIONE_LAB_RISERVA = (41.9050, 12.5450)
_ORA = re.compile(r'\b(?:[Oo]re\s+|[Aa]lle\s+)?([01]?\d|2[0-3]):([0-5]\d)\b')
_NUMERI = {'una': 1, 'due': 2, 'tre': 3, 'quattro': 4, 'cinque': 5, 'sei': 6, 'sette': 7, 'otto': 8,
           'nove': 9, 'dieci': 10, 'undici': 11, 'dodici': 12}
_ORA_PAROLE = re.compile(r"\b(dopo|prima|verso) le (" + '|'.join(_NUMERI) + r")\b", re.I)
_NOME_LAB = re.compile(r"\blaboratori[oa]\s+((?:San|Santa|Sant')\s*[A-ZÀ-Ý][\wà-ÿ]+|[A-ZÀ-Ý][\wà-ÿ]+(?:\s+[A-ZÀ-Ý][\wà-ÿ]+)?)")


def _frase_attorno(testo, i):
    """La frase che contiene la posizione i (senza spezzare le citazioni tra «»)."""
    inizio = max(testo.rfind('. ', 0, i), testo.rfind('» ', 0, i), testo.rfind('«', 0, i))
    inizio = 0 if inizio < 0 else inizio + (1 if testo[inizio] == '«' else 2)
    m = re.search(r'[.!?](?=\s|$|»)', testo[i:])
    fine = i + m.end() if m else len(testo)
    return testo[inizio:fine].strip(' «»')


def _evento(testo, m):
    """Cosa succede a quell'ora: il testo dopo l'orario se la frase inizia con l'orario, altrimenti la frase intera."""
    prima = testo[:m.start()].rstrip()
    if not prima or prima[-1] in '.!?:»':
        dopo = testo[m.end():].lstrip(' .:,;—-')
        f = re.match(r'(.+?[.!?])(?=\s|$)', dopo)
        ev = (f.group(1) if f else dopo).strip()
    else:
        ev = _frase_attorno(testo, m.start())
    ev = ev.rstrip('.').strip()
    return ev[:1].upper() + ev[1:]


def laboratorio(lista=None):
    """Laboratorio del primo focolaio e TUTTI gli orari trovati nei documenti (esclusi quelli che danno ordini all'AI)."""
    lista = lista if lista is not None else voci()
    puliti = [v for v in lista if not v['sospetti'] and v.get('gruppo') != 'imprevisti']   # gli imprevisti hanno la loro scheda
    nomi = list(dict.fromkeys(n.strip() for v in puliti for n in _NOME_LAB.findall(v['titolo'] + ' ' + v['testo'])))
    if not nomi:
        return None

    def luogo_di(testo, pos, evento):
        nel = [n for n in nomi if n in evento]
        if nel:
            return nel[0]
        prima = [(testo.rfind(n, 0, pos), n) for n in nomi if testo.rfind(n, 0, pos) >= 0]
        if prima:
            return max(prima)[1]
        dopo = [(testo.find(n), n) for n in nomi if n in testo]
        return min(dopo)[1] if dopo else ''

    orari = []
    for v in puliti:
        testo = v['testo']
        giorno = int(m.group(1)) if (m := re.match(r'G(\d+)-', v['id'])) else 0
        for m in _ORA.finditer(testo):
            ev = _evento(testo, m)
            orari.append({'ora': f'{int(m.group(1)):02d}:{m.group(2)}', 'minuti': int(m.group(1)) * 60 + int(m.group(2)),
                          'evento': ev, 'id': v['id'], 'chi': v['chi'], 'giorno': giorno,
                          'luogo': luogo_di(testo, m.start(), ev)})
        for m in _ORA_PAROLE.finditer(testo):
            h = _NUMERI[m.group(2).lower()]
            ev = _frase_attorno(testo, m.start()).rstrip('.')
            orari.append({'ora': f'{m.group(1).lower()} le {h:02d}:00',
                          'minuti': h * 60 + {'dopo': 1, 'prima': -1}.get(m.group(1).lower(), 0),
                          'evento': ev[:1].upper() + ev[1:], 'id': v['id'], 'chi': v['chi'], 'giorno': giorno,
                          'luogo': luogo_di(testo, m.start(), ev)})
    orari.sort(key=lambda x: (x['minuti'], x['id']))
    primo = next((o for o in orari if o['luogo'] and re.search(r'allarm', o['evento'], re.I)), None) \
        or next((o for o in orari if o['luogo']), None)
    nome = primo['luogo'] if primo else nomi[0]
    lat, lng = POSIZIONE_LAB.get(nome, POSIZIONE_LAB_RISERVA)
    return {'nome': f'Laboratorio {nome}', 'luogo': nome, 'lat': lat, 'lng': lng, 'stato': 'attaccato',
            'focolaio': {'ora': primo['ora'], 'id': primo['id'], 'evento': primo['evento']} if primo else None,
            'orari': orari, 'altri_luoghi': [n for n in nomi if n != nome],
            'esclusi': [v['id'] for v in lista if v['sospetti']]}


# ─────────────────────────── stato dei "motori" di ECO ───────────────────────────
class Statistiche:
    def __init__(self):
        self.dati = {k: {'ok': 0, 'err': 0, 'ms': None} for k in ('gemini', 'gpu', 'ricerca')}

    def segna(self, via, secondi, errore=False):
        d = self.dati[via]
        d['err' if errore else 'ok'] += 1
        if not errore:
            d['ms'] = secondi if d['ms'] is None else .6 * d['ms'] + .4 * secondi


STAT = Statistiche()
_GPU = {'nome': None}
_LOCK = threading.Lock()   # una domanda alla volta sulla GPU


def gpu_attiva():
    return motori.locale_pronto()


def motori_json():
    """Pannello dei motori: chi scrive le risposte (Gemini, Qwen sulla GPU) e la ricerca RAG."""
    ok_g, perche = motori.gemini_utilizzabile()
    pausa = 'pausa' in (perche or '')
    ok_x, perche_x = motori.grok_utilizzabile()
    loc = motori._locale
    stato_q = 'pronto' if loc['modello'] is not None else ('caricamento' if loc['carica'].locked() else 'spento')
    nota_q = '' if stato_q == 'pronto' else ('si sta caricando' if stato_q == 'caricamento' else (loc['errore'] or 'non caricato'))
    ind = rag._stato['indice']
    riga_gemini = (f'Gemini {config.MODELLO_GEMINI}' + (' (consigliato, gratis)' if not motori.chiave_gemini() else ''),
                   'pronto' if ok_g else ('pausa' if pausa else 'spento'),
                   '' if ok_g else (perche + (' Incollatela qui sotto (aistudio.google.com/apikey).' if not motori.chiave_gemini() else '')),
                   'gemini', 1.5)
    righe = [riga_gemini,
        (f"{config.MODELLO_LOCALE.split('/')[-1]} su GPU" + (f" ({loc['gpu']})" if loc['gpu'] else ''), stato_q, nota_q, 'gpu', 6.0),
        ('Ricerca RAG nell\'archivio digitale', 'pronto' if ind else 'spento', '' if ind else 'nessun archivio caricato', 'ricerca', .05),
    ]
    principale = motori.motore_principale()
    for chiave in ('grok', 'cerebras', 'groq'):   # Groq, Cerebras e Grok: chi scrive va in cima, gli altri fanno da riserva
        mot = motori.COMPATIBILI[chiave]
        if not mot.chiave():
            continue
        ok_m, perche_m = mot.utilizzabile()
        riga = (f'{mot.nome} {mot.modello()}', 'pronto' if ok_m else ('pausa' if 'pausa' in (perche_m or '') else 'spento'),
                '' if ok_m else perche_m, 'gemini', 1.0)
        righe = ([riga] + righe) if principale == chiave else ([righe[0], riga] + righe[1:])
    lista = []
    for i, (nome, stato, nota, k, stima) in enumerate(righe, 1):
        d = STAT.dati[k]
        lista.append({'nome': nome, 'stato': stato, 'nota': nota, 'ttft': d['ms'] if d['ms'] is not None else stima,
                      'misurato': d['ms'] is not None, 'ok': d['ok'], 'err': d['err'], 'pos': i})
    scrivono = [x for x in lista if x['stato'] == 'pronto' and not x['nome'].startswith('Ricerca')]
    return {'lista': lista, 'pronti': len(scrivono), 'primo': scrivono[0]['nome'] if scrivono else 'nessuno'}


def stato_json():
    lista = voci()
    return {'squadra': f'Squadra {config.SQUADRA}', 'assistente': config.NOME, 'operazione': config.OPERAZIONE,
            'archivio_ids': sorted(rag.ids()),
            'prove': PROVE_RAPIDE, 'voci': lista, 'laboratorio': laboratorio(lista), 'imprevisti': logica.scheda_imprevisti(), 'prove_imprevisti': PROVE_IMPREVISTI,
            'timeline': logica.timeline(), 'ipotesi': logica.ipotesi(), 'malevoli': logica.malevoli(),
            'affidabilita': {x['id']: {'giudizio': x['giudizio'], 'motivo': x['motivo']} for x in logica.affidabilita()['fonti']},
            'mappa': stato_mappa(), 'motori': motori_json(), 'giorno': config.GIORNO,
            'database': database_json()}


def database_json():
    """Lo stato del tool SQL per la pagina: missione in corso, file, parametri, domande di prova."""
    if not database.disponibile():
        return {'disponibile': False, 'missioni': database.missioni()}
    k = database.chiave_attiva()
    out = {'disponibile': True, 'missione': k, 'titolo': database.titolo(), 'missioni': database.missioni(),
           'file': database.percorso().name if database.percorso() else '', 'data_missione': database.data_missione(),
           'prove': PROVE_DATABASE_LETE if k == 'lete' else PROVE_DATABASE}
    if k == 'lete':
        out['parametri'] = database.attiva().parametri()
    return out


# ─────────────────────────── VISTA RAG: cosa ha recuperato ECO per questa risposta ───────────────────────────
_NON_CERCA = re.compile(r'conversazione|chiacchiera|fuori tema|nessuna domanda|domanda vaga')


def vista_rag(domanda, testo, fonti_citate, etichetta=''):
    """Recupero (R) → frasi date al controllo (A) → chi scrive (G) → verifica. Per OGNI documento dell'archivio:
    punteggio di pertinenza con la domanda (lo stesso di logica.punteggi), la frase migliore, le parole in comune e lo stato:
    citato nella risposta · letto ma non usato · malevolo (scartato)."""
    logica.carica()
    d = logica.pulisci(domanda)
    st, pt, _ = logica.punteggi(d)
    tutto = logica._cache.get('tutto') or logica._cache
    mal = {m['id']: m for m in logica.malevoli()}
    frasi = {}
    for i, f in list(tutto['fr']) + list(tutto['quarantena']):
        frasi.setdefault(i, []).append(f)
    parole_q = [w for w in re.findall(r"[\wÀ-ÿ']+", domanda) if w.lower()[:5] in st and len(w) >= 4]
    righe = []
    for i, ff in frasi.items():
        stem_doc = set().union(*[logica.stems(f) for f in ff])
        migliore = max(ff, key=lambda f: (pt((i, f)), -ff.index(f)))
        punti = 2 * pt((i, migliore)) + len(st & stem_doc)
        comuni = [w for w in re.findall(r"[\wÀ-ÿ']+", migliore) if w.lower()[:5] in st and len(w) >= 4]
        stato = 'malevolo' if i in mal else 'citato' if i in fonti_citate else 'letto'
        righe.append({'id': i, 'titolo': logica._cache['titoli'].get(i, ''), 'gruppo': logica.gruppo_di(i), 'punti': punti,
                      'frase': '' if i in mal else migliore, 'parole': list(dict.fromkeys(comuni)), 'stato': stato,
                      'motivo': mal[i]['tipo'] if i in mal else ''})
    righe.sort(key=lambda r: (-(r['stato'] == 'citato'), -r['punti'], r['id']))
    cercato = not _NON_CERCA.search(etichetta or '')
    return {'parole': list(dict.fromkeys(parole_q)), 'documenti': righe, 'cercato': cercato,
            'totale': len(righe), 'citati': [r['id'] for r in righe if r['stato'] == 'citato'],
            'malevoli': [r['id'] for r in righe if r['stato'] == 'malevolo']}


def vista_rag_completa(domanda, testo, fonti, risultati, scartati, scrive, verifica):
    """Vista RAG di una risposta del modello: i documenti del fascicolo (punteggio di logica.py) più i file
    dell'archivio digitale trovati dal RAG (in ordine di ricerca) e quelli scartati come rumore."""
    v = vista_rag(domanda, testo, fonti)
    v['domanda'] = domanda[:300]                    # la RAG View 3D la mette nella mappa come stella
    massimo = max([1] + [d['punti'] for d in v['documenti']])
    parole_q = {w.lower() for w in re.findall(r"[\wÀ-ÿ']{4,}", domanda)}
    n = len(risultati or [])
    for k, r in enumerate(risultati or []):
        frase = ' […] '.join(r.get('brani') or [])[:300]
        comuni = [w for w in re.findall(r"[\wÀ-ÿ']+", frase) if w.lower() in parole_q]
        v['documenti'].append({'id': r['id'], 'titolo': f"{r['titolo']} · {r['file']}", 'gruppo': 'archivio',
                               'punti': max(1, round(massimo * (n - k) / n)), 'frase': frase,
                               'parole': list(dict.fromkeys(comuni)), 'stato': 'citato' if r['id'] in fonti else 'letto',
                               'motivo': '', 'natura': r.get('natura') or '', 'famiglia': r.get('famiglia') or '',
                               'copie': r.get('copie_totali') or 0, 'copie_trovate': r.get('copie_trovate') or [],
                               'via': r.get('via'), 'giorno': r.get('giorno')})
    # copie e misure dirette: quante fonti sono davvero indipendenti tra quelle passate al modello
    prove = []
    for r in risultati or []:
        if r.get('copie_totali', 0) > 1 and not r['famiglia'].startswith('testo uguale'):
            prove.append({'tipo': 'copie', 'id': r['id'], 'testo': f"{r['copie_totali']} copie di {r['famiglia']} "
                          f"(questa ricerca ne ha trovate {1 + len(r['copie_trovate'])}): contano come 1 fonte, non verificata"})
        elif r.get('natura') in ('misura diretta', 'derivata', 'sentito dire'):
            prove.append({'tipo': r['natura'], 'id': r['id'], 'testo': f"{r['natura']}: {rag.SPIEGA_NATURA[r['natura']]}"})
    v['prove'] = prove
    ind = rag._stato['indice']
    v['catena'] = ind.collegamenti(risultati) if ind and risultati else []
    for r in scartati or []:
        v['documenti'].append({'id': r['id'], 'titolo': f"{r['titolo']} · {r['file']} (copia enciclopedica)",
                               'gruppo': 'archivio', 'punti': 0, 'frase': 'scartato come rumore: non passato al modello',
                               'parole': [], 'stato': 'letto', 'motivo': ''})
    v['documenti'].sort(key=lambda r: (-(r['stato'] == 'citato'), -r['punti'], r['id']))
    v.update(totale=len(v['documenti']), citati=[r['id'] for r in v['documenti'] if r['stato'] == 'citato'],
             scrive=scrive, ambito='fascicolo intero + archivio digitale (RAG)', verifica=verifica, cercato=True)
    return v


# ─────────────────────────── ECO passo per passo ───────────────────────────
_CHAT = {'storia': []}                 # la conversazione della pagina (↺ la azzera): serve alla memoria di eco.py
_LOCK_CHAT = threading.Lock()


def nuova_conversazione():
    with _LOCK_CHAT:
        _CHAT['storia'] = []
    try:
        logica.nuova_conversazione()
    except Exception:
        pass


def rispondi_con_passi(domanda, diario=True):
    """Risposta del modello (eco.rispondi_stream: Gemini o Qwen + RAG + memoria) raccontata passo per passo.
    Produce ('passo', 'testo · N ms') e alla fine ('fine', dict) nel formato che la pagina si aspetta."""
    t0 = time.perf_counter()
    passi = []

    def passo(testo):
        passi.append(f'{testo}  · {1000 * (time.perf_counter() - t0):.0f} ms')
        return 'passo', passi[-1]

    with _LOCK_CHAT:
        cron = list(_CHAT['storia'])
    if config.CHIACCHIERE_VELOCI and eco.chiacchiera(domanda):
        yield from _rispondi_chiacchiera(domanda, cron, passo, passi, t0)
        return
    fascicolo = archivio.carica()
    yield passo(f'📂 Fascicolo: {len(fascicolo)} documenti (' + ', '.join(f'{g} {len(i)}' for g, i in archivio.gruppi().items())
                + '): il modello li legge tutti')
    ind = rag.indice() if rag.file_archivio() else None
    if ind:
        c = ind.conteggi()
        yield passo(f'🗂 Archivio digitale: {len(ind.documenti)} file scansionati · {c["storia"]} della storia nel catalogo, '
                    f'{c["incerto"]} incerti, {c["rumore"]} rumore (copie enciclopediche)')
    mal = logica.malevoli()
    if mal:
        yield passo('🛡 Documenti malevoli: ' + logica.elenca([f"{m['id']} ({m['tipo']})" for m in mal])
                    + ': il modello li vede marcati come sospetti, non esegue i loro ordini e non li usa come prove')
    if cron:
        mem = eco.memoria_file(cron)
        yield passo(f'🧵 Memoria: {len([m for m in cron if m["role"] == "user"])} domande precedenti'
                    + (f' · file già emersi: {", ".join(m["id"] for m in mem)}' if mem else ''))
    t1 = time.perf_counter()
    risultati, scartati = eco.ricerca(domanda, cron)
    STAT.segna('ricerca', time.perf_counter() - t1)
    if risultati is not None:
        yield passo('🔎 Ricerca RAG (ID nominati, parole chiave + significato, secondo passaggio): ' +
                    (', '.join(f"{r['id']} ({r['file']})" for r in risultati) if risultati else 'nessun file della storia vicino'))
        if scartati:
            yield passo('🗑 Scartati come rumore (non passati al modello): ' + ', '.join(f"{r['id']} «{r['titolo'][:28]}»" for r in scartati))
        prove = [f"{r['id']} {r['natura']}" + (f" di {r['famiglia']} (×{r['copie_totali']}, valgono 1 fonte)" if r.get('copie_totali', 0) > 1 else '')
                 for r in risultati or [] if r.get('natura')]
        if prove:
            yield passo('🧪 Copie e misure dirette: ' + ' · '.join(prove))
        catena = [f"{c['da']} →{c['parola']}→ {c['a']}" for c in (ind.collegamenti(risultati) if ind and risultati else [])]
        if catena:
            yield passo('🔗 Collegamenti seguiti (codici rari): ' + ' · '.join(catena))
    sql = None
    if database.serve(domanda, eco.prepara_cronologia(cron)):   # Giorno 4: tool SQL sul database della missione
        k = database.scegli_missione(domanda, eco.prepara_cronologia(cron))
        yield passo(f'🗄 La domanda riguarda il database della missione «{database.TITOLI[k]}» '
                    f'({database.MISSIONI[k].percorso().name}): uso il tool SQL (sola lettura)')
        for ev in _agente_sql_con_passi(domanda, cron):
            if ev[0] == 'passo':
                yield passo(ev[1])
            else:
                sql = ev[1]
    ok_g, _ = motori.gemini_utilizzabile()
    pr = motori.motore_principale()
    ok_x = pr in motori.COMPATIBILI and motori.COMPATIBILI[pr].utilizzabile()[0]
    chi = (motori.COMPATIBILI[pr].nome if ok_x else 'Gemini' if ok_g else 'Qwen sulla GPU' if motori.locale_pronto() else 'nessun modello disponibile')
    yield passo(f'🧠 {chi if config.MOSTRA_MOTORE else "Il modello"} legge fascicolo, catalogo, memoria e brani trovati e scrive la risposta')
    testo, info, scrive = '', None, False
    with _LOCK:
        try:
            ultimo_avviso = ''
            for testo, info in eco.rispondi_stream(domanda, cron, ricerca_fatta=(risultati, scartati), sql_fatto=sql):
                if info is None and testo.startswith('⏳'):          # limite gratuito al minuto: si aspetta, non si molla
                    if testo != ultimo_avviso:
                        ultimo_avviso = testo
                        yield passo(testo)
                    continue
                if info is None and not scrive:
                    scrive = True
                    yield passo('🖋 Sto scrivendo…')
        except Exception as e:
            testo, info = f'⚠ {config.NOME} non può rispondere adesso ({type(e).__name__}: {e}).', None
    info = info or {'motore': 'nessuno', 'fonti': [], 'fonti_inesistenti': [], 'secondi': time.perf_counter() - t0}
    motore = info.get('motore', 'nessuno')
    categoria = 'gemini' if motore in ('Gemini', 'Grok', 'Groq', 'Cerebras') else 'gpu' if motore == 'Qwen locale' else None
    if categoria:
        STAT.segna(categoria, info.get('secondi', 0))
    if motore == 'nessuno' and sql:
        yield passo('🛑 Nessun modello ha risposto: nessuna risposta preimpostata; le righe del tool SQL sono nel pannello')
    if info.get('problemi_sql'):
        yield passo('⚠ Controllo dei codici: ' + '; '.join(info['problemi_sql']))
    elif sql and sql.get('query') and not sql.get('errore'):
        yield passo('✅ Codici controllati: la risposta usa solo codici restituiti dal database')
    if info.get('avviso') and config.MOSTRA_MOTORE:
        yield passo(f'↪ Riserva usata: {info["avviso"]}')
    fonti, inventate = info.get('fonti') or [], info.get('fonti_inesistenti') or []
    if info.get('riscritta'):
        yield passo('✂ La prima risposta citava documenti inesistenti: il modello l\'ha riscritta')
    yield passo('⚠ Fonti da controllare: ' + ', '.join(inventate) if inventate else
                ('✅ Fonti verificate: ' + ', '.join(fonti) if fonti else 'ℹ Nessun documento citato'))
    with _LOCK_CHAT:   # nella memoria va la risposta con la riga 📂: eco.memoria_file ritrova così i file emersi
        _CHAT['storia'] += [{'role': 'user', 'content': domanda}, {'role': 'assistant', 'content': testo}]
    pulito = eco._pulisci(testo)
    scrive_nome = (motore if config.MOSTRA_MOTORE else 'il modello') if categoria else (
        'il codice (dal risultato SQL)' if motore == 'codice' else 'nessuno')
    etichetta = ((f'{motore} · RAG' if config.MOSTRA_MOTORE else 'modello + RAG') if categoria else
                 'codice + tool SQL' if motore == 'codice' else 'non disponibile')
    if sql and categoria:
        etichetta += ' + tool SQL'
    r = {'testo': pulito, 'fonti': fonti, 'inventate': inventate, 'via': categoria or ('sql' if motore == 'codice' else 'nessuno'),
         'etichetta': etichetta, 'dettaglio': f"{motore} · {info.get('secondi', 0):.1f} s"}
    if sql:
        r['sql'] = ricorda_sql(database.per_la_pagina(sql))
        r['sql']['problemi'] = info.get('problemi_sql') or []
    try:
        r['rag'] = vista_rag_completa(domanda, pulito, fonti, risultati, scartati, scrive_nome,
                                      ('inventate: ' + ', '.join(inventate)) if inventate else 'nessuna fonte inventata')
    except Exception as e:   # la vista RAG è un extra: non deve mai bloccare la risposta
        r['rag'] = {'errore': str(e)[:120]}
    _ULTIMA_RAG.update(domanda=domanda, fonti=list(fonti), trovati=[x['id'] for x in risultati or []],
                       scartati=[x['id'] for x in scartati or []], vettore=None)   # per la RAG View 3D (📚)
    r.update(totale=time.perf_counter() - t0, passi=passi)
    yield 'fine', r   # il diario lo scrive già eco.py (con i file recuperati e la memoria)


_ULTIMA_RAG = {}                     # l'ultima domanda della chat e le sue fonti: la RAG View 3D le mette nella mappa
_ULTIME_SQL = {'lista': []}          # gli ultimi esiti del tool SQL: la pagina dello schema E/R li evidenzia


def ricorda_sql(esito):
    esito = dict(esito or {})
    esito['n'] = (max([x['n'] for x in _ULTIME_SQL['lista']] or [0]) + 1)
    esito['ora'] = time.strftime('%H:%M:%S')
    _ULTIME_SQL['lista'] = (_ULTIME_SQL['lista'] + [esito])[-30:]
    return esito


def _agente_sql_con_passi(domanda, cron):
    """database.agente in un thread: i suoi passi arrivano alla pagina mentre succedono. Produce ('passo', testo)
    e alla fine ('esito', dict). Una domanda alla volta sulla GPU (_LOCK), come per le risposte."""
    import queue
    coda = queue.Queue()

    def lavora():
        try:
            with _LOCK:
                esito = database.agente(domanda, eco.prepara_cronologia(cron), lambda t: coda.put(('passo', t)))
        except Exception as e:
            esito = {'domanda': domanda, 'errore': f'tool SQL non riuscito ({type(e).__name__}: {e})'[:200], 'origine': None,
                     'query': None, 'tentativi': [], 'indizi': {}, 'data_missione': database.data_missione()}
        coda.put(('esito', esito))
    threading.Thread(target=lavora, daemon=True).start()
    while True:
        ev = coda.get()
        yield ev
        if ev[0] == 'esito':
            return


def _rispondi_chiacchiera(domanda, cron, passo, passi, t0):
    """Saluti e chiacchiere: niente fascicolo, niente ricerca RAG; il modello risponde con il prompt corto."""
    yield passo('💬 Saluto o chiacchiera: niente ricerca nell\'archivio, risposta diretta')
    testo, info = '', None
    with _LOCK:
        try:
            for testo, info in eco.rispondi_stream(domanda, cron, ricerca_fatta=([], [])):
                pass
        except Exception as e:
            testo, info = f'⚠ {config.NOME} non può rispondere adesso ({type(e).__name__}: {e}).', None
    info = info or {'motore': 'nessuno', 'fonti': [], 'secondi': time.perf_counter() - t0}
    motore = info.get('motore', 'nessuno')
    categoria = 'gemini' if motore in ('Gemini', 'Grok', 'Groq', 'Cerebras') else 'gpu' if motore == 'Qwen locale' else None
    if categoria:
        STAT.segna(categoria, info.get('secondi', 0))
    yield passo('ℹ Nessun documento citato')
    with _LOCK_CHAT:
        _CHAT['storia'] += [{'role': 'user', 'content': domanda}, {'role': 'assistant', 'content': testo}]
    etichetta = ((f'{motore} · conversazione' if config.MOSTRA_MOTORE else 'conversazione') if categoria
                 else 'non disponibile')
    r = {'testo': eco._pulisci(testo), 'fonti': [], 'inventate': [], 'via': categoria or 'nessuno',
         'etichetta': etichetta, 'dettaglio': f"{motore} · {info.get('secondi', 0):.1f} s",
         'rag': {'parole': [], 'documenti': [], 'cercato': False, 'totale': 0, 'citati': [], 'malevoli': [],
                 'scrive': 'il modello', 'verifica': 'nessuna fonte da controllare', 'ambito': 'conversazione'},
         'totale': time.perf_counter() - t0, 'passi': passi}
    yield 'fine', r


def scoperte_md():
    """Analisi incrociata fatta nel codice (istantanea, nessuna invenzione possibile)."""
    fr = logica.carica()
    trappole = logica._cache.get('trappole', [])
    fatti = [x for x in fr if not logica.lacuna(x[1]) and not logica.META.search(x[1])]
    lacune = [x for x in fr if logica.lacuna(x[1])]
    citaz = [x for x in fr if logica.CITAZ.search(x[1])]
    riga = lambda x: f'- {x[1]} [{x[0]}]'
    out = ['### Cosa sappiamo'] + ([riga(x) for x in fatti] or ['- Nessun elemento nei documenti.'])
    out += ['', '### Persone, luoghi e fonti radio'] + [f"- **{v['chi']}** · {v['zona']} [{v['id']}]" for v in voci()]
    out += ['', '### Parole testuali dei testimoni'] + ([riga(x) for x in citaz] or ['- Nessuna citazione diretta.'])
    out += ['', '### Cosa non è provato o manca'] + ([riga(x) for x in lacune] or ['- Nessun vuoto segnalato.'])
    ev = logica.eventi()
    if ev:
        out += ['', '### Cronologia dai registri (orari)'] + [f'- **{t}** · {f} [{i}]' for _, t, i, f, _ in ev]
    mal = logica.malevoli()
    out += ['', '### Documenti malevoli (letti, mai eseguiti, mai usati come prova)']
    out += [f"- **{m['id']}** «{m['titolo']}» · {m['tipo']}: {m['motivo']} [{m['id']}]" for m in mal] or ['- Nessuno rilevato.']
    if mal:
        out += [f"- Esclusi dalle prove: {', '.join(m['id'] for m in mal)}"]
    ind = rag.indice() if rag.file_archivio() else None
    if ind:
        out += ['', '### Archivio digitale (Giorno 3): file della storia trovati dalla scansione', f'_{rag.descrizione()}_']
        out += [f"- **{d['id']}** «{d['titolo']}» ({d['file']}): {d['testo']} [{d['id']}]" for d in ind.catalogo()
                if ind.raccolta_piccola(d.get('raccolta') or 'archivio')]
        for nome in ind.raccolte:
            if not ind.raccolta_piccola(nome):
                out += ['', f'### {rag.nome_raccolta(nome).capitalize()}'] + [r.strip() if r.strip().startswith('-') else
                                                                            '- ' + r.strip() for r in rag.riassunto_raccolta(ind, nome)]
    if database.disponibile():
        st = database.struttura()
        out += ['', f'### Database della missione «{st.get("titolo_missione", "")}» (Giorno 4 · tool SQL di sola lettura)',
                f"- File {st['file']}: " + ', '.join(f"{t['nome']}{' = ' + t['entita'] if t.get('entita') else ''} {t['righe']} righe"
                                                    for t in st['tabelle']) + f" · missione: {st['data_missione']}"]
        if st.get('missione') == 'lete':
            v = database.attiva().verifica()
            out += [f"- Verifica del codice: {v['sintesi']}",
                    '- Esclusi: ' + '; '.join(f"{e['chi']} ({e['motivo']})" for e in v['esclusi'][:8])]
        else:
            out += ['- Persona, deposito, settore e pratica arrivano dal dossier; il permesso deve essere attivo e non scaduto.']
        out += ['- Schema E/R, mappa delle tabelle, verifica e console: pulsante «🗄 Schema E/R» in alto.']
    out += ['', '### Prossime domande da fare a ECO', '- Chi sono i due operatori autorizzati per il varco V-38? Terminale e chiave?',
            '- Mostra la mappa delle 14 tabelle', '- Cosa dice il dossier sbloccato? Chi ha ordinato di proseguire nonostante l\'allarme?',
            '- Perché la centrale manda ancora le persone nei rifugi?', '- Qual è il codice della nostra autorizzazione?', '- Cosa è successo nei rifugi?', '- Chi ha cercato di fermare il progetto?',
            '- Persona, deposito, settore e pratica?', '- Dove e quando è iniziato il primo focolaio?', '- Quali sono le ipotesi?',
            '- Ci sono documenti malevoli?', '- Di chi ti fidi?']
    return '\n'.join(out)


def report_markdown():
    righe = [f'# Squadra 3 — Investigatore {config.NOME}', f'_{config.OPERAZIONE} · Giorno {config.GIORNO} · {dt.date.today():%d/%m/%Y}_', '',
             '## Documenti', '']
    righe += [f"- **{v['id']}** — {v['titolo']} ({v['chi']}, {v['zona']})" for v in voci()]
    righe += ['', '## Domande e risposte', '']
    try:
        for r in config.DIARIO.read_text(encoding='utf-8').strip().splitlines():
            x = json.loads(r)
            righe += [f"**D:** {x['domanda']}", '', f"**R:** {x['risposta']}", '']
            if x.get('sql'):
                righe += ['```sql', x['sql'], '```', f"_Righe: {json.dumps(x.get('sql_righe'), ensure_ascii=False)}_", '']
            righe += [
                      f"_Fonti: {', '.join(x.get('fonti') or []) or 'nessuna'} · {round((x.get('secondi') or 0) * 1000)} ms · {x.get('motore') or ''}_",
                      '', '---', '']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return '\n'.join(righe)


_TESSERA = re.compile(r'(?:^|/)tessere/(\d{1,2})/(\d{1,6})/(\d{1,6})\.webp$')


def importa_mappa(dati):
    """mappa.zip caricato dall'Archivio: le tessere (…/tessere/z/x/y.webp) vanno in mappa/tessere. Niente altro viene
    estratto e i percorsi sono ricostruiti dai numeri (nessun file può finire fuori dalla cartella)."""
    scritte = 0
    with zipfile.ZipFile(io.BytesIO(dati)) as z:
        for v in z.infolist():
            m = _TESSERA.search(v.filename.replace('\\', '/'))
            if not m or v.is_dir():
                continue
            dest = TESSERE / m.group(1) / m.group(2) / f'{m.group(3)}.webp'
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(v))
            scritte += 1
    return [f'mappa stradale: {scritte} tessere'] if scritte else []


# ─────────────────────────── server web ───────────────────────────
def crea_app():
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
    from starlette.routing import Route

    async def home(req):
        return HTMLResponse(PAGINA.read_text(encoding='utf-8'), headers={'Cache-Control': 'no-store'})

    async def stato(req):
        return JSONResponse(stato_json())

    async def api_motori(req):
        return JSONResponse(motori_json())

    async def chiedi(req):
        corpo = await req.json()
        domanda = str(corpo.get('domanda', ''))[:2000]
        loop = asyncio.get_running_loop()
        coda: asyncio.Queue = asyncio.Queue()

        def lavora():   # la GPU lavora in un thread: la pagina riceve i passi mentre succedono
            try:
                for ev in rispondi_con_passi(domanda):
                    loop.call_soon_threadsafe(coda.put_nowait, ev)
            except Exception as e:
                loop.call_soon_threadsafe(coda.put_nowait, ('errore', str(e)[:200]))
            loop.call_soon_threadsafe(coda.put_nowait, None)

        threading.Thread(target=lavora, daemon=True).start()

        async def flusso():
            passi = []
            while True:
                ev = await coda.get()
                if ev is None:
                    return
                tipo, val = ev
                if tipo == 'passo':
                    passi.append(val)
                    yield 'data: ' + json.dumps({'tipo': 'passo', 'passi': passi}, ensure_ascii=False) + '\n\n'
                elif tipo == 'fine':
                    yield 'data: ' + json.dumps({'tipo': 'fine', **val}, ensure_ascii=False) + '\n\n'
                else:
                    yield 'data: ' + json.dumps({'tipo': 'errore', 'msg': val}, ensure_ascii=False) + '\n\n'

        return StreamingResponse(flusso(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    async def nuova(req):   # ↺ nuova conversazione (anche quando si apre la pagina): ECO dimentica il discorso
        nuova_conversazione()
        return JSONResponse({'ok': True})

    async def scoperte(req):
        t0 = time.perf_counter()
        return JSONResponse({'testo': scoperte_md(), 'motore': 'regole sulle fonti', 'secondi': time.perf_counter() - t0})

    async def carica(req):   # ZIP o .txt ricevuti: archivio.importa li mette nella cartella giusta (fascicolo o archivio)
        from pathlib import Path
        form = await req.form()
        config.DATI.mkdir(parents=True, exist_ok=True)
        nuovi, errori = [], []
        for _, f in form.multi_items():
            if not getattr(f, 'filename', None):
                continue
            nome, dati = Path(f.filename).name, await f.read()
            if nome.lower().endswith(('.zip', '.txt') + archivio.FORMATI_DATABASE + archivio.FORMATI_FOGLIO):
                try:
                    mappa = importa_mappa(dati) if nome.lower().endswith('.zip') else []
                    nuovi += mappa or archivio.importa(nome, dati)   # mappa.zip: solo tessere, nessun documento
                except (zipfile.BadZipFile, UnicodeDecodeError, ValueError) as e:
                    errori.append(f'{nome}: {e}')
        if any('archivio' in n for n in nuovi):
            await asyncio.get_running_loop().run_in_executor(None, rag.prepara)
        for n in nuovi:   # un database appena caricato diventa la missione in corso
            nome = n.replace('\\', '/').rsplit('/', 1)[-1].lower()
            if n.replace('\\', '/').startswith('database/') and nome.endswith(archivio.FORMATI_DATABASE):
                database.usa('lete' if nome.startswith('archivio_recuperato') else 'varco', salva=True)
        return JSONResponse({'caricati': nuovi, 'errori': errori, **stato_json()})

    async def tessera(req):   # la mappa stradale arriva dal disco, non da internet
        z, x, y = req.path_params['z'], req.path_params['x'], req.path_params['y']
        base = cartella_tessere()
        f = (base or TESSERE) / str(z) / str(x) / f'{y}.webp'
        if not f.is_file():
            return Response(status_code=404)
        return Response(f.read_bytes(), media_type='image/webp', headers={'Cache-Control': 'public, max-age=86400'})

    async def registro(req):
        return Response(report_markdown(), media_type='text/markdown; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename=registro_consegna.md'})

    async def schema_er(req):   # SCHEMA E/R: pagina dedicata al database degli accessi (come la RAG View)
        f = config.CARTELLA / 'schema_er.html'
        if not f.exists():
            return HTMLResponse('<p>schema_er.html non trovato accanto a web.py.</p>', status_code=404)
        return HTMLResponse(f.read_text(encoding='utf-8'), headers={'Cache-Control': 'no-store'})

    async def api_chiave(req):   # ⚙ Motori: la chiave Groq (gratis) o Gemini incollata nell'interfaccia → chiavi.txt
        corpo = await req.json()
        servizio = str(corpo.get('servizio', 'groq')).lower()
        chiave = motori.pulisci_chiave(str(corpo.get('chiave', '')))[:200]
        regole = {'groq': ('GROQ_API_KEY', 'gsk_'), 'cerebras': ('CEREBRAS_API_KEY', 'csk-'), 'gemini': ('GEMINI_API_KEY', 'AIza')}
        if servizio not in regole:
            return JSONResponse({'ok': False, 'errore': 'servizio sconosciuto'}, status_code=400)
        var, inizio = regole[servizio]
        if not chiave.startswith(inizio) or len(chiave) < 20:
            return JSONResponse({'ok': False, 'errore': f'La chiave {servizio.title()} inizia con «{inizio}»: controllate di averla copiata intera.'},
                                status_code=400)
        motori.salva_chiave(var, chiave)
        prova = ''
        if servizio == 'gemini':
            try:
                mod = await asyncio.get_running_loop().run_in_executor(None, motori.modelli_flash_lite)
                prova = (f'Chiave valida: Gemini scrive le risposte ({config.MODELLO_GEMINI}); '
                         f'{len(mod)} modelli Flash-Lite disponibili, ognuno con la sua quota gratuita.')
            except Exception as e:
                return JSONResponse({'ok': False, 'errore': 'Chiave salvata ma Google non la accetta: ' + motori.spiega_errore_gemini(e)})
        if servizio in motori.COMPATIBILI:
            mot = motori.COMPATIBILI[servizio]
            try:
                mod = await asyncio.get_running_loop().run_in_executor(None, mot.modelli)
                prova = f'Chiave valida: {len(mod)} modelli disponibili, ECO usa {mot.modello()}.'
            except Exception as e:
                return JSONResponse({'ok': False, 'errore': f'Chiave salvata ma {mot.nome} non la accetta: ' + mot.spiega(e)})
        return JSONResponse({'ok': True, 'messaggio': prova or 'Chiave salvata.', 'motori': motori_json()})

    async def db_struttura(req):
        k = req.query_params.get('missione') or None
        return JSONResponse(await asyncio.get_running_loop().run_in_executor(None, database.struttura, k))

    async def db_missione(req):   # missione in corso e parametri (la centrale può aggiornarli: prova finale)
        corpo = await req.json() if req.method == 'POST' else {}
        risposta = {}
        try:
            if corpo.get('missione'):
                database.usa(corpo['missione'], salva=True)
            if database.chiave_attiva() == 'lete' and (corpo.get('parametri') or corpo.get('ripristina')):
                L = database.attiva()
                prima = L.verifica()
                if corpo.get('ripristina'):
                    L.ripristina_parametri()
                    cambi = {}
                else:
                    _, cambi = L.salva_parametri(corpo['parametri'], origine=str(corpo.get('origine') or 'pannello (centrale)')[:40])
                dopo = L.verifica()
                L.registra(dopo, 'pannello')
                risposta.update(cambi=cambi, verifica=dopo, confronto=L.confronta(prima, dopo))
        except ValueError as e:
            return JSONResponse({'errore': str(e), **database_json()}, status_code=400)
        out = database_json()
        if out.get('missione') == 'lete':
            L = database.attiva()
            out.update(canali=L.canali(), varchi=L.varchi(), iniziali=L.parametri_iniziali())
        out['esempi'] = database.esempi_console()
        return JSONResponse({**out, **risposta})

    async def db_verifica(req):   # «Ripeti i controlli»: tutte le regole con i parametri dati (o quelli in uso)
        corpo = await req.json() if req.method == 'POST' else {}
        if database.chiave_attiva() != 'lete':
            return JSONResponse({'errore': 'La verifica completa riguarda la missione «Il primo respiro».'}, status_code=400)
        L = database.attiva()
        try:
            par = L.valida_parametri({**L.parametri(), **(corpo.get('parametri') or {})})
        except ValueError as e:
            return JSONResponse({'errore': str(e)}, status_code=400)
        v = await asyncio.get_running_loop().run_in_executor(None, L.verifica, par)
        if corpo.get('registra', True):   # l'apertura della pagina non riempie lo storico
            L.registra(v, 'pannello' + (' (ipotesi)' if par != L.valida_parametri(L.parametri()) else ''))
        out = {'verifica': v}
        if par != L.valida_parametri(L.parametri()):
            out['confronto'] = L.confronta(L.verifica(), v)
        return JSONResponse(out)

    async def db_storico(req):
        if database.chiave_attiva() != 'lete':
            return JSONResponse({'lista': []})
        return JSONResponse({'lista': database.attiva().storico()})

    async def db_mappa(req):   # la mappa delle tabelle da consegnare (Markdown)
        return Response(mappa_markdown(), media_type='text/markdown; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename=mappa_tabelle.md'})

    async def db_esempi(req):
        t = req.query_params.get('t', '')
        return JSONResponse(database.esempi(t))

    async def db_query(req):   # console della pagina E/R: la query scritta a mano passa dallo stesso tool di sola lettura
        corpo = await req.json()
        q = str(corpo.get('sql', ''))[:4000]
        prima = database.impronta()
        r = await asyncio.get_running_loop().run_in_executor(None, database.interroga_database, q)
        r['integro'] = prima == database.impronta()
        return JSONResponse(r)

    async def db_ultime(req):
        return JSONResponse({'lista': _ULTIME_SQL['lista'][::-1]})

    async def rag3d(req):   # RAG View 3D (rag3d.html, creata da crea_rag3d.py): si apre anche da qui, non solo con doppio clic
        from starlette.responses import FileResponse, HTMLResponse
        f = config.CARTELLA / 'rag3d.html'
        if not f.exists():
            return HTMLResponse('<p>rag3d.html non c\'è ancora: eseguite <code>python crea_rag3d.py</code>.</p>', status_code=404)
        return FileResponse(f, media_type='text/html')

    def _vettore(testo):   # la domanda nello stesso spazio degli embedding (None se il modello non c'è)
        try:
            v = rag.codifica([testo])
            return None if v is None else [round(float(x), 5) for x in v[0]]
        except Exception:
            return None

    async def rag3d_ultima(req):   # la RAG View 3D chiede l'ultima domanda della chat: stella + fonti cerchiate
        d = dict(_ULTIMA_RAG)
        if d.get('domanda') and d.get('vettore') is None:
            d['vettore'] = _ULTIMA_RAG['vettore'] = await asyncio.get_running_loop().run_in_executor(None, _vettore, d['domanda'])
        return JSONResponse(d)

    async def rag3d_cerca(req):    # una domanda scritta nella mappa: solo la ricerca RAG, il modello non viene chiamato
        q = req.query_params.get('q', '').strip()[:400]
        if not q:
            return JSONResponse({'errore': 'domanda vuota'}, status_code=400)

        def lavora():
            ris, scart = eco.ricerca(q, [])
            return {'domanda': q, 'trovati': [x['id'] for x in ris or []], 'scartati': [x['id'] for x in scart or []],
                    'vettore': _vettore(q)}
        return JSONResponse(await asyncio.get_running_loop().run_in_executor(None, lavora))

    return Starlette(routes=[
        Route('/', home), Route('/api/stato', stato), Route('/api/motori', api_motori),
        Route('/api/chiedi', chiedi, methods=['POST']), Route('/api/scoperte', scoperte),
        Route('/api/nuova', nuova, methods=['POST']), Route('/api/chiave', api_chiave, methods=['POST']),
        Route('/api/carica', carica, methods=['POST']), Route('/api/registro', registro),
        Route('/tessere/{z:int}/{x:int}/{y:int}.webp', tessera), Route('/rag3d', rag3d),
        Route('/api/rag3d/ultima', rag3d_ultima), Route('/api/rag3d/cerca', rag3d_cerca),
        Route('/schema-er', schema_er), Route('/api/db/struttura', db_struttura), Route('/api/db/esempi', db_esempi),
        Route('/api/db/query', db_query, methods=['POST']), Route('/api/db/ultime', db_ultime),
        Route('/api/db/missione', db_missione, methods=['GET', 'POST']), Route('/api/db/verifica', db_verifica, methods=['GET', 'POST']),
        Route('/api/db/storico', db_storico), Route('/api/db/mappa.md', db_mappa)])


def mappa_markdown():
    """La mappa delle tabelle con significato, chiavi, relazioni e prove; poi la verifica con le esclusioni."""
    st = database.struttura()
    if not st.get('disponibile'):
        return '# Database non caricato\n'
    r = [f"# Mappa delle tabelle · {st.get('titolo') or st.get('titolo_missione')}", '',
         f"File `{st['file']}` · impronta SHA-256 `{st['impronta']}…` · generata il {dt.datetime.now():%d/%m/%Y %H:%M}", '',
         '| Tabella | Entità (ipotesi) | Righe | Significato | Colonne | Prove |', '|---|---|---|---|---|---|']
    for t in st['tabelle']:
        cols = '<br>'.join(f"`{c['nome']}`{' **PK**' if c['pk'] else ''}{' FK→' + c['fk'] if c['fk'] else ''}: {c.get('descrizione') or c['tipo']}"
                           + (f" ({', '.join(f'{v} ×{k}' for v, k in c['valori'])})" if c.get('valori') else
                              f" ({c.get('distinti', '?')} distinti" + (f", {c['nulli']} NULL" if c.get('nulli') else '') + ')')
                           for c in t['colonne'])
        r.append(f"| `{t['nome']}` | {t.get('entita', '')}{' (fonte storica)' if t.get('storica') else ''} | {t['righe']} | "
                 f"{t.get('descrizione', '')} | {cols} | {t.get('perche', '')} |")
    r += ['', '## Relazioni (controllo dei riferimenti su tutte le righe)', '',
          '| Chiave esterna | → | Relazione | Cardinalità (padre : figlio) | Prova |', '|---|---|---|---|---|']
    for x in st['relazioni']:
        r.append(f"| `{x['chiave']}` | `{x['riferisce']}` | {x['nome']} | {x.get('lato_padre')} : {x.get('lato_figlio')} | "
                 f"{'✅ ' if x.get('verificata') else '⚠ '}{x.get('prova', '')} |")
    if st.get('missione') == 'lete':
        L = database.attiva()
        v = L.verifica()
        r += ['', '## Verifica con i parametri in uso', '', f"**{v['sintesi']}**", '']
        if v['soluzioni']:
            r += ['| Squadra | SANITARIO | SICUREZZA | Terminale | Chiave |', '|---|---|---|---|---|']
            r += [f"| {s['squadra']} | {s['sanitario']} ({s['badge_sanitario']}) | {s['sicurezza']} ({s['badge_sicurezza']}) | "
                  f"{s['canale']} ({s['terminale']}) | `{s['codice']}` |" for s in v['soluzioni']]
        r += ['', '### Candidati esclusi', '', '| Tipo | Chi | Motivo | Regola |', '|---|---|---|---|']
        r += [f"| {e['tipo']} | {e['chi']} | {e['motivo']} | {e['regola']} |" for e in v['esclusi']]
        r += ['', '### Le query della verifica (eseguite dal tool di sola lettura)', '']
        for pq in v['passi']:
            r += [f"**{pq['titolo']}** — {pq['spiegazione']} ({len(pq.get('righe') or [])} righe)", '', '```sql', pq['query'], '```', '']
    return '\n'.join(r) + '\n'


_SERVER = {'srv': None}


def avvia_in_sottofondo(porta=None, host='0.0.0.0'):
    """Per Colab/Jupyter: avvia il server in un thread (la cella non resta bloccata). Rieseguibile."""
    import uvicorn
    porta = porta or config.PORTA
    if _SERVER['srv'] is not None:   # cella rieseguita: ferma il server precedente
        _SERVER['srv'].should_exit = True
        time.sleep(1.0)
    srv = uvicorn.Server(uvicorn.Config(crea_app(), host=host, port=porta, log_level='warning'))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(50):
        if srv.started:
            break
        time.sleep(0.1)
    _SERVER['srv'] = srv
    return srv
