# TennisIQ Analytics

Genera analisi tennis pronte per Telegram/Discord: record per superficie,
forma pesata per superficie ("momentum"), clutch factor (break point +
tiebreak) e un insight testuale da tipster.

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
# con quote → calcola EV e value pick:
python main.py "Sinner" "Alcaraz" "Roland Garros" --odds1 1.85 --odds2 1.95
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

Il modello di probabilità (`betting.py`) è una combinazione logistica dei
differenziali di metrica. Di default usa pesi-prior euristici; per **calibrarlo
sui dati reali** genera i pesi fittati:

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
- `main.py` — CLI + rendering del post
- `app.py` — frontend Streamlit
