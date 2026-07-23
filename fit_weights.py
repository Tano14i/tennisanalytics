"""
fit_weights.py — calibra i pesi di betting.py sui match ATP reali (Sackmann).

Trasforma il modello di probabilità da euristico a fittato, SENZA data leakage:
per ogni match le feature (record superficie, forma, clutch) sono calcolate
dallo stato del giocatore PRIMA di quel match; il match viene usato per
aggiornare lo stato solo dopo aver preso lo snapshot. Ordine cronologico
rigoroso → nessuna informazione futura entra nelle feature.

Le feature sono prodotte da analytics.compute_all sugli stessi dict che usa il
runtime, quindi i pesi fittati si applicano alla stessa scala del modello live.

Uso:
    python fit_weights.py --from-dir ./sackmann_csv --years 8
    python fit_weights.py --years 8          # scarica i CSV da GitHub

Output: betting_weights.json (caricato in automatico da betting.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import analytics
from betting import rank_feature
from build_dataset import (
    _canon_surface,
    _count_tiebreaks,
    _parse_date,
    _to_int,
    fetch_year_csv,
    local_csv_path,
    parse_score,
)

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "betting_weights.json")
GAMES_OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "games_weights.json")
# Media games/match usata come centro della feature "avg_games_prior" nella
# regressione — deve combaciare con betting._GAMES_PRIOR_MEAN.
GAMES_PRIOR_MEAN = 22.0

# Storia minima (match giocati) perché un giocatore contribuisca a un campione:
# sotto, le metriche pre-match sono troppo instabili.
MIN_HISTORY = 10
RECENT_KEEP = 3


def _new_state(name: str) -> dict:
    return {
        "full_name": name,
        "match_count": 0,
        "recent_matches": [],  # most-recent-first, max RECENT_KEEP
        "surface_records": {},
        "break_points": {"opportunities": 0, "converted": 0},
        "break_points_saved": {"faced": 0, "saved": 0},
        "tiebreaks": {"played": 0, "won": 0},
        "games_sum": 0, "games_matches": 0,
    }


def _games_avg(st: dict) -> float:
    return (st["games_sum"] / st["games_matches"]) if st["games_matches"] else 0.0


def _update_state(st: dict, surface: str, minutes: int, result: str,
                  bp_faced: int, bp_saved: int, bp_opp: int, bp_conv: int,
                  tb_played: int, tb_won: int,
                  total_games: int = 0, games_completed: bool = False) -> None:
    st["match_count"] += 1
    rec = st["surface_records"].setdefault(surface, {"wins": 0, "losses": 0})
    rec["wins" if result == "W" else "losses"] += 1
    st["recent_matches"].insert(0, {"duration_min": minutes, "result": result, "surface": surface})
    del st["recent_matches"][RECENT_KEEP:]
    st["break_points"]["opportunities"] += bp_opp
    st["break_points"]["converted"] += bp_conv
    st["break_points_saved"]["faced"] += bp_faced
    st["break_points_saved"]["saved"] += bp_saved
    st["tiebreaks"]["played"] += tb_played
    st["tiebreaks"]["won"] += tb_won
    if games_completed:
        st["games_sum"] += total_games
        st["games_matches"] += 1


def _orientation(date_key: str, w: str, l: str) -> int:
    """0 = winner è player1, 1 = loser è player1. Deterministico e bilanciato."""
    h = hashlib.md5(f"{date_key}|{w}|{l}".encode()).hexdigest()
    return int(h, 16) & 1


def _read_rows(from_dir: str | None, years: int):
    import csv
    import io
    current = datetime.now(timezone.utc).year
    year_list = list(range(current - years + 1, current + 1))
    rows = []
    if from_dir:
        for y in year_list:
            path = local_csv_path(from_dir, y)
            if not path:
                print(f"[skip] nessun CSV per {y} in {from_dir}")
                continue
            with open(path, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    rows.append(r)
            print(f"[ok] {os.path.basename(path)}")
    else:
        for y in year_list:
            text = fetch_year_csv(y)
            if text is None:
                continue
            for r in csv.DictReader(io.StringIO(text)):
                rows.append(r)
            print(f"[ok] {y}")
    return rows


def build_samples(rows: list[dict]):
    """
    Ritorna (X, y, dates, Xg, yg, dates_g) walk-forward, senza leakage.

    X/y/dates      → moneyline (chi vince), come prima.
    Xg/yg/dates_g  → regressione games totali: feature [avg_games_prior - 22,
                     |rank_gap|, |surface_gap|, best_of_flag] (pre-match),
                     target = games totali REALI del match (solo se lo score
                     è completo, niente ritiri/walkover che falserebbero il
                     totale). best_of_flag = 1 per Slam maschili (bo5), 0 per
                     circuito regolare (bo3) — un match bo5 è strutturalmente
                     molto più lungo, mischiare i due formati senza questa
                     feature gonfia intercetta e deviazione standard.
    """
    # ordina per (data, match_num) crescente
    def sort_key(r):
        d = _parse_date(r.get("tourney_date", ""))
        return (d or datetime.min, _to_int(r.get("match_num"), 0))

    rows = sorted(rows, key=sort_key)
    state: dict[str, dict] = {}
    X, y, dates = [], [], []
    Xg, yg, dates_g = [], [], []

    for r in rows:
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
        # ranking al momento del match (colonne winner_rank/loser_rank): è
        # informazione pre-partita, quindi nessun leakage.
        w_rank, l_rank = _to_int(r.get("winner_rank")), _to_int(r.get("loser_rank"))
        total_games, _total_sets, games_completed = parse_score(score)
        # best_of: solo 3 o 5 sono formati validi in ATP; qualunque altro
        # valore (dato mancante/sporco) esclude il match dal training games,
        # non da quello moneyline (che non dipende dal formato).
        best_of = _to_int(r.get("best_of"), 0)

        ws = state.get(w)
        ls = state.get(l)

        # SNAPSHOT pre-match (solo se entrambi hanno storia sufficiente)
        if ws and ls and ws["match_count"] >= MIN_HISTORY and ls["match_count"] >= MIN_HISTORY:
            w_stats = analytics.compute_all(ws, surface)
            l_stats = analytics.compute_all(ls, surface)
            if _orientation(r.get("tourney_date", ""), w, l) == 0:
                p1, p2, r1, r2, target = w_stats, l_stats, w_rank, l_rank, 1
            else:
                p1, p2, r1, r2, target = l_stats, w_stats, l_rank, w_rank, 0
            X.append([
                p1["surface_win_rate"] - p2["surface_win_rate"],
                p1["momentum_score"] - p2["momentum_score"],
                p1["clutch_factor"] - p2["clutch_factor"],
                rank_feature(r1, r2),
            ])
            y.append(target)
            dates.append(date or datetime.min)

            # Campione games: richiede anche games_avg noto per entrambi
            # (games_matches>0), altrimenti la feature "avg_games_prior"
            # sarebbe 0 e sballerebbe la regressione.
            g_w, g_l = _games_avg(ws), _games_avg(ls)
            if games_completed and g_w and g_l and best_of in (3, 5):
                avg_games_prior = (g_w + g_l) / 2
                rank_gap = abs(rank_feature(r1, r2))
                surf_gap = abs(p1["surface_win_rate"] - p2["surface_win_rate"])
                bo_flag = 1.0 if best_of >= 5 else 0.0
                Xg.append([avg_games_prior - GAMES_PRIOR_MEAN, rank_gap, surf_gap, bo_flag])
                yg.append(total_games)
                dates_g.append(date or datetime.min)

        # UPDATE dopo lo snapshot: il match del vincitore e del perdente
        state.setdefault(w, _new_state(w))
        state.setdefault(l, _new_state(l))
        _update_state(state[w], surface, minutes, "W",
                      bp_faced=w_bp_faced, bp_saved=w_bp_saved,
                      bp_opp=l_bp_faced, bp_conv=max(0, l_bp_faced - l_bp_saved),
                      tb_played=w_tb_played, tb_won=w_tb_won,
                      total_games=total_games, games_completed=games_completed)
        _update_state(state[l], surface, minutes, "L",
                      bp_faced=l_bp_faced, bp_saved=l_bp_saved,
                      bp_opp=w_bp_faced, bp_conv=max(0, w_bp_faced - w_bp_saved),
                      tb_played=l_tb_played, tb_won=l_tb_won,
                      total_games=total_games, games_completed=games_completed)

    return X, y, dates, Xg, yg, dates_g


def _metrics(model, X, y) -> dict:
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
    if not X:
        return {}
    probs = model.predict_proba(X)[:, 1]
    preds = (probs >= 0.5).astype(int)
    return {
        "n": len(y),
        "accuracy": round(float(accuracy_score(y, preds)), 4),
        "log_loss": round(float(log_loss(y, probs, labels=[0, 1])), 4),
        "brier": round(float(brier_score_loss(y, probs)), 4),
    }


def fit(X, y, dates) -> dict:
    from sklearn.linear_model import LogisticRegression

    # Validazione temporale: ultimo 20% dei campioni (già in ordine cronologico)
    # come holdout. Split per indice → niente informazione futura nel train, e
    # un val abbastanza grande da essere affidabile (a differenza del solo
    # ultimo anno solare, che su un anno appena iniziato è minuscolo).
    n = len(X)
    split = int(n * 0.8)
    train_idx = list(range(split))
    val_idx = list(range(split, n))

    # baseline: sempre 0.5 → log_loss = ln 2 ≈ 0.6931; il modello deve batterlo.
    def subset(idx):
        return [X[i] for i in idx], [y[i] for i in idx]

    # fit_intercept=False → simmetria garantita: scambiando i giocatori
    # (feature negate) la probabilità diventa 1-p, come richiede betting.py.
    val_metrics = {}
    if train_idx and val_idx and len(set(y[i] for i in train_idx)) > 1:
        Xtr, ytr = subset(train_idx)
        Xva, yva = subset(val_idx)
        vm = LogisticRegression(fit_intercept=False, C=1.0, max_iter=1000)
        vm.fit(Xtr, ytr)
        val_metrics = _metrics(vm, Xva, yva)

    model = LogisticRegression(fit_intercept=False, C=1.0, max_iter=1000)
    model.fit(X, y)
    coef = model.coef_[0]
    train_metrics = _metrics(model, X, y)

    return {
        "w_surface": round(float(coef[0]), 6),
        "w_momentum": round(float(coef[1]), 6),
        "w_clutch": round(float(coef[2]), 6),
        "w_rank": round(float(coef[3]), 6),
        "n_samples": len(X),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "train_metrics": train_metrics,
        "val_metrics": val_metrics,
        "note": "Walk-forward, no leakage. Baseline log_loss (p=0.5)=0.6931.",
    }


def fit_games(Xg, yg, dates_g) -> dict | None:
    """
    Regressione lineare: games_totali ~ intercetta + coef · feature.
    Std dei residui calcolata sull'holdout (per la Normale usata nell'O/U),
    non sul train, altrimenti sottostimerebbe l'incertezza reale.
    """
    if len(Xg) < 200:
        return None
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_absolute_error

    n = len(Xg)
    split = int(n * 0.8)
    Xtr, ytr = Xg[:split], yg[:split]
    Xva, yva = Xg[split:], yg[split:]

    model = LinearRegression()
    model.fit(Xtr, ytr)
    val_pred = model.predict(Xva)
    residuals = [a - p for a, p in zip(yva, val_pred)]
    residual_std = (sum(r * r for r in residuals) / len(residuals)) ** 0.5 if residuals else 4.5
    val_mae = float(mean_absolute_error(yva, val_pred)) if Xva else None

    # rifitta su tutti i dati per il modello finale (intercept/coef usati a runtime)
    final_model = LinearRegression()
    final_model.fit(Xg, yg)

    # NB: la feature 0 (avg_games_prior) è già centrata su GAMES_PRIOR_MEAN in
    # build_samples, e il target (yg) è il numero di games grezzo — quindi
    # l'intercetta di LinearRegression È GIÀ il valore fisico corretto
    # ("games attesi con avg_games_prior=22, rank_gap=0, surf_gap=0"),
    # nessuna somma aggiuntiva va applicata qui.
    return {
        "intercept": round(float(final_model.intercept_), 4),
        "coef": [round(float(c), 5) for c in final_model.coef_],
        "feature_names": ["avg_games_prior_centered", "abs_rank_gap", "abs_surface_gap", "best_of_flag"],
        "residual_std": round(residual_std, 3),
        "n_samples": n,
        "val_mae_games": round(val_mae, 3) if val_mae is not None else None,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "note": "Target: total games reali (score completi). Holdout 20% finale per residual_std e MAE.",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Fitta i pesi di betting.py sui match ATP reali (Sackmann/TML).")
    ap.add_argument("--years", type=int, default=8, help="Anni recenti da includere (default 8)")
    ap.add_argument("--from-dir", default=None, help="Cartella con atp_matches_YYYY.csv o YYYY.csv")
    ap.add_argument("--out", default=OUTPUT, help="Percorso betting_weights.json")
    ap.add_argument("--games-out", default=GAMES_OUTPUT, help="Percorso games_weights.json")
    args = ap.parse_args()

    rows = _read_rows(args.from_dir, args.years)
    if not rows:
        print("Nessun match caricato."); return 1
    print(f"Match totali letti: {len(rows)}")

    X, y, dates, Xg, yg, dates_g = build_samples(rows)
    if len(X) < 200:
        print(f"Troppi pochi campioni walk-forward: {len(X)}. Aumenta --years."); return 1
    print(f"Campioni walk-forward (moneyline): {len(X)} | target medio: {sum(y)/len(y):.3f} (atteso ~0.5)")
    print(f"Campioni walk-forward (games)    : {len(Xg)}")

    result = fit(X, y, dates)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    print("\n── Pesi fittati (moneyline) ──")
    print(f"  w_surface  = {result['w_surface']}")
    print(f"  w_momentum = {result['w_momentum']}")
    print(f"  w_clutch   = {result['w_clutch']}")
    print(f"  w_rank     = {result['w_rank']}")
    print(f"  train: {result['train_metrics']}")
    print(f"  val  : {result['val_metrics']}")
    print(f"Scritto {args.out}.")

    games_result = fit_games(Xg, yg, dates_g)
    if games_result is None:
        print(f"\nTroppi pochi campioni games ({len(Xg)}): games_weights.json NON generato, resta il prior.")
    else:
        with open(args.games_out, "w", encoding="utf-8") as fh:
            json.dump(games_result, fh, ensure_ascii=False, indent=2)
        print("\n── Pesi fittati (games O/U) ──")
        print(f"  intercept (games medi base) = {games_result['intercept']}")
        print(f"  coef {games_result['feature_names']} = {games_result['coef']}")
        print(f"  residual_std (σ)  = {games_result['residual_std']}")
        print(f"  val MAE (games)   = {games_result['val_mae_games']}")
        print(f"Scritto {args.games_out}.")

    print("\nbetting.py caricherà entrambi in automatico.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
