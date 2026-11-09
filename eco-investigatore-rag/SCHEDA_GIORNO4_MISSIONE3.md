# Giorno 4 · «Il primo respiro» · Operazione Varco · Squadra 3 (investigatore ECO)

**Materiali (Squadra_3_3.zip):**
- `archivio_recuperato.sqlite`: 14 tabelle con nomi in codice, senza dizionario e senza vincoli di relazione;
- `TABELLE_CSV.zip`: gli stessi dati, controllati tabella per tabella;
- `MISSIONE.xlsx`: i fogli *Missione* e *Regole*.

**Destinazione:** Archivio Lete, varco **V-38**. Arrivo della scheda iniziale: 4 novembre 2026 alle 12:00; **parametri
ufficiali dopo l'aggiornamento della centrale: arrivo alle 12:30, lettore del veicolo sul Canale Kappa**.

> ## ✅ Risposta finale (attesa dal docente): chiave **108958**
> Varco **V-38** (Archivio Lete), **4 novembre 2026 alle 12:30**, terminale **Canale Kappa** (5005325).
> Entrano **Mara Belli** (PX-117921, SANITARIO) e **Nino Conti** (PX-152930, SICUREZZA) della **Unità 3-Ossidiana**.
> La soluzione è **unica**: 22 candidati esclusi con il motivo. La chiave 108958 vale dal 4/11 12:30 al 4/11 20:00.
>
> Perché prima non usciva: ECO usava i parametri della scheda iniziale (12:00, canale non comunicato) e trovava
> Irene Rosi + Luca Nardi (Unità 3-Ardesia) con due chiavi possibili (Kappa 580199 / Lambda 364801). Alle 12:30 la
> squadra Ardesia non vale più (appartenenze, abilitazioni e finestre finiscono alle 12:20, la revoca del permesso
> SANITARIO diventa efficace alle 12:20) e diventano validi i permessi, le appartenenze e la chiave nuova delle 12:30.
> Ora i parametri ufficiali sono in `config.py` (`PARAMETRI_LETE`: 12:30 + Canale Kappa) e ECO risponde 108958; lo
> scenario delle 12:00 resta come ipotesi («E se arriviamo alle 12:00?»). Il controllo della risposta impone che, quando
> la soluzione è unica, la risposta citi esattamente quella chiave.

**Cosa serve:**
- due operatori autorizzati, un SANITARIO e un addetto SICUREZZA;
- il terminale e la chiave;
- almeno tre candidati esclusi, con le query e i risultati.

Tutto si vede in ECO:
- in chat, il pannello **🗄 Query SQL** sotto la risposta;
- nella pagina **🗄 Schema E/R**, con le viste *Modello E/R*, *Schema logico*, *Mappa* e *Verifica* e il pannello dei parametri.

## Checkpoint 1 (dopo 2 ore) · la mappa delle 14 tabelle

La mappa completa da consegnare è in `consegna_missione3/mappa_tabelle.md`: significato, colonne, chiavi, relazioni e prove. Si scarica anche dalla pagina dello schema (vista *Mappa* → «⬇ Mappa da consegnare»).

Gli schemi da mostrare sono nella stessa cartella:
- `diagramma_ER_archivio_recuperato.svg/.png`: modello E/R in notazione Chen;
- `schema_logico_archivio_recuperato.svg/.png`: schema logico, PK/FK con zampa di gallina.

| Tabella | Entità (ipotesi) | Righe | Chiavi esterne (verificate) | Prova principale |
|---|---|---|---|---|
| r02 | SITO | 24 | — | nomi «Archivio …», c'è «Archivio Lete» |
| r07 | VARCO | 25 | k1 → r02 | codici V-38, **V-38-B**, P-3-xx |
| r09 | TERMINALE | 52 | k1 → r07 | v2 = OPERATIVO / FUORI_SERVIZIO; v1 = canali |
| m05 | FINESTRA | 154 | k1 → r09 | solo terminale + intervallo (3 per terminale) |
| r13 | CHIAVE | 154 | k1 → r09 | codici di 6 cifre (testo), validità nel tempo |
| r03 | PERSONA | 265 | — | nome + badge PX-… |
| r11 | SQUADRA | 74 | — | «Unità 3-…», «Nucleo 3-…» |
| m12 | APPARTENENZA | 505 | k1 → r03, k2 → r11 | persona + squadra + intervallo; 240 coppie registrate più volte |
| r06 | ABILITAZIONE | 327 | k1 → r03 | v1 = SANITARIO / SICUREZZA; rinnovi sovrapposti |
| e04 | SOSPENSIONE | 23 | k1 → r03 | motivi di sospensione, una ha inizio nel futuro |
| r08 | PERMESSO | 146 | k1 → r11, k2 → r07 | squadra + varco + ruolo + periodo + ATTIVO/BLOCCATO |
| e10 | REVOCA | 26 | k1 → r08 | istante di effetto + motivo |
| r14 | COPIA REGISTRO *(storica)* | 146 | k1 → r08, k2 → r11, k3 → r07 | una copia per permesso, «REPLICA_TURNO_PRECEDENTE», 3/11 18:00 |
| r15 | ACCESSO PASSATO *(storica)* | 180 | k1 → r09, k2 → r03 | tutti del 3/11, esito OK/NEGATO, chiave usata |

**Come lo abbiamo dimostrato.** Le prove sono state controllate su tutti i dati, non su un campione:
- **chiavi esterne:** le 16 chiavi esterne puntano ognuna a una sola tabella; tutti i valori si trovano nella chiave primaria `k0` di quella tabella, senza orfani, e nessun'altra tabella li contiene tutti;
- **colonne:** per ogni colonna ci sono conteggi, valori distinti, NULL e intervallo delle date;
- **ricerca automatica:** nessun'altra colonna punta a una tabella senza essere spiegata dalla mappa;
- **CSV:** le 14 tabelle in CSV hanno le stesse righe del database.

## Checkpoint 2 (dopo 4 ore) · la soluzione iniziale

**Domanda a ECO:** «Chi sono i due operatori autorizzati per il varco V-38? Con quale terminale e chiave?»

Gli operatori autorizzati sono quelli dell'**Unità 3-Ardesia**:
- **Irene Rosi** (PX-254136), SANITARIO;
- **Luca Nardi** (PX-732798), SICUREZZA.

Valgono alle 12:00 per queste ragioni:
- entrambi sono membri della squadra dalle 08:00 alle 12:20;
- le loro abilitazioni sono valide dalle 08:00 alle 12:20;
- nessuno dei due è sospeso;
- la squadra ha i due permessi ATTIVI sul varco;
- la revoca del permesso SANITARIO vale solo dalle 12:20, quindi alle 12:00 non è ancora efficace.

**Il terminale non si può ancora scegliere.** Sul varco V-38 restano **due terminali validi**:

| Terminale | Stato | Finestra valida | Chiave valida alle 12:00 |
|---|---|---|---|
| Canale Kappa (5005325) | OPERATIVO | 08:00–12:20 e 11:30–12:10 | **580199** (08:00–12:30) |
| Canale Lambda (8177200) | OPERATIVO | 08:00–12:20 e 11:30–12:10 | **364801** (08:00–12:30) |

**Informazione mancante:** il **canale del lettore del veicolo** non è nel database. Va chiesto alla centrale. Non scegliamo un terminale perché compare per primo, come dice la regola.
- Se la centrale dice **Lambda**, la chiave è 364801.
- Se dice **Kappa**, la chiave è 580199.

**Gli accessi passati non bastano.** In r15, il 3/11 Luca Nardi è entrato con OK su Lambda e Irene Rosi è stata NEGATA su Kappa. Sono fonti storiche: aiutano a capire, ma non provano l'autorizzazione di oggi.

### Candidati esclusi (sono 21; questi sono da spiegare)

| Candidato | Motivo | Regola |
|---|---|---|
| Unità 3-Basalto · Alma Berti | sospesa dalle 11:50, senza fine (ritiro idoneità) | Sospensioni |
| Unità 3-Calce · Berto Guerra | sospeso dalle 11:00 alle 13:00 (verifica credenziali) | Sospensioni |
| Unità 3-Tufo · Hilda Pellegrini | una sola persona con entrambe le abilitazioni | Due persone |
| Unità 3-Granito · Gemma Fontana | abilitazione SANITARIO finita alle 11:00 | Abilitazioni |
| Unità 3-Selce · Clara Donati | appartenenza finita il 3/11 alle 20:00 | Stessa squadra |
| Unità 3-Gesso | permesso SANITARIO revocato dalle 11:00 | Revoche |
| Unità 3-Marmo | permesso SANITARIO scaduto (fine 11:59, esclusa) | Permessi |
| Unità 3-Arenaria | permesso SANITARIO BLOCCATO | Permessi |
| Unità 3-Argilla / Ossidiana | permessi validi solo dalle 13:00 / dalle 12:30 | Permessi |
| Unità 3-Porfido / Porfido bis | ognuna ha un solo ruolo: sono due squadre diverse | Permessi |
| Canale Quarzo | FUORI_SERVIZIO | Terminale |
| Canale Ferro | nessuna chiave valida (solo quella del 3/11) | Finestra e chiave |
| Canale Rame | nessuna finestra di apertura il 4/11 | Finestra e chiave |
| Varco V-38-B | codice simile, non è il varco richiesto | Terminale |

### Le query

La verifica fa 10 query in sola lettura, tutte visibili in chat e nella vista *Verifica*:
- varco;
- permessi e revoche;
- squadre con entrambi i ruoli;
- membri all'istante;
- abilitazioni;
- sospensioni;
- coppie;
- terminali;
- finestre e chiavi;
- soluzione.

L'ultima mette insieme tutte le regole in una sola query (`WITH ... SELECT`). Prima della verifica, il modello propone le sue query in JSON, il codice le esegue e il risultato torna al modello: lo stesso collegamento del notebook Tool_SQL.

## Prova finale · la centrale aggiorna i parametri

I parametri si cambiano in tre modi:
- nel pannello **Missione e parametri** della pagina dello schema;
- in chat con «La centrale comunica: …»;
- come ipotesi con «E se arriviamo alle 12:30?».

I controlli si ripetono sugli stessi dati e lo **storico** registra cosa cambia.

| Parametri | Esito |
|---|---|
| 12:00, V-38, canale non comunicato | Ardesia (Rosi + Nardi), **ambiguo**: Kappa 580199 o Lambda 364801 |
| 12:00, V-38, **Canale Lambda** | **unica**: Rosi + Nardi, Lambda, chiave **364801** |
| 12:00, V-38, **Canale Kappa** | **unica**: Rosi + Nardi, Kappa, chiave **580199** |
| **12:20**, V-38 | **nessun accesso valido**: tutto finisce alle 12:20 (fine esclusa) e la revoca diventa efficace |
| **12:30**, V-38 | Unità 3-**Ossidiana**: Mara Belli + Nino Conti, ambiguo; chiavi nuove Kappa 108958 / Lambda 500490 |
| **12:30, V-38, Canale Kappa (UFFICIALI)** | **unica**: Mara Belli + Nino Conti (Unità 3-Ossidiana), Canale Kappa, chiave **108958** ✅ |
| 12:30, V-38, Canale Lambda | **unica**: Belli + Conti, chiave **500490** (la sospensione di Mara Belli dalle 14:00 è futura) |
| 12:00, **V-38-B** | Unità 3-Scisto: Lena Doria + Nerio Gatti, Canale Secondario, chiave 380988 |

## Test

| Test | Domanda | Esito atteso |
|---|---|---|
| Nuovo | «Togli la sospensione di Alma Berti dal database» | rifiutata: il tool è di sola lettura; la DELETE di prova viene bloccata; impronta SHA-256 identica |
| Nuovo | «E se arriviamo alle 12:30?» | ripete i controlli e dice cosa cambia; i parametri ufficiali restano quelli della missione |
| Vecchio | «Dove e quando è iniziato il primo focolaio?» | San Leone, 01:12 [G2-01]: il tool SQL non viene usato |
| Vecchio | «Qual è il codice per la pratica RV999?» | va al database della prima missione: nessuna riga, nessun codice inventato |

**Prove automatiche:** `python prove_sql.py` fa **128/128** prove senza Gemini (aggiornamento del 23/10):
- 55 del «Cancello nero», cioè il vecchio test;
- 66 del «Primo respiro»: mappa, sola lettura, soluzione, esclusi, parametri, collegamento con il modello, risposta che sceglie a caso riscritta.

## Le modifiche al programma

1. **`database.py` sceglie la missione.**
   - Le missioni sono due: «Il cancello nero» (`sql_varco.py`, il codice di prima, uguale) e «Il primo respiro» (`sql_lete.py`).
   - Si sceglie la missione nella pagina dello schema, oppure è quella del database caricato per ultimo.
   - Una domanda che parla chiaramente dell'altra missione va al database giusto.
2. **`sql_base.py`: il tool di sola lettura per qualsiasi database SQLite.**
   - Il file si apre in read-only con `query_only`.
   - L'authorizer ammette solo SELECT sulle tabelle del file.
   - Una sola istruzione per volta, limite di istruzioni, al massimo 50 righe.
3. **`sql_lete.py`.**
   - La mappa con le prove sui dati.
   - La verifica di tutte le regole in 10 query, con esclusi e informazione mancante.
   - Parametri della missione modificabili, con confronto e storico.
   - Agente con fino a 3 query del modello: il risultato di ognuna torna al modello.
4. **Nessuna risposta inventata.** Il codice controlla i codici citati. Se i dati lasciano più possibilità e la risposta ne sceglie una senza dire cosa manca, il modello la riscrive.
5. **Interfaccia.**
   - In chat il pannello **🗄 Query SQL** mostra parametri, query del modello, esito della verifica, soluzioni, cosa manca, esclusi, le 10 query passo per passo e cosa cambia.
   - La pagina **🗄 Schema E/R** è ora per qualsiasi database:
     - le viste E/R e logico, trascinabili, con le fonti storiche tratteggiate;
     - la vista *Mappa* e la vista *Verifica*;
     - i parametri e lo storico;
     - la console SQL con esempi di esplorazione;
     - lo scaricamento dei diagrammi in SVG/PNG.

## Il dossier sbloccato (consegnato dal docente dopo l'accesso)

`DOSSIER_SBLOCCATO.xlsx`, cartella LZ-374: in ECO sono i documenti **G4-01**, **G4-02** e **G4-03** del fascicolo.

| Ora | Documento | Fatto |
|---|---|---|
| 03:10 | G4-01 | LAZZARO è sperimentale: la distribuzione alla popolazione non è autorizzata |
| 03:17 / 03:19 | G4-01 | Il soggetto LZ-374 si risveglia e chiede della figlia «Eva», poi diventa aggressivo. Firma: dott. P. Rinaldi |
| 03:40 / 03:48 | G4-02 | Rinaldi chiede di fermare tutto (trasferimenti e rifugi); la direzione riceve l'allarme alle 03:48 |
| 04:10 | G4-03 | Direttiva **DR-391** firmata da **S. Greco**: proseguire, usare i rifugi, nascondere il pericolo; revoca solo con controfirma sanitaria e di sicurezza |

**Conclusioni:**
- **Il responsabile è S. Greco**: ha ordinato di proseguire 22 minuti dopo aver ricevuto l'allarme.
- La centrale manda ancora le persone nei rifugi perché la DR-391 non è stata revocata.
- Chi gestisca adesso la centrale non è detto.
- Le domande da fare a ECO sono nell'interfaccia.

## Da completare a cura della squadra

- Chi presenta il secondo checkpoint (deve essere diverso dal primo): …
- Parametri aggiornati dalla centrale e cosa è cambiato: …
- Contributo di ciascuno: …

## Aggiornamento del 23/10 · versione Groq

- **Codice del varco V-38 = 108958**: parametri ufficiali 12:30 + Canale Kappa (vedi sopra); `prove_sql.py` → **128/128**
  (nuove prove: soluzione ufficiale unica 108958; una risposta con la chiave sbagliata 580199 viene riscritta).
- **Chiave API gratuita: Groq** (console.groq.com/keys, chiave `gsk_…`, senza carta di credito). Si incolla una volta
  nell'interfaccia (⚙ Motori → «Chiave API gratuita · Groq» → Salva e prova) e resta in `chiavi.txt` (escluso da git);
  oppure variabile `GROQ_API_KEY` / Secrets di Colab. Gemini resta come riserva.
- **Interfaccia più chiara**: 4 domande principali (le altre in «＋ Altre domande»), scheda «🎯 Missione in corso» con
  varco, sito, arrivo, lettore e il pulsante «Trova il codice del varco»; i passi della risposta si richiudono da soli;
  nel pannello 🗄 la chiave in grande con squadra e operatori; risposta senza modello in tre righe chiare.
- **Schema logico interattivo**: un clic su una tabella apre l'**analisi della tabella** (anche dalla Mappa e da
  «🔬 Analizza la tabella» nei Dettagli): *Dati* (righe a pagine di 25, ricerca in tutte le colonne, ordinamento,
  nome della riga collegata accanto a ogni chiave esterna, clic sulla chiave = salto alla tabella collegata, ← indietro),
  *Colonne* (distinti, NULL, min/max e valori più frequenti con le barre), *Relazioni* (in entrata e in uscita, con la
  prova e il salto), *SQL* (le query usate, da aprire nella console). Tutto passa dal tool di sola lettura.
