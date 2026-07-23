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
_PRIOR_W_RANK = 0.300   # feature log-rank (~-4..+4): il predittore piu' forte

# Pesi attivi: prior finché fit_weights.py non genera betting_weights.json.
_W_SURFACE = _PRIOR_W_SURFACE
_W_MOMENTUM = _PRIOR_W_MOMENTUM
_W_CLUTCH = _PRIOR_W_CLUTCH
_W_RANK = _PRIOR_W_RANK
WEIGHTS_SOURCE = "prior"  # "fitted" quando caricati da betting_weights.json

_WEIGHTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "betting_weights.json")


def _load_fitted_weights() -> None:
    """Carica i pesi fittati da betting_weights.json (walk-forward, senza
    leakage) se il file esiste. Altrimenti restano i prior."""
    global _W_SURFACE, _W_MOMENTUM, _W_CLUTCH, _W_RANK, WEIGHTS_SOURCE
    if not os.path.exists(_WEIGHTS_PATH):
        return
    try:
        with open(_WEIGHTS_PATH, encoding="utf-8") as fh:
            w = json.load(fh)
        _W_SURFACE = float(w["w_surface"])
        _W_MOMENTUM = float(w["w_momentum"])
        _W_CLUTCH = float(w["w_clutch"])
        # w_rank opzionale: pesi fittati vecchi (senza ranking) restano validi.
        _W_RANK = float(w.get("w_rank", 0.0))
        WEIGHTS_SOURCE = "fitted"
    except Exception:
        pass  # file corrotto → resta sui prior


_load_fitted_weights()


def rank_feature(rank1, rank2) -> float:
    """Feature di ranking = log(rank2) - log(rank1): positiva quando player1 è
    meglio classificato (numero di ranking più basso). Scala logaritmica perché
    la differenza 1→5 pesa molto più di 100→104. Ritorna 0 se un ranking manca
    o è 0 (giocatore non classificato) → nessun contributo, mai un falso segnale."""
    try:
        r1 = int(rank1 or 0)
        r2 = int(rank2 or 0)
    except (TypeError, ValueError):
        return 0.0
    if r1 <= 0 or r2 <= 0:
        return 0.0
    return math.log(r2) - math.log(r1)

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
    rank_diff = rank_feature(p1_stats.get("ranking", 0), p2_stats.get("ranking", 0))

    logit = (
        _W_SURFACE * surf_diff
        + _W_MOMENTUM * mom_diff
        + _W_CLUTCH * clutch_diff
        + _W_RANK * rank_diff
    )
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


# ═══════════════════════════════════════════════════════════════════════════
# MERCATO SET — formula chiusa, nessun peso da fittare. Generalizzata a
# best-of-3 (circuito regolare) e best-of-5 (Slam maschili: Australian Open,
# Roland Garros, Wimbledon, US Open).
#
# Assunzione: ogni set è un evento indipendente Bernoulli con probabilità
# fissa q che player1 vince il set (modello "Bradley-Terry per set", standard
# in letteratura tennis). Per un match al meglio di (2k-1) set, servono k set
# vinti; la probabilità di vincere il match in ESATTAMENTE k+j set è:
#   P(k+j set) = C(k+j-1, j) · q^k · (1-q)^j        [j = 0 .. k-1]
# Sommando su j si ottiene P(match) = Σ C(k+j-1,j)·q^k·(1-q)^j, monotona
# crescente in q → invertibile per bisezione dalla probabilità di vittoria
# del match. Bo3 (k=2) si riduce a q²(3-2q), la formula originale.
# Verificato con simulazione Monte Carlo (100k trial) per bo3 e bo5 su più q.
# ═══════════════════════════════════════════════════════════════════════════

from math import comb as _comb


def _sets_needed_to_win(best_of: int) -> int:
    return (best_of + 1) // 2  # bo3 -> 2, bo5 -> 3


def _match_win_prob_from_set_prob(q: float, best_of: int = 3) -> float:
    k = _sets_needed_to_win(best_of)
    return sum(_comb(k + j - 1, j) * (q ** k) * ((1 - q) ** j) for j in range(k))


def implied_set_win_prob(match_win_prob: float, best_of: int = 3, tol: float = 1e-6) -> float:
    """Inverte P(match)=Σ... per bisezione. match_win_prob in [0,1] → q in [0,1]."""
    p = min(1.0, max(0.0, match_win_prob))
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _match_win_prob_from_set_prob(mid, best_of) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


def sets_distribution(p1_match_prob: float, best_of: int = 3) -> dict:
    """
    Distribuzione del numero di set dati P(player1 vince il match), per un
    match al meglio di `best_of` set (3 o 5) e set indipendenti con
    probabilità costante q (vedi sopra).

    Ritorna: best_of, q (prob. per-set di player1), per_length (dict lunghezza
    match -> probabilità), prob_straight_sets (match nel minimo di set
    possibile, es. 2-0 o 3-0), prob_extra_sets (match più lungo del minimo).
    """
    q = implied_set_win_prob(p1_match_prob, best_of)
    k = _sets_needed_to_win(best_of)
    per_length = {}
    for j in range(k):
        n_sets = k + j
        c = _comb(k + j - 1, j)
        per_length[n_sets] = round(c * (q ** k) * ((1 - q) ** j) + c * ((1 - q) ** k) * (q ** j), 6)
    prob_straight = per_length[k]
    prob_extra = round(1.0 - prob_straight, 6)
    return {
        "best_of": best_of,
        "implied_set_prob": round(q, 4),
        "per_length": per_length,
        "prob_straight_sets": round(prob_straight, 4),
        "prob_extra_sets": prob_extra,
    }


def evaluate_sets_value(
    p1_prob: float,
    best_of: int = 3,
    odds_straight: float | None = None,
    odds_extra: float | None = None,
    min_edge: float = DEFAULT_MIN_EDGE,
) -> dict:
    """
    Valore su "match nel minimo di set" (straight sets: 2-0 bo3 / 3-0 bo5)
    vs "match oltre il minimo" (3 set bo3 / 4-5 set bo5), con le quote di
    quel mercato (spesso chiamato "Straight Sets" dai bookmaker).
    """
    dist = sets_distribution(p1_prob, best_of)
    result = {
        **dist,
        "has_odds": False,
        "odds_straight": odds_straight, "odds_extra": odds_extra,
        "ev_straight": None, "ev_extra": None,
        "value_pick": None, "value_edge": None, "value_odds": None,
    }
    if not odds_straight or not odds_extra:
        return result

    ev_straight = expected_value(dist["prob_straight_sets"], odds_straight)
    ev_extra = expected_value(dist["prob_extra_sets"], odds_extra)
    result.update(has_odds=True, ev_straight=ev_straight, ev_extra=ev_extra)

    straight_label = f"{best_of - (_sets_needed_to_win(best_of) - 1)}-0 (straight sets)"
    extra_label = "match oltre il minimo di set"
    if ev_straight >= ev_extra and ev_straight >= min_edge:
        result.update(value_pick=straight_label, value_edge=ev_straight, value_odds=odds_straight)
    elif ev_extra >= min_edge:
        result.update(value_pick=extra_label, value_edge=ev_extra, value_odds=odds_extra)
    return result


def format_sets_block(sets_ev: dict) -> str:
    bo = sets_ev["best_of"]
    lengths_str = "  •  ".join(f"{n} set {p*100:.0f}%" for n, p in sorted(sets_ev["per_length"].items()))
    lines = [
        f"    Model (best-of-{bo}): {lengths_str}  "
        f"(da match win prob, per-set q={sets_ev['implied_set_prob']*100:.0f}%)"
    ]
    if not sets_ev["has_odds"]:
        lines.append("    Odds: — (inserisci le quote 'Straight Sets' per valutare l'EV)")
        return "\n".join(lines)
    lines.append(
        f"    EV: straight sets {sets_ev['ev_straight']*100:+.1f}%  •  "
        f"oltre il minimo {sets_ev['ev_extra']*100:+.1f}%"
    )
    if sets_ev["value_pick"]:
        lines.append(
            f"    ✅ VALUE PICK  : {sets_ev['value_pick']} @ {sets_ev['value_odds']} "
            f"(edge {sets_ev['value_edge']*100:+.1f}%)"
        )
    else:
        lines.append("    ⛔ No value    : nessun lato supera il margine minimo — passa.")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# MERCATO GAMES TOTALI (Over/Under) — regressione lineare fittata + Normale.
#
# expected_total_games = intercetta + coef · [avg_games_prior, |rank_diff|,
#                                              |surface_diff|, best_of_flag]
# fittata da fit_weights.py sui match reali (walk-forward, no leakage).
# best_of_flag = 0 per best-of-3, 1 per best-of-5 (Slam maschili): un match al
# meglio dei 5 set ha strutturalmente molti più games (fino a ~65) di uno al
# meglio dei 3 — senza questa feature un dataset misto bo3/bo5 gonfia
# artificialmente sia l'intercetta che la deviazione standard dei residui.
# Senza games_weights.json: prior grezzo = media dei games_avg dei due
# giocatori (o 22.0 di default), std fissa a 4.5 (tipico match best-of-3).
# La probabilità Over/Under una linea usa una Normale attorno alla media
# stimata (approssimazione ragionevole per un totale discreto ~12-65).
# ═══════════════════════════════════════════════════════════════════════════

_GAMES_PRIOR_MEAN = 22.0
_GAMES_PRIOR_STD = 4.5

_GAMES_INTERCEPT = _GAMES_PRIOR_MEAN
_GAMES_COEF = [1.0, 0.0, 0.0, 0.0]  # [avg_games_prior, |rank_diff|, |surface_diff|, best_of_flag]
# Sigma per formato: un match bo5 ha strutturalmente più varianza assoluta
# di un bo3 (più set = più eventi che sommano incertezza), non solo una
# media più alta — una sigma unica sovrastimerebbe l'incertezza sui bo3 (la
# stragrande maggioranza dei match) e la sottostimerebbe sui bo5.
_GAMES_STD_BO3 = _GAMES_PRIOR_STD
_GAMES_STD_BO5 = _GAMES_PRIOR_STD
GAMES_SOURCE = "prior"

_GAMES_WEIGHTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "games_weights.json")


def _load_games_weights() -> None:
    global _GAMES_INTERCEPT, _GAMES_COEF, _GAMES_STD_BO3, _GAMES_STD_BO5, GAMES_SOURCE
    if not os.path.exists(_GAMES_WEIGHTS_PATH):
        return
    try:
        with open(_GAMES_WEIGHTS_PATH, encoding="utf-8") as fh:
            w = json.load(fh)
        _GAMES_INTERCEPT = float(w["intercept"])
        coef = [float(c) for c in w["coef"]]
        # retrocompat: file generati prima della feature best_of hanno solo 3
        # coefficienti → padding a 0.0 (nessun aggiustamento bo3/bo5).
        while len(coef) < 4:
            coef.append(0.0)
        _GAMES_COEF = coef
        # retrocompat: file generati prima della sigma per-formato hanno solo
        # "residual_std" (pooled) → usata per entrambi i formati.
        pooled = float(w.get("residual_std", _GAMES_PRIOR_STD))
        _GAMES_STD_BO3 = float(w.get("residual_std_bo3", pooled))
        _GAMES_STD_BO5 = float(w.get("residual_std_bo5", pooled))
        GAMES_SOURCE = "fitted"
    except Exception:
        pass


_load_games_weights()


def _games_std(best_of: int) -> float:
    return _GAMES_STD_BO5 if best_of >= 5 else _GAMES_STD_BO3


def _norm_cdf(x: float, mean: float, std: float) -> float:
    if std <= 0:
        return 1.0 if x >= mean else 0.0
    return 0.5 * (1.0 + math.erf((x - mean) / (std * math.sqrt(2))))


def expected_total_games(p1_stats: dict, p2_stats: dict, best_of: int = 3) -> float:
    """Media attesa di games totali nel match, dal modello fittato (o dal
    prior grezzo se games_weights.json non è presente)."""
    g1 = p1_stats.get("games_avg") or 0.0
    g2 = p2_stats.get("games_avg") or 0.0
    if g1 and g2:
        avg_games_prior = (g1 + g2) / 2
    elif g1 or g2:
        avg_games_prior = g1 or g2
    else:
        avg_games_prior = _GAMES_PRIOR_MEAN

    rank_gap = abs(rank_feature(p1_stats.get("ranking", 0), p2_stats.get("ranking", 0)))
    surf_gap = abs(p1_stats.get("surface_win_rate", 0.0) - p2_stats.get("surface_win_rate", 0.0))
    bo_flag = 1.0 if best_of >= 5 else 0.0

    mean = _GAMES_INTERCEPT + (
        _GAMES_COEF[0] * (avg_games_prior - _GAMES_PRIOR_MEAN)
        + _GAMES_COEF[1] * rank_gap
        + _GAMES_COEF[2] * surf_gap
        + _GAMES_COEF[3] * bo_flag
    )
    min_games = 6 * ((best_of + 1) // 2)  # bo3: 12 (6-0 6-0), bo5: 18 (6-0 6-0 6-0)
    return max(float(min_games), mean)


def evaluate_games_value(
    p1_stats: dict, p2_stats: dict, line: float, best_of: int = 3,
    odds_over: float | None = None, odds_under: float | None = None,
    min_edge: float = DEFAULT_MIN_EDGE,
) -> dict:
    """Valuta Over/Under `line` games totali (es. 22.5) per un match al
    meglio di `best_of` set."""
    mean = expected_total_games(p1_stats, p2_stats, best_of)
    std = _games_std(best_of)
    p_under = _norm_cdf(line, mean, std)
    p_over = 1.0 - p_under
    tag = "fitted" if GAMES_SOURCE == "fitted" else "heuristic prior"
    result = {
        "line": line, "expected_games": round(mean, 1), "std": round(std, 2),
        "prob_over": round(p_over, 4), "prob_under": round(p_under, 4),
        "source": tag,
        "has_odds": False, "odds_over": odds_over, "odds_under": odds_under,
        "ev_over": None, "ev_under": None,
        "value_pick": None, "value_edge": None, "value_odds": None,
    }
    if not odds_over or not odds_under:
        return result

    ev_over = expected_value(p_over, odds_over)
    ev_under = expected_value(p_under, odds_under)
    result.update(has_odds=True, ev_over=ev_over, ev_under=ev_under)

    if ev_over >= ev_under and ev_over >= min_edge:
        result.update(value_pick=f"Over {line}", value_edge=ev_over, value_odds=odds_over)
    elif ev_under >= min_edge:
        result.update(value_pick=f"Under {line}", value_edge=ev_under, value_odds=odds_under)
    return result


def format_games_block(games_ev: dict) -> str:
    lines = [
        f"    Model: expected {games_ev['expected_games']} games (σ={games_ev['std']}, {games_ev['source']})  •  "
        f"line {games_ev['line']}  →  Over {games_ev['prob_over']*100:.0f}%  •  Under {games_ev['prob_under']*100:.0f}%"
    ]
    if not games_ev["has_odds"]:
        lines.append("    Odds: — (inserisci le quote O/U games per valutare l'EV)")
        return "\n".join(lines)
    lines.append(
        f"    EV: Over {games_ev['ev_over']*100:+.1f}%  •  Under {games_ev['ev_under']*100:+.1f}%"
    )
    if games_ev["value_pick"]:
        lines.append(
            f"    ✅ VALUE PICK  : {games_ev['value_pick']} @ {games_ev['value_odds']} "
            f"(edge {games_ev['value_edge']*100:+.1f}%)"
        )
    else:
        lines.append("    ⛔ No value    : nessun lato supera il margine minimo — passa.")
    return "\n".join(lines)


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
