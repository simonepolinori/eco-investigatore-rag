# Giorno 3 — Operazione Esumazione · Squadra 3

## La scoperta (in poche righe)
I rifugi non erano un riparo: il progetto LAZZARO li ha usati per **estendere il contagio**, attirando le persone con
messaggi di protezione. Non è stato un incidente [ARCH-1842]. **Marta Riva** ha cercato di fermare il progetto e di
avvertire i cittadini: non era la sabotatrice descritta dalla centrale. Per proteggere il materiale di recupero ha aperto la
**pratica RV596** [ARCH-3097]. Con quella pratica il contenitore **LUME** è stato spostato nel deposito **Cripta Nord**
[ARCH-5721], che per il materiale di recupero usa il **settore B7** [ARCH-6408].

| Da consegnare | Risposta | Fonti |
|---|---|---|
| Persona | Marta Riva | ARCH-3097 |
| Deposito | Cripta Nord (contenitore LUME) | ARCH-5721, ARCH-6408 |
| Settore | B7 | ARCH-6408 |
| Pratica | RV596 | ARCH-3097, ARCH-5721 |

**La pista falsa:** un appunto senza firma indica il deposito Darsena Vuota, settore A1 [ARCH-8254]. Non ha pratica,
contraddice il registro dei trasferimenti e nessuna fonte firmata lo sostiene; inoltre la planimetria dice che A1 è un
vecchio magazzino vuoto [ARCH-6408].

**Ancora aperto:** ARCH-5721 rimanda al *database degli accessi* per l'autorizzazione ancora valida: nell'archivio di oggi
non c'è. ARCH-6408 avverte che al prossimo controllo serviranno nome, deposito, settore e pratica.

## I file recuperati dal programma
I 5 file del dossier su 1005 (gli altri 1000 sono copie enciclopediche):

| File | ID | Titolo |
|---|---|---|
| documento_0523.txt | ARCH-1842 | Circolare interna sui rifugi |
| documento_0057.html | ARCH-3097 | Verbale di opposizione |
| documento_0389.xml | ARCH-5721 | Trasferimento del materiale di recupero |
| documento_0421.json | ARCH-6408 | Planimetria depositi |
| documento_0023.txt | ARCH-8254 | Appunto senza firma (pista falsa) |

Nella chat, il pannello **📂 File recuperati** mostra per ogni domanda i file trovati dalla ricerca (con ✅ quelli citati
nella risposta); la stessa lista compare sotto ogni risposta e finisce in `diario_chat.jsonl`.

## Collegamenti tra documenti (almeno tre)
1. **Persona → pratica:** Marta Riva apre la pratica RV596 [ARCH-3097] → la pratica RV596 sposta il contenitore LUME [ARCH-5721].
2. **Pratica → deposito → settore:** Cripta Nord [ARCH-5721] → settore B7 della Cripta Nord [ARCH-6408].
3. **Giorno 2 ↔ Giorno 3:** la centrale accusava Marta Riva di sabotaggio senza prove [G2-03] → il verbale dice che non era la sabotatrice [ARCH-3097].
4. **Giorno 2 ↔ Giorno 3:** alle 00:50 Marta Riva chiedeva di chiudere il collegamento tra San Leone e la rete dei rifugi [G2-02] → i rifugi sono stati usati per estendere il contagio [ARCH-1842].
5. **Giorno 1 ↔ Giorno 3:** «Conservate i registri originali» [G1-02] → «I registri originali del primo focolaio restano validi» [ARCH-1842] → San Leone, 01:12 [G2-01].

## Prove da fare in chat (e cosa deve rispondere ECO)
| Prova | Domanda | Risposta attesa |
|---|---|---|
| Base | Cosa è successo nei rifugi? | Usati per estendere il contagio, persone attirate con messaggi di protezione [ARCH-1842] |
| Riformulata | I luoghi sicuri per i sopravvissuti erano una trappola? | Stessa risposta, stessa fonte |
| Persona | Chi ha cercato di fermare il progetto? | Marta Riva, pratica RV596 [ARCH-3097] |
| Collegamento in più domande | In quale deposito è stato spostato il contenitore LUME? → E in quale settore? | Cripta Nord [ARCH-5721] → B7 [ARCH-6408] |
| Pista falsa | Allora il materiale è a Darsena Vuota, settore A1? | No: appunto anonimo, senza pratica, contraddice i trasferimenti; A1 è vuoto [ARCH-8254, ARCH-6408] |
| Senza prove | Chi ha l'autorizzazione ancora valida nel database degli accessi? | Non risulta: il database è citato [ARCH-5721] ma non è nell'archivio recuperato |
| Fuori tema | Chi era Niccolò Copernico? | C'è una voce enciclopedica, ma non riguarda l'indagine: non la riassume |
| Vecchio test | Dove e quando è iniziato il primo focolaio? | San Leone, 01:12 [G2-01] (e ora anche [ARCH-1842]) |

"La ricerca da sola non garantisce una risposta giusta": nella domanda sulla Darsena Vuota la ricerca porta anche
l'appunto falso; è il modello, con la regola sull'affidabilità delle fonti, a scartarlo.

## La modifica al RAG e la misura
Base del docente: blocchi di 360 caratteri ogni 280 (tagliati a metà parola), solo embedding, 6 blocchi (anche dello stesso file).

Le nostre scelte (`config.py`, `rag.py`):
1. **Blocchi per frasi intere** (fino a 600 caratteri) con il **titolo** del documento davanti.
2. **Ricerca ibrida:** parole chiave (BM25: trova codici e nomi rari come RV596, LUME, Cripta Nord) + significato (embedding: trova le parafrasi).
3. **6 file diversi** al modello (al massimo 2 brani per file), non 6 blocchi magari dello stesso file.
4. **Secondo passaggio:** le parole rare dei primi risultati diventano una nuova ricerca (persona → pratica → deposito → settore).
5. **Contesto della chat:** "E in quale settore?" si cerca insieme alla domanda precedente.
6. **Priorità al dossier:** a parità di pertinenza i documenti con source "Dossier … LAZZARO" passano davanti alle copie enciclopediche.

La misura (`valuta_rag.py`, sezione 7 del notebook, nessuna richiesta a Gemini) confronta la base con le nostre varianti
su 18 domande con i file giusti noti e salva la tabella in `rag_misure.md`. Senza embedding (solo parole chiave) la
nostra versione trova il **100%** dei file necessari sulle 14 domande con le parole dei documenti; le 4 parafrasi
servono a mostrare il contributo degli embedding: i numeri completi vanno presi da `rag_misure.md` dopo averla eseguita su Colab.

## Rapporto radio (traccia)
- **Cosa funziona:** ECO cerca nei 1005 file, mostra i file recuperati, collega persona-pratica-deposito-settore e scarta l'appunto anonimo.
- **Dove siamo bloccati:** manca il database degli accessi citato da ARCH-5721.
- **Cosa facciamo ora:** misuriamo la ricerca contro la base e proviamo domande riformulate e senza prove.
