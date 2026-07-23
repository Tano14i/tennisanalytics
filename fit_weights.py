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
from build_dataset import (
    _canon_surface,
    _count_tiebreaks,
    _parse_date,
    _to_int,
    fetch_year_csv,
    local_csv_path,
)

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "betting_weights.json")

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
    }


def _update_state(st: dict, surface: str, minutes: int, result: str,
                  bp_faced: int, bp_saved: int, bp_opp: int, bp_conv: int,
                  tb_played: int, tb_won: int) -> None:
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
    """Ritorna (X, y, dates) walk-forward, senza leakage."""
    # ordina per (data, match_num) crescente
    def sort_key(r):
        d = _parse_date(r.get("tourney_date", ""))
        return (d or datetime.min, _to_int(r.get("match_num"), 0))

    rows = sorted(rows, key=sort_key)
    state: dict[str, dict] = {}
    X, y, dates = [], [], []

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

        ws = state.get(w)
        ls = state.get(l)

        # SNAPSHOT pre-match (solo se entrambi hanno storia sufficiente)
        if ws and ls and ws["match_count"] >= MIN_HISTORY and ls["match_count"] >= MIN_HISTORY:
            w_stats = analytics.compute_all(ws, surface)
            l_stats = analytics.compute_all(ls, surface)
            if _orientation(r.get("tourney_date", ""), w, l) == 0:
                p1, p2, target = w_stats, l_stats, 1
            else:
                p1, p2, target = l_stats, w_stats, 0
            X.append([
                p1["surface_win_rate"] - p2["surface_win_rate"],
                p1["momentum_score"] - p2["momentum_score"],
                p1["clutch_factor"] - p2["clutch_factor"],
            ])
            y.append(target)
            dates.append(date or datetime.min)

        # UPDATE dopo lo snapshot: il match del vincitore e del perdente
        state.setdefault(w, _new_state(w))
        state.setdefault(l, _new_state(l))
        _update_state(state[w], surface, minutes, "W",
                      bp_faced=w_bp_faced, bp_saved=w_bp_saved,
                      bp_opp=l_bp_faced, bp_conv=max(0, l_bp_faced - l_bp_saved),
                      tb_played=w_tb_played, tb_won=w_tb_won)
        _update_state(state[l], surface, minutes, "L",
                      bp_faced=l_bp_faced, bp_saved=l_bp_saved,
                      bp_opp=w_bp_faced, bp_conv=max(0, w_bp_faced - w_bp_saved),
                      tb_played=l_tb_played, tb_won=l_tb_won)

    return X, y, dates


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
        "n_samples": len(X),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "train_metrics": train_metrics,
        "val_metrics": val_metrics,
        "note": "Walk-forward, no leakage. Baseline log_loss (p=0.5)=0.6931.",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Fitta i pesi di betting.py sui match ATP reali (Sackmann).")
    ap.add_argument("--years", type=int, default=8, help="Anni recenti da includere (default 8)")
    ap.add_argument("--from-dir", default=None, help="Cartella con atp_matches_YYYY.csv")
    ap.add_argument("--out", default=OUTPUT, help="Percorso betting_weights.json")
    args = ap.parse_args()

    rows = _read_rows(args.from_dir, args.years)
    if not rows:
        print("Nessun match caricato."); return 1
    print(f"Match totali letti: {len(rows)}")

    X, y, dates = build_samples(rows)
    if len(X) < 200:
        print(f"Troppi pochi campioni walk-forward: {len(X)}. Aumenta --years."); return 1
    print(f"Campioni walk-forward: {len(X)} | target medio: {sum(y)/len(y):.3f} (atteso ~0.5)")

    result = fit(X, y, dates)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    print("\n── Pesi fittati ──")
    print(f"  w_surface  = {result['w_surface']}")
    print(f"  w_momentum = {result['w_momentum']}")
    print(f"  w_clutch   = {result['w_clutch']}")
    print(f"  train: {result['train_metrics']}")
    print(f"  val  : {result['val_metrics']}")
    print(f"\nScritto {args.out}. betting.py li caricherà in automatico.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
