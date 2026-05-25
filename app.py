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
c1, c2, c3 = st.columns(3)
c1.metric("🏆 Tournament", fixture["tournament"])
c2.metric("🏟️ Surface",    fixture["surface"])
c3.metric("🕐 Time",       fixture["time"])

st.markdown("---")

# ── Step 3 — Generate report ──────────────────────────────────────────────────
st.subheader("📊 Step 3 — Generate Report")

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
            )

        except Exception as exc:
            st.error(f"❌ Error generating report: {exc}")

# Render report if one exists (persists across rerenders)
if st.session_state.report:
    st.success("✅ Report generated — copy and paste below!")

    # Data-source sub-badge inside the report section
    p1_src = "🟢 Live" if fixture.get("_source") == "live" else "🟡 Mock"
    st.caption(f"Player data source: {p1_src}")

    st.text_area(
        label="Copy directly to your Telegram / Discord channel:",
        value=st.session_state.report,
        height=440,
    )

    st.caption(
        "💡 Tipster tip: Screenshot the text area above for visual channels."
    )
