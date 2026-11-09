"""Crea rag3d.html: la RAG View 3D, la MAPPA DEI SIGNIFICATI di tutto quello che il RAG di ECO legge.

    python crea_rag3d.py            -> scrive rag3d.html accanto a questo file (si apre con il pulsante 📚 o con doppio clic)

Ogni punto è un documento (i 1505 file dell'archivio digitale + il fascicolo G1…G5). La posizione viene dagli
EMBEDDING, gli stessi vettori che il RAG usa per cercare per significato (paraphrase-multilingual-MiniLM, 384 numeri
per blocco di testo; per un documento si fa la media dei suoi blocchi):
  - asse X = «più vicino al caso»: la somiglianza (coseno) con il CENTRO DEL CASO, cioè la media dei documenti
    dell'indagine (fascicolo, dossier ARCH, registri LX3);
  - assi Y e Z = le due principali variazioni RIMANENTI (analisi delle componenti principali dopo aver tolto la
    direzione del caso): documenti vicini nello spazio parlano di cose simili.
I CLUSTER si calcolano con k-means sui vettori: il «cluster dell'indagine» è quello dove la maggioranza dei documenti
fa parte della storia (rosso nella mappa). I documenti sospetti (ordini rivolti all'AI) sono arancioni.
Nella pagina ci sono anche i parametri della proiezione: con il server di ECO avviato, una domanda (quella scritta lì o
l'ultima della chat) viene trasformata nello stesso spazio e compare come una stella, con le sue fonti cerchiate.

Rieseguitelo quando cambiano i documenti in dati/. Senza il modello di embedding (né la cache) usa una mappa di
riserva fatta con le parole (TF-IDF + SVD) e lo dice nella pagina.
"""
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))

import archivio  # noqa: E402
import config    # noqa: E402
import rag       # noqa: E402

MODELLO = QUI / 'rag3d_modello.html'
USCITA = QUI / 'rag3d.html'
CLUSTER = 30           # quanti cluster (k-means)
TESTO_MAX = 1400       # caratteri del documento mostrati nel pannello
VICINI = 6             # documenti più simili mostrati per ogni punto


def _norm(m):
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.maximum(n, 1e-9)


def vettori_tfidf(testi, dim=96):
    """Riserva senza embedding: TF-IDF delle parole + SVD (stesso spazio per tutti i testi)."""
    tok = [re.findall(r"[a-zà-ù]{4,}", t.lower()) for t in testi]
    df = {}
    for t in tok:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    voc = [w for w, c in sorted(df.items(), key=lambda x: -x[1]) if 2 <= c <= len(testi) * .5][:4000]
    pos = {w: i for i, w in enumerate(voc)}
    M = np.zeros((len(testi), len(voc)), dtype=np.float32)
    for r, t in enumerate(tok):
        for w in t:
            if w in pos:
                M[r, pos[w]] += 1
    M = np.log1p(M) * np.log(len(testi) / np.array([df[w] for w in voc], dtype=np.float32))
    M = _norm(M)
    U, S, Vt = np.linalg.svd(M - M.mean(0), full_matrices=False)
    return _norm((U[:, :dim] * S[:dim]).astype(np.float32)), (M.mean(0), Vt[:dim], pos)


def kmeans(X, k, giri=40, seme=7):
    """k-means sul coseno (vettori normalizzati), inizializzazione k-means++ con seme fisso: stessa mappa ogni volta."""
    rng = np.random.default_rng(seme)
    centri = [X[rng.integers(len(X))]]
    for _ in range(1, k):
        d = 1 - np.max(X @ np.array(centri).T, axis=1)
        p = np.maximum(d, 0) ** 2
        centri.append(X[rng.choice(len(X), p=p / p.sum())] if p.sum() > 0 else X[rng.integers(len(X))])
    C = np.array(centri)
    for _ in range(giri):
        lab = np.argmax(X @ C.T, axis=1)
        nuovi = np.array([_norm(X[lab == j].mean(0)) if np.any(lab == j) else C[j] for j in range(k)])
        if np.allclose(nuovi, C, atol=1e-5):
            break
        C = nuovi
    return np.argmax(X @ C.T, axis=1)


def main():
    t0 = time.time()
    ind = rag.prepara(mostra=False)
    fascicolo = archivio.carica()
    try:
        import logica
        malevoli = {m['id'] for m in logica.malevoli()}
    except Exception:
        malevoli = set()

    docs = []
    for d in fascicolo:
        docs.append({'id': d['id'], 'file': Path(d['file']).name, 'titolo': d['titolo'], 'testo': d['testo'],
                     'giorno': d['giorno'], 'gruppo': 'fascicolo', 'storia': True,
                     'sospetto': bool(d['sospetto'] or d['id'] in malevoli), 'fonte': 'fascicolo della squadra'})
    arch = ind.documenti if ind else []
    for d in arch:
        g = d.get('giorno')
        docs.append({'id': d['id'], 'file': d['file'], 'titolo': d['titolo'], 'testo': d['testo'],
                     'giorno': int(g) if str(g).isdigit() else 3,
                     'gruppo': 'registri LX3' if d.get('raccolta') == 'archivio_imprevisti_g3' else
                               ('dossier' if d['classe'] != 'rumore' else 'enciclopedia'),
                     'storia': d['classe'] != 'rumore', 'sospetto': bool(d.get('sospetto')),
                     'fonte': (d.get('fonte') or '')[:120], 'classe': d['classe']})

    # ── vettori dei documenti ──
    metodo, proiezione_parole = 'embedding', None
    V_arch = None
    if ind is not None and ind.vettori is not None:
        V_arch = np.array([_norm(ind.vettori[ind.blocchi_di[i]].mean(0)) for i in range(len(arch))], dtype=np.float32)
    if V_arch is not None:
        testi_f = [f'{d["titolo"]}. {d["testo"]}' for d in fascicolo]
        V_f = rag.codifica(testi_f) if testi_f else np.zeros((0, V_arch.shape[1]), np.float32)
        if V_f is None:            # niente modello: il fascicolo va dove sono i blocchi dell'archivio più simili (BM25)
            metodo = 'embedding (fascicolo stimato dai blocchi più simili)'
            V_f = []
            for t in testi_f:
                pp = ind.bm25.punteggi(t) if hasattr(ind.bm25, 'punteggi') else None
                if pp is None:
                    pp = np.array([ind.bm25.score(t, j) for j in range(len(ind.blocchi))]) if hasattr(ind.bm25, 'score') else None
                if pp is None:
                    V_f.append(_norm(ind.vettori.mean(0)))
                    continue
                top = np.argsort(-np.asarray(pp))[:6]
                V_f.append(_norm(ind.vettori[top].mean(0)))
            V_f = np.array(V_f, dtype=np.float32)
        V = np.vstack([V_f, V_arch]) if len(V_f) else V_arch
    else:
        metodo = 'parole (TF-IDF + SVD): il modello di embedding non è disponibile'
        V, proiezione_parole = vettori_tfidf([f'{d["titolo"]}. {d["testo"]}' for d in docs])
    V = _norm(V.astype(np.float32))

    # ── il centro del caso: fascicolo, dossier e registri pesano uguale (i 500 registri non devono dominare) ──
    gruppi = [np.array([d['gruppo'] == g for d in docs]) for g in ('fascicolo', 'dossier', 'registri LX3')]
    medie = [V[m].mean(0) for m in gruppi if m.any()]
    caso = _norm(np.mean(medie, axis=0))
    sim = V @ caso
    R = V - np.outer(sim, caso)                      # quello che resta dopo aver tolto la direzione del caso
    media_R = R.mean(0)
    _, _, Vt = np.linalg.svd(R - media_R, full_matrices=False)
    comp = Vt[:2]
    yz = (R - media_R) @ comp.T
    # scale: X da -1 a 1 circa sulla somiglianza, Y e Z con la stessa ampiezza
    sx = (sim - sim.mean()) / (sim.std() or 1)
    syz = yz / (yz.std(0) + 1e-9)
    scala = float(np.percentile(np.abs(np.c_[sx, syz]), 98)) or 1
    P = np.c_[sx, syz] / scala
    centro_yz = (P[:, 1:].max(0) + P[:, 1:].min(0)) / 2
    P[:, 1:] -= centro_yz                                       # la nuvola ruota intorno al suo centro

    # ── cluster ──
    lab = kmeans(V, min(CLUSTER, len(V)))
    quota = {j: float(np.mean([docs[i]['storia'] for i in np.where(lab == j)[0]])) for j in set(lab.tolist())}
    indagine = {j for j, q in quota.items() if q >= .5}
    rinumera = {j: n + 1 for n, j in enumerate(sorted(set(lab.tolist()), key=lambda j: (-quota[j], j)))}

    # ── vicini (coseno) ──
    S = V @ V.T
    np.fill_diagonal(S, -2)
    vicini = np.argsort(-S, axis=1)[:, :VICINI]

    punti = []
    for i, d in enumerate(docs):
        punti.append({'id': d['id'], 'f': d['file'], 't': d['titolo'][:90], 'g': d['giorno'], 'gr': d['gruppo'],
                      'c': rinumera[int(lab[i])], 'p': int(lab[i]) in indagine, 's': d['sospetto'], 'st': d['storia'],
                      'sim': round(float(sim[i]), 3), 'x': round(float(P[i, 0]), 4), 'y': round(float(P[i, 1]), 4),
                      'z': round(float(P[i, 2]), 4), 'tx': d['testo'][:TESTO_MAX] + ('…' if len(d['testo']) > TESTO_MAX else ''),
                      'fo': d['fonte'], 'v': [[int(j), round(float(S[i, j]), 3)] for j in vicini[i]]})
    dati = {'punti': punti, 'metodo': metodo, 'creato': time.strftime('%d/%m/%Y %H:%M'),
            'cluster': len(set(lab.tolist())), 'indagine': sorted(rinumera[j] for j in indagine),
            'giorno': config.GIORNO,
            # la proiezione, per mettere nella mappa una domanda nuova (il server ne calcola il vettore)
            'proiezione': None if proiezione_parole else {
                'caso': [round(float(x), 6) for x in caso], 'media_R': [round(float(x), 6) for x in media_R],
                'comp': [[round(float(x), 6) for x in r] for r in comp], 'media_sim': float(sim.mean()),
                'dev_sim': float(sim.std() or 1), 'dev_yz': [float(x) for x in yz.std(0) + 1e-9], 'scala': scala,
                'centro_yz': [float(x) for x in centro_yz]}}
    html = MODELLO.read_text(encoding='utf-8').replace('/*__DATI__*/null', json.dumps(dati, ensure_ascii=False, separators=(',', ':')))
    USCITA.write_text(html, encoding='utf-8')
    print(f'RAG View 3D: {len(punti)} documenti, {dati["cluster"]} cluster ({len(indagine)} dell\'indagine), '
          f'metodo: {metodo} → {USCITA.name} ({USCITA.stat().st_size // 1024} KB, {time.time() - t0:.0f} s)')


if __name__ == '__main__':
    main()
