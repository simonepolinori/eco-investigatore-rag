# Mappa delle tabelle · Giorno 4 · Il primo respiro

File `archivio_recuperato.sqlite` · impronta SHA-256 `97fc8f1e8e09538b…` · generata il 22/10/2026 12:42

| Tabella | Entità (ipotesi) | Righe | Significato | Colonne | Prove |
|---|---|---|---|---|---|
| `r02` | SITO | 24 | I siti (archivi) della zona: nome e sigla. | `k0` **PK**: chiave primaria (24 distinti)<br>`v1`: nome del sito (es. «Archivio Lete») (24 distinti)<br>`v2`: sigla del sito (AR-3-xx, AC-374) (24 distinti) | 24 righe, nomi tutti diversi «Archivio …»: c'è anche «Archivio Lete», la nostra destinazione; r07.k1 punta qui. |
| `r07` | VARCO | 25 | I varchi d'ingresso di ogni sito. | `k0` **PK**: chiave primaria (25 distinti)<br>`k1` FK→r02.k0: sito → r02.k0 (24 distinti)<br>`v1`: codice del varco (V-38, V-38-B, P-3-xx) (25 distinti) | v1 contiene «V-38» (il varco della missione) e il simile «V-38-B»; k1 punta a r02 su tutte le righe. |
| `r09` | TERMINALE | 52 | I terminali che controllano un varco: canale e stato. | `k0` **PK**: chiave primaria (52 distinti)<br>`k1` FK→r07.k0: varco controllato → r07.k0 (25 distinti)<br>`v1`: canale del terminale (Canale …) (Canale Delta ×23, Canale Omega ×23, Canale Ferro ×1, Canale Kappa ×1, Canale Lambda ×1, Canale Quarzo ×1, Canale Rame ×1, Canale Secondario ×1)<br>`v2`: stato: OPERATIVO / FUORI_SERVIZIO (OPERATIVO ×51, FUORI_SERVIZIO ×1) | v2 ha solo OPERATIVO e FUORI_SERVIZIO (la regola «Terminale»); v1 sono canali; k1 punta a r07. |
| `m05` | FINESTRA | 154 | Le finestre di apertura di ogni terminale. | `k0` **PK**: chiave primaria (154 distinti)<br>`k1` FK→r09.k0: terminale → r09.k0 (52 distinti)<br>`ts_a`: inizio (incluso) (2026-11-04 08:00 ×51, 2026-11-04 11:30 ×51, 2026-11-04 12:30 ×51, 2026-11-03 08:00 ×1)<br>`ts_b`: fine (esclusa) (2026-11-04 12:10 ×51, 2026-11-04 12:20 ×51, 2026-11-04 20:00 ×51, 2026-11-03 20:00 ×1) | Solo un terminale e un intervallo di tempo (3 per terminale): la regola «Finestra di apertura». |
| `r13` | CHIAVE | 154 | Le versioni della chiave di ogni terminale (codice e validità). | `k0` **PK**: chiave primaria (154 distinti)<br>`k1` FK→r09.k0: terminale → r09.k0 (52 distinti)<br>`v1`: codice della chiave (TESTO, 6 cifre) (154 distinti)<br>`ts_a`: valida dal (incluso) (2026-11-03 08:00 ×52, 2026-11-04 08:00 ×51, 2026-11-04 12:30 ×51)<br>`ts_b`: valida fino a (escluso) (2026-11-03 20:00 ×52, 2026-11-04 12:30 ×51, 2026-11-04 20:00 ×51) | v1 sono codici di 6 cifre, tutti diversi; un terminale ne ha diverse, in periodi diversi: «versione della chiave». |
| `r03` | PERSONA | 265 | Le persone: nome e badge. | `k0` **PK**: chiave primaria (265 distinti)<br>`v1`: nome e cognome (265 distinti)<br>`v2`: badge (PX-…) (265 distinti) | 265 righe con nomi di persona e un identificativo PX-…; m12, r06, e04 e r15 puntano qui. |
| `r11` | SQUADRA | 74 | Le squadre (Unità / Nucleo). | `k0` **PK**: chiave primaria (74 distinti)<br>`v1`: nome della squadra (Unità 3-…, Nucleo 3-…) (74 distinti) | 74 nomi «Unità …» e «Nucleo …»; i permessi (r08) e le appartenenze (m12) puntano qui. |
| `m12` | APPARTENENZA | 505 | Chi fa parte di quale squadra e da quando a quando. | `k0` **PK**: chiave primaria (505 distinti)<br>`k1` FK→r03.k0: persona → r03.k0 (265 distinti)<br>`k2` FK→r11.k0: squadra → r11.k0 (74 distinti)<br>`ts_a`: dal (incluso) (2026-11-04 08:00 ×262, 2026-11-03 08:00 ×241, 2026-11-04 12:30 ×2)<br>`ts_b`: al (escluso; NULL = ancora membro) (None ×262, 2026-11-03 20:00 ×241, 2026-11-04 12:20 ×2) | Collega persone e squadre nel tempo (regola «Stessa squadra»); alcune persone hanno registrazioni doppie. |
| `r06` | ABILITAZIONE | 327 | Le abilitazioni di una persona a un ruolo. | `k0` **PK**: chiave primaria (327 distinti)<br>`k1` FK→r03.k0: persona → r03.k0 (265 distinti)<br>`v1`: ruolo: SANITARIO / SICUREZZA (SANITARIO ×164, SICUREZZA ×163)<br>`ts_a`: valida dal (incluso) (2026-11-04 08:00 ×266, 2026-11-04 09:00 ×61)<br>`ts_b`: fino a (escluso; NULL = senza scadenza) (None ×323, 2026-11-04 12:20 ×3, 2026-11-04 11:00 ×1) | v1 ha solo SANITARIO e SICUREZZA (i due ruoli); k1 punta a r03; ci sono rinnovi sovrapposti. |
| `e04` | SOSPENSIONE | 23 | Le sospensioni delle persone. | `k0` **PK**: chiave primaria (23 distinti)<br>`k1` FK→r03.k0: persona → r03.k0 (23 distinti)<br>`ts_a`: dal (incluso) (2026-11-04 10:00 ×20, 2026-11-04 11:00 ×1, 2026-11-04 11:50 ×1, 2026-11-04 14:00 ×1)<br>`ts_b`: al (escluso; NULL = senza fine) (2026-11-04 13:00 ×21, None ×1, 2026-11-04 15:00 ×1)<br>`v1`: motivo (controllo ordinario, ritiro idoneità…) (controllo ordinario ×20, ritiro idoneità ×1, verifica credenziali ×1, verifica periodica ×1) | Pochi casi (23), motivi da sospensione e un intervallo; una ha inizio nel futuro (regola «Sospensioni»). |
| `r08` | PERMESSO | 146 | Il permesso di una squadra su un varco, per un ruolo. | `k0` **PK**: chiave primaria (146 distinti)<br>`k1` FK→r11.k0: squadra → r11.k0 (74 distinti)<br>`k2` FK→r07.k0: varco → r07.k0 (25 distinti)<br>`v1`: ruolo: SANITARIO / SICUREZZA (SANITARIO ×73, SICUREZZA ×73)<br>`ts_a`: valido dal (incluso) (2026-11-04 08:00 ×143, 2026-11-04 12:30 ×2, 2026-11-04 13:00 ×1)<br>`ts_b`: fino a (escluso; NULL = senza scadenza) (None ×145, 2026-11-04 11:59 ×1)<br>`v2`: stato: ATTIVO / BLOCCATO (ATTIVO ×145, BLOCCATO ×1) | Squadra + varco + ruolo + periodo + stato ATTIVO/BLOCCATO: esattamente la regola «Permessi». |
| `e10` | REVOCA | 26 | Le revoche dei permessi (con l'istante da cui valgono). | `k0` **PK**: chiave primaria (26 distinti)<br>`k1` FK→r08.k0: permesso revocato → r08.k0 (26 distinti)<br>`ts_a`: istante di effetto (2026-11-04 11:30 ×24, 2026-11-04 11:00 ×1, 2026-11-04 12:20 ×1)<br>`v1`: motivo (aggiornamento turni ×24, cambio turno ×1, revoca direzione ×1) | k1 punta a r08; motivi «revoca direzione», «cambio turno»; un solo istante: quello da cui la revoca vale. |
| `r14` | COPIA REGISTRO (fonte storica) | 146 | Copia del registro dei permessi fatta nel turno precedente: FONTE STORICA. | `k0` **PK**: chiave primaria (146 distinti)<br>`k1` FK→r08.k0: permesso copiato → r08.k0 (146 distinti)<br>`k2` FK→r11.k0: squadra → r11.k0 (74 distinti)<br>`k3` FK→r07.k0: varco → r07.k0 (25 distinti)<br>`v1`: ruolo (SANITARIO ×73, SICUREZZA ×73)<br>`ts_a`: dal (2026-11-04 08:00 ×146)<br>`ts_b`: al (2026-11-04 20:00 ×146)<br>`v2`: stato copiato (ATTIVO ×146)<br>`ts_c`: data della copia (2026-11-03 18:00 ×146)<br>`v3`: provenienza (REPLICA_TURNO_PRECEDENTE) (REPLICA_TURNO_PRECEDENTE ×146) | Una riga per ogni permesso (k1 → r08, tutti diversi), con provenienza e data della copia (3/11 18:00): aiuta a capire i dati ma non prova autorizzazioni correnti. |
| `r15` | ACCESSO PASSATO (fonte storica) | 180 | Gli accessi registrati il giorno prima (3/11): FONTE STORICA. | `k0` **PK**: chiave primaria (180 distinti)<br>`k1` FK→r09.k0: terminale → r09.k0 (52 distinti)<br>`k2` FK→r03.k0: persona → r03.k0 (180 distinti)<br>`ts_a`: quando (60 distinti)<br>`v1`: esito: OK / NEGATO (OK ×144, NEGATO ×36)<br>`v2`: codice della chiave usata (52 distinti) | Tutti del 3/11, esito OK/NEGATO e la chiave usata: è un registro di accessi passati, non un'autorizzazione. |

## Relazioni (controllo dei riferimenti su tutte le righe)

| Chiave esterna | → | Relazione | Cardinalità (padre : figlio) | Prova |
|---|---|---|---|---|
| `r07.k1` | `r02.k0` | si trova in | (1,N) : (1,1) | ✅ 25 valori di r07.k1 (24 distinti): 25 si trovano in r02.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `r09.k1` | `r07.k0` | controlla | (1,N) : (1,1) | ✅ 52 valori di r09.k1 (25 distinti): 52 si trovano in r07.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `m05.k1` | `r09.k0` | apre in | (1,N) : (1,1) | ✅ 154 valori di m05.k1 (52 distinti): 154 si trovano in r09.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `r13.k1` | `r09.k0` | versione di | (1,N) : (1,1) | ✅ 154 valori di r13.k1 (52 distinti): 154 si trovano in r09.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `m12.k1` | `r03.k0` | membro | (1,N) : (1,1) | ✅ 505 valori di m12.k1 (265 distinti): 505 si trovano in r03.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `m12.k2` | `r11.k0` | di squadra | (1,N) : (1,1) | ✅ 505 valori di m12.k2 (74 distinti): 505 si trovano in r11.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `r06.k1` | `r03.k0` | abilita | (1,N) : (1,1) | ✅ 327 valori di r06.k1 (265 distinti): 327 si trovano in r03.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `e04.k1` | `r03.k0` | sospende | (0,1) : (1,1) | ✅ 23 valori di e04.k1 (23 distinti): 23 si trovano in r03.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `r08.k1` | `r11.k0` | concesso a | (1,N) : (1,1) | ✅ 146 valori di r08.k1 (74 distinti): 146 si trovano in r11.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `r08.k2` | `r07.k0` | per varco | (1,N) : (1,1) | ✅ 146 valori di r08.k2 (25 distinti): 146 si trovano in r07.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `e10.k1` | `r08.k0` | revoca | (0,1) : (1,1) | ✅ 26 valori di e10.k1 (26 distinti): 26 si trovano in r08.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `r14.k1` | `r08.k0` | copia di | (1,1) : (1,1) | ✅ 146 valori di r14.k1 (146 distinti): 146 si trovano in r08.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `r14.k2` | `r11.k0` | copia squadra | (1,N) : (1,1) | ✅ 146 valori di r14.k2 (74 distinti): 146 si trovano in r11.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `r14.k3` | `r07.k0` | copia varco | (1,N) : (1,1) | ✅ 146 valori di r14.k3 (25 distinti): 146 si trovano in r07.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `r15.k1` | `r09.k0` | registrato da | (1,N) : (1,1) | ✅ 180 valori di r15.k1 (52 distinti): 180 si trovano in r09.k0, nessun orfano; nessun'altra tabella li contiene tutti |
| `r15.k2` | `r03.k0` | eseguito da | (0,1) : (1,1) | ✅ 180 valori di r15.k2 (180 distinti): 180 si trovano in r03.k0, nessun orfano; nessun'altra tabella li contiene tutti |

## Verifica con i parametri in uso

**varco V-38 (Archivio Lete), 2026-11-04 12:00: 2 possibilità valide (sempre Irene Rosi + Luca Nardi della Unità 3-Ardesia, cambia il terminale); manca il canale del lettore del veicolo: va chiesto alla centrale.**

| Squadra | SANITARIO | SICUREZZA | Terminale | Chiave |
|---|---|---|---|---|
| Unità 3-Ardesia | Irene Rosi (PX-254136) | Luca Nardi (PX-732798) | Canale Kappa (5005325) | `580199` |
| Unità 3-Ardesia | Irene Rosi (PX-254136) | Luca Nardi (PX-732798) | Canale Lambda (8177200) | `364801` |

### Candidati esclusi

| Tipo | Chi | Motivo | Regola |
|---|---|---|---|
| varco | V-38-B (Archivio Lete) | codice simile: NON è il varco richiesto | Terminale: deve controllare il varco richiesto |
| squadra | Unità 3-Arenaria | permesso SANITARIO stato BLOCCATO | Permessi / Revoche |
| squadra | Unità 3-Argilla | permesso SANITARIO vale solo dal 2026-11-04 13:00 | Permessi / Revoche |
| squadra | Unità 3-Gesso | permesso SANITARIO revocato dal 2026-11-04 11:00 | Permessi / Revoche |
| squadra | Unità 3-Marmo | permesso SANITARIO scaduto (fine 2026-11-04 11:59, esclusa) | Permessi / Revoche |
| squadra | Unità 3-Ossidiana | permesso SANITARIO vale solo dal 2026-11-04 12:30; permesso SICUREZZA vale solo dal 2026-11-04 12:30 | Permessi / Revoche |
| squadra | Unità 3-Porfido | nessun permesso SICUREZZA sul varco | Permessi / Revoche |
| squadra | Unità 3-Porfido bis | nessun permesso SANITARIO sul varco | Permessi / Revoche |
| persona | Alma Berti (PX-430041) | Unità 3-Basalto: sospesa dal 2026-11-04 11:50 (senza fine) (ritiro idoneità) | Sospensioni |
| squadra | Unità 3-Basalto | permessi validi, ma nessun membro utilizzabile come SANITARIO | Due persone / Stessa squadra |
| persona | Berto Guerra (PX-985826) | Unità 3-Calce: sospesa dal 2026-11-04 11:00 al 2026-11-04 13:00 (verifica credenziali) | Sospensioni |
| squadra | Unità 3-Calce | permessi validi, ma nessun membro utilizzabile come SICUREZZA | Due persone / Stessa squadra |
| persona | Gemma Fontana (PX-697993) | Unità 3-Granito: abilitazione SANITARIO scaduta (2026-11-04 08:00–2026-11-04 11:00) | Abilitazioni |
| squadra | Unità 3-Granito | permessi validi, ma nessun membro utilizzabile come SANITARIO | Due persone / Stessa squadra |
| persona | Clara Donati (PX-626048) | appartenenza a Unità 3-Selce finita il 2026-11-03 20:00 | Stessa squadra: conta l'istante richiesto |
| squadra | Unità 3-Selce | permessi validi, ma nessun membro utilizzabile come SANITARIO | Due persone / Stessa squadra |
| persona | Hilda Pellegrini (PX-561431) | Unità 3-Tufo: una sola persona utilizzabile (Hilda Pellegrini) con entrambe le abilitazioni: servono due persone diverse | Due persone |
| squadra | Unità 3-Tufo | permessi validi, ma una sola persona utilizzabile (Hilda Pellegrini) con entrambe le abilitazioni: servono due persone diverse | Due persone / Stessa squadra |
| terminale | Canale Ferro (terminale 2892344) | nessuna chiave valida | Terminale / Finestra e chiave |
| terminale | Canale Quarzo (terminale 7617325) | FUORI_SERVIZIO | Terminale / Finestra e chiave |
| terminale | Canale Rame (terminale 273432) | nessuna finestra di apertura valida | Terminale / Finestra e chiave |

### Le query della verifica (eseguite dal tool di sola lettura)

**1 · Il varco richiesto** — Varco V-38 del sito «Archivio Lete»: r07 (varchi) collegato a r02 (siti). I codici simili sono mostrati e scartati. (2 righe)

```sql
SELECT v.k0 AS varco_id, v.v1 AS varco, s.v1 AS sito, s.v2 AS sigla,
  CASE WHEN v.v1 = 'V-38' AND s.v1 = 'Archivio Lete' THEN 'varco richiesto'
       WHEN v.v1 = 'V-38' THEN 'stesso codice ma in un altro sito: escluso'
       ELSE 'codice simile: NON è il varco richiesto' END AS esito
FROM r07 v
JOIN r02 s ON s.k0 = v.k1
WHERE v.v1 = 'V-38' OR v.v1 LIKE 'V-38-%'
ORDER BY v.v1
```

**2 · Permessi sul varco (r08) e revoche (e10)** — Per ogni squadra e ruolo: ATTIVO, valido all'istante (inizio incluso, fine esclusa, NULL = senza scadenza) e senza una revoca già efficace (conta l'istante di effetto). (24 righe)

```sql
SELECT p.k0 AS permesso, p.k1 AS squadra_id, q.v1 AS squadra, p.v1 AS ruolo, p.v2 AS stato,
  p.ts_a AS dal, p.ts_b AS al, (SELECT MIN(r.ts_a) FROM e10 r WHERE r.k1 = p.k0) AS revoca_dal,
  CASE WHEN p.v2 <> 'ATTIVO' THEN 'escluso: stato ' || p.v2
       WHEN p.ts_a > '2026-11-04 12:00' THEN 'escluso: vale solo dal ' || p.ts_a
       WHEN p.ts_b IS NOT NULL AND p.ts_b <= '2026-11-04 12:00' THEN 'escluso: scaduto (fine ' || p.ts_b || ', esclusa)'
       WHEN EXISTS (SELECT 1 FROM e10 r WHERE r.k1 = p.k0 AND r.ts_a <= '2026-11-04 12:00')
         THEN 'escluso: revocato dal ' || (SELECT MIN(r.ts_a) FROM e10 r WHERE r.k1 = p.k0 AND r.ts_a <= '2026-11-04 12:00')
       WHEN EXISTS (SELECT 1 FROM e10 r WHERE r.k1 = p.k0)
         THEN 'valido (revoca dal ' || (SELECT MIN(r.ts_a) FROM e10 r WHERE r.k1 = p.k0) || ': non ancora efficace)'
       ELSE 'valido' END AS esito
FROM r08 p
JOIN r11 q ON q.k0 = p.k1
WHERE p.k2 IN (3307343)
ORDER BY q.v1, p.v1
```

**3 · Squadre con un permesso valido per ENTRAMBI i ruoli** — La regola dei permessi in una sola query: GROUP BY squadra, servono 2 ruoli validi. (6 righe)

```sql
SELECT q.v1 AS squadra, p.k1 AS squadra_id, GROUP_CONCAT(DISTINCT p.v1) AS ruoli_validi
FROM r08 p
JOIN r11 q ON q.k0 = p.k1
WHERE p.k2 IN (3307343)
  AND p.v2 = 'ATTIVO'
  AND p.ts_a <= '2026-11-04 12:00' AND (p.ts_b IS NULL OR '2026-11-04 12:00' < p.ts_b)
  AND NOT EXISTS (SELECT 1 FROM e10 r WHERE r.k1 = p.k0 AND r.ts_a <= '2026-11-04 12:00')
GROUP BY p.k1
HAVING COUNT(DISTINCT p.v1) = 2
ORDER BY q.v1
```

**4 · Membri delle squadre candidate (m12) nell'istante richiesto** — Una vecchia appartenenza non vale; più registrazioni della stessa persona contano una volta. (11 righe)

```sql
SELECT q.v1 AS squadra, m.k2 AS squadra_id, pe.k0 AS persona_id, pe.v1 AS persona, pe.v2 AS badge,
  COUNT(*) AS registrazioni, MIN(m.ts_a) AS dal,
  CASE WHEN SUM(m.ts_b IS NULL) > 0 THEN NULL ELSE MAX(m.ts_b) END AS al,
  MAX(CASE WHEN m.ts_a <= '2026-11-04 12:00' AND (m.ts_b IS NULL OR '2026-11-04 12:00' < m.ts_b) THEN 1 ELSE 0 END) AS membro_ora
FROM m12 m
JOIN r03 pe ON pe.k0 = m.k1
JOIN r11 q ON q.k0 = m.k2
WHERE m.k2 IN (6671650, 4486312, 2916256, 6640983, 1433533, 6023938)
GROUP BY m.k2, pe.k0
ORDER BY q.v1, pe.v1
```

**5 · Abilitazioni dei membri (r06)** — Ruolo valido all'istante; i rinnovi sovrapposti non sono persone diverse. (13 righe)

```sql
SELECT pe.v1 AS persona, a.k1 AS persona_id, a.v1 AS ruolo, a.ts_a AS dal, a.ts_b AS al,
  CASE WHEN a.ts_a > '2026-11-04 12:00' THEN 'non ancora valida'
       WHEN a.ts_b IS NOT NULL AND a.ts_b <= '2026-11-04 12:00' THEN 'scaduta'
       ELSE 'valida' END AS esito
FROM r06 a
JOIN r03 pe ON pe.k0 = a.k1
WHERE a.k1 IN (20789, 1492414, 2353889, 5106582, 5177281, 7764921, 7842365, 7852439, 7951569, 8640532, 9562436)
ORDER BY pe.v1, a.v1, a.ts_a
```

**6 · Sospensioni dei membri (e04)** — Esclude chi è sospeso all'istante; una sospensione futura non è ancora attiva. (2 righe)

```sql
SELECT pe.v1 AS persona, s.k1 AS persona_id, s.v1 AS motivo, s.ts_a AS dal, s.ts_b AS al,
  CASE WHEN s.ts_a > '2026-11-04 12:00' THEN 'futura: non ancora attiva'
       WHEN s.ts_b IS NOT NULL AND s.ts_b <= '2026-11-04 12:00' THEN 'finita'
       ELSE 'ATTIVA' END AS esito
FROM e04 s
JOIN r03 pe ON pe.k0 = s.k1
WHERE s.k1 IN (20789, 1492414, 2353889, 5106582, 5177281, 7764921, 7842365, 7852439, 7951569, 8640532, 9562436)
ORDER BY pe.v1
```

**7 · Coppie valide (SANITARIO + SICUREZZA): tutte le regole sulle persone** — Stessa squadra nell'istante, persone diverse, abilitazioni valide, nessuna sospensione attiva, permessi validi della squadra per i due ruoli. (1 righe)

```sql
WITH membri AS (SELECT DISTINCT m.k2 AS squadra, m.k1 AS persona FROM m12 m WHERE m.ts_a <= '2026-11-04 12:00' AND (m.ts_b IS NULL OR '2026-11-04 12:00' < m.ts_b)),
abilitati AS (SELECT DISTINCT a.k1 AS persona, a.v1 AS ruolo FROM r06 a WHERE a.ts_a <= '2026-11-04 12:00' AND (a.ts_b IS NULL OR '2026-11-04 12:00' < a.ts_b)),
sospesi AS (SELECT DISTINCT s.k1 AS persona FROM e04 s WHERE s.ts_a <= '2026-11-04 12:00' AND (s.ts_b IS NULL OR '2026-11-04 12:00' < s.ts_b)),
permessi AS (SELECT DISTINCT p.k1 AS squadra, p.v1 AS ruolo FROM r08 p
  WHERE p.k2 IN (3307343) AND p.v2 = 'ATTIVO' AND p.ts_a <= '2026-11-04 12:00' AND (p.ts_b IS NULL OR '2026-11-04 12:00' < p.ts_b)
    AND NOT EXISTS (SELECT 1 FROM e10 r WHERE r.k1 = p.k0 AND r.ts_a <= '2026-11-04 12:00')),
coppie AS (SELECT m1.squadra, m1.persona AS sanitario, m2.persona AS sicurezza
  FROM membri m1
  JOIN membri m2 ON m2.squadra = m1.squadra AND m2.persona <> m1.persona
  JOIN abilitati a1 ON a1.persona = m1.persona AND a1.ruolo = 'SANITARIO'
  JOIN abilitati a2 ON a2.persona = m2.persona AND a2.ruolo = 'SICUREZZA'
  JOIN permessi p1 ON p1.squadra = m1.squadra AND p1.ruolo = 'SANITARIO'
  JOIN permessi p2 ON p2.squadra = m1.squadra AND p2.ruolo = 'SICUREZZA'
  WHERE m1.persona NOT IN (SELECT persona FROM sospesi) AND m2.persona NOT IN (SELECT persona FROM sospesi))
SELECT q.v1 AS squadra, c.squadra AS squadra_id, s1.v1 AS sanitario, s1.v2 AS badge_sanitario, c.sanitario AS sanitario_id,
  s2.v1 AS sicurezza, s2.v2 AS badge_sicurezza, c.sicurezza AS sicurezza_id
FROM coppie c
JOIN r11 q ON q.k0 = c.squadra
JOIN r03 s1 ON s1.k0 = c.sanitario
JOIN r03 s2 ON s2.k0 = c.sicurezza
ORDER BY q.v1, s1.v1, s2.v1
```

**8 · Terminali del varco (r09) con finestra (m05) e chiave (r13) valide** — OPERATIVO, canale compatibile con il lettore del veicolo (canale non comunicato: tutti i canali restano possibili), almeno una finestra di apertura e una versione della chiave valide all'istante. (5 righe)

```sql
SELECT t.k0 AS terminale, t.v1 AS canale, t.v2 AS stato,
  (SELECT COUNT(*) FROM m05 f WHERE f.k1 = t.k0 AND f.ts_a <= '2026-11-04 12:00' AND (f.ts_b IS NULL OR '2026-11-04 12:00' < f.ts_b)) AS finestre_valide,
  (SELECT GROUP_CONCAT(c.v1, ' / ') FROM r13 c WHERE c.k1 = t.k0 AND c.ts_a <= '2026-11-04 12:00' AND (c.ts_b IS NULL OR '2026-11-04 12:00' < c.ts_b)) AS codice,
  CASE WHEN t.v2 <> 'OPERATIVO' THEN 'escluso: ' || t.v2
       WHEN (SELECT COUNT(*) FROM m05 f WHERE f.k1 = t.k0 AND f.ts_a <= '2026-11-04 12:00' AND (f.ts_b IS NULL OR '2026-11-04 12:00' < f.ts_b)) = 0 THEN 'escluso: nessuna finestra di apertura valida'
       WHEN (SELECT COUNT(*) FROM r13 c WHERE c.k1 = t.k0 AND c.ts_a <= '2026-11-04 12:00' AND (c.ts_b IS NULL OR '2026-11-04 12:00' < c.ts_b)) = 0 THEN 'escluso: nessuna chiave valida'
       ELSE 'valido' END AS esito
FROM r09 t
WHERE t.k1 IN (3307343)
ORDER BY t.v1
```

**9 · Finestre di apertura e versioni della chiave dei terminali** — Il dettaglio dei periodi: valida = l'istante è dentro [dal, al). (26 righe)

```sql
SELECT t.v1 AS canale, 'finestra' AS tipo, NULL AS codice, f.ts_a AS dal, f.ts_b AS al,
  CASE WHEN f.ts_a <= '2026-11-04 12:00' AND (f.ts_b IS NULL OR '2026-11-04 12:00' < f.ts_b) THEN 'valida' WHEN f.ts_a > '2026-11-04 12:00' THEN 'futura' ELSE 'finita' END AS esito
FROM m05 f JOIN r09 t ON t.k0 = f.k1
WHERE t.k1 IN (3307343)
UNION ALL
SELECT t.v1, 'chiave', c.v1, c.ts_a, c.ts_b,
  CASE WHEN c.ts_a <= '2026-11-04 12:00' AND (c.ts_b IS NULL OR '2026-11-04 12:00' < c.ts_b) THEN 'valida' WHEN c.ts_a > '2026-11-04 12:00' THEN 'futura' ELSE 'finita' END
FROM r13 c JOIN r09 t ON t.k0 = c.k1
WHERE t.k1 IN (3307343)
ORDER BY canale, tipo, dal
```

**10 · Soluzione: due operatori autorizzati, terminale e chiave** — Tutte le regole insieme. Nessun ordinamento per identificativo: se le righe sono più di una, i dati lasciano più possibilità. (2 righe)

```sql
WITH membri AS (SELECT DISTINCT m.k2 AS squadra, m.k1 AS persona FROM m12 m WHERE m.ts_a <= '2026-11-04 12:00' AND (m.ts_b IS NULL OR '2026-11-04 12:00' < m.ts_b)),
abilitati AS (SELECT DISTINCT a.k1 AS persona, a.v1 AS ruolo FROM r06 a WHERE a.ts_a <= '2026-11-04 12:00' AND (a.ts_b IS NULL OR '2026-11-04 12:00' < a.ts_b)),
sospesi AS (SELECT DISTINCT s.k1 AS persona FROM e04 s WHERE s.ts_a <= '2026-11-04 12:00' AND (s.ts_b IS NULL OR '2026-11-04 12:00' < s.ts_b)),
permessi AS (SELECT DISTINCT p.k1 AS squadra, p.v1 AS ruolo FROM r08 p
  WHERE p.k2 IN (3307343) AND p.v2 = 'ATTIVO' AND p.ts_a <= '2026-11-04 12:00' AND (p.ts_b IS NULL OR '2026-11-04 12:00' < p.ts_b)
    AND NOT EXISTS (SELECT 1 FROM e10 r WHERE r.k1 = p.k0 AND r.ts_a <= '2026-11-04 12:00')),
coppie AS (SELECT m1.squadra, m1.persona AS sanitario, m2.persona AS sicurezza
  FROM membri m1
  JOIN membri m2 ON m2.squadra = m1.squadra AND m2.persona <> m1.persona
  JOIN abilitati a1 ON a1.persona = m1.persona AND a1.ruolo = 'SANITARIO'
  JOIN abilitati a2 ON a2.persona = m2.persona AND a2.ruolo = 'SICUREZZA'
  JOIN permessi p1 ON p1.squadra = m1.squadra AND p1.ruolo = 'SANITARIO'
  JOIN permessi p2 ON p2.squadra = m1.squadra AND p2.ruolo = 'SICUREZZA'
  WHERE m1.persona NOT IN (SELECT persona FROM sospesi) AND m2.persona NOT IN (SELECT persona FROM sospesi)),
terminali AS (SELECT t.k0 AS terminale, t.v1 AS canale, c.v1 AS chiave, c.ts_a AS chiave_dal, c.ts_b AS chiave_al
  FROM r09 t
  JOIN r13 c ON c.k1 = t.k0 AND c.ts_a <= '2026-11-04 12:00' AND (c.ts_b IS NULL OR '2026-11-04 12:00' < c.ts_b)
  WHERE t.k1 IN (3307343) AND t.v2 = 'OPERATIVO'
    AND EXISTS (SELECT 1 FROM m05 f WHERE f.k1 = t.k0 AND f.ts_a <= '2026-11-04 12:00' AND (f.ts_b IS NULL OR '2026-11-04 12:00' < f.ts_b)))
SELECT q.v1 AS squadra, s1.v1 AS sanitario, s1.v2 AS badge_sanitario, s2.v1 AS sicurezza, s2.v2 AS badge_sicurezza,
  te.canale, te.terminale, te.chiave AS codice, te.chiave_dal, te.chiave_al
FROM coppie c
JOIN r11 q ON q.k0 = c.squadra
JOIN r03 s1 ON s1.k0 = c.sanitario
JOIN r03 s2 ON s2.k0 = c.sicurezza
CROSS JOIN terminali te
ORDER BY q.v1, te.canale
```

