"""Chat di ECO (interfaccia di base, Gradio): python app.py  → si apre http://127.0.0.1:7860

Opzioni:
  --console   chat nel terminale, senza browser
  --locale    usa solo Qwen sulla GPU (niente Gemini)
  --rete      la pagina è raggiungibile dagli altri PC della stessa rete
"""
import sys
import time

import archivio
import config
import eco
import motori
import rag

ESEMPI = ['Di tutti questi file, quali sono quelli inerenti alla storia? Come si chiamano? Cosa c\'è dentro?',
          'Cosa è successo nei rifugi?', 'Chi ha cercato di fermare il progetto?',
          'Dove si trova il materiale di recupero?', 'Persona, deposito, settore e pratica?',
          'Dove e quando è iniziato il primo focolaio?']
ATTESA = '_🔎 Cerco nell\'archivio…_'


def chat(messaggio, cronologia):
    """Funzione della chat Gradio: restituisce (risposta mentre la scrive, tabella dei file recuperati)."""
    ultimo, pannello = 0.0, ATTESA
    for testo, info in eco.rispondi_stream(messaggio, cronologia):
        if info is not None:
            pannello = eco.tabella_recuperati(info)
        if info is not None or time.perf_counter() - ultimo > 0.08:   # ridisegna al massimo ~12 volte al secondo
            ultimo = time.perf_counter()
            yield testo, pannello


def stato():
    righe = ['Fascicolo: ' + ' · '.join(f'{nome} ({len(i)})' for nome, i in archivio.gruppi().items())]
    if rag._stato['indice'] is not None:
        righe.append('Archivio digitale: ' + rag.descrizione())
    if motori.chiave_groq() and config.MOTORE in ('groq', 'auto'):
        ok, perche = motori.groq_utilizzabile()
        righe.append(f'Groq: {motori.modello_groq()}' + ('' if ok else f' — {perche}'))
    if motori.chiave_grok() and config.MOTORE in ('grok', 'auto'):
        ok, perche = motori.grok_utilizzabile()
        righe.append(f'Grok: {motori.modello_grok()}' + ('' if ok else f' — {perche}'))
    if config.MOTORE in ('gemini', 'auto'):
        ok, perche = motori.gemini_utilizzabile()
        righe.append(f'Gemini: {config.MODELLO_GEMINI}' + ('' if ok else f' — {perche}'))
    if config.RISERVA_LOCALE or config.MOTORE == 'locale':
        righe.append('Riserva locale: ' + ('pronta' if motori.locale_pronto() else
                                           (motori._locale['errore'] or ('in caricamento' if motori._locale['carica'].locked() else 'non caricata'))))
    return '  \n'.join(righe)


def pannello_iniziale():
    ind = rag.indice() if rag.file_archivio() else None
    if not ind:
        return 'Nessun archivio digitale caricato.'
    return ('Dopo ogni domanda qui compaiono i file trovati dalla ricerca e la memoria della conversazione.\n\n'
            '#### 🗂 Catalogo della scansione\n' + f'_{rag.descrizione()}_\n\n' +
            '\n'.join(f'- {d["id"]} · {d["file"]} · {d["titolo"]}' for d in ind.catalogo()))


def crea_interfaccia():
    """Chat a sinistra, file recuperati dalla ricerca a destra."""
    import gradio as gr
    with gr.Blocks(title=f'Investigatore {config.NOME}') as demo:
        gr.Markdown(f'## Protocollo LAZZARO — Investigatore {config.NOME} (Squadra {config.SQUADRA}, Giorno {config.GIORNO})'
                    f'\n{stato()}')
        pannello = gr.Markdown(pannello_iniziale(), render=False)
        with gr.Row():
            with gr.Column(scale=3):
                gr.ChatInterface(
                    fn=chat, additional_outputs=[pannello], examples=ESEMPI, run_examples_on_click=True,
                    chatbot=gr.Chatbot(height=600, placeholder=f'Chiedi a {config.NOME} qualcosa sull\'indagine.'),
                    textbox=gr.Textbox(placeholder='Scrivi una domanda…', submit_btn=True),
                    save_history=config.SALVA_CHAT)
            with gr.Column(scale=2):
                gr.Markdown('### 📂 Archivio digitale: ricerca, memoria, catalogo')
                pannello.render()
    return demo


def console():
    conv = eco.Conversazione()
    print(f'Chat con {config.NOME} (riga vuota per uscire, "nuova" per ricominciare)\n')
    while True:
        try:
            q = input('TU: ').strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            break
        if q.lower() == 'nuova':
            conv = eco.Conversazione()
            print('— nuova conversazione —\n')
            continue
        testo, info = conv.chiedi(q)
        print(f'{config.NOME}: {testo}\n')


def prepara():
    print(archivio.riepilogo(), '\n')
    if rag.file_archivio():
        print('Preparo la ricerca nell\'archivio digitale (la prima volta può volerci qualche minuto)...')
        rag.prepara()
    if '--locale' in sys.argv:
        config.MOTORE = 'locale'
    if motori.chiave_groq() and config.MOTORE in ('groq', 'auto'):
        ok, perche = motori.groq_utilizzabile()
        print('Groq:', motori.modello_groq(), '✅' if ok else f'❌ {perche}')
    if motori.chiave_grok() and config.MOTORE in ('grok', 'auto'):
        ok, perche = motori.grok_utilizzabile()
        print('Grok:', motori.modello_grok(), '✅' if ok else f'❌ {perche}')
    if config.MOTORE in ('gemini', 'auto'):
        ok, perche = motori.gemini_utilizzabile()
        print('Gemini:', config.MODELLO_GEMINI, '✅' if ok else f'❌ {perche}')
    if config.MOTORE == 'locale':
        motori.avvia_locale()
    elif config.RISERVA_LOCALE and config.CARICA_LOCALE_ALL_AVVIO:
        motori.avvia_locale_in_sottofondo()   # Gemini risponde subito; Qwen si carica intanto


if __name__ == '__main__':
    prepara()
    if '--console' in sys.argv:
        console()
    else:
        host = '0.0.0.0' if '--rete' in sys.argv else '127.0.0.1'
        print(f'\nInvestigatore {config.NOME} su http://127.0.0.1:{config.PORTA}  (Ctrl+C per fermare)\n')
        crea_interfaccia().launch(server_name=host, server_port=config.PORTA, inbrowser=True)