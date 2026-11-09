"""Aggiunge i documenti ricevuti: python importa.py Dati_giorno_3.zip G3-imprevisti.zip ...

Va bene sia lo ZIP dei dati del giorno (dati/G3-01.txt, ...) sia lo ZIP degli imprevisti con le cartelle
Squadra_1, Squadra_2, ...: di quello prende solo la nostra squadra (config.SQUADRA). Mai il kit docente.
"""
import sys
from pathlib import Path

import archivio

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)
for nome in sys.argv[1:]:
    scritti = archivio.importa(Path(nome).name, Path(nome).read_bytes())
    print(f'{nome}: {len(scritti)} documenti →', ', '.join(scritti) or 'nessuno')
print()
print(archivio.riepilogo())