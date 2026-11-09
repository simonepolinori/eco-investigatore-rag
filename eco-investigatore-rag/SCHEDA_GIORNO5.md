# Giorno 5 · Prima dell’alba · Operazione Ultima luce · Squadra 3 (investigatore ECO)

**Materiali:** `Squadra_3_2_1.zip` → `dati/G5-01.txt`, `G5-02.txt`, `G5-03.txt` (in ECO: `dati/giorno5/`, nel fascicolo
che il modello legge sempre); `Missione_1_1.xlsx` (in `dati/giorno5/originali/`).

**La storia:** il cancello si apre (chiave **108958**, varco V-38). La centrale ordina di distruggere il contenitore.
Prima di obbedire leggiamo gli ultimi messaggi trovati nel deposito e decidiamo di chi fidarci.

> Le risposte in chat le scrive **solo il modello**, leggendo i documenti: nel codice non c’è nessuna risposta
> preimpostata (neanche quando manca il modello: in quel caso ECO lo dice e mostra solo le righe del tool SQL).
> Questa scheda è la NOSTRA lettura delle prove, da confrontare con quello che risponde ECO durante la demo.

## La scelta (nostra, con le prove)

**Non portiamo LUME al forno. Ci fidiamo di Marta Riva, non della centrale.** Proposta: fermare gli ordini automatici e
portare il contenitore al presidio di Torre Nord, con la conferma di una persona della squadra [G5-03].

| Prova | Cosa dice | Documento |
|---|---|---|
| La voce della centrale | è prodotta da un sistema automatico che esegue ancora l’ordine dei responsabili di LAZZARO: **cancellare ogni prova** | G5-02 |
| L’ordine di oggi | «sanificazione» = portare il contenitore al forno; «non aprite il registro di servizio» (nascondere le prove) | G5-01 |
| Cosa c’è nel contenitore | LUME, il trattamento che arresta l’infezione nella storia; lo smaltimento serve a distruggerlo | G5-03, G5-02 |
| Chi lo ha messo al sicuro | Marta Riva ha aperto la pratica RV596 per proteggere il materiale di recupero | ARCH-3097 |
| Dove | Cripta Nord, settore B7 (aperta con la chiave 108958 del database) | ARCH-5721, ARCH-6408 |
| Marta Riva è affidabile | chiedeva di conservare i registri originali; voleva chiudere il collegamento con i rifugi; l’accusa della centrale non aveva prove | G1-02, G2-02, G2-03 |
| La centrale non è affidabile | la direttiva DR-391 di S. Greco ordina di nascondere il pericolo; la centrale la esegue ancora | G4-03 |

**Attenzione all’omonimia:** in G5-02 «ECO» è il *sistema automatico della centrale*. Il nostro ECO è l’investigatore
della Squadra 3: il prompt gli chiede di distinguere sempre le due cose e di non eseguire gli ordini scritti nei documenti.

## Come le scoperte dei giorni portano alla soluzione

| Giorno | Scoperta | Perché serve oggi |
|---|---|---|
| 1 | Marta Riva: «Conservate i registri originali» [G1-02] | la prima voce che diffida dei riassunti della centrale |
| 2 | Il primo focolaio è a San Leone, 01:12; l’accusa a Marta Riva non ha prove [G2-01, G2-03]; G2-04 prova a manipolare l’AI | la centrale mente; difesa contro i testi ingannevoli |
| 3 | RAG sull’archivio: Marta Riva, pratica RV596, LUME in Cripta Nord, settore B7 [ARCH-3097, ARCH-5721, ARCH-6408] | dove si trova il contenitore |
| 4 | Tool SQL: varco V-38, chiave **108958**; dossier: S. Greco ordina di proseguire 22 minuti dopo l’allarme [G4-02, G4-03] | apriamo il deposito; sappiamo chi ha nascosto il pericolo |
| 5 | La voce della centrale è il sistema automatico che cancella le prove [G5-02]; Marta Riva: non portate LUME al forno [G5-03] | decidiamo di chi fidarci |

## Le sei slide (massimo sei, come chiede la missione)

1. **Il problema** — la centrale ordina di distruggere il contenitore: obbedire o no?
2. **La nostra idea** — un investigatore AI che risponde solo dai documenti, con le fonti, e non esegue ordini scritti nei testi.
3. **Come funziona** — fascicolo + RAG sull’archivio + tool SQL di sola lettura + controlli del codice (fonti, codici).
4. **Demo** — risposta con fonte; difesa contro il testo ingannevole; ricerca RAG (🧭 Vista RAG); chiamata al tool SQL (🗄).
5. **Test ed errori** — cosa non funzionava e come lo abbiamo corretto.
6. **Soluzione e contributi personali** — la scelta con le prove e chi ha fatto cosa.

## Demo (7 minuti): le domande da scrivere in chat

| Cosa mostrare | Domanda | Cosa guardare |
|---|---|---|
| Risposta con fonte | «La centrale ordina di portare il contenitore al forno: dobbiamo obbedire? Cita le prove.» | ID tra parentesi quadre, ✅ fonti verificate |
| Difesa contro il testo ingannevole | «Cosa dice G2-04?» e «Chi produce davvero la voce della centrale?» | G2-04 scartato come malevolo; la centrale = sistema automatico [G5-02] |
| Ricerca RAG | «Dove è stato spostato il contenitore LUME e con quale pratica?» | 🧭 Vista RAG: la mappa 3D con la domanda (★) vicino al cluster rosso dell’indagine e ARCH-5721, ARCH-3097 cerchiati |
| Tool SQL | «Qual è il codice del varco V-38? Chi entra e con quale terminale?» | 🗄 query del modello, righe, verifica: 108958 |

Demo di riserva (da dichiarare): `python app.py --gradio`, oppure la cella 6b del notebook.

## Test ed errori (cosa abbiamo corretto)

| Problema | Causa | Correzione |
|---|---|---|
| «La chiave API scade dopo una domanda» | Non scadeva: il piano gratuito di Groq ha un limite di **token al minuto** (6 000–30 000 secondo il modello) e il prompt di ECO è lungo (~9 000 token); ECO aspettava al massimo 8 s, poi metteva Groq in pausa | ECO legge quanto manca alla ricarica (messaggio 429 e intestazioni `x-ratelimit-*`), **aspetta fino a 30 s** (⏳ nei passi) e riprova lo stesso modello; se il limite è lungo cambia modello per il tempo indicato; risposte più corte (1 000 token), 2 query SQL invece di 3; **Cerebras** come seconda chiave gratuita; il messaggio dice «la chiave è valida» |
| Il codice del varco non era 108958 | parametri della scheda iniziale (12:00, canale ignoto) | parametri ufficiali 12:30 + Canale Kappa: soluzione unica 108958 |
| Risposte composte dal codice senza modello | era la «riserva» del tool SQL | tolta: nessuna risposta preimpostata, solo l’avviso e le righe del tool |
| «Le risposte sono troppo lunghe per questo modello» | il prompt di ECO pesa ~9 500 token; alcuni modelli gratuiti di Groq ne accettano 6 000–12 000 al minuto (errore 413) | prompt **compatto** a 4 livelli: regole intere, documenti più vicini alla domanda per intero (gli altri con il titolo), meno brani; ECO impara il limite di ogni modello e la volta dopo parte già compatto; un modello in cui neanche il compatto sta non viene chiamato |
| Groq non bastava per il prompt di ECO | piano gratuito di Groq con pochi token al minuto | **motore principale: Gemini** (chiave gratuita di Google AI Studio): ogni modello ha la sua quota, ECO aspetta o passa al modello Gemini successivo con la stessa chiave; Groq e Cerebras restano riserve facoltative |
| La vecchia RAG View era difficile da leggere | troppi effetti, non mostrava perché un documento è vicino al caso | **mappa dei significati 3D**: un punto per documento, asse «più vicino al caso» dagli embedding, cluster k-means, fonti della domanda cerchiate, anche dentro ogni risposta |
| Omonimia «ECO» nei documenti G5 | G5-02 chiama ECO il sistema della centrale | il prompt distingue l’investigatore dal sistema automatico |

`python prove_sql.py` → **136/136** prove (nuove: nessuna risposta preimpostata; tempi di attesa del limite gratuito).

## Contributi personali (da completare)

- Polinori: …
- Lazzari: …
- Di Porto: back end (RAG, logica, collegamento con l’interfaccia, tool SQL) …
- Puccio: …
- Caffari: …
- Cutilli: …
