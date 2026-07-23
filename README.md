# TennisIQ Analytics

Genera analisi tennis pronte per Telegram/Discord: record per superficie,
forma pesata per superficie ("momentum"), clutch factor (break point +
tiebreak) e un insight testuale da tipster.

CLI e app Streamlit condividono lo stesso motore (`analytics.py`).

## Dati: reali vs mock

Il tool nasce con 8 giocatori d'esempio (mock) hardcoded in `data_provider.py`,
così funziona subito. Per usare **statistiche reali** genera il dataset dai
match ATP storici di [Jeff Sackmann](https://github.com/JeffSackmann/tennis_atp)
(pubblico, gratuito):

```bash
pip install -r requirements.txt
python build_dataset.py --years 4 --top 60
```

Questo crea `players_data.json` con record per superficie, conversione/salvataggio
break point e tiebreak **veri**. `data_provider.py` lo carica in automatico
all'avvio; se il file non c'è, resta il fallback mock.

Commit del file generato (`git add players_data.json`) così anche l'app
deployata parte con i dati reali.

Se hai già scaricato i CSV a mano:

```bash
python build_dataset.py --from-dir ./cartella_csv --years 4 --top 60
```

## Avvio

CLI:

```bash
python main.py "Sinner" "Alcaraz" "Roland Garros"
```

App web:

```bash
streamlit run app.py
```

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
