"""I motori di ECO: Groq (chiave gratis, GROQ_API_KEY), Grok di xAI (XAI_API_KEY), Gemini Flash-Lite (GEMINI_API_KEY)
e Qwen3-4B-Instruct-2507 sulla GPU.

Con MOTORE = 'auto' (config.py) ECO usa Groq se c'è la sua chiave, poi Grok, poi Gemini; se il primo motore non
risponde prova gli altri e poi la riserva locale.

rispondi() prova Gemini; se non c'è la chiave, se internet cade, se il limite gratuito è finito o se Gemini
non risponde in tempo, passa da solo a Qwen in locale con lo stesso prompt e la stessa conversazione.
PyTorch viene importato solo per la riserva locale: senza GPU ECO funziona lo stesso con Gemini.
"""
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import config


class MotoreErrore(Exception):
    pass


# ================================ GEMINI ==========================================================
_gemini = {'client': None, 'chiave': None, 'pausa_fino': 0.0, 'pause_modello': {}}   # ogni modello Gemini ha la sua quota


def pulisci_chiave(k):
    """Toglie spazi, a capo, virgolette e caratteri invisibili ovunque siano (anche in mezzo)."""
    import re
    return re.sub(r'[\s​‌‍⁠﻿"\'`<>«»]', '', k or '')


# ================================ CHIAVI SALVATE NEL PROGETTO =====================================
# Oltre alle variabili d'ambiente e ai Secrets di Colab, le chiavi si possono incollare UNA volta nell'interfaccia
# (⚙ Motori → «Chiave Groq gratuita»): finiscono in chiavi.txt accanto al codice (escluso da git, mai nel codice).
FILE_CHIAVI = config.CARTELLA / 'chiavi.txt'


def chiavi_salvate():
    """{'GROQ_API_KEY': 'gsk_...', ...} da chiavi.txt (righe NOME=valore)."""
    out = {}
    try:
        for riga in FILE_CHIAVI.read_text(encoding='utf-8').splitlines():
            if '=' in riga and not riga.strip().startswith('#'):
                k, v = riga.split('=', 1)
                out[k.strip()] = pulisci_chiave(v)
    except OSError:
        pass
    return out


def salva_chiave(variabile, valore):
    """Salva la chiave in chiavi.txt, la mette nell'ambiente e fa ripartire il motore con la chiave nuova."""
    valore = pulisci_chiave(valore)
    tutte = chiavi_salvate()
    tutte[variabile] = valore
    FILE_CHIAVI.write_text('# chiavi API di ECO (non condividete questo file)\n' +
                           ''.join(f'{k}={v}\n' for k, v in tutte.items() if v), encoding='utf-8')
    os.environ[variabile] = valore
    for m in COMPATIBILI.values():
        if variabile in m.variabili:
            m.stato.update(chiave=None, modelli=None, modello=None, pausa_fino=0.0, pause_modello={})
    if variabile in ('GEMINI_API_KEY', 'GOOGLE_API_KEY'):
        _gemini.update(chiave=None, client=None, pausa_fino=0.0)
    return valore


def chiave_gemini():
    """La chiave arriva dalla variabile d'ambiente GEMINI_API_KEY o, in Colab, dai Secrets. Mai dal codice."""
    if _gemini['chiave']:
        return _gemini['chiave']
    k = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY') or chiavi_salvate().get('GEMINI_API_KEY')
    if not k:
        try:
            from google.colab import userdata  # solo in Colab
            k = userdata.get('GEMINI_API_KEY')
        except Exception:
            k = None
    _gemini['chiave'] = pulisci_chiave(k) or None
    return _gemini['chiave']


def messaggio_google(e):
    """Il messaggio originale di Google, senza la chiave."""
    import re
    m = getattr(e, 'message', None) or str(e)
    return re.sub(r'AIza[0-9A-Za-z_\-]{10,}', '<chiave>', str(m))[:220]


def _client():
    if _gemini['client'] is None:
        from google import genai
        from google.genai import types
        _gemini['client'] = genai.Client(api_key=chiave_gemini(), http_options=types.HttpOptions(
            timeout=int(config.TIMEOUT_GEMINI * 1000)))   # niente ripetizioni automatiche: se Google è lento o
                                                           # sovraccarico ECO passa subito al modello di riserva
    return _gemini['client']


def gemini_utilizzabile():
    if not chiave_gemini():
        return False, 'Manca la chiave Gemini (GEMINI_API_KEY).'
    attesa = _gemini['pausa_fino'] - time.time()
    if attesa > 0:
        return False, f'Gemini: limite gratuito raggiunto su tutti i modelli (la chiave è valida), si libera tra {durata(attesa)}.'
    return True, ''


def _oggi_pacifico():   # il limite giornaliero di Gemini riparte a mezzanotte, ora del Pacifico
    return datetime.now(timezone(timedelta(hours=-8))).strftime('%Y-%m-%d')


def conta_richiesta_gemini():
    dati = richieste_gemini_oggi(con_data=True)
    dati['richieste'] += 1
    try:
        config.CONTATORE.write_text(json.dumps(dati), encoding='utf-8')
    except OSError:
        pass
    return dati['richieste']


def richieste_gemini_oggi(con_data=False):
    oggi = _oggi_pacifico()
    try:
        dati = json.loads(config.CONTATORE.read_text(encoding='utf-8'))
        if dati.get('data') != oggi:
            raise ValueError
    except (OSError, ValueError):
        dati = {'data': oggi, 'richieste': 0}
    return dati if con_data else dati['richieste']


_SENZA_PENSIERO = set()          # modelli che non accettano PENSIERO_GEMINI (si chiama senza solo per loro)


def stream_gemini(sistema, messaggi, max_tokens=None, modello=None, temperatura=None):
    from google.genai import types
    contenuti = [types.Content(role='model' if m['role'] == 'assistant' else 'user', parts=[types.Part(text=m['content'])])
                 for m in messaggi]
    cfg = dict(system_instruction=sistema, temperature=config.TEMPERATURA if temperatura is None else temperatura, top_p=config.TOP_P,
               max_output_tokens=max_tokens or config.MAX_TOKENS)
    if config.PENSIERO_GEMINI is not None and (modello or config.MODELLO_GEMINI) not in _SENZA_PENSIERO:
        p = config.PENSIERO_GEMINI
        try:
            cfg['thinking_config'] = (types.ThinkingConfig(thinking_budget=p) if isinstance(p, int)
                                      else types.ThinkingConfig(thinking_level=p))
        except Exception:          # versione vecchia di google-genai che non conosce l'impostazione: si va senza
            config.PENSIERO_GEMINI = None
    conta_richiesta_gemini()
    for pezzo in _client().models.generate_content_stream(model=modello or config.MODELLO_GEMINI, contents=contenuti,
                                                          config=types.GenerateContentConfig(**cfg)):
        t = pezzo.text
        if t:
            yield t


def modelli_flash_lite():
    """I modelli Flash-Lite che la chiave può usare, dal più adatto al meno adatto
    (prima le versioni stabili, poi le più recenti)."""
    import re
    nomi = []
    for m in _client().models.list():
        n = (m.name or '').replace('models/', '')
        azioni = m.supported_actions or []
        if 'flash-lite' not in n or (azioni and 'generateContent' not in azioni):
            continue
        if any(x in n for x in ('tts', 'image', 'live', 'audio', 'embedding')):
            continue
        nomi.append(n)

    def ordine(n):
        v = re.search(r'gemini-(\d+(?:\.\d+)?)', n)
        instabile = any(x in n for x in ('preview', 'exp'))
        return (n.endswith('-latest'), not instabile, float(v.group(1)) if v else 0.0, n)

    return sorted(nomi, key=ordine, reverse=True)


def correggi_modello():
    """Se il nome in config.py non esiste, sceglie da solo il miglior Flash-Lite disponibile. True se l'ha trovato."""
    try:
        candidati = [n for n in modelli_flash_lite() if n != config.MODELLO_GEMINI]
    except Exception:
        return False
    if not candidati:
        return False
    print(f'Gemini: il modello «{config.MODELLO_GEMINI}» non esiste per questa chiave, uso «{candidati[0]}».')
    config.MODELLO_GEMINI = candidati[0]
    return True


def spiega_errore_gemini(e):
    """Traduce l'errore in una frase per la squadra; dopo un 429 mette Gemini in pausa."""
    codice = getattr(e, 'code', None)
    testo = str(e)
    if codice == 429 or 'RESOURCE_EXHAUSTED' in testo:
        attesa = attesa_da(testo)
        giorno = 'al giorno' if re.search(r'PerDay|per day', testo, re.I) else 'al minuto'
        return (f'Gemini: limite gratuito {giorno} raggiunto (la chiave è valida, non è scaduta)'
                + (f'; si libera tra {durata(attesa)}.' if attesa else '.'))
    if codice in (401, 403) or 'API_KEY_INVALID' in testo or 'API key not valid' in testo:
        k = chiave_gemini() or ''
        return (f'Gemini ha rifiutato la chiave in uso ({len(k)} caratteri, finisce con «{k[-4:]}»). '
                f'Messaggio di Google: «{messaggio_google(e)}»')
    if 'location is not supported' in testo.lower():
        return 'Gemini: Google dice che il servizio non è disponibile da questa posizione.'
    if codice in (500, 502, 503, 504) or 'UNAVAILABLE' in testo or 'high demand' in testo:
        return ('Gemini è sovraccarico in questo momento (errore temporaneo di Google, anche con i modelli di riserva): '
                'riprovate tra qualche secondo.')
    if codice == 404:
        return (f'Gemini: la chiave funziona, ma il MODELLO «{config.MODELLO_GEMINI}» non esiste '
                '(python diagnostica.py elenca i nomi giusti).')
    nome = type(e).__name__
    if 'Timeout' in nome or 'timed out' in testo.lower():
        return f'Gemini non ha risposto entro {config.TIMEOUT_GEMINI} s.'
    if 'Connect' in nome or 'getaddrinfo' in testo or 'Network' in nome:
        return 'Gemini non raggiungibile (connessione a internet?).'
    return f'Gemini: errore {codice or nome} ({testo[:160]}).'


# ================================ QWEN LOCALE ====================================================
_locale = {'tokenizer': None, 'modello': None, 'errore': None, 'carica': threading.Lock(), 'gpu': None}
DEV = 'cuda'


def controlla_gpu():
    """Errore chiaro se manca PyTorch con CUDA o la GPU NVIDIA."""
    try:
        import torch
    except ImportError:
        raise MotoreErrore('PyTorch non è installato: la riserva locale serve solo su un PC con GPU NVIDIA.')
    if torch.cuda.is_available():
        return torch.cuda.get_device_name(0)
    if torch.version.cuda is None:
        raise MotoreErrore('PyTorch è la versione solo CPU: per la riserva locale serve PyTorch con CUDA (README).')
    raise MotoreErrore('PyTorch non trova la GPU NVIDIA (controlla nvidia-smi e i driver).')


def avvia_locale():
    """Carica Qwen in float16 sulla GPU (la prima volta scarica circa 8 GB). Restituisce True se è pronto."""
    with _locale['carica']:
        if _locale['modello'] is not None:
            return True
        try:
            nome_gpu = controlla_gpu()
            import torch
            import transformers
            from packaging import version
            from transformers import AutoModelForCausalLM, AutoTokenizer
            print(f'Riserva locale: carico {config.MODELLO_LOCALE} su {nome_gpu}...')
            tv = version.parse(transformers.__version__)
            if tv < version.parse('4.51'):
                raise MotoreErrore(f'transformers {transformers.__version__} è troppo vecchio per Qwen3: '
                                   'pip install -U transformers')
            kw = {'dtype' if tv >= version.parse('4.56') else 'torch_dtype': torch.float16, 'attn_implementation': 'sdpa'}
            tok = AutoTokenizer.from_pretrained(config.MODELLO_LOCALE)
            mod = AutoModelForCausalLM.from_pretrained(config.MODELLO_LOCALE, **kw).to(DEV).eval()
            _locale.update(tokenizer=tok, modello=mod, gpu=nome_gpu, errore=None)
            ''.join(stream_locale('Rispondi in una parola.', [{'role': 'user', 'content': 'Ciao'}], max_tokens=4))
            print(f'Riserva locale pronta: {config.MODELLO_LOCALE} su {nome_gpu} '
                  f'({torch.cuda.memory_allocated() / 2**30:.1f} GB)')
            return True
        except Exception as e:
            _locale['errore'] = str(e) if isinstance(e, MotoreErrore) else f'{type(e).__name__}: {e}'
            print('Riserva locale non disponibile:', _locale['errore'])
            return False


def avvia_locale_in_sottofondo():
    threading.Thread(target=avvia_locale, daemon=True).start()


def locale_pronto():
    return _locale['modello'] is not None


def _leggi_a_pezzi(mod, ids, pezzo):
    """Legge il prompt a pezzi di `pezzo` token e restituisce la memoria (KV cache) di tutto tranne l'ultimo token.
    Così la GPU non deve mai calcolare l'attenzione di migliaia di token tutti insieme (servirebbero ~3 GB in più
    su una T4 con un prompt di 7000 token): il risultato è identico, la memoria usata molto più piccola."""
    from transformers import DynamicCache
    cache = DynamicCache()
    n = ids.shape[1]
    for i in range(0, n - 1, pezzo):
        j = min(i + pezzo, n - 1)
        try:
            out = mod(input_ids=ids[:, i:j], past_key_values=cache, use_cache=True, logits_to_keep=1)
        except TypeError:                       # versioni di transformers senza logits_to_keep
            out = mod(input_ids=ids[:, i:j], past_key_values=cache, use_cache=True)
        cache = out.past_key_values
        del out
    return cache


def stream_locale(sistema, messaggi, max_tokens=None, temperatura=None):
    import torch
    from transformers import TextIteratorStreamer
    tok, mod = _locale['tokenizer'], _locale['modello']
    errore = []

    def prepara(msgs, pezzo):
        testo = tok.apply_chat_template([{'role': 'system', 'content': sistema}] + msgs,
                                        tokenize=False, add_generation_prompt=True)
        dati = tok(testo, return_tensors='pt').to(DEV)
        kw = dict(**dati, max_new_tokens=max_tokens or config.MAX_TOKENS_LOCALE, do_sample=True,
                  temperature=max(.05, config.TEMPERATURA if temperatura is None else temperatura), top_p=config.TOP_P, top_k=20, pad_token_id=tok.eos_token_id)
        if dati['input_ids'].shape[1] > pezzo:
            with torch.inference_mode():
                kw['past_key_values'] = _leggi_a_pezzi(mod, dati['input_ids'], pezzo)
        return kw

    # 1° tentativo: tutto il prompt, letto a pezzi da 1024 token; se la GPU finisce la memoria si libera e si riprova
    # con pezzi più piccoli e solo l'ultimo scambio della conversazione (il fascicolo e i brani restano interi)
    tentativi = [(messaggi, config.QWEN_PEZZO), (messaggi[-1:], 256)]
    for k, (msgs, pezzo) in enumerate(tentativi):
        try:
            kw = prepara(msgs, pezzo)
            break
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            if k == len(tentativi) - 1:
                raise MotoreErrore('la GPU ha finito la memoria anche leggendo il prompt a pezzi: chiudete altri '
                                   'programmi o notebook che usano la GPU, oppure usate Gemini.')
    st = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True, timeout=120)
    kw['streamer'] = st

    def lavora():
        try:
            with torch.inference_mode():
                mod.generate(**kw)
        except Exception as e:
            errore.append(e)
            st.end()
        finally:
            kw.pop('past_key_values', None)
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    threading.Thread(target=lavora, daemon=True).start()
    for t in st:
        if t:
            yield t
    if errore:
        raise errore[0]


# ================================ GROQ e GROK: API compatibili con OpenAI ========================
# Due servizi diversi con lo stesso formato (chat/completions):
#   - GROQ  (console.groq.com, chiave gratis, molto veloce, modelli Llama/Kimi/Qwen)  → variabile GROQ_API_KEY
#   - GROK  (console.x.ai, il modello di xAI, a pagamento)                            → variabile XAI_API_KEY
# Le chiavi NON vanno nel codice: variabile d'ambiente (PowerShell: $env:GROQ_API_KEY="gsk_...") o Secrets di Colab.
class ErroreCompatibile(Exception):
    def __init__(self, codice, messaggio):
        super().__init__(messaggio)
        self.code, self.message = codice, messaggio


ErroreGrok = ErroreCompatibile          # nome di prima (lo usano altri file)


def stima_token(testo):
    """Stima prudente dei token (italiano: circa 3,3 caratteri per token con i tokenizer di Llama/Kimi/GPT-OSS)."""
    return int(len(testo) / 3.3) + 4


_TITOLI_TAGLIABILI = ("ARCHIVIO DIGITALE — CATALOGO DELLA SCANSIONE", "ARCHIVIO DIGITALE — MEMORIA DELLA CONVERSAZIONE",
                      "ARCHIVIO DIGITALE — RISULTATI DELLA RICERCA PER L'ULTIMA DOMANDA")


def accorcia(sistema, messaggi, budget):
    """Fa stare la richiesta in `budget` token (modelli con un limite basso, piano gratuito di Groq).
    Ordine: 1) le battute più vecchie della chat; 2) catalogo, memoria e brani dell'archivio, dal più lungo, tenendo
    l'inizio di ognuno; le regole, il fascicolo, il risultato SQL e la domanda restano interi.
    Restituisce (sistema, messaggi, accorciato)."""
    totale = lambda s, m: stima_token(s) + sum(stima_token(x['content']) + 4 for x in m)
    if totale(sistema, messaggi) <= budget:
        return sistema, messaggi, False
    msgs = list(messaggi)
    while len(msgs) > 1 and totale(sistema, msgs) > budget:
        msgs = msgs[2:] if len(msgs) > 2 else msgs[1:]           # via uno scambio (domanda + risposta) alla volta
    while msgs and msgs[0]['role'] != 'user' and len(msgs) > 1:
        msgs = msgs[1:]

    def sezioni(s):
        pos = [(s.find(t), t) for t in _TITOLI_TAGLIABILI if s.find(t) >= 0]
        pos.sort()
        out = []
        for i, (a, t) in enumerate(pos):
            inizio = a + len(t)
            fine = pos[i + 1][0] if i + 1 < len(pos) else len(s)
            if i + 1 == len(pos):                                  # i brani finiscono dove comincia il blocco SQL
                for segno in ('\nDATABASE DELLA MISSIONE', '\nDATABASE DEGLI ACCESSI'):
                    k = s.find(segno, inizio)
                    if k >= 0:
                        fine = min(fine, k)
            out.append((inizio, fine))
        return out

    nota = '\n[… accorciato per il limite di questo modello: le parti più importanti sono sopra …]\n'
    giri = 0
    while totale(sistema, msgs) > budget and giri < 12:
        giri += 1
        sez = [(f - i, i, f) for i, f in sezioni(sistema) if f - i > 400]
        if not sez:
            break
        _, i, f = max(sez)
        tieni = max(300, (f - i) // 2)
        sistema = sistema[:i] + sistema[i:i + tieni].rsplit('\n', 1)[0] + nota + sistema[f:]
    return sistema, msgs, True


CONTINUA = ('Continua la risposta esattamente dal punto in cui si è interrotta: non ripetere niente di quello che hai già '
            'scritto e non aggiungere frasi di introduzione.')


def unisci(testo, seguito):
    """Attacca la continuazione alla risposta tagliata, togliendo le parole che il modello ripete all'inizio."""
    s = seguito.lstrip()
    coda = testo[-120:]
    for k in range(min(len(coda), len(s)), 7, -1):          # «…i risvegli non» + «i risvegli non possono…»
        if coda.endswith(s[:k]):
            s = s[k:]
            break
    if not s:
        return testo
    if testo and not testo[-1].isspace() and (s[0].isalnum() or s[0] in '(«"*[') and testo[-1] not in '(«"\'':
        return testo + ' ' + s
    return testo + s


def attesa_da(testo):
    """Secondi da un messaggio o un'intestazione: «try again in 1m2.5s», «12.3s», «350ms», «2h1m», «retry after 7 seconds»."""
    if not testo:
        return None
    t = str(testo).strip()
    durata_re = r'((?:\d+(?:\.\d+)?(?:ms|h|m|s))+)'
    m = (re.search(r'(?:try again in|retry after|retry in|riprova(?:re)? tra)\s*' + durata_re, t, re.I)
         or re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?" + durata_re, t) or re.fullmatch(durata_re, t))
    if m:
        return sum(float(v) * {'h': 3600, 'm': 60, 's': 1, 'ms': .001}[u]
                   for v, u in re.findall(r'(\d+(?:\.\d+)?)(ms|h|m|s)', m.group(1)))
    k = re.search(r'(\d+(?:\.\d+)?)\s*(?:seconds|secondi|sec)\b', t, re.I)
    return float(k.group(1)) if k else None


def durata(sec):
    sec = max(1, int(round(sec)))
    if sec < 90:
        return f'{sec} s'
    if sec < 3600:
        return f'{sec // 60} min {sec % 60:02d} s'
    return f'{sec // 3600} h {sec % 3600 // 60:02d} min'


class MotoreCompatibile:
    """Un servizio con API compatibile OpenAI: chiave, modelli disponibili, streaming, errori spiegati, pause."""

    def __init__(self, nome, chiave_conf, url_conf, modello_conf, variabili, preferiti, escludi, console):
        self.nome, self.chiave_conf, self.url_conf, self.modello_conf = nome, chiave_conf, url_conf, modello_conf
        self.variabili, self.preferiti, self.escludi, self.console = variabili, preferiti, escludi, console
        self.stato = {'chiave': None, 'modelli': None, 'modello': None, 'pausa_fino': 0.0, 'pause_modello': {},
                      'limiti': {}}   # per modello: token rimasti nel minuto e quando si ricaricano (dalle intestazioni)

    # --- chiave e disponibilità ---
    def chiave(self):
        if self.stato['chiave']:
            return self.stato['chiave']
        k = next((os.environ.get(v) for v in self.variabili if os.environ.get(v)), None)
        k = k or next((chiavi_salvate().get(v) for v in self.variabili if chiavi_salvate().get(v)), None)
        if not k:
            try:
                from google.colab import userdata  # solo in Colab (Secrets)
                k = userdata.get(self.variabili[0])
            except Exception:
                k = None
        self.stato['chiave'] = pulisci_chiave(k) or None
        return self.stato['chiave']

    def utilizzabile(self):
        if not self.chiave():
            return False, f'Manca la chiave {self.nome} ({self.variabili[0]}).'
        attesa = self.stato['pausa_fino'] - time.time()
        if attesa > 0:
            return False, f'{self.nome}: limite gratuito raggiunto (la chiave è valida), si libera tra {durata(attesa)}.'
        return True, ''

    # --- HTTP ---
    def _http(self, percorso, corpo=None, timeout=None):
        import urllib.error
        import urllib.request
        url = getattr(config, self.url_conf).rstrip('/') + percorso
        dati = json.dumps(corpo).encode('utf-8') if corpo is not None else None
        req = urllib.request.Request(url, data=dati, method='POST' if corpo is not None else 'GET', headers={
            'Authorization': f'Bearer {self.chiave()}', 'Content-Type': 'application/json', 'Accept': 'application/json',
            'User-Agent': 'investigatore-eco/4'})
        try:
            return urllib.request.urlopen(req, timeout=timeout or getattr(config, 'TIMEOUT_' + self.nome.upper(), 30))
        except urllib.error.HTTPError as e:
            try:
                testo = e.read().decode('utf-8', 'replace')
                j = json.loads(testo)
                msg = j.get('error') if isinstance(j.get('error'), str) else (j.get('error') or {}).get('message') or j.get('message') or testo
            except Exception:
                msg = str(e)
            raise ErroreCompatibile(e.code, str(msg)[:260])
        except (urllib.error.URLError, OSError) as e:
            raise ErroreCompatibile(None, f'connessione non riuscita ({getattr(e, "reason", e)})')

    # --- modelli ---
    def modelli(self):
        """I modelli di testo che la chiave può usare (GET /models), senza audio, immagini, moderazione."""
        if self.stato['modelli'] is None:
            with self._http('/models', timeout=15) as r:
                dati = json.loads(r.read().decode('utf-8'))
            ids = [m.get('id', '') for m in dati.get('data', []) if m.get('active', True)]
            self.stato['modelli'] = [i for i in ids if not any(x in i.lower() for x in self.escludi)]
        return self.stato['modelli']

    def candidati(self):
        """Il modello di config.py, oppure quelli preferiti che la chiave ha davvero (in ordine), poi gli altri."""
        scelto = getattr(config, self.modello_conf, 'auto')
        try:
            disp = self.modelli()
        except ErroreCompatibile:
            disp = []
        ordine = [m for m in self.preferiti if not disp or m in disp] + [m for m in disp if m not in self.preferiti]
        if scelto and scelto != 'auto':
            ordine = [scelto] + [m for m in ordine if m != scelto]
        ora = time.time()
        liberi = [m for m in ordine if self.stato['pause_modello'].get(m, 0) <= ora]
        return liberi or ordine[:1]

    def modello(self):
        if not self.stato['modello'] or self.stato['pause_modello'].get(self.stato['modello'], 0) > time.time():
            c = self.candidati()
            self.stato['modello'] = c[0] if c else (self.preferiti[0] if self.preferiti else '')
        return self.stato['modello']

    # --- errori ---
    def spiega(self, e):
        codice, msg = getattr(e, 'code', None), getattr(e, 'message', None) or str(e)
        if codice == 429 or codice == 413 and 'rate' in msg.lower():
            attesa = attesa_da(msg)
            quando = f' Si libera tra {durata(attesa)}.' if attesa else ''
            giorno = 'al giorno' if re.search(r'per day|\bTPD\b|\bRPD\b', msg, re.I) else 'al minuto'
            return (f'{self.nome}: limite gratuito {giorno} raggiunto per questo modello. La chiave è valida, non è '
                    f'scaduta.{quando}')
        if codice == 413:
            return (f'{self.nome}: il prompt di ECO è più lungo di quanto questo modello accetti nel piano gratuito; '
                    f'ECO usa un prompt compatto o un altro modello.')
        if codice in (401, 403):
            return (f'{self.nome} ha rifiutato la chiave (…{(self.chiave() or "")[-4:]}): «{msg}». '
                    f'Controllate la chiave su {self.console}.')
        if codice == 404 or codice == 400 and 'model' in msg.lower():
            return f'{self.nome}: il modello «{self.modello()}» non è disponibile («{msg[:150]}»).'
        if 'timed out' in msg.lower() or 'Timeout' in type(e).__name__:
            return f'{self.nome} non ha risposto in tempo.'
        return f'{self.nome} non ha risposto: {msg}'

    # --- streaming ---
    def stream(self, sistema, messaggi, max_tokens=None, modello=None, temperatura=None, fine=None):
        """Chat completions in streaming (formato OpenAI). I ragionamenti <think>…</think> non si mostrano.
        fine (dict, facoltativo): alla fine fine['motivo'] = 'stop' (finita) o 'length' (tagliata al limite di token)."""
        m = modello or self.modello()
        sistema = sistema + (getattr(config, 'STILE_COMPATIBILI', '') or '')
        corpo = {'model': m, 'stream': True,
                 'messages': [{'role': 'system', 'content': sistema}] + [{'role': x['role'], 'content': x['content']} for x in messaggi],
                 'temperature': config.TEMPERATURA if temperatura is None else temperatura,
                 'max_tokens': max_tokens or config.MAX_TOKENS}
        if self.nome == 'Groq' and 'qwen3' in m.lower():
            corpo['reasoning_format'] = 'hidden'     # Qwen3 su Groq: niente ragionamento nel testo
        dentro = False
        with self._http('/chat/completions', corpo) as r:
            self.registra_limiti(m, getattr(r, 'headers', None))
            for riga in r:
                riga = riga.decode('utf-8', 'replace').strip()
                if not riga.startswith('data:'):
                    continue
                dato = riga[5:].strip()
                if dato == '[DONE]':
                    break
                try:
                    j = json.loads(dato)
                    if j.get('error'):
                        raise ErroreCompatibile(None, str(j['error'])[:240])
                    scelta = j['choices'][0]
                    if scelta.get('finish_reason') and fine is not None:
                        fine['motivo'] = scelta['finish_reason']
                    pezzo = scelta.get('delta', {}).get('content')
                except (ValueError, KeyError, IndexError):
                    continue
                if not pezzo:
                    continue
                fuori = ''                     # il testo fuori da <think>…</think> (anche se i tag arrivano spezzati)
                while pezzo:
                    if dentro:
                        k = pezzo.find('</think>')
                        if k < 0:
                            break
                        pezzo, dentro = pezzo[k + 8:], False
                    else:
                        k = pezzo.find('<think>')
                        if k < 0:
                            fuori, pezzo = fuori + pezzo, ''
                        else:
                            fuori, pezzo, dentro = fuori + pezzo[:k], pezzo[k + 7:], True
                if fuori:
                    yield fuori

    def _uno(self, sistema, messaggi, uscita, m, temperatura, t0, esito):
        """Un modello: accorcia la richiesta se supera il suo limite (413), aspetta poco se il limite al minuto si
        libera tra pochi secondi (429 «try again in 2.5s»). Genera (testo, None); restituisce il testo completo."""
        import re
        limite = ((getattr(config, 'LIMITI_TOKEN', {}) or {}).get(m)          # token al minuto del piano gratuito
                  or self.stato.setdefault('limiti_noti', {}).get(m))          # ...o quello che il servizio ci ha detto
        sis, msgs = sistema, messaggi
        if limite:
            if limite < 9000:                   # modelli con pochi token: risposta un po' più corta, più spazio al prompt
                uscita = min(uscita, 700)
            sis, msgs, corto = self.adatta(sistema, messaggi, int(limite * .9) - uscita)
            if corto:
                print(f'{self.nome}: prompt compatto per {m} (limite {limite} token al minuto).')
            richiesta = stima_token(sis) + sum(stima_token(x['content']) + 4 for x in msgs) + uscita
            if richiesta > limite:              # neanche compatto ci sta: inutile chiamarlo, si passa al modello dopo
                raise ErroreCompatibile(413, f'Request too large for model {m}: Limit {limite}, Requested {richiesta} (stima)')
        fine = {}
        for giro in range(3):
            testo, fine = '', {}
            try:
                for pezzo in self.stream(sis, msgs, uscita, m, temperatura, fine):
                    if esito.get('primo') is None:
                        esito['primo'] = time.perf_counter() - t0
                    testo += pezzo
                    esito['parziale'] = testo
                    yield testo, None
                break
            except ErroreCompatibile as e:
                msg = e.message or ''
                if testo or giro == 2:
                    raise
                lim = re.search(r'Limit\s*:?\s*(\d+)', msg)
                richiesti = re.search(r'Requested\s*:?\s*(\d+)', msg)
                if lim and (e.code == 413 or richiesti and int(richiesti.group(1)) > int(lim.group(1))):
                    self.stato.setdefault('limiti_noti', {})[m] = int(lim.group(1))   # la prossima volta subito compatto
                    uscita = min(uscita, 700) if int(lim.group(1)) < 9000 else uscita
                    nuovo = int(int(lim.group(1)) * .85) - uscita    # la richiesta da sola supera il limite: prompt compatto
                    if nuovo < 1500:
                        raise
                    sis, msgs, _ = self.adatta(sistema, messaggi, nuovo)
                    print(f'{self.nome}: {m} accetta {lim.group(1)} token al minuto: accorcio la richiesta e riprovo.')
                    continue
                attesa = attesa_da(e.message or '')
                if e.code == 429 and attesa is not None and attesa <= getattr(config, 'ATTESA_MAX', 30):
                    yield f'⏳ Limite gratuito al minuto di {self.nome}: la chiave è valida, riprendo tra {durata(attesa)}…', None
                if self._aspetta(e):
                    continue
                raise
        else:
            return ''
        # arrivata al limite di lunghezza (finish_reason = 'length'): si chiede al modello di continuare
        for _ in range(getattr(config, 'CONTINUAZIONI', 2)):
            if fine.get('motivo') != 'length':
                return testo
            print(f'{self.nome}: risposta arrivata al limite di {uscita} token, chiedo di continuare.')
            seguito = msgs + [{'role': 'assistant', 'content': testo}, {'role': 'user', 'content': CONTINUA}]
            for giro in range(2):
                fine, buffer, unito = {}, '', False
                try:
                    for pezzo in self.stream(sis, seguito, uscita, m, temperatura, fine):
                        if unito:
                            testo += pezzo
                        else:                           # i primi caratteri: si tolgono le parole ripetute
                            buffer += pezzo
                            if len(buffer) < 80:
                                continue
                            testo, unito = unisci(testo, buffer), True
                        esito['parziale'] = testo
                        yield testo, None
                    if not unito and buffer:
                        testo = unisci(testo, buffer)
                        esito['parziale'] = testo
                        yield testo, None
                    break
                except ErroreCompatibile as e:
                    if not unito and not buffer and giro == 0 and self._aspetta(e):
                        continue
                    print(f'{self.nome}: la continuazione non è riuscita ({self.spiega(e)}).')
                    if buffer and not unito:
                        testo = unisci(testo, buffer)
                    return testo.rstrip() + ' […]'
        if fine.get('motivo') == 'length':
            return testo.rstrip() + ' […]'
        return testo

    def adatta(self, sistema, messaggi, budget):
        """Fa stare la richiesta in `budget` token. Se il prompt sa accorciarsi da solo (istruzioni.PromptAdattabile),
        si usa la sua versione compatta (regole intere, documenti più vicini alla domanda per intero, gli altri con il
        titolo); poi, se serve ancora, si tolgono le battute più vecchie della chat. Restituisce (sistema, messaggi, corto)."""
        totale = stima_token(sistema) + sum(stima_token(x['content']) + 4 for x in messaggi)
        if totale <= budget:
            return sistema, messaggi, False
        corto = False
        if hasattr(sistema, 'riduci'):
            ultimi = messaggi[-1:]
            sis, livello = sistema.riduci(budget - sum(stima_token(x['content']) + 4 for x in ultimi) - 200)
            if livello:
                print(f'{self.nome}: prompt compatto, livello {livello} ({stima_token(sis)} token)')
            sistema, corto = sis, True
        sis, msgs, c2 = accorcia(sistema, messaggi, budget)
        return sis, msgs, corto or c2

    def _aspetta(self, e):
        """429 «try again in 12.5s»: se l'attesa è breve (≤ ATTESA_MAX) si aspetta e si riprova con lo STESSO modello.
        È il caso normale del piano gratuito: il prompt di ECO è lungo e il limite di token al minuto si riempie in
        una o due domande; dopo pochi secondi si ricarica. Non è la chiave che scade."""
        attesa = attesa_da(e.message or '')
        if e.code == 429 and attesa is not None and attesa <= getattr(config, 'ATTESA_MAX', 30):
            print(f'{self.nome}: limite al minuto, aspetto {attesa:.1f} s e riprovo.')
            time.sleep(attesa + .4)
            return True
        return False

    # --- limiti del piano gratuito, letti dalle intestazioni delle risposte ---
    def registra_limiti(self, m, intestazioni):
        if not intestazioni:
            return
        try:
            rimasti = intestazioni.get('x-ratelimit-remaining-tokens')
            ricarica = attesa_da(intestazioni.get('x-ratelimit-reset-tokens') or '')
            if rimasti is not None:
                self.stato['limiti'][m] = (int(float(rimasti)), time.time() + (ricarica or 60))
        except (TypeError, ValueError):
            pass

    def attesa_prevista(self, m, servono):
        """Secondi da aspettare prima di chiamare il modello m (0 = subito; None = troppi: meglio un altro modello)."""
        ora = time.time()
        pausa = self.stato['pause_modello'].get(m, 0) - ora
        if pausa > 0:
            return pausa if pausa <= getattr(config, 'ATTESA_MAX', 30) else None
        rimasti, quando = self.stato['limiti'].get(m, (None, 0))
        if rimasti is None or quando <= ora or rimasti >= servono:
            return 0
        w = quando - ora
        return w if w <= getattr(config, 'ATTESA_MAX', 30) else None

    def prova(self, sistema, messaggi, max_tokens, temperatura, t0, esito):
        """Genera (testo, None) mentre il servizio scrive. Se un modello è al limite (429/413) prova il successivo.
        Alla fine esito['ok'] dice se ha risposto, esito['modello'] con quale modello, esito['avviso'] perché no."""
        ok, perche = self.utilizzabile()
        if not ok:
            esito['avviso'] = perche
            return
        tentati = 0
        uscita = max_tokens or getattr(config, 'MAX_TOKENS_COMPATIBILI', config.MAX_TOKENS)
        servono = stima_token(sistema) + sum(stima_token(x['content']) + 4 for x in messaggi) + uscita
        for m in self.candidati()[:getattr(config, 'MODELLI_PROVATI', 4)]:
            attesa = self.attesa_prevista(m, servono)
            if attesa is None:                  # questo modello ha finito i token per un po': si passa al successivo
                continue
            if attesa > 0:                      # pochi secondi: meglio aspettare che cambiare modello
                yield f'⏳ Limite gratuito al minuto di {self.nome}: la chiave è valida, riprendo tra {durata(attesa)}…', None
                time.sleep(attesa + .4)
            tentati += 1
            testo = ''
            esito.pop('parziale', None)
            try:
                testo = yield from self._uno(sistema, messaggi, uscita, m, temperatura, t0, esito)
                if not (testo or '').strip():
                    raise ErroreCompatibile(None, 'risposta vuota')
                self.stato['modello'] = m
                esito.update(ok=True, testo=testo, modello=m)
                return
            except Exception as e:
                codice = getattr(e, 'code', None)
                esito['avviso'] = self.spiega(e)
                print(esito['avviso'])
                parziale = esito.pop('parziale', '') or testo
                if parziale.strip():            # aveva già cominciato a scrivere: si tiene quello che ha scritto
                    print(f'{self.nome}: la risposta si è interrotta a metà, tengo il testo già scritto.')
                    self.stato['modello'] = m
                    esito.update(ok=True, testo=parziale.rstrip() + ' […]', modello=m)
                    return
                if codice in (429, 413):        # limite di QUESTO modello: pausa per il tempo che dice il servizio
                    attesa = attesa_da(getattr(e, 'message', '') or '')
                    self.stato['pause_modello'][m] = time.time() + (attesa + 1 if attesa else getattr(config, 'PAUSA_MODELLO', 60))
                    continue
                if codice in (404, 400) and ('model' in str(e).lower() or codice == 404):
                    self.stato['pause_modello'][m] = time.time() + 3600
                    continue
                if codice in (500, 502, 503, 504) or codice is None and 'connessione' not in str(e):
                    continue
                if codice == 401:               # chiave sbagliata o revocata: inutile riprovare subito
                    self.stato['pausa_fino'] = time.time() + 600
                elif codice == 403:
                    self.stato['pausa_fino'] = time.time() + 60
                return
        ora = time.time()
        pause = [self.stato['pause_modello'].get(m, 0) for m in self.candidati()]
        if pause and all(x > ora for x in pause):   # tutti i modelli al limite: pausa fino al primo che si libera
            self.stato['pausa_fino'] = min(pause)
        if not tentati and not esito.get('avviso'):
            esito['avviso'] = f'{self.nome}: tutti i modelli hanno finito i token gratuiti per qualche minuto.'


GROQ = MotoreCompatibile(
    'Groq', 'GROQ_API_KEY', 'GROQ_URL', 'MODELLO_GROQ', ('GROQ_API_KEY',),
    # in ordine: tanti token al minuto nel piano gratuito (il prompt di ECO è lungo), buon italiano, niente ragionamento
    preferiti=['meta-llama/llama-4-scout-17b-16e-instruct', 'llama-3.3-70b-versatile', 'moonshotai/kimi-k2-instruct-0905',
               'moonshotai/kimi-k2-instruct', 'openai/gpt-oss-120b', 'openai/gpt-oss-20b', 'qwen/qwen3-32b',
               'meta-llama/llama-4-maverick-17b-128e-instruct', 'llama-3.1-8b-instant'],
    escludi=('whisper', 'tts', 'guard', 'orpheus', 'playai', 'compound', 'allam', 'distil', 'vision'),
    console='console.groq.com')
GROK = MotoreCompatibile(
    'Grok', 'XAI_API_KEY', 'GROK_URL', 'MODELLO_GROK', ('XAI_API_KEY', 'GROK_API_KEY'),
    preferiti=['grok-3-mini', 'grok-3', 'grok-4-fast-non-reasoning', 'grok-4'],
    escludi=('image', 'imagine', 'vision', 'video', 'embed', 'tts', 'voice'),
    console='console.x.ai (servono crediti)')
CEREBRAS = MotoreCompatibile(
    'Cerebras', 'CEREBRAS_API_KEY', 'CEREBRAS_URL', 'MODELLO_CEREBRAS', ('CEREBRAS_API_KEY',),
    # piano gratuito con molti token al giorno: la riserva gratuita di Groq quando Groq è al limite
    preferiti=['gpt-oss-120b', 'llama-3.3-70b', 'qwen-3-235b-a22b-instruct-2507', 'qwen-3-32b', 'llama3.1-8b'],
    escludi=('vision', 'embed'),
    console='cloud.cerebras.ai')
COMPATIBILI = {'groq': GROQ, 'cerebras': CEREBRAS, 'grok': GROK}
ORDINE_COMPATIBILI = ('groq', 'cerebras', 'grok')


# nomi di prima (li usano app.py, web.py, diagnostica.py, app_gradio.py)
def chiave_grok():
    return GROK.chiave()


def grok_utilizzabile():
    return GROK.utilizzabile()


def modelli_grok():
    return GROK.modelli()


def modello_grok():
    return GROK.modello()


def spiega_errore_grok(e):
    return GROK.spiega(e)


def stream_grok(sistema, messaggi, max_tokens=None, modello=None, temperatura=None):
    return GROK.stream(sistema, messaggi, max_tokens, modello, temperatura)


def chiave_groq():
    return GROQ.chiave()


def groq_utilizzabile():
    return GROQ.utilizzabile()


def modelli_groq():
    return GROQ.modelli()


def modello_groq():
    return GROQ.modello()


def spiega_errore_groq(e):
    return GROQ.spiega(e)


def stream_groq(sistema, messaggi, max_tokens=None, modello=None, temperatura=None):
    return GROQ.stream(sistema, messaggi, max_tokens, modello, temperatura)


# ================================ SCELTA DEL MOTORE ==============================================
def motore_principale():
    """Con MOTORE = 'auto': Gemini se c'è GEMINI_API_KEY (PRIMA_GEMINI = True), altrimenti Groq, Cerebras, Grok."""
    m = config.MOTORE
    if m == 'auto':
        if getattr(config, 'PRIMA_GEMINI', True) and chiave_gemini():
            return 'gemini'
        return next((k for k in ORDINE_COMPATIBILI if COMPATIBILI[k].chiave()), 'gemini')
    return m


def nome_motore_principale():
    return {'groq': 'Groq', 'cerebras': 'Cerebras', 'grok': 'Grok', 'gemini': 'Gemini',
            'locale': 'Qwen sulla GPU'}.get(motore_principale(), 'Gemini')


def rispondi(sistema, messaggi, motore=None, max_tokens=None, temperatura=None):
    """Generatore di (testo_finora, info). info è None finché il testo non è completo.
    info = {'motore', 'modello', 'secondi', 'primo', 'avviso'}.
    Ordine con MOTORE = 'auto': Groq → Grok → Gemini → Qwen sulla GPU (ognuno solo se c'è la sua chiave / la GPU)."""
    motore = motore or motore_principale()
    if motore == 'auto':
        motore = motore_principale()
    t0 = time.perf_counter()
    avviso, provati = None, set()

    def info(nome, modello, primo):
        return {'motore': nome, 'modello': modello, 'secondi': time.perf_counter() - t0,
                'primo': primo, 'avviso': avviso}

    def prova_compatibile(chiave):
        nonlocal avviso
        mot = COMPATIBILI[chiave]
        provati.add(chiave)
        esito = {}
        for x in mot.prova(sistema, messaggi, max_tokens, temperatura, t0, esito):
            yield x
        if esito.get('ok'):
            yield esito['testo'], info(mot.nome, esito.get('modello') or mot.modello(), esito.get('primo'))
            esito['fatto'] = True
        else:
            avviso = f'{avviso or ""} {esito.get("avviso") or ""}'.strip()
        prova_compatibile.fatto = bool(esito.get('fatto'))

    if motore in COMPATIBILI:                    # Groq o Grok; se non risponde: l'altro, poi Gemini, poi la riserva locale
        for x in prova_compatibile(motore):
            yield x
        if prova_compatibile.fatto:
            return
        for altro in ORDINE_COMPATIBILI:         # le altre chiavi gratuite, in ordine (Cerebras, Grok)
            if altro == motore or config.MOTORE != 'auto' or not COMPATIBILI[altro].chiave():
                continue
            if not COMPATIBILI[altro].utilizzabile()[0]:
                continue
            print(f'{COMPATIBILI[motore].nome} non disponibile: provo {COMPATIBILI[altro].nome}.')
            for x in prova_compatibile(altro):
                yield x
            if prova_compatibile.fatto:
                return
        if getattr(config, 'RISERVA_GEMINI', True) and gemini_utilizzabile()[0]:
            print(f'{COMPATIBILI[motore].nome} non disponibile: provo Gemini.')
            motore = 'gemini'

    if motore == 'gemini':
        ok, perche = gemini_utilizzabile()
        if ok:
            # Ogni modello Gemini ha la SUA quota gratuita: se uno è al limite si passa al successivo con la stessa
            # chiave; se il limite al minuto si libera tra pochi secondi si aspetta e si riprova lo stesso modello.
            ordine = [config.MODELLO_GEMINI] + [m for m in config.MODELLI_GEMINI_RISERVA if m != config.MODELLO_GEMINI]
            assenti, giri_sovraccarico, attese = set(), 0, {}
            i = 0
            while i < len(ordine):
                modello = ordine[i]
                pausa = _gemini['pause_modello'].get(modello, 0) - time.time()
                if modello in assenti or pausa > getattr(config, 'ATTESA_MAX', 30):
                    i += 1
                    continue
                if pausa > 0:
                    yield f'⏳ Limite gratuito al minuto di Gemini: la chiave è valida, riprendo tra {durata(pausa)}…', None
                    time.sleep(pausa + .4)
                testo, primo = '', None
                try:
                    for pezzo in stream_gemini(sistema, messaggi, max_tokens, modello, temperatura):
                        if primo is None:
                            primo = time.perf_counter() - t0
                        testo += pezzo
                        yield testo, None
                    if not testo.strip():
                        raise MotoreErrore('Gemini ha restituito una risposta vuota.')
                    yield testo, info('Gemini', modello, primo)
                    return
                except Exception as e:
                    if testo.strip():                  # aveva già scritto: si tiene il testo
                        yield testo.rstrip() + ' […]', info('Gemini', modello, primo)
                        return
                    codice = getattr(e, 'code', None)
                    msg = str(e)
                    if codice == 429 or 'RESOURCE_EXHAUSTED' in msg:
                        attesa = attesa_da(msg)
                        al_giorno = bool(re.search(r'PerDay|per day', msg, re.I))
                        attese[modello] = attese.get(modello, 0) + 1
                        if attesa is not None and attesa <= getattr(config, 'ATTESA_MAX', 30) and not al_giorno \
                                and attese[modello] <= 2:
                            yield f'⏳ Limite gratuito al minuto di Gemini: la chiave è valida, riprendo tra {durata(attesa)}…', None
                            time.sleep(attesa + .4)
                            continue                    # stesso modello
                        _gemini['pause_modello'][modello] = time.time() + (attesa or (3600 if al_giorno else 60)) + 1
                        print(f'Gemini: «{modello}» al limite gratuito ({"giornaliero" if al_giorno else "al minuto"}), provo il successivo.')
                        avviso = spiega_errore_gemini(e)
                        i += 1
                        continue
                    lento = 'Timeout' in type(e).__name__ or 'timed out' in msg.lower()
                    if (codice in (500, 502, 503, 504) or 'UNAVAILABLE' in msg or lento) and \
                            time.perf_counter() - t0 < config.TEMPO_MAX_GEMINI:
                        print(f'Gemini {"lento" if lento else f"sovraccarico ({codice})"} su «{modello}»: provo il successivo.')
                        i += 1
                        if i >= len(ordine) and giri_sovraccarico < 2:   # giro finito: breve pausa e si ricomincia
                            giri_sovraccarico += 1
                            time.sleep(1.5 * giri_sovraccarico)
                            i = 0
                        continue
                    if codice == 404:
                        assenti.add(modello)            # modello che questa chiave non ha
                        if modello == config.MODELLO_GEMINI and correggi_modello():
                            ordine.insert(i + 1, config.MODELLO_GEMINI)
                        i += 1
                        continue
                    if (codice == 400 and 'think' in msg.lower() and config.PENSIERO_GEMINI is not None
                            and modello not in _SENZA_PENSIERO):
                        print(f'Gemini: «{modello}» non accetta PENSIERO_GEMINI = {config.PENSIERO_GEMINI!r}, lo tolgo per lui.')
                        _SENZA_PENSIERO.add(modello)
                        continue
                    if codice in (401, 403) or 'API_KEY_INVALID' in msg:
                        _gemini['pausa_fino'] = time.time() + 120
                    avviso = ((avviso + ' ') if avviso else '') + (msg if isinstance(e, MotoreErrore) else spiega_errore_gemini(e))
                    break
            ora = time.time()
            pause = [_gemini['pause_modello'].get(m, 0) for m in ordine if m not in assenti]
            if pause and all(x > ora for x in pause):
                _gemini['pausa_fino'] = min(pause)
        else:
            avviso = avviso or perche
            if not any(COMPATIBILI[k].chiave() for k in ORDINE_COMPATIBILI) and not chiave_gemini():
                avviso = ('Nessuna chiave API: incollate una chiave gratuita di Gemini («AIza…», da aistudio.google.com/apikey) '
                          'in ⚙ Motori, oppure impostate GEMINI_API_KEY.')
        if config.MOTORE == 'auto':          # Gemini non risponde: si provano Groq e Grok prima della riserva locale
            for chiave in ORDINE_COMPATIBILI:
                if chiave not in provati and COMPATIBILI[chiave].chiave() and COMPATIBILI[chiave].utilizzabile()[0]:
                    for x in prova_compatibile(chiave):
                        yield x
                    if prova_compatibile.fatto:
                        return
        if not config.RISERVA_LOCALE:
            yield f'⚠ {config.NOME} non può rispondere. {avviso}', info('nessuno', '', None)
            return

    # riserva (o motore scelto) locale
    if motore in COMPATIBILI and not config.RISERVA_LOCALE:
        yield f'⚠ {config.NOME} non può rispondere. {avviso}', info('nessuno', '', None)
        return
    if not locale_pronto() and motore in ('gemini',) + ORDINE_COMPATIBILI and not _locale['carica'].locked():
        # la riserva non è stata caricata (es. Colab con CARICA_QWEN = False): niente download di 8 GB in mezzo alla chat
        yield (f'⚠ {config.NOME} non può rispondere adesso. {avviso} La riserva locale non è caricata '
               '(in Colab: sezione 5 con CARICA_QWEN = True).'), info('nessuno', '', None)
        return
    if not locale_pronto():
        if _locale['carica'].locked():
            yield f'⏳ {avviso or ""} Aspetto che la riserva locale finisca di caricarsi…'.strip(), None
        if not avvia_locale():
            yield (f'⚠ {config.NOME} non può rispondere. {avviso or ""} '
                   f'Riserva locale non disponibile: {_locale["errore"]}').replace('  ', ' '), info('nessuno', '', None)
            return
    if avviso:
        yield f'⏳ {avviso} Rispondo con la riserva locale…', None
    testo, primo = '', None
    for pezzo in stream_locale(sistema, messaggi, max_tokens, temperatura):
        if primo is None:
            primo = time.perf_counter() - t0
        testo += pezzo
        yield testo, None
    yield testo, info('Qwen locale', config.MODELLO_LOCALE, primo)