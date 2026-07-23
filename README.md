# TennisIQ Analytics

Genera analisi tennis pronte per Telegram/Discord: record per superficie,
forma pesata per superficie ("momentum"), clutch factor (break point +
tiebreak), un insight testuale da tipster, e valore atteso (EV) su tre
mercati — **vincente match**, **Over/Under games totali**, **2 vs 3 set**.

CLI e app Streamlit condividono lo stesso motore (`analytics.py`).

## Dati: reali vs mock

Il tool nasce con 8 giocatori d'esempio (mock) hardcoded in `data_provider.py`,
così funziona subito. Per usare **statistiche reali** genera il dataset dai
match ATP storici. Fonte dati:
[TML-Database](https://github.com/Tennismylife/TML-Database) — mirror ATP vivo
e aggiornato con lo schema di Jeff Sackmann (il repo originale
`JeffSackmann/tennis_atp` è stato rimosso da GitHub; resta come fallback se
tornasse online).

```bash
pip install -r requirements.txt
python build_dataset.py --years 4 --top 60
```

Questo crea `players_data.json` con record per superficie, conversione/salvataggio
break point e tiebreak **veri**. `data_provider.py` lo carica in automatico
all'avvio; se il file non c'è, resta il fallback mock.

Commit del file generato (`git add players_data.json`) così anche l'app
deployata parte con i dati reali.

Se il download diretto è bloccato dalla tua rete, clona il database e usa
`--from-dir` (accetta sia i file TML `YYYY.csv` sia quelli Sackmann
`atp_matches_YYYY.csv`):

```bash
git clone --depth 1 https://github.com/Tennismylife/TML-Database.git
python build_dataset.py --from-dir ./TML-Database --years 4 --top 60
```

## Avvio

CLI:

```bash
python main.py "Sinner" "Alcaraz" "Roland Garros"
# con quote → calcola EV e value pick sui tre mercati:
python main.py "Sinner" "Alcaraz" "Roland Garros" \
  --odds1 1.85 --odds2 1.95 \
  --games-line 22.5 --odds-games-over 1.90 --odds-games-under 1.90 \
  --odds-straight-sets 2.10 --odds-extra-sets 1.75
```

App web:

```bash
streamlit run app.py
```

## Valore atteso (EV)

Il tool stima una probabilità di vittoria da record per superficie, forma e
clutch, poi — se fornisci le quote (argomenti CLI o campi nell'app) — la
confronta con la probabilità implicita del bookmaker (margine rimosso) e
calcola l'**EV**: un lato è "value pick" solo se `prob × quota − 1` supera il
margine minimo. Senza quote non c'è scommessa valutabile, solo analisi.

Il modello di probabilità (`betting.py`) è una combinazione logistica di quattro
differenziali: **ranking** (log-rank, il predittore più forte nel tennis), record
per superficie, forma e clutch. Di default usa pesi-prior euristici; per
**calibrarlo sui dati reali** genera i pesi fittati:

```bash
python fit_weights.py --years 8
git add betting_weights.json && git commit -m "fit betting weights"
```

`fit_weights.py` costruisce un training set **walk-forward senza data leakage**
(per ogni match le feature vengono dallo stato precedente al match), fitta una
logistica senza intercetta (così la simmetria "scambio giocatori → 1−prob"
resta garantita) e valida su split temporale (ultimo anno come holdout,
riportando log-loss/accuracy/Brier vs la baseline p=0.5 → log-loss 0.693).
`betting.py` carica `betting_weights.json` in automatico; senza il file resta
sui prior. Il report indica quale dei due è attivo (`fitted` / `heuristic prior`).

## Mercati Games e Set

- **Total Games O/U**: la media attesa di games nel match viene da una
  **regressione lineare fittata** (`fit_weights.py` la scrive in
  `games_weights.json`) su tre feature pre-match: la media storica di
  games/match dei due giocatori, il divario di ranking, il divario di record
  per superficie. La probabilità Over/Under una linea usa una distribuzione
  Normale attorno a quella media, con deviazione standard misurata sui residui
  reali (holdout). Senza il file, resta un prior grezzo (media dei due
  giocatori, o 22.0 games con σ=4.5 se mancano dati).
- **Straight sets vs oltre il minimo**: **non è fittato** — è una formula
  chiusa derivata matematicamente dalla probabilità di vittoria del match,
  assumendo set indipendenti con probabilità costante *q* ("Bradley-Terry per
  set"), generalizzata a best-of-3 e best-of-5 (gli Slam maschili si giocano
  al meglio dei 5, non 3 — `data_provider.best_of_for_tournament()` lo
  determina dal torneo). Nessun peso extra da addestrare: è conseguenza
  diretta del modello vincente, verificata contro una simulazione Monte
  Carlo indipendente.
- **best-of-3 vs best-of-5**: un match bo5 ha strutturalmente più games (in
  media) E più varianza assoluta di un bo3 — non solo una media diversa. Il
  modello games ha una feature dedicata (`best_of_flag`) e **due deviazioni
  standard separate** (`residual_std_bo3`/`residual_std_bo5`, fallback al
  valore aggregato se un formato ha troppo pochi campioni nell'holdout).

`fit_weights.py` genera entrambi i file in un solo comando (`python
fit_weights.py --years 8`); commit di `games_weights.json` insieme agli altri
due (`players_data.json`, `betting_weights.json`) per portare tutto in
produzione.

## Backtest: il modello avrebbe fatto soldi davvero?

`fit_weights.py` misura solo l'**accuratezza** (quanto spesso il modello
indovina il vincitore) — non dice se, alle quote vere, avrebbe generato
profitto. `backtest.py` chiude quel cerchio: cammina i match storici in
ordine cronologico (stessa disciplina walk-forward, zero leakage), abbina
ogni match a una quota storica reale, e simula "punta 1 unità ogni volta che
l'EV supera la soglia" — poi misura il ROI **realizzato**.

Fonte quote: [tennis-data.co.uk](http://www.tennis-data.co.uk/alldata.php) —
un file per anno (xlsx/csv), quote di più bookmaker + medie. Scaricalo tu
manualmente (questo ambiente non può raggiungere quel dominio) e **leggi tu
i termini d'uso del sito** prima di scaricare/usare i dati.

```bash
python backtest.py --odds-dir ./tennis-data --from-dir ./TML-Database --years 8
```

Limiti onesti:
- **Solo il mercato vincente match** ha un backtest storico — tennis-data.co.uk
  non ha quote O/U games/set storiche (nessuna fonte gratuita nota le ha).
- I nomi sono scritti in modo diverso nei due dataset ("Jannik Sinner" vs
  "Sinner J."): l'abbinamento è per cognome+iniziale su **entrambi** i
  giocatori, con finestra di date attorno al torneo. Match ambigui (più
  candidati) o non abbinabili (es. cognomi con "Del/Van/De") vengono
  **scartati**, mai indovinati — meno campioni ma nessun dato falsato. Ogni
  riga di quote viene usata al massimo una volta.
- Il ROI dipende moltissimo dalla soglia `--min-edge` (default 0.05) e dalla
  qualità delle quote scelte (`AvgW/AvgL`, media su più bookmaker, è la stima
  di mercato più robusta — preferibile a un singolo bookmaker).

## Calendario live (opzionale)

`data_provider.py` può leggere il calendario del giorno da un'API tennis via
la variabile d'ambiente `APISPORTS_KEY`. Senza chiave, l'app mostra fixture
d'esempio. Nota: verifica che l'endpoint tennis del provider configurato sia
attivo — in caso contrario il calendario resta sui fixture d'esempio mentre le
statistiche giocatore usano comunque il dataset reale generato sopra.

## File

- `analytics.py` — motore metriche (funzioni pure, senza side effect)
- `data_provider.py` — dati giocatori (dataset reale → mock) + calendario
- `build_dataset.py` — genera `players_data.json` dai match ATP reali
- `betting.py` — probabilità di vittoria, EV, mercati Total Games e Set
- `fit_weights.py` — calibra `betting_weights.json` e `games_weights.json` sui dati reali
- `backtest.py` — backtest ROI/hit-rate sul mercato vincente con quote storiche reali
- `main.py` — CLI + rendering del post
- `app.py` — frontend Streamlit
