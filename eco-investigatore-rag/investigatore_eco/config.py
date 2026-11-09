"""Configurazione dell'investigatore ECO (Giorno 4: motore 4.1 + interfaccia con mappa + tool SQL). Si cambia solo qui."""
import os
from pathlib import Path

# la memoria della GPU si frammenta meno (va impostato prima che PyTorch usi la GPU: config.py si importa per primo)
os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')

NOME = 'ECO'
SQUADRA = 3
GIORNO = 5                      # il giorno in corso: lo dice al modello (Giorno 5 · Operazione Ultima luce)

# --- Motore -------------------------------------------------------------------------------------
# 'gemini' = Gemini Flash-Lite via chiave API (principale), con Qwen sulla GPU come riserva automatica
# 'locale' = solo Qwen sulla GPU (niente internet)
MOTORE = 'auto'                 # 'auto' = GEMINI se c'è GEMINI_API_KEY; poi Groq, Cerebras, Grok (solo con la chiave)
PRIMA_GEMINI = True             # Gemini scrive le risposte; gli altri motori fanno solo da riserva
                                # oppure: 'groq' | 'grok' | 'gemini' | 'locale'
# Groq (console.groq.com, chiave GRATIS, molto veloce): la chiave NON va scritta qui. Mettetela nella variabile
# d'ambiente GROQ_API_KEY (PowerShell: $env:GROQ_API_KEY="gsk_..."), in Colab nei Secrets con nome GROQ_API_KEY.
GROQ_URL = 'https://api.groq.com/openai/v1'
MODELLO_GROQ = 'auto'           # 'auto' = il primo disponibile tra: Llama 4 Scout (30 000 token al minuto gratis: il
                                # prompt di ECO è lungo), Llama 3.3 70B, Kimi K2, GPT-OSS 120B... (diagnostica.py li elenca)
TIMEOUT_GROQ = 30               # secondi per una risposta
PAUSA_GROQ = 60                 # se tutti i modelli sono al limite (429) non si riprova Groq per 1 minuto
PAUSA_MODELLO = 60              # un modello al limite si lascia riposare 1 minuto e intanto si usa il successivo
MODELLI_PROVATI = 4             # quanti modelli Groq/Grok provare per una risposta prima di passare a Gemini
ATTESA_MAX = 30                 # limite gratuito AL MINUTO (429 «try again in 12s»): ECO aspetta fino a 30 s e riprova lo
                                # stesso modello invece di arrendersi (prima 8 s: sembrava che la chiave «scadesse»)
MAX_TOKENS_COMPATIBILI = 1000   # lunghezza massima di una risposta di Groq/Grok (i modelli Llama scrivono più di Gemini:
                                # con 700 le risposte lunghe si fermavano a metà frase). Groq è veloce: non rallenta.
CONTINUAZIONI = 2               # se la risposta arriva comunque al limite, ECO chiede al modello di continuare (fino a 2 volte)
# Aggiunto in fondo alle istruzioni solo per Groq/Grok: Llama tende a scrivere lungo, con titoli ed elenchi.
STILE_COMPATIBILI = ('\n\nSTILE DELLA RISPOSTA: vai dritto al punto, in italiano, con frasi brevi (di solito non più di '
                     '200 parole; se la domanda chiede un elenco completo fallo, ma una riga per voce). Niente titoli con #, '
                     'niente elenchi con l\'asterisco: paragrafi brevi o righe che iniziano con «- ». Orari, nomi e codici '
                     'vanno copiati esattamente come sono scritti nei documenti, senza arrotondare o spostare.')
# Token al minuto del piano gratuito di Groq: il prompt di ECO pesa circa 9 000 token, quindi per i modelli con un limite
# più basso ECO accorcia da sola la richiesta (prima la chat vecchia, poi catalogo e brani dell'archivio; regole,
# fascicolo e risultato SQL restano interi). Se Groq cambia i limiti, lo dice l'errore e ECO si adatta lo stesso.
LIMITI_TOKEN = {'meta-llama/llama-4-scout-17b-16e-instruct': 30000, 'llama-3.3-70b-versatile': 12000,
                'moonshotai/kimi-k2-instruct-0905': 10000, 'moonshotai/kimi-k2-instruct': 10000,
                'openai/gpt-oss-120b': 8000, 'openai/gpt-oss-20b': 8000, 'qwen/qwen3-32b': 6000,
                'meta-llama/llama-4-maverick-17b-128e-instruct': 6000, 'llama-3.1-8b-instant': 6000}
# Cerebras (cloud.cerebras.ai, chiave GRATIS «csk-…», molti token al giorno): riserva automatica quando Groq è al limite.
# Chiave nella variabile CEREBRAS_API_KEY, nei Secrets di Colab o incollata in ⚙ Motori (chiavi.txt).
CEREBRAS_URL = 'https://api.cerebras.ai/v1'
MODELLO_CEREBRAS = 'auto'       # 'auto' = il primo disponibile tra GPT-OSS 120B, Llama 3.3 70B, Qwen 3...
TIMEOUT_CEREBRAS = 30
PAUSA_CEREBRAS = 60
# Grok (xAI): la chiave NON va scritta qui. Createla su https://console.x.ai (API Keys) e mettetela nella variabile
# d'ambiente XAI_API_KEY (PowerShell: $env:XAI_API_KEY="xai-..."), in Colab nei Secrets con nome XAI_API_KEY.
GROK_URL = 'https://api.x.ai/v1'
MODELLO_GROK = 'auto'           # 'auto' = il modello Grok veloce più recente che la chiave vede (diagnostica.py li elenca)
TIMEOUT_GROK = 30               # secondi per una risposta
PAUSA_GROK = 120                # dopo "limite raggiunto" (429) non si riprova Grok per 2 minuti
RISERVA_GEMINI = True           # se Grok non risponde si prova Gemini (se c'è la sua chiave)

# Gemini: la chiave NON va scritta qui. Mettetela nella variabile d'ambiente GEMINI_API_KEY
# (avvia_eco.bat la chiede la prima volta) oppure, in Colab, nei Secrets (icona della chiave) con nome GEMINI_API_KEY.
MODELLO_GEMINI = 'gemini-flash-lite-latest'   # alias del Flash-Lite più recente; diagnostica.py elenca i nomi esatti
PENSIERO_GEMINI = 'minimal'     # ragionamento nascosto al minimo = risposte più rapide; se il modello non lo accetta,
                                # ECO lo toglie da solo. None = impostazione del modello
MODELLI_GEMINI_RISERVA = ['gemini-2.5-flash-lite', 'gemini-flash-latest', 'gemini-2.5-flash', 'gemini-2.0-flash-lite', 'gemini-2.0-flash']
                                # se Google risponde «sovraccarico» (503) o è lento ECO prova questi, con la stessa chiave
TIMEOUT_GEMINI = 25             # secondi per tentativo: di solito Flash-Lite risponde in 2-4 s; oltre, si prova il
                                # modello di riserva
TEMPO_MAX_GEMINI = 60           # secondi in tutto: se Google è sovraccarico ECO riprova a giro i modelli, con brevi
                                # pause, finché ne risponde uno; oltre, si passa a Qwen o si avvisa
PAUSA_GEMINI = 300              # (non più usato: dopo un 429 si mette in pausa solo QUEL modello, per il tempo detto da Google)

# Riserva locale: Qwen3-4B-Instruct-2507 in float16 su GPU NVIDIA (circa 8 GB di memoria video).
# Senza GPU la riserva resta spenta e ECO usa solo Gemini.
RISERVA_LOCALE = True
MODELLO_LOCALE = 'Qwen/Qwen3-4B-Instruct-2507'
CARICA_LOCALE_ALL_AVVIO = True  # app.py carica Qwen in sottofondo: se Gemini cade, la riserva è già pronta

# --- Come scrive ----------------------------------------------------------------------------------
TEMPERATURA = 0.7               # varietà delle parole (consigliata per Qwen3-Instruct-2507: 0.7)
TOP_P = 0.8
MAX_TOKENS = 1200               # risposta più lunga possibile (Gemini): basta per elencare e descrivere tutti i file
MAX_TOKENS_LOCALE = 320         # Qwen sulla GPU è più lento (~15-20 parole/s su T4): risposte più corte
QWEN_PEZZO = 1024               # Qwen legge il prompt a pezzi di 1024 token: niente memoria esaurita sulla T4 con prompt lunghi

# --- Memoria della conversazione -----------------------------------------------------------------
MEMORIA_TURNI = 20              # quanti scambi precedenti (domanda + risposta) rilegge il modello
MEMORIA_FILE = 15               # quanti file dell'archivio già emersi restano nel prompt (i più recenti)
SALVA_CHAT = True               # la chat resta nel browser anche se si ricarica la pagina (elenco a sinistra)

CHIACCHIERE_VELOCI = True       # «ciao», «grazie», «chi sei?»: niente ricerca e prompt corto (risposta in 1-2 s)

# --- Rete di sicurezza ---------------------------------------------------------------------------
CONTROLLO_FONTI = True          # se la risposta cita un ID che non esiste, il modello la riscrive una volta
SEGNALA_SOSPETTI = True         # i documenti con ordini rivolti all'AI vengono marcati come sospetti nell'archivio
MOSTRA_MOTORE = False          # False = sotto la risposta non compare il nome del modello (Gemini/Qwen) né il contatore richieste
MOSTRA_DETTAGLI = True          # sotto ogni risposta: motore, tempo, fonti citate, file recuperati

# --- RAG: scansione e ricerca nell'archivio digitale (Giorno 3) ----------------------------------
# Scansione (una volta, all'avvio): ogni file prende punti da ID, fonte, licenza, contenuto e collegamenti.
SCANSIONE_PREFISSI_STORIA = ('ARCH', 'LX3')   # ID dei documenti del dossier (ARCH) e dei registri della rete (LX3)
SCANSIONE_PREFISSI_RUMORE = ('WIKI',)   # ID delle copie enciclopediche
SCANSIONE_SOGLIA_STORIA = 3     # da 3 punti in su: file della storia
SCANSIONE_SOGLIA_RUMORE = -2    # da -2 in giù: rumore. In mezzo: "incerto" (va al modello con l'avviso)
CATALOGO_TESTO_MAX = 6000       # se i file della storia insieme stanno sotto questi caratteri, il catalogo li
                                # contiene interi (qui 5 file, ~1700 caratteri); altrimenti solo ID e titoli
# Ricerca (a ogni domanda)
RAG_EMBEDDING = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'   # lo stesso della base del docente
RAG_BLOCCO = 600                # caratteri massimi per blocco (frasi intere); base del docente: 360 tagliati a metà
RAG_SOVRAPPOSIZIONE = 1         # frasi ripetute tra un blocco e il successivo
RAG_RISULTATI = 8               # quanti FILE diversi passano al modello (al massimo 2 brani per file);
                                # le copie della stessa fonte occupano UN posto solo (con il conteggio delle copie)
RAG_IBRIDA = True               # parole chiave (BM25) + significato (embedding); False = solo BM25
RAG_SECONDO_PASSAGGIO = True    # le parole rare dei primi risultati (codici, nomi) diventano una seconda ricerca
RAG_CONTESTO_CHAT = True        # le domande brevi si cercano insieme alla domanda precedente
RAG_PAROLA_RARA = 3             # "rara" = compare in al massimo 3 blocchi di tutto l'archivio
RAG_PASSAGGI = 3                # passaggi della ricerca: 1 = domanda, 2 e 3 = salti con le parole rare
                                # (Ruggine → pratica M362 → lotto K391 → armadio)
RAG_POSTI_COLLEGATI = 2         # posti garantiti ai documenti trovati seguendo un codice (anelli della catena)
RAG_MAX_PER_TIPO = 2            # al massimo 2 file per tipo di documento molto ripetuto (100 «Scheda di reparto»...)
RAG_PESO_ALTRO_GIORNO = 0.35    # se la domanda nomina un giorno operativo, i documenti di un altro giorno valgono così
RAG_FILTRO_STORIA = True        # al modello passano solo i file della storia (e gli incerti); il rumore solo come titolo
RAG_INTENTO_EMBEDDING = True    # capisce con gli embedding se la domanda CHIEDE i file rumore o file "a caso" (non solo da parole chiave)
RAG_SOGLIA_RUMORE = 0.55        # somiglianza minima (coseno) con le richieste-tipo "dammi file che non riguardano la storia"
RAG_MARGINE_RUMORE = 0.04       # deve battere le domande sulla storia di almeno questo margine
RAG_SOGLIA_CASO = 0.55          # somiglianza minima con "scegli dei documenti a caso"
                                # le soglie vanno controllate con calibra_intenti.py (stampa le somiglianze di domande di prova)
RAG_RUMORE_PERTINENTE = True    # se la domanda parla proprio di un file che non riguarda la storia (es. «chi è Giulio
                                # Cesare?»), quel file passa al modello: risponde da lì, dicendo che non riguarda l'indagine
RAG_TESTO_VOCE = 2500           # ...e il modello ne riceve il testo dall'inizio, fino a questi caratteri
RAG_SOGLIA_VOCE = 0.60          # ...anche per significato: somiglianza minima (coseno) del file con la domanda
RAG_MARGINE_VOCE = 0.10         # ...e di quanto deve battere il file della storia più vicino
RAG_SCARTATI_MOSTRATI = 3       # quanti file rumore "scartati" mostrare per domanda

# --- Interfaccia con la mappa (web.py + interfaccia.html) -------------------------------------
# La mappa, la timeline, le ipotesi, i documenti malevoli e la scheda degli imprevisti li calcola logica.py
# (le regole sui documenti del fascicolo). Le RISPOSTE in chat le scrive il modello (eco.py: Gemini o Qwen + RAG).
OPERAZIONE = 'Operazione Ultima luce'

# --- Tool SQL del Giorno 4 (database.py sceglie la missione: sql_varco.py e sql_lete.py) ----------------
# Lo ZIP del giorno 4 (Squadra_3_2.zip) contiene accessi.sqlite: caricandolo dall'Archivio finisce in dati/database/.
# Il tool è di SOLA LETTURA: file aperto read-only, solo SELECT sulle tre tabelle, limite di istruzioni, max 50 righe.
DATABASE_NOME = 'accessi.sqlite'
DATA_MISSIONE = '2031-10-12 06:00'   # «Data della missione: 12 ottobre 2031, ore 06:00» (permesso attivo e non scaduto)
# Giorno 4 · seconda missione «Il primo respiro» (Squadra_3_3.zip): archivio_recuperato.sqlite, 14 tabelle in codice
# (sql_lete.py). I parametri li può aggiornare la centrale: pannello 🗄 Schema E/R oppure «la centrale comunica: ...» in chat
# (vengono salvati in dati/database/missione_lete.json; questi sono quelli della scheda MISSIONE.xlsx).
DATABASE_LETE = 'archivio_recuperato.sqlite'
# Parametri UFFICIALI della missione (prova finale: la centrale ha aggiornato arrivo e canale del lettore del veicolo).
# Con questi la soluzione è UNICA: Unità 3-Ossidiana, Mara Belli (SANITARIO) + Nino Conti (SICUREZZA), terminale
# Canale Kappa, chiave 108958 (la risposta attesa dal docente). I parametri della scheda iniziale (12:00, canale non
# comunicato) restano in PARAMETRI_LETE_SCHEDA: ECO li usa per il confronto («E se arriviamo alle 12:00?»).
PARAMETRI_LETE = {'istante': '2026-11-04 12:30',   # arrivo aggiornato dalla centrale: 4 novembre 2026, ore 12:30
                  'varco': 'V-38', 'sito': 'Archivio Lete',
                  'canale': 'Canale Kappa'}          # canale del lettore del veicolo comunicato dalla centrale
PARAMETRI_LETE_SCHEDA = {'istante': '2026-11-04 12:00', 'varco': 'V-38', 'sito': 'Archivio Lete', 'canale': ''}
MISSIONE_SQL = 'auto'           # 'lete' | 'varco' | 'auto' (= la scelta fatta nell'interfaccia, altrimenti la più recente)
SQL_PASSI = 2                   # quante query può proporre il modello per una domanda (il risultato di ognuna gli torna)
MODELLO = MODELLO_LOCALE        # nome mostrato nel pannello dei motori
SOLO_ESTRATTIVO = False         # usati da logica.py (solo per i dati della mappa: logica non genera testo qui)
RISPONDE_LLM = False
SECONDA_OPINIONE = False
GIUDICE = False
BUDGET = 1.6
BUDGET_APERTA = 6.0
MAX_TOKENS_APERTA = 100
MAX_FRASI_APERTA = 40

# --- Cartelle ------------------------------------------------------------------------------------
CARTELLA = Path(__file__).resolve().parent
DATI = CARTELLA / 'dati'        # dati/giorno1, dati/giorno2, dati/imprevisti_g2, dati/archivio_g3, ...
DIARIO = CARTELLA / 'diario_chat.jsonl'
CONTATORE = CARTELLA / 'contatore_gemini.json'   # richieste a Gemini di oggi (il piano gratuito ha un limite giornaliero)
PORTA = 7860
