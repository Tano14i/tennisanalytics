"""
betting.py — dalla analisi al VALORE.

Converte le metriche di analytics.py in una probabilità di vittoria, la
confronta con le quote del bookmaker e calcola il valore atteso (EV).
È lo strato che distingue "chi è più forte" (narrativa) da "questa quota
paga più di quanto vale" (scommessa di valore).

Onestà intellettuale: il modello di probabilità NON è addestrato su dati
storici — è una combinazione logistica trasparente dei differenziali di
metrica con pesi-prior documentati. Va usato come stima ragionata, non come
verità. I pesi sono costanti a livello di modulo, quindi tarabili.
"""
from __future__ import annotations

import json
import math
import os

# Pesi-prior (non fittati) applicati ai differenziali player1 - player2.
# Usati SOLO come fallback se betting_weights.json non è presente.
# Scala pensata così: da soli, un vantaggio di ~20 punti su una metrica
# sposta la probabilità verso ~0.60-0.65, mai a certezza.
_PRIOR_W_SURFACE = 0.030
_PRIOR_W_MOMENTUM = 0.015
_PRIOR_W_CLUTCH = 0.022

# Pesi attivi: prior finché fit_weights.py non genera betting_weights.json.
_W_SURFACE = _PRIOR_W_SURFACE
_W_MOMENTUM = _PRIOR_W_MOMENTUM
_W_CLUTCH = _PRIOR_W_CLUTCH
WEIGHTS_SOURCE = "prior"  # "fitted" quando caricati da betting_weights.json

_WEIGHTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "betting_weights.json")


def _load_fitted_weights() -> None:
    """Carica i pesi fittati da betting_weights.json (walk-forward, senza
    leakage) se il file esiste. Altrimenti restano i prior."""
    global _W_SURFACE, _W_MOMENTUM, _W_CLUTCH, WEIGHTS_SOURCE
    if not os.path.exists(_WEIGHTS_PATH):
        return
    try:
        with open(_WEIGHTS_PATH, encoding="utf-8") as fh:
            w = json.load(fh)
        _W_SURFACE = float(w["w_surface"])
        _W_MOMENTUM = float(w["w_momentum"])
        _W_CLUTCH = float(w["w_clutch"])
        WEIGHTS_SOURCE = "fitted"
    except Exception:
        pass  # file corrotto → resta sui prior


_load_fitted_weights()

# La probabilità del modello è troncata per non dare mai certezza estrema.
_PROB_FLOOR = 0.05
_PROB_CEIL = 0.95

# Margine minimo di EV perché un pick sia segnalato come "valore".
DEFAULT_MIN_EDGE = 0.05


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def win_probability(p1_stats: dict, p2_stats: dict) -> tuple[float, float]:
    """
    Stima P(player1 vince) e P(player2 vince) dai differenziali di metrica.
    Ritorna (p1_prob, p2_prob) con p1_prob + p2_prob == 1.
    """
    surf_diff = p1_stats.get("surface_win_rate", 0.0) - p2_stats.get("surface_win_rate", 0.0)
    mom_diff = p1_stats.get("momentum_score", 0.0) - p2_stats.get("momentum_score", 0.0)
    clutch_diff = p1_stats.get("clutch_factor", 0.0) - p2_stats.get("clutch_factor", 0.0)

    logit = _W_SURFACE * surf_diff + _W_MOMENTUM * mom_diff + _W_CLUTCH * clutch_diff
    p1 = min(_PROB_CEIL, max(_PROB_FLOOR, _sigmoid(logit)))
    return round(p1, 4), round(1.0 - p1, 4)


def implied_probabilities(odds1: float, odds2: float) -> tuple[float, float]:
    """
    Probabilità implicite dalle quote decimali, con il margine del bookmaker
    (overround) rimosso, così sono confrontabili con quelle del modello.
    Ritorna (imp1, imp2) normalizzate a somma 1, oppure (0, 0) se le quote
    non sono valide.
    """
    if not odds1 or not odds2 or odds1 <= 1.0 or odds2 <= 1.0:
        return 0.0, 0.0
    raw1, raw2 = 1.0 / odds1, 1.0 / odds2
    total = raw1 + raw2
    if total <= 0:
        return 0.0, 0.0
    return round(raw1 / total, 4), round(raw2 / total, 4)


def expected_value(model_prob: float, odds: float) -> float:
    """EV per 1 unità puntata: prob * (quota - 1) - (1 - prob) = prob*quota - 1."""
    if not odds or odds <= 1.0:
        return 0.0
    return round(model_prob * odds - 1.0, 4)


def evaluate_value(
    p1_name: str, p1_stats: dict,
    p2_name: str, p2_stats: dict,
    odds1: float | None = None, odds2: float | None = None,
    min_edge: float = DEFAULT_MIN_EDGE,
) -> dict:
    """
    Valutazione completa di valore per il match.

    Ritorna un dict con la probabilità del modello per entrambi, e — se le
    quote sono fornite — EV per lato, probabilità implicite (senza margine),
    e il pick di valore consigliato (o None se nessun lato supera min_edge).
    """
    p1_prob, p2_prob = win_probability(p1_stats, p2_stats)
    result = {
        "p1_name": p1_name, "p2_name": p2_name,
        "p1_prob": p1_prob, "p2_prob": p2_prob,
        "has_odds": False,
        "odds1": odds1, "odds2": odds2,
        "imp1": None, "imp2": None,
        "ev1": None, "ev2": None,
        "value_pick": None, "value_edge": None, "value_odds": None,
    }
    if not odds1 or not odds2:
        return result

    imp1, imp2 = implied_probabilities(odds1, odds2)
    ev1 = expected_value(p1_prob, odds1)
    ev2 = expected_value(p2_prob, odds2)
    result.update(has_odds=True, imp1=imp1, imp2=imp2, ev1=ev1, ev2=ev2)

    # Pick di valore = lato con EV più alto, purché superi il margine minimo.
    best_name, best_ev, best_odds = (p1_name, ev1, odds1) if ev1 >= ev2 else (p2_name, ev2, odds2)
    if best_ev >= min_edge:
        result.update(value_pick=best_name, value_edge=best_ev, value_odds=best_odds)
    return result


def format_value_block(ev: dict) -> str:
    """Riga(he) testuali sul valore, da appendere al post generato."""
    lines = []
    p1, p2 = ev["p1_name"], ev["p2_name"]
    tag = "fitted" if WEIGHTS_SOURCE == "fitted" else "heuristic prior"
    lines.append(f"    Model win prob : {p1} {ev['p1_prob']*100:.0f}%  •  {p2} {ev['p2_prob']*100:.0f}%  ({tag})")
    if not ev["has_odds"]:
        lines.append("    Odds           : — (inserisci le quote per valutare l'EV)")
        return "\n".join(lines)

    lines.append(
        f"    Odds (implied) : {p1} {ev['odds1']} ({ev['imp1']*100:.0f}%)  •  "
        f"{p2} {ev['odds2']} ({ev['imp2']*100:.0f}%)"
    )
    lines.append(f"    Expected value : {p1} {ev['ev1']*100:+.1f}%  •  {p2} {ev['ev2']*100:+.1f}%")
    if ev["value_pick"]:
        lines.append(
            f"    ✅ VALUE PICK  : {ev['value_pick']} @ {ev['value_odds']} "
            f"(edge {ev['value_edge']*100:+.1f}%)"
        )
    else:
        lines.append("    ⛔ No value    : nessun lato supera il margine minimo — passa.")
    return "\n".join(lines)
