"""
Analytics engine for TennisIQ.

Exposes three pure functions that each accept a player dict
(as returned by data_provider.get_player) and return a numeric score:

  surface_adjusted_form(player, surface) -> dict  (fatigue_score, momentum_score)
  surface_win_rate(player, surf)         -> float (win % on that surface)
  clutch_factor(player)                  -> float (combined BP + TB efficiency %)

All functions are stateless and side-effect-free.
"""

import math

_SURFACE_MATCH_WEIGHT = 1.5
_SURFACE_OTHER_WEIGHT = 0.5
_WIN_POINTS   =  10
_LOSS_POINTS  =  -5

# Asymptotic ceiling for momentum compression (tanh-based).
# The raw weighted sum is passed through tanh(x / CAP) * CAP so the
# output is always in (-CAP, +CAP), with diminishing returns as the
# score grows — three surface-matching wins cap out around +27, not +45.
_MOMENTUM_CAP = 30.0


def _compress_momentum(raw: float) -> float:
    """
    Asymptotic compression via tanh.

    Maps any raw sum onto the open interval (-_MOMENTUM_CAP, +_MOMENTUM_CAP).
    The curve is approximately linear near 0 and flattens as |raw| grows,
    so each additional consecutive win on the same surface contributes
    progressively less to the final score.
    """
    return round(_MOMENTUM_CAP * math.tanh(raw / _MOMENTUM_CAP), 1)


def surface_adjusted_form(player: dict, current_surface: str) -> dict:
    """
    Weighted analysis of the player's last 3 matches relative to the
    current surface.

    Each match gets weight 1.5 when its surface matches current_surface,
    and 0.5 when it does not.

    fatigue_score  = sum(duration_min * weight)          [linear, unbounded]
    momentum_score = tanh-compressed sum((+10 W / -5 L) * weight)  [capped ±30]

    Returns {'fatigue_score': float, 'momentum_score': float}.
    """
    current = current_surface.strip().title()
    fatigue = 0.0
    raw_momentum = 0.0

    for match in player["recent_matches"]:
        weight = (
            _SURFACE_MATCH_WEIGHT
            if match["surface"].strip().title() == current
            else _SURFACE_OTHER_WEIGHT
        )
        fatigue      += match["duration_min"] * weight
        raw_momentum += (_WIN_POINTS if match["result"] == "W" else _LOSS_POINTS) * weight

    return {
        "fatigue_score":  round(fatigue, 1),
        "momentum_score": _compress_momentum(raw_momentum),
    }


def surface_win_rate(player: dict, surface: str) -> float:
    """
    Win percentage on the given surface.

    Supports the Hard (Indoor) / Hard (Outdoor) sub-type split:
    if the player's records don't carry the specific variant yet,
    falls back to the parent surface key (the part before the first '(').

    Returns 0.0 if neither the variant nor the parent is found.
    """
    surface = surface.strip().title()
    record = player["surface_records"].get(surface)

    if not record and "(" in surface:
        parent = surface[: surface.index("(")].strip()
        record = player["surface_records"].get(parent)

    if not record:
        return 0.0
    total = record["wins"] + record["losses"]
    if total == 0:
        return 0.0
    return round(record["wins"] / total * 100, 1)


def clutch_factor(player: dict) -> float:
    """
    Combined efficiency across break points attacked, break points saved,
    and tie-breaks.

    Actions   = BP opportunities + BP faced + TB played
    Successes = BP converted     + BP saved + TB won
    Clutch %  = Successes / Actions * 100
    """
    bp  = player["break_points"]
    bps = player["break_points_saved"]
    tb  = player["tiebreaks"]

    actions    = bp["opportunities"] + bps["faced"]   + tb["played"]
    successes  = bp["converted"]     + bps["saved"]   + tb["won"]

    if actions == 0:
        return 0.0
    return round(successes / actions * 100, 1)


def compute_all(player: dict, surface: str) -> dict:
    """Convenience wrapper — returns all metrics in one dict."""
    form = surface_adjusted_form(player, surface)
    return {
        "fatigue_score":    form["fatigue_score"],
        "momentum_score":   form["momentum_score"],
        "surface_win_rate": surface_win_rate(player, surface),
        "clutch_factor":    clutch_factor(player),
    }
