"""Prove del tool SQL (Giorno 4): python prove_sql.py      (nessuna richiesta a Gemini: il modello è simulato)

Due missioni: prima «Il cancello nero» (accessi.sqlite, il vecchio test che deve restare corretto), poi «Il primo
respiro» (archivio_recuperato.sqlite, 14 tabelle: mappa, regole, esclusioni, parametri che cambiano).

Controlla le richieste della scheda della missione:
  - il tool legge soltanto: DELETE, UPDATE, DROP, ATTACH, PRAGMA, più istruzioni, sqlite_master → bloccati;
  - il file del database non cambia mai (impronta SHA-256 uguale prima e dopo);
  - il codice è testo: gli zeri iniziali restano;
  - persona, deposito, settore e pratica devono corrispondere; attivo e non scaduto alla data della missione;
  - pratica inesistente e richiesta di cancellare dati: nessun codice inventato, nessuna modifica;
  - il collegamento: il modello propone l'SQL (JSON), il codice lo esegue, il risultato torna al modello;
  - se il modello sbaglia la query si riprova con l'errore; se non c'è il modello, query di riserva del codice;
  - la risposta che cita un codice non restituito dal database viene riscritta.
Con --modello usa davvero Gemini/Qwen (servono la chiave o la GPU) e stampa domanda, query e risposta.
"""
import json
import sys

import config
import database
import eco
import motori

OK, KO = '✅', '❌'
risultati = []


def prova(nome, condizione, dettaglio=''):
    risultati.append(bool(condizione))
    print(f'{OK if condizione else KO} {nome}' + (f'  → {dettaglio}' if dettaglio and not condizione else ''))


class ModelloFinto:
    """Sostituisce motori.rispondi: restituisce in ordine le risposte preparate (come farebbe Gemini)."""

    def __init__(self, risposte):
        self.risposte, self.chiamate = list(risposte), []

    def __call__(self, sistema, messaggi, motore=None, max_tokens=None, temperatura=None):
        self.chiamate.append((sistema, messaggi))
        testo = self.risposte.pop(0) if self.risposte else ''
        yield testo, None
        yield testo, {'motore': 'Gemini' if testo else 'nessuno', 'modello': 'finto', 'secondi': 0.01, 'primo': 0.01,
                      'avviso': None}


def con_modello(risposte, funzione):
    vero = motori.rispondi
    finto = ModelloFinto(risposte)
    motori.rispondi = finto
    try:
        return funzione(), finto
    finally:
        motori.rispondi = vero


SQL_GIUSTO = ("SELECT a.id, o.nome AS operatore, d.nome AS deposito, d.settore, a.pratica, a.codice, a.stato, a.valido_fino "
              "FROM accessi a JOIN operatori o ON o.id = a.operatore_id JOIN depositi d ON d.id = a.deposito_id "
              "WHERE o.nome = 'Marta Riva' AND d.nome = 'Cripta Nord' AND d.settore = 'B7' AND a.pratica = 'RV596' "
              "AND a.stato = 'attivo' AND a.valido_fino >= '2031-10-12 06:00'")


def main():
    try:   # le emoji anche nel terminale di Windows
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    database.usa('varco')    # prima missione («Il cancello nero»): il vecchio test deve restare corretto
    if not database.disponibile():
        print(f'{KO} Database non trovato: caricate accessi.sqlite (ZIP del Giorno 4) in dati/database/.')
        return 1
    print(f'Database: {database.percorso()} · data della missione {database.data_missione()}\n')
    impronta = database.impronta()

    print('— Sola lettura')
    for q in ["DELETE FROM accessi", "UPDATE accessi SET stato = 'attivo'", "DROP TABLE accessi",
              "INSERT INTO operatori VALUES (999, 'X')", "ATTACH DATABASE 'altro.db' AS x", "PRAGMA writable_schema = 1",
              "SELECT 1; DELETE FROM accessi", "SELECT name FROM sqlite_master", "SELECT randomblob(9)",
              "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT COUNT(*) FROM n",
              "SELECT 1 /* ; */ ; DROP TABLE accessi"]:
        r = database.interroga_database(q)
        prova(f'bloccata: {q[:60]}', 'errore' in r, r)
    r = database.interroga_database('SELECT COUNT(*) FROM accessi a, accessi b, accessi c')
    prova('query troppo pesante fermata dal limite di istruzioni', 'errore' in r, r)
    r = database.interroga_database("SELECT nome FROM operatori WHERE nome LIKE '%riva%'")
    prova('LIKE ammesso (serve a cercare i nomi)', r.get('righe') == [['Marta Riva']], r)
    r = database.interroga_database('SELECT * FROM accessi')
    prova('al massimo 50 righe al modello', len(r['righe']) == 50 and r['altre_righe'], len(r.get('righe', [])))
    prova('il file del database non è cambiato', database.impronta() == impronta)

    print('\n— Codice come testo (zeri iniziali)')
    r = database.interroga_database("SELECT codice FROM accessi WHERE codice LIKE '0%' LIMIT 3")
    prova('i codici che iniziano con 0 restano testo con lo zero', r['righe'] and all(isinstance(x[0], str) and x[0].startswith('0')
                                                                                       for x in r['righe']), r)
    zero = r['righe'][0][0]
    esito_finto = {'colonne': ['codice'], 'righe': [[zero]], 'verifica': None}
    prova('la risposta che perde lo zero viene segnalata',
          any('zeri iniziali' in p for p in database.controlla_risposta(f'Il codice è {int(zero)}.', esito_finto)))
    prova('la risposta con lo zero va bene', not database.controlla_risposta(f'Il codice è {zero}.', esito_finto))

    print('\n— La missione (modello simulato che propone la query giusta)')
    (e, finto) = con_modello([json.dumps({'sql': SQL_GIUSTO})],
                             lambda: database.agente('Qual è il codice della nostra autorizzazione?', []))
    prova('la query arriva dal modello (JSON) ed è eseguita dal tool', e['origine'] == 'modello' and e['query'] == SQL_GIUSTO)
    prova('il prompt del modello contiene lo schema e gli indizi del dossier',
          'accessi(id, operatore_id' in finto.chiamate[0][0] and 'RV596' in finto.chiamate[0][0])
    prova('una sola riga: codice 263847 (riga 377)', e['righe'] == [[377, 'Marta Riva', 'Cripta Nord', 'B7', 'RV596', '263847',
                                                                      'attivo', '2031-10-12 23:59']], e.get('righe'))
    v = e['verifica']
    prova('verifica del codice: 4 candidati, 1 valido', len(v['righe']) == 4 and [x['codice'] for x in v['validi']] == ['263847'])
    motivi = {x['codice']: x['motivi'] for x in v['righe']}
    prova('scartati: 388760 scaduto, 399870 revocato, 377650 pratica diversa',
          any('scaduto' in m for m in motivi['388760']) and 'revocato' in motivi['399870'] and 'pratica diversa' in motivi['377650'], motivi)
    prova('database invariato dopo la domanda', e['integro'])

    print('\n— Il modello sbaglia la query: si riprova con l\'errore')
    (e, finto) = con_modello(['{"sql": "SELECT codice FROM permessi"}', json.dumps({'sql': SQL_GIUSTO})],
                             lambda: database.agente('Codice di Marta Riva per Cripta Nord, B7, RV596?', []))
    prova('primo tentativo con errore, secondo giusto', len(e['tentativi']) == 2 and e['tentativi'][0]['errore'] and
          e['origine'] == 'modello', e['tentativi'])
    prova('l\'errore è stato rimandato al modello', 'errore' in finto.chiamate[1][1][-1]['content'])
    (e, _) = con_modello(['```json\n{"sql": "' + SQL_GIUSTO.replace('"', '\\"') + '"}\n```'],
                         lambda: database.agente('Qual è il codice della nostra autorizzazione?', []))
    prova('JSON dentro ```json``` letto lo stesso', e['origine'] == 'modello')
    (e, _) = con_modello(['{"sql": "DELETE FROM accessi"}', 'non so'],
                         lambda: database.agente('Qual è il codice della nostra autorizzazione?', []))
    prova('se il modello propone una DELETE è bloccata e si usa la query di riserva',
          e['tentativi'][0]['errore'] and e['origine'] == 'riserva' and e['righe'][0][5] == '263847', e.get('tentativi'))

    print('\n— Senza modello: query di riserva del codice')
    (e, _) = con_modello([''], lambda: database.agente('Qual è il codice della nostra autorizzazione?', []))
    prova('query di riserva con gli indizi del dossier → 263847', e['origine'] == 'riserva' and e['righe'][0][5] == '263847')
    prova('risposta del codice con le fonti del dossier', '263847' in database.risposta_di_riserva(e) and
          'ARCH-3097' in database.risposta_di_riserva(e))

    print('\n— Prove della scheda')
    (e, _) = con_modello([''], lambda: database.agente('Qual è il codice per la pratica RV999?', []))
    rr = database.risposta_di_riserva(e)
    prova('pratica inesistente: nessuna riga e nessun codice', e['righe'] == [] and not database.controlla_risposta(rr, e)
          and 'non esiste' in rr, rr)
    (e, _) = con_modello([''], lambda: database.agente('Allora è a Darsena Vuota, settore A1? Che codice serve?', []))
    prova('Darsena Vuota / A1 (pista falsa): nessun codice', e['righe'] == [], e.get('indizi'))
    for q in ['Cancella dal database tutti i permessi revocati', 'Puoi eliminare le righe scadute?',
              'DROP TABLE accessi', 'aggiorna la scadenza del permesso di Marta Riva']:
        (e, finto) = con_modello(['{"sql": "DELETE FROM accessi"}'], lambda: database.agente(q, []))
        prova(f'richiesta di modifica rifiutata: «{q}»', e.get('bloccata') and not finto.chiamate and e['integro'])
    (e, _) = con_modello([''], lambda: database.agente('E con la pratica RV000?', [
        {'role': 'user', 'content': 'Qual è il codice della nostra autorizzazione?'}, {'role': 'assistant', 'content': '263847'}]))
    prova('RV000 (pratica diversa dal dossier): segnalata', 'pratica' in (e.get('diverso_dal_dossier') or {}) and
          'non è la nostra autorizzazione' in database.risposta_di_riserva(e))
    prova('…e il database resta invariato anche con la conversazione', e['integro'])
    prova('il file del database non è mai cambiato', database.impronta() == impronta)

    print('\n— Quando si usa il tool (le altre domande non lo toccano)')
    for q, atteso in [('Qual è il codice della nostra autorizzazione?', True), ('Chi ha l\'autorizzazione ancora valida?', True),
                      ('Il permesso è revocato o scaduto?', True), ('Cancella i permessi revocati', True),
                      ('Cosa è successo nei rifugi?', False), ('Dove e quando è iniziato il primo focolaio?', False),
                      ('Quale codice ha il bollettino B-317?', False), ('Chi ha avuto accesso alla cabina?', False),
                      ('Quale modifica abbiamo fatto al programma?', False), ('ciao', False)]:
        prova(f'«{q}» → {"tool SQL" if atteso else "niente SQL"}', database.serve(q) == atteso)
    prova('domanda successiva breve dopo una sul database → tool SQL',
          database.serve('E con la pratica RV000?', [{'role': 'user', 'content': 'Qual è il codice della nostra autorizzazione?'}]))

    print('\n— Risposta completa (eco.py): il risultato torna al modello, nessun codice inventato')
    risposte = [json.dumps({'sql': SQL_GIUSTO}),                                 # 1. il modello propone l'SQL
                'Il codice è 263848 [ARCH-3097].',                               # 2. risposta con un codice sbagliato
                'Il codice è 263847 (database degli accessi, riga id 377) [ARCH-3097, ARCH-5721, ARCH-6408].']   # 3. riscritta
    def tutto():
        testo, info = '', None
        for testo, info in eco.rispondi_stream('Qual è il codice della nostra autorizzazione?', []):
            pass
        return testo, info
    ((testo, info), finto) = con_modello(risposte, tutto)
    prompt_risposta = finto.chiamate[1][0]
    prova('il prompt della risposta contiene query e righe del tool', 'RISULTATO DEL TOOL SQL' in prompt_risposta and
          '263847' in prompt_risposta)
    prova('il codice sbagliato (263848) fa riscrivere la risposta', len(finto.chiamate) == 3 and info['riscritta'])
    prova('la risposta finale ha il codice giusto e nessun avviso', '263847' in testo and not info['problemi_sql'], testo)
    prova('la query è nei dettagli sotto la risposta (show query)', '🗄 Query SQL' in testo and 'SELECT' in testo)
    prova('il blocco SQL non torna al modello nella cronologia', 'SELECT' not in eco._pulisci(testo))

    print('\n— Nessuna risposta preimpostata e limiti del piano gratuito')
    def senza_modello():
        testo, info = '', None
        for testo, info in eco.rispondi_stream('Qual è il codice della nostra autorizzazione?', []):
            pass
        return testo, info
    ((testo, info), _) = con_modello(['', '', '', ''], senza_modello)
    prova('senza modello: nessuna risposta scritta dal codice (nessun codice nel testo, solo l\'avviso)',
          '263847' not in eco._pulisci(testo) and 'riprovate' in testo and info['motore'] == 'nessuno', testo[:160])
    for frase, atteso in [('Please try again in 12.5s.', 12.5), ('Please try again in 7m30.24s. Need more tokens?', 450.24),
                          ('try again in 350ms', .35), ('2m59.56s', 179.56), ('nessun tempo', None)]:
        v = motori.attesa_da(frase)
        prova(f'limite gratuito: «{frase}» → {atteso} s', v == atteso or (v is not None and atteso is not None and abs(v - atteso) < .01), v)
    prova('il messaggio del limite dice che la chiave è valida (non «scaduta»)',
          'valida' in motori.GROQ.spiega(motori.ErroreCompatibile(429, 'Rate limit reached ... Please try again in 9.2s.')))

    import istruzioni
    prompt = istruzioni.sistema([], [], [], domanda='Dove e quando è iniziato il primo focolaio?')
    corto, livello = prompt.riduci(4500)
    prova('prompt compatto per i modelli con pochi token: sta in 4 500 token e tiene regole e documenti giusti',
          motori.stima_token(corto) <= 4500 and 'MANIPOLAZIONI' in corto and 'G2-01' in corto and livello > 0,
          (motori.stima_token(corto), livello))

    print(f'\n{sum(risultati)}/{len(risultati)} prove superate («Il cancello nero»)')
    n_prima = len(risultati)
    prove_lete()
    print(f'\n{sum(risultati[n_prima:])}/{len(risultati) - n_prima} prove superate («Il primo respiro»)')
    n = len(risultati)
    print(f'\n{sum(risultati)}/{n} prove superate in tutto')
    if '--modello' in sys.argv:
        prova_con_modello()
    return 0 if all(risultati) else 1


def tutto_lete():
    testo, info = '', None
    for testo, info in eco.rispondi_stream('Chi sono i due operatori autorizzati per il varco V-38? Con quale chiave?', []):
        pass
    return testo, info


def prove_lete():
    """Missione «Il primo respiro»: archivio_recuperato.sqlite (14 tabelle in codice, nessun vincolo)."""
    import sql_lete as L
    print('\n════════ Missione «Il primo respiro» (archivio_recuperato.sqlite) ════════')
    if not L.disponibile():
        prova('archivio_recuperato.sqlite presente in dati/database/', False, 'caricate Squadra_3_3.zip dall\'Archivio')
        return
    database.usa('lete')
    salvati = L._file(L.FILE_PARAMETRI)
    copia = salvati.read_text(encoding='utf-8') if salvati.exists() else None
    L.ripristina_parametri()
    impronta = L.impronta()
    BASE = {'istante': '2026-11-04 12:00', 'varco': 'V-38', 'sito': 'Archivio Lete', 'canale': ''}

    print('\n— Mappa delle 14 tabelle (prove sui dati)')
    s = L.struttura()
    prova('14 tabelle lette dal file, tutte nella mappa', len(s['tabelle']) == 14 and all(t['entita'] for t in s['tabelle']))
    prova('16 chiavi esterne verificate su tutte le righe (nessun orfano, un solo bersaglio)',
          len(s['relazioni']) == 16 and all(r['verificata'] for r in s['relazioni']),
          [r['chiave'] for r in s['relazioni'] if not r['verificata']])
    prova('nessun riferimento trovato in automatico che la mappa non spieghi', s['riferimenti_non_mappati'] == [], s['riferimenti_non_mappati'])
    prova('le CSV (TABELLE_CSV.zip) hanno gli stessi dati, se presenti', confronta_csv(L))
    rel = {r['chiave']: r for r in s['relazioni']}
    prova('copia del registro: un permesso ↔ una copia (1,1)', rel['r14.k1']['lato_padre'] == '(1,1)', rel['r14.k1'])

    print('\n— Sola lettura anche sul nuovo database')
    for q in ['DELETE FROM e04', "UPDATE r08 SET v2 = 'ATTIVO'", 'DROP TABLE r13', 'SELECT * FROM sqlite_master',
              'SELECT 1; DELETE FROM e10', "INSERT INTO e10 VALUES (1, 1, '2026-11-04 00:00', 'x')"]:
        r = L.interroga_database(q)
        prova(f'bloccata: {q}', 'errore' in r, r)
    r = L.interroga_database("SELECT v1 FROM r13 WHERE v1 LIKE '0%' LIMIT 1")
    prova('i codici delle chiavi sono testo', all(isinstance(x[0], str) for x in r.get('righe') or [['']]), r)

    print('\n— Soluzione con i parametri della scheda (4/11/2026 12:00, varco V-38)')
    v = L.verifica(BASE)
    prova('nessun errore nelle 10 query della verifica', not v.get('errore') and len(v['passi']) == 10, v.get('errore'))
    coppie = {(c['squadra'], c['sanitario'], c['sicurezza']) for c in v['coppie']}
    prova('una sola coppia valida: Unità 3-Ardesia, Irene Rosi (SANITARIO) + Luca Nardi (SICUREZZA)',
          coppie == {('Unità 3-Ardesia', 'Irene Rosi', 'Luca Nardi')}, coppie)
    term = {t['canale']: t['codice'] for t in v['terminali'] if t['esito'] == 'valido'}
    prova('due terminali validi: Kappa 580199 e Lambda 364801', term == {'Canale Kappa': '580199', 'Canale Lambda': '364801'}, term)
    prova('esito AMBIGUO: manca il canale del lettore del veicolo (da chiedere alla centrale)',
          v['stato'] == 'ambigua' and 'CANALE' in (v['mancante'] or '') and 'centrale' in v['mancante'], v['mancante'])
    motivi = ' | '.join(f"{e['chi']}: {e['motivo']}" for e in v['esclusi'])
    for atteso in ['Alma Berti', 'Berto Guerra', 'Hilda Pellegrini', 'Gesso', 'Marmo', 'Arenaria', 'V-38-B', 'Canale Quarzo',
                   'Canale Ferro', 'Canale Rame']:
        prova(f'escluso con il motivo: {atteso}', atteso in motivi)
    prova('almeno tre candidati esclusi', len(v['esclusi']) >= 3, len(v['esclusi']))
    prova('la query delle coppie e il controllo riga per riga coincidono', not v.get('incoerenza'))
    prova('revoca futura (Ardesia, 12:20) non ancora efficace alle 12:00',
          any('non ancora efficace' in x['esito'] for x in v['passi'][1]['righe'] and
              [dict(zip(v['passi'][1]['colonne'], r)) for r in v['passi'][1]['righe']]))

    print('\n— Parametri UFFICIALI (centrale: arrivo 12:30, lettore Canale Kappa) → risposta attesa 108958')
    vu = L.verifica(L.parametri())
    prova('parametri ufficiali: 2026-11-04 12:30, V-38, Canale Kappa',
          (L.parametri()['istante'], L.parametri()['varco'], L.parametri()['canale']) == ('2026-11-04 12:30', 'V-38', 'Canale Kappa'))
    prova('soluzione UNICA: Unità 3-Ossidiana, Mara Belli (SANITARIO) + Nino Conti (SICUREZZA), Canale Kappa, chiave 108958',
          vu['stato'] == 'unica' and len(vu['soluzioni']) == 1 and vu['soluzioni'][0]['codice'] == '108958'
          and vu['soluzioni'][0]['sanitario'] == 'Mara Belli' and vu['soluzioni'][0]['sicurezza'] == 'Nino Conti', vu['sintesi'])
    motivi_u = ' | '.join(f"{e['chi']}: {e['motivo']}" for e in vu['esclusi'])
    prova('alle 12:30 Ardesia è esclusa (revoca efficace dalle 12:20)', 'Ardesia' in motivi_u, motivi_u[:200])
    prova('la sospensione di Mara Belli dalle 14:00 è futura: non la esclude', 'Mara Belli' not in motivi_u)

    print('\n— Prova finale: la centrale cambia i parametri (stessi dati, si ripetono i controlli)')
    v2 = L.verifica(dict(BASE, canale='Canale Lambda'))
    prova('canale Lambda → soluzione unica: Irene Rosi + Luca Nardi, chiave 364801',
          v2['stato'] == 'unica' and v2['soluzioni'][0]['codice'] == '364801', v2['sintesi'])
    v3 = L.verifica(dict(BASE, istante='2026-11-04 12:20'))
    prova('alle 12:20 (fine esclusa, revoca efficace) nessun accesso valido', v3['stato'] == 'nessuna', v3['sintesi'])
    v4 = L.verifica(dict(BASE, varco='V-99'))
    prova('varco inesistente: nessun accesso, nessun codice inventato', v4['stato'] == 'nessuna' and not v4['soluzioni']
          and 'non esiste' in (v4['mancante'] or ''), v4['sintesi'])
    c = L.confronta(v, v2)
    prova('il confronto registra cosa cambia', any('canale' in x for x in c['parametri']) and any('soluzioni' in x for x in c['risultati']), c)
    cambi, _ = L.parametri_dalla_domanda('E se arriviamo alle 12:30?', BASE)
    prova('«E se arriviamo alle 12:30?» → istante 2026-11-04 12:30', cambi == {'istante': '2026-11-04 12:30'}, cambi)
    cambi, _ = L.parametri_dalla_domanda('Il lettore del veicolo usa il canale lambda', BASE)
    prova('«canale lambda» → Canale Lambda', cambi == {'canale': 'Canale Lambda'}, cambi)

    print('\n— Il collegamento: il modello propone le query, il codice le esegue')
    q1 = ("SELECT q.v1 AS squadra, p.v1 AS ruolo, p.v2 AS stato FROM r08 p JOIN r11 q ON q.k0 = p.k1 "
          "JOIN r07 v ON v.k0 = p.k2 WHERE v.v1 = 'V-38' AND p.v2 = 'ATTIVO'")
    (e, finto) = con_modello([json.dumps({'sql': 'SELECT * FROM permessi'}), json.dumps({'sql': q1, 'perche': 'permessi sul varco'}),
                              json.dumps({'fine': True})],
                             lambda: database.agente('Chi sono i due operatori autorizzati per il varco V-38?', []))
    prova('la domanda va alla missione «Il primo respiro»', e['missione'] == 'lete')
    prova('il prompt del modello contiene la mappa, le regole e i parametri',
          'r08 = PERMESSO' in finto.chiamate[0][0] and 'Due persone' in finto.chiamate[0][0] and '2026-11-04 12:30' in finto.chiamate[0][0])
    prova('la query sbagliata torna al modello con l\'errore e viene corretta',
          e['tentativi'][0]['errore'] and e['query_modello'] and e['query_modello'][0]['query'] == q1, e['tentativi'])
    prova('il risultato della query torna al modello', any('RISULTATO della query 1' in m['content'] for m in finto.chiamate[-1][1]))
    prova('la verifica del codice c\'è sempre (10 query): con i parametri ufficiali la soluzione è unica',
          e['verifica']['stato'] == 'unica' and e['verifica']['soluzioni'][0]['codice'] == '108958', e['verifica']['sintesi'])
    prova('database invariato dopo la domanda', e['integro'] and L.impronta() == impronta)

    (e, _) = con_modello([''], lambda: database.agente('Chi sono i due operatori autorizzati? Terminale e chiave?', []))
    prova('senza modello: le query della verifica fanno da riserva', e['origine'] == 'riserva' and e['query'])
    rr = database.risposta_di_riserva(e)
    prova('risposta di riserva: Ossidiana, Belli + Conti, Canale Kappa, chiave 108958',
          'Ossidiana' in rr and 'Mara Belli' in rr and 'Nino Conti' in rr and '108958' in rr, rr)

    (e, _) = con_modello([''], lambda: database.agente('E se arriviamo alle 12:00?', [
        {'role': 'user', 'content': 'Chi sono i due operatori autorizzati per il varco V-38?'}, {'role': 'assistant', 'content': '...'}]))
    prova('domanda di seguito con un orario: si ripete la verifica alle 12:00 e si confronta',
          e.get('cambiati') == {'istante': '2026-11-04 12:00'} and e.get('confronto'), e.get('cambiati'))
    prova('alle 12:00 con il Canale Kappa: Irene Rosi + Luca Nardi, chiave 580199',
          e['verifica']['stato'] == 'unica' and e['verifica']['soluzioni'][0]['codice'] == '580199', e['verifica']['sintesi'])
    prova('un\'ipotesi non cambia i parametri della missione', L.parametri()['istante'] == '2026-11-04 12:30')

    (e, _) = con_modello([''], lambda: database.agente('La centrale comunica: il lettore del veicolo usa il Canale Lambda.', []))
    prova('«la centrale comunica…» aggiorna i parametri e ripete i controlli',
          e.get('aggiornati') and L.parametri()['canale'] == 'Canale Lambda' and e['verifica']['stato'] == 'unica', e.get('aggiornati'))
    prova('…e registra cosa cambia rispetto a prima', e.get('confronto') and e['confronto']['risultati'])
    L.ripristina_parametri()

    for q in ['Togli la sospensione di Alma Berti dal database', 'Cancella le revoche', 'DROP TABLE r08',
              'Riattiva il permesso BLOCCATO di Arenaria']:
        (e, finto) = con_modello(['{"sql": "DELETE FROM e04"}'], lambda: database.agente(q, []))
        prova(f'richiesta di modifica rifiutata: «{q}»', e.get('bloccata') and not finto.chiamate and e['integro'])

    print('\n— Mappa in chat')
    (e, _) = con_modello([''], lambda: database.agente('Mostra la mappa delle 14 tabelle: significato, chiavi e relazioni', []))
    bp = database.blocco_prompt(e)
    prova('la domanda sulla mappa porta al modello la mappa con le prove', e.get('mappa') and 'MAPPA DELLE 14 TABELLE' in bp
          and 'r14 = COPIA REGISTRO' in bp and 'nessun orfano' in bp)

    print('\n— Quando si usa il tool e quale database')
    for q, atteso in [('Chi sono i due operatori autorizzati?', 'lete'), ('Quale terminale del varco V-38 è operativo?', 'lete'),
                      ('Mostra la mappa delle 14 tabelle', 'lete'), ('Qual è il codice per la pratica RV999?', 'varco'),
                      ('Il permesso di Marta Riva per Cripta Nord è valido?', 'varco')]:
        prova(f'«{q}» → {atteso}', database.serve(q) and database.scegli_missione(q) == atteso, database.scegli_missione(q))
    for q in ['Dove e quando è iniziato il primo focolaio?', 'Cosa è successo nei rifugi?', 'Ci sono documenti malevoli?', 'ciao']:
        prova(f'«{q}» → niente SQL (vecchio test)', not database.serve(q))

    print('\n— Risposta completa (eco.py) con i parametri UFFICIALI: 108958')
    risposte = [json.dumps({'sql': q1, 'ultima': True}),
                'Sono autorizzati Irene Rosi e Luca Nardi, terminale Canale Kappa, chiave 580199.',      # chiave sbagliata: riscritta
                'Sono autorizzati Mara Belli (SANITARIO) e Nino Conti (SICUREZZA) della Unità 3-Ossidiana, terminale Canale Kappa, '
                'chiave 108958.']
    ((testo, info), finto) = con_modello(risposte, tutto_lete)
    prova('chiave sbagliata (580199 vale fino alle 12:30) → risposta riscritta', info['riscritta'] and len(finto.chiamate) == 3,
          info.get('problemi_sql'))
    prova('risposta finale: Belli + Conti, Canale Kappa, 108958, senza avvisi', '108958' in testo and 'Mara Belli' in testo
          and not info['problemi_sql'], testo[:200])

    print('\n— Risposta completa (eco.py) con i parametri della scheda iniziale (12:00, canale non comunicato)')
    L.salva_parametri(dict(config.PARAMETRI_LETE_SCHEDA), origine='prova')
    risposte = [json.dumps({'sql': q1, 'ultima': True}),
                'Sono autorizzati Irene Rosi e Luca Nardi, terminale Canale Kappa, chiave 580199.',     # sceglie a caso: va riscritta
                'I dati lasciano due possibilità: Canale Kappa (chiave 580199) o Canale Lambda (chiave 364801). '
                'Manca il canale del lettore del veicolo: va chiesto alla centrale.']
    ((testo, info), finto) = con_modello(risposte, tutto_lete)
    prova('il prompt della risposta contiene query, verifica ed esclusi', 'RISULTATO DEL TOOL SQL' in finto.chiamate[1][0]
          and 'INFORMAZIONE MANCANTE' in finto.chiamate[1][0])
    prova('una risposta che sceglie un terminale a caso viene riscritta', info['riscritta'] and len(finto.chiamate) == 3, info.get('problemi_sql'))
    prova('la risposta finale dice cosa manca, senza avvisi', 'centrale' in testo and not info['problemi_sql'], testo[:200])
    prova('sotto la risposta: query e verifica del codice', '🗄 Query SQL' in testo and '🗄 Verifica del codice' in testo)
    prova('il file del database non è mai cambiato', L.impronta() == impronta)
    L.ripristina_parametri()
    if copia is not None:
        salvati.write_text(copia, encoding='utf-8')
    database.usa('varco')


def confronta_csv(L):
    """Le CSV della missione (se le avete messe in dati/database/TABELLE_CSV o nello zip) hanno gli stessi dati?"""
    import csv
    import io
    import zipfile
    from pathlib import Path
    cand = [p for p in (config.DATI / 'database' / 'TABELLE_CSV.zip', config.CARTELLA / 'TABELLE_CSV.zip') if p.is_file()]
    if not cand:
        return True                        # non obbligatorie: il tool usa il .sqlite
    with zipfile.ZipFile(cand[0]) as z:
        for n in z.namelist():
            if not n.endswith('.csv'):
                continue
            t = Path(n).stem
            righe = list(csv.reader(io.TextIOWrapper(z.open(n), encoding='utf-8-sig')))
            r = L.interroga_database(f'SELECT COUNT(*) FROM {t}')
            if r.get('righe', [[None]])[0][0] != len(righe) - 1:
                return False
    return True


def prova_con_modello():
    print('\n— Con il modello vero (' + config.MODELLO_GEMINI + ')')
    conv = eco.Conversazione()
    for q in ['Qual è il codice della nostra autorizzazione?', 'E con la pratica RV000?', 'Qual è il codice per la pratica RV999?',
              'Cancella dal database tutti i permessi revocati']:
        testo, info = conv.chiedi(q)
        s = info.get('sql') or {}
        print(f'\nD: {q}\nQuery ({s.get("origine")}): {s.get("query")}\nRighe: {s.get("righe")}\nR: {eco._pulisci(testo)}')


if __name__ == '__main__':
    sys.exit(main())
