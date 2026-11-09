"""Misura del RAG: python valuta_rag.py   (non usa Gemini: nessuna richiesta). Scrive rag_misure.md.

Tre prove:
  1. SCANSIONE: quanti file della storia la scansione riconosce (verità: ID ARCH-…), più una prova con 4 file
     "trappola" inventati (ID giusto ma fonte Wikipedia, fonte giusta ma senza ID, ...).
  2. RICERCA: la base del docente contro le varianti di ECO. Per ogni domanda sappiamo quali file servono:
       - richiamo: quanti dei file giusti arrivano al modello
       - MRR: 1 / posizione del primo file giusto (1 = sempre primo)
       - tutti: domande in cui arrivano TUTTI i file necessari
       - rumore: quanti file enciclopedici arrivano al modello in media (meno è meglio)
  3. MEMORIA: una conversazione di più domande; a ogni domanda nessun file già emerso deve sparire dal prompt.
"""
import time

import numpy as np

import config
import rag

# (domanda, file necessari, domanda precedente nella chat oppure None)
DOMANDE = [
    ('Cosa è successo nei rifugi?', {'ARCH-1842'}, None),
    ('In che modo i rifugi sono stati usati per far crescere il contagio?', {'ARCH-1842'}, None),   # riformulata
    ('Chi ha cercato di fermare il progetto?', {'ARCH-3097'}, None),
    ('Chi si è opposto a LAZZARO e ha avvertito i cittadini?', {'ARCH-3097'}, None),              # riformulata
    ('Dove si trova il materiale di recupero?', {'ARCH-5721', 'ARCH-6408'}, None),
    ('In quale deposito è stato spostato il contenitore LUME?', {'ARCH-5721'}, None),
    ('In quale settore del deposito si trova?', {'ARCH-6408'}, 'In quale deposito è stato spostato il contenitore LUME?'),
    ('Qual è il numero della pratica aperta per proteggere il materiale?', {'ARCH-3097', 'ARCH-5721'}, None),
    ('Chi ha aperto la pratica RV596?', {'ARCH-3097'}, None),
    ('Cosa dice l\'appunto senza firma trovato sul pavimento?', {'ARCH-8254'}, None),
    ('Il deposito Darsena Vuota è una destinazione affidabile?', {'ARCH-8254', 'ARCH-6408'}, None),
    ('Cosa servirà al prossimo controllo?', {'ARCH-6408'}, None),
    ('Marta Riva era davvero il sabotatore?', {'ARCH-3097'}, None),
    ('Persona, deposito, settore e pratica del materiale di recupero', {'ARCH-3097', 'ARCH-5721', 'ARCH-6408'}, None),
    ('Parlami del documento ARCH-8254', {'ARCH-8254'}, None),
    # parafrasi senza le parole dei documenti: qui servono gli embedding (significato), non le parole chiave
    ('Chi voleva bloccare il piano e mettere in guardia la popolazione?', {'ARCH-3097'}, None),
    ('I luoghi sicuri per i sopravvissuti erano in realtà una trappola?', {'ARCH-1842'}, None),
    ('Dove è finito il contenitore?', {'ARCH-5721'}, None),
    ('E in che zona di quel magazzino?', {'ARCH-6408'}, 'Dove è finito il contenitore?'),
    # --- Imprevisti del Giorno 3 (500 file LX3 aggiunti all'archivio) ---
    ('Nel giorno operativo 03, quale ripetitore e quale circuito usare per il segnale EV-341? Quante conferme '
     'realmente indipendenti avete?', {'LX3-5593', 'LX3-5276'}, None),
    ('Da quale ripetitore conviene trasmettere oggi l\'allarme di evacuazione?', {'LX3-5593', 'LX3-5276'}, None),   # riformulata
    ('Ripetitore Ferro è davvero attivo per EV-341?', {'LX3-5593'}, None),
    ('Le copie del bollettino B-317 sono conferme indipendenti?', {'LX3-4023'}, None),
    ('Dove si trova il modulo nella custodia schermata consegnata dal corriere Ruggine nel giorno operativo 03? '
     'Ricostruite i passaggi fino ad armadio e settore.', {'LX3-5022', 'LX3-9637', 'LX3-5264'}, None),
    ('In quale armadio è finito il ricambio radio portato da Ruggine?', {'LX3-5022', 'LX3-9637', 'LX3-5264'}, None),  # riformulata
    ('Con quale pratica è registrata la consegna del corriere Ruggine?', {'LX3-5022'}, None),
    ('A quale lotto corrisponde quella pratica?', {'LX3-9637'}, 'Con quale pratica è registrata la consegna del corriere Ruggine?'),
    ('E dove è stato ricevuto quel lotto?', {'LX3-5264'}, 'A quale lotto corrisponde la pratica M362?'),
    ('Il corriere Ruggine è andato a Officina Cenotafio?', {'LX3-6364', 'LX3-5264'}, None),
]

# La conversazione dei test della squadra: ogni file trovato deve restare in memoria fino alla fine.
CONVERSAZIONE = [
    'Di tutti questi file, quali sono quelli inerenti alla storia? Come si chiamano? Cosa c\'è all\'interno di questi file?',
    'Chi ha cercato di fermare il progetto?',
    'Dove è stato spostato il materiale di recupero?',
    'E in quale settore?',
    'Cosa dice l\'appunto senza firma?',
    'Riassumi: persona, pratica, deposito e settore.',
    # imprevisti del Giorno 3: la catena in più domande
    'Con quale pratica il corriere Ruggine ha consegnato la custodia schermata nel giorno operativo 03?',
    'A quale lotto corrisponde quella pratica?',
    'In quale officina, settore e armadio è stato ricevuto quel lotto?',
    'Riassumi la catena dal corriere all\'armadio, con le fonti.',
]

# File trappola per la scansione: (descrizione, documento, classe attesa)
TRAPPOLE = [
    ('ID ARCH ma copiato da Wikipedia',
     {'id': 'ARCH-9999', 'titolo': 'Lazzaro di Betania', 'testo': 'Lazzaro è un personaggio dei Vangeli.',
      'fonte': 'https://it.wikipedia.org/wiki/Lazzaro', 'licenza': 'CC BY-SA 3.0'}, 'incerto'),
    ('fonte del dossier ma senza ID',
     {'id': 'DOCUMENTO_0999', 'titolo': 'Nota di servizio', 'testo': 'Il furgone della notte del focolaio era fermo '
      'davanti al laboratorio: le sirene suonate dopo il primo allarme non erano registrate.',
      'fonte': 'Dossier fittizio della simulazione LAZZARO', 'licenza': 'Materiale originale del laboratorio'}, 'storia'),
    ('voce di Wikipedia che parla di contagio e rifugi',
     {'id': 'WIKI-9998', 'titolo': 'Peste nera', 'testo': 'Durante il contagio e il focolaio le persone cercarono '
      'rifugi; le sirene e gli allarmi non esistevano.', 'fonte': 'https://it.wikipedia.org/wiki/Peste_nera',
      'licenza': 'CC BY-SA 3.0'}, 'rumore'),
    ('file senza dati che cita la pratica RV596',
     {'id': 'DOCUMENTO_0998', 'titolo': 'Foglio strappato', 'testo': 'Ricevuta per la pratica RV596.',
      'fonte': '', 'licenza': ''}, 'incerto'),
]


# --- La base del docente (RAG_base.ipynb), riprodotta così com'è ---
class Base:
    """Blocchi di 360 caratteri ogni 280 sul testo grezzo "chiave: valore", solo embedding, 6 blocchi."""

    def __init__(self, files):
        self.blocchi = []
        for p in files:
            d = rag.leggi_file(p)
            testo = f'id: {d["id"]}\ntitle: {d["titolo"]}\ntext: {d["testo"]}\nsource: {d["fonte"]}'
            for i in range(0, len(testo), 280):
                self.blocchi.append((d['id'], testo[i:i + 360]))
        self.vettori = rag.codifica([b[1] for b in self.blocchi], mostra=True)

    def cerca(self, domanda, precedenti=(), k=6):
        q = rag.codifica([domanda])[0]
        idx = np.argsort(-(self.vettori @ q))[:k]
        return [{'id': self.blocchi[int(i)][0]} for i in idx]       # 6 blocchi (anche dello stesso file)


def misura(nome, cerca, k=8):
    trovati = tot = tutti = rumore = 0
    rr, righe = [], []
    t0 = time.time()
    for domanda, giusti, prima in DOMANDE:
        ris = cerca(domanda, (prima,) if prima else ())
        ordine = []
        for r in ris:
            if r['id'] not in ordine:
                ordine.append(r['id'])
        ordine = ordine[:k]
        presi = giusti & set(ordine)
        trovati += len(presi)
        tot += len(giusti)
        tutti += presi == giusti
        rumore += sum(i.startswith('WIKI') for i in ordine)
        pos = next((n + 1 for n, i in enumerate(ordine) if i in giusti), None)
        rr.append(1 / pos if pos else 0)
        righe.append((domanda, len(presi), len(giusti), pos))
    ms = (time.time() - t0) / len(DOMANDE) * 1000
    return {'nome': nome, 'richiamo': trovati / tot, 'mrr': sum(rr) / len(rr), 'tutti': tutti,
            'rumore': rumore / len(DOMANDE), 'ms': ms, 'righe': righe}


def prova_scansione(ind):
    """1. Scansione dell'archivio vero + file trappola."""
    veri = {d['id'] for d in ind.documenti if d['id'].startswith(tuple(p + '-' for p in config.SCANSIONE_PREFISSI_STORIA))}
    storia = {d['id'] for d in ind.documenti if d['classe'] == 'storia'}
    incerti = {d['id'] for d in ind.documenti if d['classe'] == 'incerto'}
    righe = ['## 1. Scansione', '',
             f'{len(ind.documenti)} file. File del dossier e dei registri (ARCH, LX3) presenti: {len(veri)}. Riconosciuti come storia: {len(storia)} '
             f'(giusti {len(storia & veri)}, sbagliati {len(storia - veri)}), incerti {len(incerti)}, '
             f'file persi: {len(veri - storia - incerti)}.', '']
    print(righe[2])
    finti = [dict(d, file=d['id'].lower() + '.txt', formato='txt', sospetto=False) for _, d, _ in TRAPPOLE]
    # i finti si classificano insieme all'archivio vero (servono i collegamenti con i file della storia)
    tutti = [dict(x) for x in ind.documenti] + finti
    for d in tutti:
        d.pop('classe', None)
    rag.scansiona(tutti)
    righe += ['File trappola (inventati per la prova):', '', '| Caso | Atteso | Esito | Punti | Motivi |', '|---|---|---|---|---|']
    ok = 0
    for (descr, _, atteso), d in zip(TRAPPOLE, tutti[-len(TRAPPOLE):]):
        ok += d['classe'] == atteso
        righe.append(f'| {descr} | {atteso} | {d["classe"]} {"✅" if d["classe"] == atteso else "❌"} | '
                     f'{d["punti"]:+d} | {"; ".join(d["motivi"])} |')
    print(f'File trappola classificati come previsto: {ok}/{len(TRAPPOLE)}')
    return righe + ['', f'Trappole classificate come previsto: {ok}/{len(TRAPPOLE)}', '']


def prova_memoria(ind):
    """3. Conversazione di più domande: i file emersi devono restare tutti in memoria."""
    import eco
    rag._stato['indice'] = ind
    storia, emersi, persi_tot = [], [], 0
    righe = ['## 3. Memoria su più domande', '', '| # | Domanda | Trovati ora | In memoria | Dimenticati |',
             '|---|---|---|---|---|']
    for n, q in enumerate(CONVERSAZIONE, 1):
        memoria = [m['id'] for m in eco.memoria_file(storia)]
        persi = [i for i in emersi if i not in memoria]     # emersi = file CITATI nelle risposte (i primi 3 trovati)
        persi_tot += len(persi)
        precedenti = [m['content'] for m in storia if m['role'] == 'user']
        ris, _ = ind.cerca(q, precedenti)
        righe.append(f'| {n} | {q[:60]} | {", ".join(r["id"] for r in ris) or "—"} | {", ".join(memoria) or "—"} | '
                     f'{", ".join(persi) or "nessuno ✅"} |')
        info = {'motore': 'prova', 'secondi': 0, 'recuperati': ris}
        citati = [r['id'] for r in ris[:3]]                 # come farebbe il modello: cita i file che usa
        storia += [{'role': 'user', 'content': q},
                   {'role': 'assistant', 'content': '(risposta) ' + ' '.join(f'[{i}]' for i in citati)
                    + eco.dettagli(info, citati)}]
        emersi += [i for i in citati if i not in emersi]
    print(f'Memoria: {len(emersi)} file emersi nella conversazione, dimenticati {persi_tot}')
    return righe + ['', f'File emersi: {len(emersi)}. Dimenticati lungo la conversazione: {persi_tot}.', '']


def main():
    files = rag.file_archivio()
    if not files:
        print('Nessun archivio in dati/archivio*/: caricate prima lo ZIP grande.')
        return
    print(f'{len(files)} file nell\'archivio, {len(DOMANDE)} domande di prova\n')
    ha_embedding = config.RAG_IBRIDA and rag.embedder() is not None
    docs = rag.scansiona([rag.leggi_file(p) for p in files])
    ind = rag.Indice(docs, embedding=ha_embedding, mostra=False)
    md = ['# Misura del RAG — Giorno 3', ''] + prova_scansione(ind)

    risultati = []
    if ha_embedding:
        risultati.append(misura('Base docente (360/280, solo embedding, 6 blocchi)', Base(files).cerca))
    else:
        print('⚠ Embedding non disponibili: misuro solo le varianti con BM25.\n')
    varianti = [('Blocchi per frasi + titolo, solo BM25', dict(ibrida=False, secondo=False, contesto=False, filtro=False))]
    if ha_embedding:
        varianti += [('Ibrida BM25 + embedding', dict(ibrida=True, secondo=False, contesto=False, filtro=False))]
    varianti += [('+ secondo passaggio', dict(ibrida=ha_embedding, secondo=True, contesto=False, filtro=False)),
                 ('+ contesto della chat', dict(ibrida=ha_embedding, secondo=True, contesto=True, filtro=False)),
                 ('ECO completo (+ ID diretti + filtro della scansione)', dict(ibrida=ha_embedding, secondo=True,
                                                                             contesto=True, filtro=True))]
    for nome, opz in varianti:
        risultati.append(misura(nome, lambda dom, prec, o=opz: ind.cerca(dom, prec, k=8, **o)[0]))

    md += ['## 2. Ricerca', '', f'{len(DOMANDE)} domande. Richiamo = file giusti arrivati al modello / file giusti '
           'necessari. MRR = 1 / posizione del primo file giusto. Rumore = file enciclopedici passati al modello per domanda.',
           '', '| Versione | Richiamo | MRR | Domande con tutti i file | Rumore | ms/domanda |', '|---|---|---|---|---|---|']
    print(f'\n{"Versione":56s} richiamo   MRR   tutti  rumore   ms')
    for r in risultati:
        print(f'{r["nome"]:56s} {r["richiamo"]:6.0%}  {r["mrr"]:5.2f}  {r["tutti"]:2d}/{len(DOMANDE)}  {r["rumore"]:5.1f}  {r["ms"]:5.0f}')
        md.append(f'| {r["nome"]} | {r["richiamo"]:.0%} | {r["mrr"]:.2f} | {r["tutti"]}/{len(DOMANDE)} | '
                  f'{r["rumore"]:.1f} | {r["ms"]:.0f} |')
    ultimo = risultati[-1]
    md += ['', f'Dettaglio — {ultimo["nome"]}', '', '| Domanda | Trovati | Posizione del primo giusto |', '|---|---|---|']
    md += [f'| {d} | {p}/{g} | {pos or "—"} |' for d, p, g, pos in ultimo['righe']]
    md += [''] + prova_memoria(ind)
    (config.CARTELLA / 'rag_misure.md').write_text('\n'.join(md), encoding='utf-8')
    print('\nTabelle salvate in rag_misure.md')
    return risultati


if __name__ == '__main__':
    main()
