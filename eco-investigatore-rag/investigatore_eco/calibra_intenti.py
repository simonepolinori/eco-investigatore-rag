"""Controllo delle soglie con cui ECO capisce che una domanda CHIEDE i file rumore o file a caso. python calibra_intenti.py
Usa solo gli embedding (nessuna richiesta a Gemini). Per ogni domanda stampa le somiglianze e la decisione.
Se sbaglia qualche domanda, cambiate RAG_SOGLIA_RUMORE / RAG_MARGINE_RUMORE / RAG_SOGLIA_CASO in config.py."""
import config
import rag

# (domanda, atteso): 'rumore' = chiede file non della storia, 'caso' = chiede file a caso, 'storia' = domanda normale
PROVE = [
    ('Estrai un file che non riguarda la storia', 'rumore'), ('Estrai 5 documenti di Wikipedia', 'rumore'),
    ('Dammi un documento che parla di tutt\'altro', 'rumore'), ('Mostrami una voce enciclopedica', 'rumore'),
    ('Di cosa parlano i file scartati?', 'rumore'), ('Fammi vedere dei file senza rapporto con l\'epidemia', 'rumore'),
    ('Voglio leggere un articolo che non c\'entra con LAZZARO', 'rumore'),
    ('Estrai 5 documenti a caso', 'caso'), ('Pesca tre file qualsiasi dall\'archivio', 'caso'), ('Dammi un campione casuale di documenti', 'caso'),
    ('Dove si trova il materiale di recupero?', 'storia'), ('Chi ha aperto la pratica RV596?', 'storia'),
    ('Cosa è successo nei rifugi?', 'storia'), ('Qual è il file più importante per la storia?', 'storia'),
    ('Estrai i file che riguardano la storia', 'storia'), ('Il deposito Darsena Vuota è affidabile?', 'storia'),
    ('Che ne pensi del materiale LUME?', 'storia'), ('Cos\'è la fotosintesi?', 'storia'), ('Chi è Marta Riva?', 'storia'),
]


def main():
    ok = 0
    print(f'{"domanda":58s} {"rum":>5s} {"sto":>5s} {"caso":>5s}  decisione   atteso')
    for q, atteso in PROVE:
        r = rag.capisci_richiesta(q)
        if r['sim'] is None:
            print('Embedding non disponibili: la calibrazione non è possibile.')
            return
        s = r['sim']
        dec = 'caso' if r['caso'] else ('rumore' if r['rumore'] else 'storia')
        ok += dec == atteso
        print(f'{q[:58]:58s} {s["rumore"]:5.2f} {s["storia"]:5.2f} {s["caso"]:5.2f}  {dec:10s}  {atteso:7s} {"✅" if dec == atteso else "❌"}')
    print(f'\n{ok}/{len(PROVE)} corrette (soglie: rumore {config.RAG_SOGLIA_RUMORE}, margine {config.RAG_MARGINE_RUMORE}, caso {config.RAG_SOGLIA_CASO})')


if __name__ == '__main__':
    main()
