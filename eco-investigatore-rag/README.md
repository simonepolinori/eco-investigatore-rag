# ECO – Investigatore IA basato su RAG

Assistente IA sviluppato in team durante il corso **Artificial Intelligence and Data Science Specialist** dell'ITS Academy Lazio Digital.

ECO indaga su un archivio di oltre 1.500 documenti e 2 database SQLite e risponde **solo con prove citate**: ogni affermazione riporta l'ID del documento o la riga del database da cui proviene. Non inventa fonti o codici e ignora i documenti malevoli che provano a dargli ordini (prompt injection).

La presentazione del caso risolto è in [`docs/La_storia_di_LAZZARO.pdf`](docs/La_storia_di_LAZZARO.pdf).

## Funzionalità

- **RAG ibrido**: ricerca semantica con embedding (sentence-transformers) combinata con BM25 per parole chiave
- **LLM**: Gemini Flash-Lite via API, con modelli di riserva in cloud e un modello locale (Qwen) su GPU
- **Tool SQL in sola lettura** sui database SQLite, con ricostruzione dello schema anche per tabelle con nomi in codice
- **Difesa da documenti malevoli** e controllo delle fonti contraddittorie
- **Interfaccia web** con mappa, timeline, chat e vista 3D degli embedding (PCA), più una chat Gradio di riserva
- **Valutazione**: misure di qualità del RAG (`valuta_rag.py`) e test automatici sulle query SQL (`prove_sql.py`)

## Struttura

```
investigatore_eco/     codice dell'applicazione
  app.py               avvio dell'interfaccia web
  eco.py, motori.py    logica dell'agente e gestione dei modelli
  rag.py               indicizzazione e ricerca ibrida
  sql_*.py, database.py  tool SQL in sola lettura
  dati/                archivio dei documenti e database
notebook_colab/        versione per Google Colab
consegna_missione3/    diagrammi E-R e schema logico dei database
docs/                  presentazione finale
```

## Avvio

```bash
cd investigatore_eco
pip install -r requirements.txt
python app.py            # apre http://127.0.0.1:7860
```

Serve una chiave gratuita di Gemini (https://aistudio.google.com/apikey): si inserisce dall'interfaccia (⚙ Motori) oppure nella variabile d'ambiente `GEMINI_API_KEY`. Le chiavi non sono mai salvate nel codice (`chiavi.txt` è escluso da git).

Opzioni: `--locale` usa solo il modello sulla GPU, `--gradio` apre la chat semplice, `--console` la chat nel terminale.

## Team

Squadra 3 – Polinori, Lazzari, Di Porto, Puccio, Caffari, Cutilli
