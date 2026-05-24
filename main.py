"""
TennisIQ Analytics — CLI entry point.

Usage:
    python main.py "Sinner" "Alcaraz" "Roland Garros"
    python main.py "Djokovic" "Medvedev" "Wimbledon"
    python main.py "Zverev" "Ruud" "US Open"
"""

import sys
import io
import argparse

import data_provider as dp
import analytics


def _momentum_label(score: float) -> str:
    if score >= 12:
        return "🔥 Blazing"
    if score >= 5:
        return "📈 Positive"
    if score >= -5:
        return "➡️  Neutral"
    return "📉 Negative"


def _sign(value: float) -> str:
    return f"+{value}" if value >= 0 else str(value)


def build_insight(p1_name: str, p1_stats: dict,
                  p2_name: str, p2_stats: dict,
                  surface: str) -> str:
    """
    Narrative insight driven by surface-adjusted momentum, career surface
    win rate, and clutch factor — evaluated top-down in priority order.

    Leaders are resolved with strict inequality so a zero-diff never
    falsely claims an edge. Each None leader means the metric is tied.
    """
    mom_diff    = p1_stats["momentum_score"]  - p2_stats["momentum_score"]
    surf_diff   = p1_stats["surface_win_rate"] - p2_stats["surface_win_rate"]
    clutch_diff = p1_stats["clutch_factor"]   - p2_stats["clutch_factor"]

    abs_mom    = abs(mom_diff)
    abs_surf   = abs(surf_diff)
    abs_clutch = abs(clutch_diff)

    # Strict inequality → None when tied, so no metric falsely claims an edge
    leader_mom    = p1_name if mom_diff    > 0 else (p2_name if mom_diff    < 0 else None)
    leader_surf   = p1_name if surf_diff   > 0 else (p2_name if surf_diff   < 0 else None)
    leader_clutch = p1_name if clutch_diff > 0 else (p2_name if clutch_diff < 0 else None)

    # Derived convenience — only used when leader is confirmed non-None
    trailer_mom  = p2_name if leader_mom  == p1_name else p1_name
    trailer_surf = p2_name if leader_surf == p1_name else p1_name

    # ── Priority 1: dominant advantage on both axes (same direction) ──────────
    if abs_mom >= 10 and abs_surf >= 12 and leader_mom == leader_surf:
        return (
            f"{leader_mom} has a massive surface-adjusted momentum advantage AND "
            f"a stronger career record on {surface}. Everything points the same way — "
            f"this could be a statement win."
        )

    # ── Priority 2: strong momentum + clear surface edge, same player ─────────
    if abs_mom >= 10 and abs_surf >= 5 and leader_mom == leader_surf and leader_mom is not None:
        return (
            f"{leader_mom} arrives with surface-adjusted momentum of "
            f"{_sign(max(p1_stats['momentum_score'], p2_stats['momentum_score']))} "
            f"and is the better performer on {surface} historically. "
            f"Hard to make a case for {trailer_mom} here."
        )

    # ── Priority 3: strong momentum but surface tells the opposite story ───────
    if abs_mom >= 10 and leader_mom is not None and leader_surf is not None and leader_mom != leader_surf:
        leader_mom_score = p1_stats["momentum_score"] if leader_mom == p1_name else p2_stats["momentum_score"]
        return (
            f"{leader_mom} is in red-hot surface form (momentum: {_sign(leader_mom_score)}), "
            f"but {leader_surf}'s career {surface} record is the counter-argument. "
            f"This clash of form vs. history makes for a genuine betting puzzle."
        )

    # ── Priority 4: one player in clearly negative momentum territory ──────────
    neg_name = None
    if p1_stats["momentum_score"] < -3:
        neg_name = p1_name
    elif p2_stats["momentum_score"] < -3:
        neg_name = p2_name
    if neg_name:
        pos_name = p2_name if neg_name == p1_name else p1_name
        return (
            f"{neg_name} is carrying negative surface-adjusted momentum into this one — "
            f"recent results on relevant surfaces have been poor. "
            f"{pos_name} should be the confident pick barring a major upset."
        )

    # ── Priority 5: clear surface dominance, even momentum ────────────────────
    if abs_surf >= 12 and leader_surf is not None:
        return (
            f"Surface dominance is the decisive factor: {leader_surf} owns {surface} "
            f"historically and both players arrive with similar recent momentum. "
            f"Don't overthink this — lean {leader_surf}."
        )

    # ── Priority 6: meaningful momentum edge, no surface story ────────────────
    if abs_mom >= 6 and leader_mom is not None:
        return (
            f"{leader_mom} has a surface-adjusted momentum advantage going into this match. "
            f"Recent results on {surface} specifically paint a clearer picture than raw form. "
            f"Watch for {leader_mom} to impose early."
        )

    # ── Priority 7: fall back to clutch — or pure deadlock ────────────────────
    if abs_clutch >= 1.0 and leader_clutch is not None:
        leader_cf = (
            p1_stats["clutch_factor"] if leader_clutch == p1_name else p2_stats["clutch_factor"]
        )
        other_cf = (
            p2_stats["clutch_factor"] if leader_clutch == p1_name else p1_stats["clutch_factor"]
        )
        return (
            f"All surface and momentum metrics are essentially level. "
            f"{leader_clutch}'s clutch factor ({leader_cf}% vs {other_cf}%) is the only "
            f"measurable edge — and in tight matches, that's precisely where titles are won."
        )

    # ── Priority 8: true deadlock — no metric separates them ──────────────────
    return (
        f"A genuine statistical deadlock: surface record, surface-adjusted momentum, "
        f"and clutch factor are all too close to call. "
        f"Skip the pre-match angle — watch the first-set tiebreak and react live."
    )


def format_post(p1_name: str, p1_full: str, p1_stats: dict,
                p2_name: str, p2_full: str, p2_stats: dict,
                tournament: str, surface: str) -> str:

    insight = build_insight(p1_name, p1_stats, p2_name, p2_stats, surface)
    div = "━" * 40

    # Momentum labels and signed scores
    m1 = _sign(p1_stats["momentum_score"])
    m2 = _sign(p2_stats["momentum_score"])
    lbl1 = _momentum_label(p1_stats["momentum_score"])
    lbl2 = _momentum_label(p2_stats["momentum_score"])

    lines = [
        div,
        f"🎾  MATCH ANALYSIS",
        div,
        f"⚔️   {p1_full}  vs  {p2_full}",
        f"🏆  {tournament}   •   {surface}",
        div,
        "",
        f"📊  SURFACE PERFORMANCE",
        f"    {p1_full:<22} {p1_stats['surface_win_rate']:>5}% on {surface}",
        f"    {p2_full:<22} {p2_stats['surface_win_rate']:>5}% on {surface}",
        "",
        f"🏃  SURFACE-ADJUSTED FORM  (last 3 matches)",
        f"    {p1_full}",
        f"      Load : {p1_stats['fatigue_score']} weighted mins",
        f"      Form : {m1} pts  {lbl1}",
        f"    {p2_full}",
        f"      Load : {p2_stats['fatigue_score']} weighted mins",
        f"      Form : {m2} pts  {lbl2}",
        "",
        f"🧠  CLUTCH FACTOR  (BP + Tiebreak efficiency)",
        f"    {p1_full:<22} {p1_stats['clutch_factor']:>5}%",
        f"    {p2_full:<22} {p2_stats['clutch_factor']:>5}%",
        "",
        div,
        f"💡  TIPSTER INSIGHT",
        f"    {insight}",
        div,
        f"📡  TennisIQ Analytics  •  ⚠️ Not financial advice — DYOR!",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tennisiq",
        description="Generate a social-ready tennis match analysis.",
    )
    parser.add_argument("player1_name", help="First player (e.g. Sinner)")
    parser.add_argument("player2_name", help="Second player (e.g. Alcaraz)")
    parser.add_argument("tournament_name", help='Tournament (e.g. "Roland Garros")')
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Resolve surface from tournament; fall back to Hard
    surface = dp.TOURNAMENT_SURFACES.get(args.tournament_name, "Hard")
    if args.tournament_name not in dp.TOURNAMENT_SURFACES:
        print(
            f"⚠️  '{args.tournament_name}' not found in tournament list — "
            f"defaulting surface to Hard.\n"
        )

    # Fetch player data
    try:
        p1_data = dp.get_player(args.player1_name)
        p2_data = dp.get_player(args.player2_name)
    except ValueError as exc:
        print(f"❌ {exc}")
        print(f"   Available players: {', '.join(dp.list_players())}")
        sys.exit(1)

    # Compute metrics
    p1_stats = analytics.compute_all(p1_data, surface)
    p2_stats = analytics.compute_all(p2_data, surface)

    # Render and print
    post = format_post(
        args.player1_name, p1_data["full_name"], p1_stats,
        args.player2_name, p2_data["full_name"], p2_stats,
        args.tournament_name, surface,
    )
    print(post)


if __name__ == "__main__":
    # Force UTF-8 only when running as CLI, not when imported by Streamlit.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
