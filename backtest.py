"""
backtest.py — backtest reale del modello di probabilità contro le quote
storiche di tennis-data.co.uk.

Risponde alla domanda che l'accuracy da sola non può rispondere: se il
modello avesse scommesso ogni volta che il suo EV superava la soglia,
quanto avrebbe realizzato DAVVERO, alle quote vere del giorno?

FONTE QUOTE: tennis-data.co.uk — un file per anno (xlsx o csv), colonne
Winner/Loser in formato "Cognome I." (es. "Sinner J."), Date, Surface,
quote di piu' bookmaker (B365W/L, PSW/L, ...) + medie AvgW/AvgL.
Questo ambiente NON ha accesso di rete a quel dominio (proxy del sandbox):
scarica tu i file (uno per anno) dal tuo PC e passa la cartella con
--odds-dir. Verifica tu stesso i termini d'uso del sito prima di scaricare.

METODOLOGIA (stessa disciplina walk-forward di fit_weights.py — zero leakage):
  1. Ricostruisce lo stato di ogni giocatore SOLO dai match TML/Sackmann
     precedenti alla data corrente (stessa logica di fit_weights.build_samples,
     riusata da qui — stesso stato = stesse feature del modello fittato).
  2. Ogni match TML viene abbinato a una riga di tennis-data.co.uk tramite
     matching fuzzy cognome+iniziale su ENTRAMBI i giocatori (i due dataset
     usano convenzioni di nome diverse) + finestra di date attorno all'inizio
     torneo. Se il match e' ambiguo (piu' candidati), viene scartato — meglio
     un campione piu' piccolo che un abbinamento sbagliato.
  3. Con le quote reali di quel giorno, calcola p(vincitore reale) e
     p(perdente reale) dal modello, l'EV di entrambi i lati; se un lato
     supera --min-edge, simula una puntata da 1 unita'. L'esito reale
     (chi ha vinto davvero, gia' noto dal dataset TML) determina
     profitto (+odds-1) o perdita (-1).
  4. Aggrega bet piazzate, hit rate, ROI, per anno e per formato bo3/bo5.

LIMITE ONESTO: tennis-data.co.uk fornisce solo le quote sul VINCENTE del
match — Total Games e Set restano senza backtest storico (nessuna fonte
gratuita nota con quote O/U games/set storiche).

Uso:
    python backtest.py --odds-dir ./tennis-data --years 8 --from-dir ./TML-Database
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from datetime import datetime

import analytics
import betting
from build_dataset import _canon_surface, _count_tiebreaks, _parse_date, _to_int, parse_score
from fit_weights import MIN_HISTORY, _games_avg, _h2h_record, _new_state, _update_state, _read_rows

# Finestra di tolleranza tra la data di inizio torneo (TML, un valore per
# tutto l'evento) e la data del singolo match (tennis-data.co.uk, per round):
# copre eventi fino a 3 settimane (Slam + qualifiche + rinvii).
DATE_WINDOW_DAYS = 21

# Colonne quote, in ordine di preferenza (la media su piu' bookmaker è la
# stima di mercato più robusta; Pinnacle è considerato il libro più
# "efficiente" in letteratura; Bet365 è il più costante storicamente).
ODDS_COLUMN_PRIORITY = [
    ("AvgW", "AvgL", "average (multi-bookmaker)"),
    ("PSW", "PSL", "Pinnacle"),
    ("B365W", "B365L", "Bet365"),
]


# ── Normalizzazione nomi ──────────────────────────────────────────────────

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _tml_surname_initial(full_name: str) -> tuple[str, str] | None:
    """'Jannik Sinner' -> ('sinner', 's')."""
    parts = _strip_accents(full_name).strip().split()
    if len(parts) < 2:
        return None
    surname = parts[-1].lower()
    initial = parts[0][0].lower()
    return surname, initial


_TD_NAME_RE = re.compile(r"^([A-Za-zÀ-ÿ'\-\. ]+?)\s+([A-Za-z])\.?\s*$")


def _td_surname_initial(short_name: str) -> tuple[str, str] | None:
    """'Sinner J.' -> ('sinner', 'j'). Gestisce cognomi multi-parola."""
    if not short_name:
        return None
    m = _TD_NAME_RE.match(_strip_accents(short_name).strip())
    if not m:
        return None
    surname = m.group(1).strip().lower()
    initial = m.group(2).lower()
    return surname, initial


def _pair_key(a: tuple[str, str], b: tuple[str, str]) -> tuple:
    return tuple(sorted([a, b]))


# ── Caricamento quote tennis-data.co.uk ───────────────────────────────────

def load_odds_files(odds_dir: str, years: list[int]):
    """Legge i file per-anno (xlsx o csv) in un'unica lista di dict normalizzati:
    {winner_key, loser_key, date, odds_w, odds_l, odds_source, surface, tournament}."""
    import pandas as pd

    rows = []
    for year in years:
        path = None
        for ext in (".xlsx", ".xls", ".csv"):
            candidate = os.path.join(odds_dir, f"{year}{ext}")
            if os.path.exists(candidate):
                path = candidate
                break
        if not path:
            print(f"[skip quote] nessun file per {year} in {odds_dir}")
            continue

        try:
            df = pd.read_excel(path) if path.endswith((".xlsx", ".xls")) else pd.read_csv(path)
        except Exception as exc:
            print(f"[skip quote] {path}: {exc}")
            continue

        odds_cols = None
        for wcol, lcol, label in ODDS_COLUMN_PRIORITY:
            if wcol in df.columns and lcol in df.columns:
                odds_cols = (wcol, lcol, label)
                break
        if not odds_cols:
            print(f"[skip quote] {path}: nessuna colonna quote riconosciuta")
            continue
        wcol, lcol, label = odds_cols

        n_loaded = 0
        for _, row in df.iterrows():
            w_name = str(row.get("Winner", "") or "").strip()
            l_name = str(row.get("Loser", "") or "").strip()
            if not w_name or not l_name:
                continue
            w_key = _td_surname_initial(w_name)
            l_key = _td_surname_initial(l_name)
            if not w_key or not l_key:
                continue
            try:
                odds_w = float(row.get(wcol))
                odds_l = float(row.get(lcol))
            except (TypeError, ValueError):
                continue
            if odds_w <= 1.0 or odds_l <= 1.0:
                continue
            date_raw = row.get("Date")
            try:
                date = pd.to_datetime(date_raw).to_pydatetime()
            except Exception:
                continue
            rows.append({
                "id": len(rows), "winner_key": w_key, "loser_key": l_key, "date": date,
                "odds_w": odds_w, "odds_l": odds_l, "odds_source": label,
            })
            n_loaded += 1
        print(f"[ok quote] {os.path.basename(path)}: {n_loaded} match con quote ({label})")
    # id definitivo su TUTTE le righe caricate (più file), non solo per-file
    for i, r in enumerate(rows):
        r["id"] = i
    return rows


def index_odds_by_pair(odds_rows: list[dict]) -> dict:
    """pair_key -> lista di righe quote con quella coppia di giocatori."""
    index: dict[tuple, list[dict]] = {}
    for r in odds_rows:
        key = _pair_key(r["winner_key"], r["loser_key"])
        index.setdefault(key, []).append(r)
    return index


def match_odds_for_tml_row(odds_index: dict, w_name: str, l_name: str, tourney_date, used_ids: set) -> dict | None:
    """Trova la riga quote per un match TML (w_name/l_name, data torneo).
    Ritorna None se non trovato o ambiguo (più di un candidato nella finestra).
    Ogni riga quote viene consumata al massimo una volta (`used_ids`): due
    match reali tra la stessa coppia entro la finestra di date sono rari ma
    possibili, e non devono far scommettere due volte sulla stessa quota."""
    w_key = _tml_surname_initial(w_name)
    l_key = _tml_surname_initial(l_name)
    if not w_key or not l_key or not tourney_date:
        return None
    candidates = odds_index.get(_pair_key(w_key, l_key))
    if not candidates:
        return None

    in_window = [
        r for r in candidates
        if r["id"] not in used_ids and abs((r["date"] - tourney_date).days) <= DATE_WINDOW_DAYS
    ]
    if len(in_window) != 1:
        return None  # 0 = non trovato/già usata, >1 = ambiguo -> scartato per sicurezza
    used_ids.add(in_window[0]["id"])

    hit = in_window[0]
    # orienta odds_w/odds_l secondo il ruolo REALE (TML dice chi ha vinto);
    # nella riga quote "winner_key" potrebbe corrispondere a w_name o l_name.
    if hit["winner_key"] == w_key:
        return {"odds_winner": hit["odds_w"], "odds_loser": hit["odds_l"], "odds_source": hit["odds_source"]}
    else:
        return {"odds_winner": hit["odds_l"], "odds_loser": hit["odds_w"], "odds_source": hit["odds_source"]}


# ── Backtest walk-forward ─────────────────────────────────────────────────

def run_backtest(tml_rows: list[dict], odds_index: dict, min_edge: float) -> dict:
    def sort_key(r):
        d = _parse_date(r.get("tourney_date", ""))
        return (d or datetime.min, _to_int(r.get("match_num"), 0))

    tml_rows = sorted(tml_rows, key=sort_key)
    state: dict[str, dict] = {}
    used_odds_ids: set = set()
    bets = []  # ogni bet: dict con anno, best_of, stake, profit, won

    for r in tml_rows:
        w = (r.get("winner_name") or "").strip()
        l = (r.get("loser_name") or "").strip()
        if not w or not l:
            continue
        surface = _canon_surface(r.get("surface", ""))
        minutes = _to_int(r.get("minutes"), 0) or 95
        date = _parse_date(r.get("tourney_date", ""))
        score = r.get("score", "") or ""
        w_bp_saved, w_bp_faced = _to_int(r.get("w_bpSaved")), _to_int(r.get("w_bpFaced"))
        l_bp_saved, l_bp_faced = _to_int(r.get("l_bpSaved")), _to_int(r.get("l_bpFaced"))
        w_tb_played, w_tb_won = _count_tiebreaks(score, True)
        l_tb_played, l_tb_won = _count_tiebreaks(score, False)
        w_rank, l_rank = _to_int(r.get("winner_rank")), _to_int(r.get("loser_rank"))
        w_rank_pts, l_rank_pts = _to_int(r.get("winner_rank_points")), _to_int(r.get("loser_rank_points"))
        w_svpt, w_1st_won, w_2nd_won = _to_int(r.get("w_svpt")), _to_int(r.get("w_1stWon")), _to_int(r.get("w_2ndWon"))
        l_svpt, l_1st_won, l_2nd_won = _to_int(r.get("l_svpt")), _to_int(r.get("l_1stWon")), _to_int(r.get("l_2ndWon"))
        best_of = _to_int(r.get("best_of"), 0)
        total_games, _ts, games_completed = parse_score(score)

        ws = state.get(w)
        ls = state.get(l)

        match_best_of = best_of if best_of in (3, 5) else 3

        if ws and ls and ws["match_count"] >= MIN_HISTORY and ls["match_count"] >= MIN_HISTORY and date:
            odds = match_odds_for_tml_row(odds_index, w, l, date, used_odds_ids)
            if odds:
                w_stats = analytics.compute_all(ws, surface)
                l_stats = analytics.compute_all(ls, surface)
                w_stats["ranking"] = w_rank
                l_stats["ranking"] = l_rank
                w_stats["rank_points"] = w_rank_pts
                l_stats["rank_points"] = l_rank_pts
                w_stats["h2h_wins"], w_stats["h2h_losses"] = _h2h_record(ws, l)
                l_stats["h2h_wins"], l_stats["h2h_losses"] = _h2h_record(ls, w)
                w_stats["games_avg"] = _games_avg(ws)
                l_stats["games_avg"] = _games_avg(ls)

                p_winner, p_loser = betting.win_probability(w_stats, l_stats, best_of=match_best_of)
                ev_winner = betting.expected_value(p_winner, odds["odds_winner"])
                ev_loser = betting.expected_value(p_loser, odds["odds_loser"])

                bet_side = None
                if ev_winner >= ev_loser and ev_winner >= min_edge:
                    bet_side, bet_odds = "winner", odds["odds_winner"]
                elif ev_loser >= min_edge:
                    bet_side, bet_odds = "loser", odds["odds_loser"]

                if bet_side:
                    won = bet_side == "winner"  # il modello punta sul lato; l'esito reale è noto
                    profit = (bet_odds - 1.0) if won else -1.0
                    bets.append({
                        "year": date.year, "best_of": match_best_of,
                        "profit": profit, "won": won,
                        "ev": ev_winner if bet_side == "winner" else ev_loser,
                        "odds_source": odds["odds_source"],
                    })

        state.setdefault(w, _new_state(w))
        state.setdefault(l, _new_state(l))
        _update_state(state[w], surface, minutes, "W",
                      bp_faced=w_bp_faced, bp_saved=w_bp_saved,
                      bp_opp=l_bp_faced, bp_conv=max(0, l_bp_faced - l_bp_saved),
                      tb_played=w_tb_played, tb_won=w_tb_won,
                      serve_won=w_1st_won + w_2nd_won, serve_total=w_svpt,
                      return_won=max(0, l_svpt - l_1st_won - l_2nd_won), return_total=l_svpt,
                      total_games=total_games, games_completed=games_completed,
                      opponent=l)
        _update_state(state[l], surface, minutes, "L",
                      bp_faced=l_bp_faced, bp_saved=l_bp_saved,
                      bp_opp=w_bp_faced, bp_conv=max(0, w_bp_faced - w_bp_saved),
                      tb_played=l_tb_played, tb_won=l_tb_won,
                      serve_won=l_1st_won + l_2nd_won, serve_total=l_svpt,
                      return_won=max(0, w_svpt - w_1st_won - w_2nd_won), return_total=w_svpt,
                      opponent=w,
                      total_games=total_games, games_completed=games_completed)

    return _summarize(bets)


def _summarize(bets: list[dict]) -> dict:
    def agg(subset):
        n = len(subset)
        if n == 0:
            return {"bets": 0, "hit_rate": None, "roi_pct": None, "profit_units": 0.0}
        wins = sum(1 for b in subset if b["won"])
        profit = sum(b["profit"] for b in subset)
        return {
            "bets": n,
            "hit_rate": round(wins / n * 100, 1),
            "roi_pct": round(profit / n * 100, 1),
            "profit_units": round(profit, 2),
        }

    by_year = {}
    for y in sorted({b["year"] for b in bets}):
        by_year[y] = agg([b for b in bets if b["year"] == y])

    return {
        "overall": agg(bets),
        "bo3": agg([b for b in bets if b["best_of"] == 3]),
        "bo5": agg([b for b in bets if b["best_of"] == 5]),
        "by_year": by_year,
        "n_bets_total": len(bets),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest del modello contro le quote storiche di tennis-data.co.uk.")
    ap.add_argument("--odds-dir", required=True, help="Cartella con i file per-anno di tennis-data.co.uk (xlsx/csv)")
    ap.add_argument("--from-dir", default=None, help="Cartella con i CSV TML/Sackmann (YYYY.csv o atp_matches_YYYY.csv)")
    ap.add_argument("--years", type=int, default=8, help="Anni recenti da includere (default 8)")
    ap.add_argument("--min-edge", type=float, default=betting.DEFAULT_MIN_EDGE, help="Margine EV minimo per piazzare una bet (default 0.05)")
    args = ap.parse_args()

    tml_rows = _read_rows(args.from_dir, args.years)
    if not tml_rows:
        print("Nessun match TML caricato."); return 1
    print(f"Match TML totali: {len(tml_rows)}")

    current_year = datetime.now().year
    years = list(range(current_year - args.years + 1, current_year + 1))
    odds_rows = load_odds_files(args.odds_dir, years)
    if not odds_rows:
        print("Nessuna quota caricata da --odds-dir."); return 1
    print(f"Quote totali caricate: {len(odds_rows)}")
    odds_index = index_odds_by_pair(odds_rows)

    result = run_backtest(tml_rows, odds_index, args.min_edge)

    print(f"\nMatch abbinati e giocati (bet piazzate): {result['n_bets_total']}")
    print("(zero leakage: ogni bet usa solo lo stato pre-match e le quote note a quella data)")
    print("\n── RISULTATO COMPLESSIVO ──")
    o = result["overall"]
    print(f"  bet: {o['bets']} | hit rate: {o['hit_rate']}% | ROI: {o['roi_pct']}% | profitto: {o['profit_units']:+.2f}u")
    print("\n── Per formato ──")
    for label, key in (("best-of-3", "bo3"), ("best-of-5", "bo5")):
        r = result[key]
        print(f"  {label}: bet {r['bets']} | hit rate {r['hit_rate']}% | ROI {r['roi_pct']}% | profitto {r['profit_units']:+.2f}u" if r["bets"] else f"  {label}: nessuna bet")
    print("\n── Per anno ──")
    for y, r in result["by_year"].items():
        print(f"  {y}: bet {r['bets']} | hit rate {r['hit_rate']}% | ROI {r['roi_pct']}% | profitto {r['profit_units']:+.2f}u")

    return 0


if __name__ == "__main__":
    sys.exit(main())
