"""
build_dataset.py — genera dati giocatori REALI per TennisIQ.

Scarica i match ATP di Jeff Sackmann (dataset pubblico, gratuito, storico
completo) e li aggrega in `players_data.json`, che data_provider.py carica
al posto dei mock hardcoded.

Fonte: https://github.com/JeffSackmann/tennis_atp
  atp_matches_YYYY.csv — un match per riga, con superficie, esito, durata e
  statistiche break-point reali (bpSaved / bpFaced).

Uso:
    python build_dataset.py                 # ultimi 4 anni, top 60 per n. match
    python build_dataset.py --years 6 --top 100
    python build_dataset.py --from-dir ./sackmann_csv   # CSV gia' scaricati

Perche' un build step invece di chiamate API a runtime:
  - i dati storici (record per superficie, clutch) non cambiano durante un match;
  - li si calcola una volta e si committa un JSON leggero;
  - l'app resta veloce e funziona anche offline.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

RAW_BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "players_data.json")

# Superfici come le usa l'app (analytics/data_provider).
_SURFACE_CANON = {"Hard": "Hard", "Clay": "Clay", "Grass": "Grass", "Carpet": "Hard"}

# Numero minimo di match totali perche' un giocatore entri nel dataset:
# sotto questa soglia record e clutch sono troppo rumorosi.
MIN_MATCHES = 20
RECENT_LIMIT = 3


def _canon_surface(raw: str) -> str:
    return _SURFACE_CANON.get((raw or "").strip().title(), "Hard")


def _to_int(value, default=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_date(raw: str):
    raw = (raw or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _count_tiebreaks(score: str, player_is_winner: bool) -> tuple[int, int]:
    """
    Conta set al tie-break (7-6 / 6-7) e quanti vinti dal giocatore, dallo score.
    Ritorna (tiebreak_played, tiebreak_won). Parsing best-effort: score come
    "6-4 7-6(5) 6-7(3) 7-5". La cifra tra parentesi (mini-break) viene ignorata.
    """
    played = won = 0
    for raw_set in (score or "").split():
        core = raw_set.split("(")[0]
        if "-" not in core:
            continue
        a, _, b = core.partition("-")
        a_i, b_i = _to_int(a, -1), _to_int(b, -1)
        if a_i < 0 or b_i < 0:
            continue
        hi, lo = max(a_i, b_i), min(a_i, b_i)
        if hi == 7 and lo == 6:  # set deciso al tie-break
            played += 1
            # a = giochi del vincitore del match (colonna 'score' e' winner-first)
            winner_took_set = a_i > b_i
            if winner_took_set == player_is_winner:
                won += 1
    return played, won


def _blank_player(name: str) -> dict:
    return {
        "full_name": name,
        "ranking": 0,
        "match_count": 0,
        "recent_raw": [],  # (date, surface, minutes, result) — ridotto dopo
        "surface_records": defaultdict(lambda: {"wins": 0, "losses": 0}),
        # clutch aggregato (BP + tie-break) su tutto lo storico caricato
        "bp_opportunities": 0, "bp_converted": 0,
        "bp_faced": 0, "bp_saved": 0,
        "tb_played": 0, "tb_won": 0,
    }


def _ingest_match(players: dict, row: dict) -> None:
    w_name = (row.get("winner_name") or "").strip()
    l_name = (row.get("loser_name") or "").strip()
    if not w_name or not l_name:
        return

    surface = _canon_surface(row.get("surface", ""))
    minutes = _to_int(row.get("minutes"), 0) or 95
    date = _parse_date(row.get("tourney_date", ""))
    score = row.get("score", "") or ""

    w_bp_saved, w_bp_faced = _to_int(row.get("w_bpSaved")), _to_int(row.get("w_bpFaced"))
    l_bp_saved, l_bp_faced = _to_int(row.get("l_bpSaved")), _to_int(row.get("l_bpFaced"))

    w_tb_played, w_tb_won = _count_tiebreaks(score, player_is_winner=True)
    l_tb_played, l_tb_won = _count_tiebreaks(score, player_is_winner=False)

    for name, is_winner in ((w_name, True), (l_name, False)):
        p = players.setdefault(name, _blank_player(name))
        p["match_count"] += 1
        rec = p["surface_records"][surface]
        rec["wins" if is_winner else "losses"] += 1
        p["recent_raw"].append((date, surface, minutes, "W" if is_winner else "L"))

        if is_winner:
            # BP subiti/salvati dal vincitore = w_bp*; BP che il vincitore ha
            # avuto in battuta (opportunita' di break) = quelli affrontati
            # dall'avversario = l_bpFaced; convertiti = l_bpFaced - l_bpSaved.
            p["bp_faced"] += w_bp_faced
            p["bp_saved"] += w_bp_saved
            p["bp_opportunities"] += l_bp_faced
            p["bp_converted"] += max(0, l_bp_faced - l_bp_saved)
            p["tb_played"] += w_tb_played
            p["tb_won"] += w_tb_won
        else:
            p["bp_faced"] += l_bp_faced
            p["bp_saved"] += l_bp_saved
            p["bp_opportunities"] += w_bp_faced
            p["bp_converted"] += max(0, w_bp_faced - w_bp_saved)
            p["tb_played"] += l_tb_played
            p["tb_won"] += l_tb_won


def _finalize(players: dict, top: int) -> dict:
    ranked = sorted(players.values(), key=lambda p: p["match_count"], reverse=True)
    out: dict[str, dict] = {}
    for p in ranked:
        if p["match_count"] < MIN_MATCHES:
            continue
        # ultimi RECENT_LIMIT match per data (None in coda)
        recent = sorted(
            p["recent_raw"],
            key=lambda t: (t[0] is not None, t[0] or datetime.min),
            reverse=True,
        )[:RECENT_LIMIT]
        recent_matches = [
            {"opponent": "", "duration_min": mins, "result": res, "surface": surf}
            for (_d, surf, mins, res) in recent
        ]
        short_key = p["full_name"].split()[-1]  # cognome come chiave breve
        out[short_key] = {
            "full_name": p["full_name"],
            "ranking": 0,
            "recent_matches": recent_matches,
            "surface_records": {k: dict(v) for k, v in p["surface_records"].items()},
            "break_points": {
                "opportunities": p["bp_opportunities"],
                "converted": p["bp_converted"],
            },
            "break_points_saved": {"faced": p["bp_faced"], "saved": p["bp_saved"]},
            "tiebreaks": {"played": p["tb_played"], "won": p["tb_won"]},
            "_data_source": "sackmann",
        }
        if len(out) >= top:
            break
    return out


def _load_csv_text(text: str, players: dict) -> int:
    reader = csv.DictReader(io.StringIO(text))
    n = 0
    for row in reader:
        _ingest_match(players, row)
        n += 1
    return n


def build(years: int, top: int, from_dir: str | None) -> dict:
    players: dict = {}
    current_year = datetime.utcnow().year
    year_list = list(range(current_year - years + 1, current_year + 1))

    if from_dir:
        for y in year_list:
            path = os.path.join(from_dir, f"atp_matches_{y}.csv")
            if not os.path.exists(path):
                print(f"[skip] {path} non trovato")
                continue
            with open(path, encoding="utf-8") as fh:
                n = _load_csv_text(fh.read(), players)
            print(f"[ok] {os.path.basename(path)}: {n} match")
    else:
        import requests  # import ritardato: serve solo in modalita' download
        for y in year_list:
            url = f"{RAW_BASE}/atp_matches_{y}.csv"
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
            except Exception as exc:
                print(f"[skip] {url}: {exc}")
                continue
            n = _load_csv_text(resp.text, players)
            print(f"[ok] atp_matches_{y}.csv: {n} match")

    if not players:
        print("Nessun dato caricato. Con --from-dir controlla i CSV; "
              "in download verifica la connessione.")
        return {}

    result = _finalize(players, top)
    print(f"Giocatori con >= {MIN_MATCHES} match: {len(result)} (top {top}).")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera players_data.json da dati ATP reali (Sackmann).")
    ap.add_argument("--years", type=int, default=4, help="Anni recenti da includere (default 4)")
    ap.add_argument("--top", type=int, default=60, help="Numero massimo di giocatori (default 60)")
    ap.add_argument("--from-dir", default=None, help="Cartella con atp_matches_YYYY.csv gia' scaricati")
    ap.add_argument("--out", default=OUTPUT, help="Percorso file JSON di output")
    args = ap.parse_args()

    data = build(args.years, args.top, args.from_dir)
    if not data:
        return 1
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    print(f"Scritto {args.out} ({len(data)} giocatori).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
