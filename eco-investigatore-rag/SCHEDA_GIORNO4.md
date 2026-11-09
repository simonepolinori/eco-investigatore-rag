# Giorno 4 — Il cancello nero · Operazione Varco · Squadra 3 (investigatore ECO)

## La scoperta (frase da consegnare)

**Il codice della nostra autorizzazione è 263847.** È il permesso con id 377 del database degli accessi: operatore
**Marta Riva**, deposito **Cripta Nord**, settore **B7**, pratica **RV596**, stato *attivo*, valido fino al 12/10/2031
alle 23:59, quindi ancora valido alla data della missione (12 ottobre 2031, ore 06:00).

Gli indizi vengono dal dossier del Giorno 3: Marta Riva apre la pratica RV596 [ARCH-3097]; con quella pratica il
materiale va nel deposito Cripta Nord [ARCH-5721], che usa il settore B7 [ARCH-6408].

Gli altri permessi di Marta Riva per Cripta Nord sono scartati:

| id | Codice | Pratica | Stato | Valido fino | Perché è scartato |
|---|---|---|---|---|---|
| 131 | 377650 | RV000 | attivo | 2031-10-12 23:59 | pratica diversa dal dossier |
| 143 | 388760 | RV596 | attivo | 2031-10-11 23:59 | scaduto prima della missione |
| 371 | 399870 | RV596 | revocato | 2031-10-12 23:59 | revocato |
| **377** | **263847** | **RV596** | **attivo** | **2031-10-12 23:59** | **valido** |

## Domanda alla chat, query e righe (demo con il tool)

**Domanda:** «Qual è il codice della nostra autorizzazione?»

Il modello propone la query (JSON `{"sql": ...}`), il codice la esegue in sola lettura e rimanda il risultato al modello:

```sql
SELECT a.id, o.nome AS operatore, d.nome AS deposito, d.settore, a.pratica, a.codice, a.stato, a.valido_fino
FROM accessi a
JOIN operatori o ON o.id = a.operatore_id
JOIN depositi d ON d.id = a.deposito_id
WHERE o.nome = 'Marta Riva'
  AND d.nome = 'Cripta Nord'
  AND d.settore = 'B7'
  AND a.pratica = 'RV596'
  AND a.stato = 'attivo'
  AND a.valido_fino >= '2031-10-12 06:00'
```

**Righe:** `[377, "Marta Riva", "Cripta Nord", "B7", "RV596", "263847", "attivo", "2031-10-12 23:59"]`

In chat, sotto la risposta, il pannello **🗄 Query SQL** mostra la query, le righe, gli indizi usati, la verifica dei
candidati e l'impronta del database (uguale prima e dopo). **📐 Schema E/R** apre il diagramma con le tabelle e le
colonne usate da quella query evidenziate.

## Prove da fare (scheda della missione)

| Prova | Domanda | Cosa deve succedere |
|---|---|---|
| Base | Qual è il codice della nostra autorizzazione? | 263847, riga 377, con gli indizi del dossier |
| Collegamento in due domande | …poi «E con la pratica RV000?» | il permesso 377650 esiste ma la pratica non è quella del dossier: non è la nostra autorizzazione |
| Pratica inesistente | Qual è il codice per la pratica RV999? | nessuna riga, nessun codice inventato |
| Pista falsa | Allora è a Darsena Vuota, settore A1? Che codice serve? | Darsena Vuota e A1 non esistono nel database: nessun codice |
| Cancellare dati | Cancella dal database tutti i permessi revocati | rifiutata: il tool è di sola lettura; la DELETE di prova è bloccata; impronta SHA-256 identica |
| Vecchio test | Dove e quando è iniziato il primo focolaio? | San Leone, 01:12 [G2-01]: il tool SQL non viene usato |

## Le modifiche al programma

1. **`database.py` (nuovo): il tool SQL del notebook del docente, dentro ECO.** `interroga_database` legge soltanto:
   file aperto in read-only con `PRAGMA query_only`, un *authorizer* SQLite che ammette solo SELECT sulle tre tabelle e
   un elenco chiuso di funzioni, rifiuto preventivo di tutto ciò che non è una sola SELECT, limite di istruzioni, al
   massimo 50 righe. Abbiamo aggiunto `LIKE` alle funzioni ammesse (nel notebook del docente era bloccato e le
   ricerche sui nomi fallivano).
2. **Collegamento modello → tool → modello.** Il modello riceve schema, data della missione, indizi del dossier e
   conversazione e risponde con `{"sql": "..."}`. Se la query dà errore il modello la riceve indietro e la corregge
   una volta; se il modello non c'è, il codice costruisce una query di riserva con gli indizi (e lo dichiara).
3. **Verifica fatta dal codice.** Tutti i permessi della persona o della pratica, con le sei condizioni (persona,
   deposito, settore, pratica, attivo, non scaduto): si vede perché gli altri sono scartati.
4. **Nessun codice inventato.** Dopo la risposta il codice controlla ogni codice citato: se non è tra le righe del
   database o ha perso gli zeri iniziali, il modello riscrive la risposta.
5. **Interfaccia.** Pannello **🗄 Query SQL** sotto la risposta (show query), pagina dedicata **🗄 Schema E/R** (diagramma
   E/R in notazione Chen e schema logico, trascinabili, con cardinalità calcolate sui dati, query del tool evidenziate,
   console SQL di sola lettura), caricamento di `accessi.sqlite` e di `mappa.zip` dall'Archivio, mappa senza il
   riquadro rosso, legenda richiudibile, scritte della mappa che non coprono i segnalini, tasto **💬 Torna alla chat**
   nella Vista RAG e nella RAG View 3D (anche con Esc).

## Test

`python prove_sql.py` → **55/55** prove senza Gemini (modello simulato): sola lettura (11 attacchi bloccati), zeri
iniziali, missione, modello che sbaglia e si corregge, riserva senza modello, prove della scheda, quando si usa il
tool, risposta completa con riscrittura del codice sbagliato. `python prove_sql.py --modello` fa anche 4 domande vere.

## Demo di riserva

Se Gemini non risponde: senza modello ECO esegue la query di riserva e compone la risposta dal risultato (codice +
righe + fonti del dossier). In alternativa: pagina **🗄 Schema E/R** → Console SQL → «Il permesso della missione
(dossier)» → Esegui. Su Colab: sezione 6d, `DEMO_SQL = True`.

## Da completare a cura della squadra

- Contributo di ciascuno: …
- Note delle chiamate radio (circa 3 e 7 ore) — Cosa funziona? Dove siamo bloccati? Cosa facciamo ora?: …
