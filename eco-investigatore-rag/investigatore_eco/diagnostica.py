"""Controllo di Groq, Grok, Gemini e della GPU: python diagnostica.py  (mandate tutto l'output se qualcosa non va).

0. la chiave Grok (XAI_API_KEY) c'è? quali modelli vede? una domanda di prova
1. la chiave Gemini c'è?  2. quali modelli Flash-Lite vede la chiave?  3. una domanda di prova a Gemini
4. c'è una GPU per la riserva locale?   Con --locale carica anche Qwen e fa una domanda di prova.
"""
import sys
import time

import config
import motori

print('--- GROQ (console.groq.com) ---')
kq = motori.chiave_groq()
print('Chiave:', f'trovata (…{kq[-4:]}, lunga {len(kq)} caratteri, inizia con «{kq[:4]}»)' if kq else
      'NON trovata: impostate GROQ_API_KEY (PowerShell: $env:GROQ_API_KEY="gsk_...")')
if kq:
    try:
        lista = motori.modelli_groq()
        print('✅ La chiave funziona (Groq risponde). Modelli di testo:', ', '.join(lista) or '(nessuno)')
    except Exception as e:
        print('❌', motori.spiega_errore_groq(e))
    print('Ordine che userà ECO:', ', '.join(motori.GROQ.candidati()[:4]), '(config.MODELLO_GROQ = ' + repr(config.MODELLO_GROQ) + ')')
    t0 = time.perf_counter()
    esito = {}
    try:
        for _ in motori.GROQ.prova('Rispondi in italiano con una frase.', [{'role': 'user', 'content': 'Ciao, chi sei?'}], 60, None, t0, esito):
            pass
        print(f'Prova: «{(esito.get("testo") or "").strip()}» con {esito.get("modello")} in {time.perf_counter() - t0:.1f} s ✅'
              if esito.get('ok') else f'Prova non riuscita: {esito.get("avviso")}')
    except Exception as e:
        print('Prova non riuscita:', motori.spiega_errore_groq(e))

print('\n--- GROK (xAI) ---')
k = motori.chiave_grok()
print('Chiave:', f'trovata (…{k[-4:]}, lunga {len(k)} caratteri, inizia con «{k[:4]}»)' if k else
      'NON trovata: impostate XAI_API_KEY (PowerShell: $env:XAI_API_KEY="xai-...")')
if k:
    try:
        lista = motori.modelli_grok()
        print('✅ La chiave funziona (xAI risponde). Modelli:', ', '.join(lista) or '(nessuno)')
    except Exception as e:
        print('❌', motori.spiega_errore_grok(e))
    print('Modello usato da ECO:', motori.modello_grok(), '(config.MODELLO_GROK = ' + repr(config.MODELLO_GROK) + ')')
    t0 = time.perf_counter()
    try:
        r = ''.join(motori.stream_grok('Rispondi in italiano con una frase.', [{'role': 'user', 'content': 'Ciao, chi sei?'}]))
        print(f'Prova: «{r.strip()}» in {time.perf_counter() - t0:.1f} s ✅')
    except Exception as e:
        print('Prova non riuscita:', motori.spiega_errore_grok(e))
print('Motore che scrive le risposte:', motori.motore_principale(), f'(config.MOTORE = {config.MOTORE!r})')

print('\n--- GEMINI ---')
chiave = motori.chiave_gemini()
print('Chiave:', f'trovata (…{chiave[-4:]})' if chiave else 'NON trovata: impostate GEMINI_API_KEY (vedi README)')
if chiave:
    print(f'   lunga {len(chiave)} caratteri, inizia con «{chiave[:4]}»')
    try:
        lite = motori.modelli_flash_lite()
        print('✅ La chiave funziona (Google risponde).')
        print('Modelli Flash-Lite disponibili:', ', '.join(lite) or '(nessuno)')
        if config.MODELLO_GEMINI in lite:
            print(f'Modello in config.py: {config.MODELLO_GEMINI} ✅')
        elif lite:
            print(f'Modello in config.py: {config.MODELLO_GEMINI} ❌ non esiste per questa chiave.')
            config.MODELLO_GEMINI = lite[0]
            print(f'   → per ora ECO usa «{lite[0]}». Per non vederlo più, scrivete in config.py:  '
                  f"MODELLO_GEMINI = '{lite[0]}'")
    except Exception as e:
        print('❌', motori.spiega_errore_gemini(e))
    t0 = time.perf_counter()
    try:
        r = ''.join(motori.stream_gemini('Rispondi in italiano con una frase.', [{'role': 'user', 'content': 'Ciao, chi sei?'}]))
        print(f'Prova: «{r.strip()}» in {time.perf_counter() - t0:.1f} s')
    except Exception as e:
        print('Prova non riuscita:', motori.spiega_errore_gemini(e))
    print(f'Richieste a Gemini oggi (contate da ECO): {motori.richieste_gemini_oggi()}')

print('\n--- GPU (riserva locale) ---')
try:
    print('GPU:', motori.controlla_gpu())
    if '--locale' in sys.argv:
        motori.avvia_locale()
        t0 = time.perf_counter()
        r = ''.join(motori.stream_locale('Rispondi in italiano con una frase.', [{'role': 'user', 'content': 'Ciao, chi sei?'}]))
        print(f'Prova Qwen: «{r.strip()}» in {time.perf_counter() - t0:.1f} s')
except motori.MotoreErrore as e:
    print('Riserva locale non disponibile:', e)
    print('(ECO funziona lo stesso con Gemini; la riserva serve solo se Gemini non risponde.)')