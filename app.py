"""
TennisIQ Analytics — Streamlit frontend.

Schedule-driven workflow:
  Step 1  Sidebar  — pick a date + optional tournament filter, load matches
  Step 2  Main     — pick a fixture from the live / mock schedule dropdown
  Step 3  Main     — click GENERA REPORT to run analytics and get the post
"""

import os
import streamlit as st
from datetime import date as _date

# ── Secrets bootstrap ─────────────────────────────────────────────────────────
# Streamlit loads .streamlit/secrets.toml (local) or the Secrets panel
# (Streamlit Cloud) into st.secrets, but does NOT inject them into os.environ.
# data_provider.py reads the key via os.getenv() on every call, so we sync
# st.secrets → os.environ here, once, before any data_provider import runs.
try:
    if "APISPORTS_KEY" in st.secrets and not os.environ.get("APISPORTS_KEY"):
        os.environ["APISPORTS_KEY"] = st.secrets["APISPORTS_KEY"]
except Exception:
    pass  # secrets not available (e.g. CLI run) — graceful no-op

import data_provider as dp
import analytics as an
import main as mn

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TennisIQ Analytics",
    page_icon="🎾",
    layout="centered",
)

# ── Session-state defaults ────────────────────────────────────────────────────
# schedule      : list of fixture dicts returned by dp.get_daily_schedule()
# schedule_key  : "date|tournament_id" string — invalidates cache on change
# report        : the last generated post string (persists across rerenders)
for _k, _v in {
    "schedule":     [],
    "schedule_key": "",
    "report":       "",
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── Sidebar — Step 1: Date + Tournament ──────────────────────────────────────
with st.sidebar:
    st.title("🎾 TennisIQ")
    st.caption("B2B Dashboard for Tipsters & Content Creators")
    st.markdown("---")

    st.subheader("📅 Step 1 — Select Date & Tournament")

    selected_date = st.date_input(
        "Match date",
        value=_date.today(),
        min_value=_date(2020, 1, 1),
        max_value=_date(2030, 12, 31),
    )

    tournament_options = ["All tournaments"] + list(dp.TOURNAMENT_SURFACES.keys())
    tournament_filter = st.selectbox(
        "Filter by tournament (optional)",
        tournament_options,
        index=0,
    )

    load_btn = st.button("🔄 Load Today's Matches", use_container_width=True)

    st.markdown("---")
    st.caption(
        "Data: api-sports.io live when `APISPORTS_KEY` is set, "
        "sample fixtures otherwise."
    )

# ── Compute the cache key for this date + tournament combination ──────────────
date_str      = selected_date.strftime("%Y-%m-%d")
tournament_id = None if tournament_filter == "All tournaments" else tournament_filter
new_key       = f"{date_str}|{tournament_id or 'all'}"

# Fetch when: button pressed, date/tournament changed, or first run
should_fetch = (
    load_btn
    or st.session_state.schedule_key != new_key
    or not st.session_state.schedule
)

if should_fetch:
    with st.spinner(f"Loading matches for {date_str}…"):
        st.session_state.schedule     = dp.get_daily_schedule(date_str, tournament_id)
        st.session_state.schedule_key = new_key
        st.session_state.report       = ""   # clear stale report on schedule change


# ── Main panel header ─────────────────────────────────────────────────────────
st.title("🎾 TennisIQ Analytics")
st.markdown("*Generate Telegram-ready match insights in seconds.*")
st.markdown("---")

schedule = st.session_state.schedule

if not schedule:
    st.info(
        "No matches found for this date and filter. "
        "Try a different date or remove the tournament filter."
    )
    st.stop()

# ── Data-source badge ─────────────────────────────────────────────────────────
source = schedule[0].get("_source", "mock")
if source == "live":
    st.success("🟢 **Live data** — api-sports.io  •  Schedule updated in real time")
else:
    st.warning(
        "🟡 **Sample fixtures** — API key not set or API unavailable.  "
        "Set `APISPORTS_KEY` in Streamlit Secrets to enable live scheduling."
    )

st.markdown("---")

# ── Step 2 — Match selector ───────────────────────────────────────────────────
st.subheader("⚔️ Step 2 — Select a Match")

fixture_labels = [f["label"] for f in schedule]
selected_label = st.selectbox(
    "Matches in programme:",
    fixture_labels,
    label_visibility="collapsed",
)

# Resolve the full fixture dict from the selected label
fixture = next((f for f in schedule if f["label"] == selected_label), schedule[0])

# Fixture detail cards
best_of = dp.best_of_for_tournament(fixture["tournament"])
c1, c2, c3, c4 = st.columns(4)
c1.metric("🏆 Tournament", fixture["tournament"])
c2.metric("🏟️ Surface",    fixture["surface"])
c3.metric("🕐 Time",       fixture["time"])
c4.metric("🥎 Format",     f"Best-of-{best_of}")

st.markdown("---")

# ── Step 3 — Generate report ──────────────────────────────────────────────────
st.subheader("📊 Step 3 — Generate Report")

st.markdown("**Quote (opzionale)** — inseriscile per calcolare EV e value pick:")
oc1, oc2 = st.columns(2)
odds1 = oc1.number_input(
    f"Quota {fixture['p1_name']}", min_value=1.0, max_value=100.0,
    value=1.0, step=0.05, format="%.2f",
)
odds2 = oc2.number_input(
    f"Quota {fixture['p2_name']}", min_value=1.0, max_value=100.0,
    value=1.0, step=0.05, format="%.2f",
)
# 1.0 = campo lasciato vuoto → nessuna quota
odds1_val = odds1 if odds1 > 1.0 else None
odds2_val = odds2 if odds2 > 1.0 else None

with st.expander("🎯 Total Games & 🥎 Set (opzionale)"):
    gc1, gc2, gc3 = st.columns(3)
    games_line = gc1.number_input("Linea games", min_value=10.0, max_value=40.0, value=22.5, step=0.5)
    odds_games_over = gc2.number_input("Quota Over", min_value=1.0, max_value=100.0, value=1.0, step=0.05, format="%.2f")
    odds_games_under = gc3.number_input("Quota Under", min_value=1.0, max_value=100.0, value=1.0, step=0.05, format="%.2f")
    sc1, sc2 = st.columns(2)
    straight_label = "Quota straight sets (2-0)" if best_of == 3 else "Quota straight sets (3-0)"
    extra_label = "Quota oltre il minimo (3 set)" if best_of == 3 else "Quota oltre il minimo (4-5 set)"
    odds_straight = sc1.number_input(straight_label, min_value=1.0, max_value=100.0, value=1.0, step=0.05, format="%.2f")
    odds_extra = sc2.number_input(extra_label, min_value=1.0, max_value=100.0, value=1.0, step=0.05, format="%.2f")

odds_games_over_val = odds_games_over if odds_games_over > 1.0 else None
odds_games_under_val = odds_games_under if odds_games_under > 1.0 else None
odds_straight_val = odds_straight if odds_straight > 1.0 else None
odds_extra_val = odds_extra if odds_extra > 1.0 else None

gen_btn = st.button("🚀 GENERA REPORT PER TELEGRAM", use_container_width=True)

if gen_btn:
    with st.spinner(
        "Analysing surface curve, momentum compression and clutch factor…"
    ):
        try:
            p1_data = dp.get_player(fixture["p1_name"])
            p2_data = dp.get_player(fixture["p2_name"])

            p1_stats = an.compute_all(p1_data, fixture["surface"])
            p2_stats = an.compute_all(p2_data, fixture["surface"])
            p1_stats["ranking"] = p1_data.get("ranking", 0)
            p2_stats["ranking"] = p2_data.get("ranking", 0)
            p1_stats["games_avg"] = p1_data.get("games_avg", 0.0)
            p2_stats["games_avg"] = p2_data.get("games_avg", 0.0)

            # Extract short keys (e.g. "Sinner") for the insight engine.
            # Fall back to the full name if no short key is found in PLAYERS.
            p1_key = next(
                (k for k, v in dp.PLAYERS.items()
                 if v["full_name"] == p1_data["full_name"]),
                fixture["p1_name"],
            )
            p2_key = next(
                (k for k, v in dp.PLAYERS.items()
                 if v["full_name"] == p2_data["full_name"]),
                fixture["p2_name"],
            )

            st.session_state.report = mn.format_post(
                p1_key, p1_data["full_name"], p1_stats,
                p2_key, p2_data["full_name"], p2_stats,
                fixture["tournament"], fixture["surface"],
                odds1=odds1_val, odds2=odds2_val,
                games_line=games_line,
                odds_games_over=odds_games_over_val, odds_games_under=odds_games_under_val,
                odds_straight_sets=odds_straight_val, odds_extra_sets=odds_extra_val,
            )

        except Exception as exc:
            st.error(f"❌ Error generating report: {exc}")

# Render report if one exists (persists across rerenders)
if st.session_state.report:
    st.success("✅ Report generated — copy and paste below!")

    # Honest data-source breakdown: the schedule can be live while the player
    # statistics come from the static dataset (real Sackmann data or mock).
    sched_src = "🟢 Live" if fixture.get("_source") == "live" else "🟡 Sample"
    if dp.STATIC_DATA_SOURCE == "sackmann":
        stats_src = "🟢 Real (ATP historical data)"
    else:
        stats_src = "🟡 Mock (run build_dataset.py for real stats)"
    st.caption(f"Schedule: {sched_src}  •  Player stats: {stats_src}")

    st.text_area(
        label="Copy directly to your Telegram / Discord channel:",
        value=st.session_state.report,
        height=440,
    )

    st.caption(
        "💡 Tipster tip: Screenshot the text area above for visual channels."
    )
