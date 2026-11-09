"""Avvia l'investigatore ECO con l'interfaccia grafica: python app.py  → si apre http://127.0.0.1:7860

Mappa di Roma, frequenze radio, timeline, ipotesi, imprevisti e la chat con le azioni in millisecondi e la vista RAG.
Le risposte le scrive il modello (Gemini Flash-Lite, con Qwen3-4B sulla GPU di riserva) con fascicolo + RAG + memoria.

Opzioni:
  --senza-modello   non carica Qwen sulla GPU (risponde solo Gemini)
  --locale          solo Qwen sulla GPU, niente Gemini
  --rete            la pagina è raggiungibile dagli altri PC della stessa rete (per la squadra)
  --gradio          chat semplice di riserva (app_gradio.py, con il pannello dei file recuperati)
  --console         chat nel terminale
"""
import os
import sys
import threading
import webbrowser

import archivio
import config
import motori
import rag


def prepara():
    print(archivio.riepilogo(), '\n')
    if rag.file_archivio():
        print('Preparo la ricerca nell\'archivio digitale (la prima volta può volerci qualche minuto)...')
        rag.prepara()
    if '--locale' in sys.argv:
        config.MOTORE = 'locale'
    if config.MOTORE in ('groq', 'auto'):
        if motori.chiave_groq():
            ok, perche = motori.groq_utilizzabile()
            print('Groq:', motori.modello_groq(), '✅ (scrive le risposte)' if ok and motori.motore_principale() == 'groq' else
                  ('✅' if ok else f'❌ {perche}'))
        else:
            print('Groq: nessuna chiave GROQ_API_KEY')
    if config.MOTORE in ('cerebras', 'auto') and motori.CEREBRAS.chiave():
        ok, perche = motori.CEREBRAS.utilizzabile()
        print('Cerebras:', motori.CEREBRAS.modello() if ok else '', '✅ (scrive le risposte)' if ok and motori.motore_principale() == 'cerebras'
              else ('✅ (riserva gratuita)' if ok else f'❌ {perche}'))
    if config.MOTORE in ('grok', 'auto') and (config.MOTORE == 'grok' or motori.chiave_grok()):
        if motori.chiave_grok():
            ok, perche = motori.grok_utilizzabile()
            print('Grok:', motori.modello_grok(), '✅ (scrive le risposte)' if ok and motori.motore_principale() == 'grok' else
                  ('✅' if ok else f'❌ {perche}'))
        else:
            print('Grok: nessuna chiave XAI_API_KEY')
    if config.MOTORE in ('gemini', 'auto'):
        ok, perche = motori.gemini_utilizzabile()
        print('Gemini:', config.MODELLO_GEMINI, ('✅' + (' (riserva)' if motori.motore_principale() in motori.ORDINE_COMPATIBILI else '')) if ok else f'❌ {perche}')
    if config.MOTORE == 'locale':
        motori.avvia_locale()
    elif config.RISERVA_LOCALE and config.CARICA_LOCALE_ALL_AVVIO and '--senza-modello' not in sys.argv:
        motori.avvia_locale_in_sottofondo()   # Gemini risponde subito; Qwen si carica intanto


def main():
    prepara()
    if '--console' in sys.argv:
        import app_gradio
        return app_gradio.console()
    host = '0.0.0.0' if '--rete' in sys.argv else '127.0.0.1'
    url = f'http://127.0.0.1:{config.PORTA}'
    if '--gradio' in sys.argv:
        import app_gradio
        print(f'\nChat di riserva su {url}  (Ctrl+C per fermare)\n')
        return app_gradio.crea_interfaccia().launch(server_name=host, server_port=config.PORTA, inbrowser=True)
    import uvicorn
    import web
    m = web.stato_mappa()
    if m['trovata']:
        print(f"🗺  Mappa stradale: {m['tessere']} tessere in {m['cartella']}")
    else:
        print(f"⚠️ Mappa stradale non trovata: estraete mappa.zip in modo da avere {os.path.join(m['attesa'], '13')} "
              "(intanto l'interfaccia mostra la mappa schematica)")
    print(f'\n🏛  Investigatore {config.NOME} pronto su {url}  (Ctrl+C per fermare)\n')
    if not os.environ.get('ECO_NON_APRIRE'):
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(web.crea_app(), host=host, port=config.PORTA, log_level='warning')


if __name__ == '__main__':
    main()
