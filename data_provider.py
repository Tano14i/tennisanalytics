"""
Data provider for TennisIQ Analytics.

Data-source ladder — evaluated in order on every call:
  1. RapidAPI live  — schedule + player data   (requires RAPIDAPI_KEY env var)
  2. Mock fallback  — static dataset + sample fixtures, always available

Two independent caches live at module level:
  _LIVE_CACHE      — player dicts,  keyed by name.lower()
  _SCHEDULE_CACHE  — fixture lists, keyed by "date|tournament_id"

Both caches survive Streamlit rerenders within a single session and are
cleared automatically when the process restarts (deploy / dyno restart).

Every public return value carries a '_data_source' key ("live" or "mock")
so app.py can render a status badge without touching analytics.py.
"""

import os
import warnings
from datetime import date as _date
from typing import Optional

try:
    import requests as _req
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# ── API configuration ─────────────────────────────────────────────────────────
# Key is intentionally NOT cached at module level — it is read fresh on every
# call via os.getenv() so that app.py can inject it from st.secrets at runtime
# before the first API call is made.
#
# Host: tennisapi1.p.rapidapi.com  ("Tennis API" by solutionjet)
#   Subscribe free at: https://rapidapi.com/solutionjet/api/tennis-api4
#   Endpoint used for schedule:  GET /matches?status=NS&date=YYYY-MM-DD
#   Endpoint used for players:   GET /players?search=NAME
_RAPIDAPI_HOST = "tennisapi1.p.rapidapi.com"
_API_BASE      = f"https://{_RAPIDAPI_HOST}"
_TIMEOUT       = 6   # seconds
_RECENT_LIMIT  = 3   # recent matches to pull per player

# ── Module-level caches ───────────────────────────────────────────────────────
_LIVE_CACHE:     dict[str, dict]       = {}   # name.lower() → player dict
_SCHEDULE_CACHE: dict[str, list[dict]] = {}   # "date|tid"   → fixture list

# ── Mock player dataset ───────────────────────────────────────────────────────
PLAYERS: dict[str, dict] = {
    "Sinner": {
        "full_name": "Jannik Sinner",
        "ranking": 1,
        "recent_matches": [
            {"opponent": "Medvedev", "duration_min": 142, "result": "W", "surface": "Hard"},
            {"opponent": "Zverev",   "duration_min": 178, "result": "W", "surface": "Clay"},
            {"opponent": "Rune",     "duration_min":  95, "result": "W", "surface": "Clay"},
        ],
        "surface_records": {
            "Clay":  {"wins": 38, "losses": 12},
            "Hard":  {"wins": 61, "losses": 14},
            "Grass": {"wins": 18, "losses":  9},
        },
        "break_points":       {"opportunities": 84,  "converted": 38},
        "break_points_saved": {"faced": 72,  "saved": 46},
        "tiebreaks":          {"played": 34, "won": 22},
    },
    "Alcaraz": {
        "full_name": "Carlos Alcaraz",
        "ranking": 3,
        "recent_matches": [
            {"opponent": "Djokovic", "duration_min": 212, "result": "W", "surface": "Grass"},
            {"opponent": "Medvedev", "duration_min": 185, "result": "W", "surface": "Clay"},
            {"opponent": "Sinner",   "duration_min": 201, "result": "L", "surface": "Hard"},
        ],
        "surface_records": {
            "Clay":  {"wins": 42, "losses": 10},
            "Hard":  {"wins": 48, "losses": 18},
            "Grass": {"wins": 22, "losses":  6},
        },
        "break_points":       {"opportunities": 96,  "converted": 48},
        "break_points_saved": {"faced": 68,  "saved": 44},
        "tiebreaks":          {"played": 38, "won": 23},
    },
    "Djokovic": {
        "full_name": "Novak Djokovic",
        "ranking": 7,
        "recent_matches": [
            {"opponent": "Alcaraz", "duration_min": 212, "result": "L", "surface": "Grass"},
            {"opponent": "Sinner",  "duration_min": 163, "result": "L", "surface": "Hard"},
            {"opponent": "Zverev",  "duration_min": 134, "result": "W", "surface": "Clay"},
        ],
        "surface_records": {
            "Clay":  {"wins": 93,  "losses": 28},
            "Hard":  {"wins": 158, "losses": 39},
            "Grass": {"wins": 87,  "losses": 14},
        },
        "break_points":       {"opportunities": 210, "converted": 98},
        "break_points_saved": {"faced": 178, "saved": 128},
        "tiebreaks":          {"played": 124, "won": 82},
    },
    "Medvedev": {
        "full_name": "Daniil Medvedev",
        "ranking": 5,
        "recent_matches": [
            {"opponent": "Sinner",  "duration_min": 142, "result": "L", "surface": "Hard"},
            {"opponent": "Alcaraz", "duration_min": 185, "result": "L", "surface": "Clay"},
            {"opponent": "Zverev",  "duration_min": 156, "result": "W", "surface": "Hard"},
        ],
        "surface_records": {
            "Clay":  {"wins": 28, "losses": 22},
            "Hard":  {"wins": 74, "losses": 20},
            "Grass": {"wins": 16, "losses": 14},
        },
        "break_points":       {"opportunities": 88, "converted": 36},
        "break_points_saved": {"faced": 94, "saved": 58},
        "tiebreaks":          {"played": 52, "won": 29},
    },
    "Zverev": {
        "full_name": "Alexander Zverev",
        "ranking": 2,
        "recent_matches": [
            {"opponent": "Sinner",   "duration_min": 178, "result": "L", "surface": "Clay"},
            {"opponent": "Medvedev", "duration_min": 156, "result": "L", "surface": "Hard"},
            {"opponent": "Rune",     "duration_min": 112, "result": "W", "surface": "Clay"},
        ],
        "surface_records": {
            "Clay":  {"wins": 52, "losses": 20},
            "Hard":  {"wins": 68, "losses": 24},
            "Grass": {"wins": 24, "losses": 18},
        },
        "break_points":       {"opportunities": 102, "converted": 44},
        "break_points_saved": {"faced": 86, "saved": 50},
        "tiebreaks":          {"played": 46, "won": 24},
    },
    "Rune": {
        "full_name": "Holger Rune",
        "ranking": 14,
        "recent_matches": [
            {"opponent": "Sinner",    "duration_min":  95, "result": "L", "surface": "Clay"},
            {"opponent": "Zverev",    "duration_min": 112, "result": "L", "surface": "Clay"},
            {"opponent": "Tsitsipas", "duration_min": 138, "result": "W", "surface": "Clay"},
        ],
        "surface_records": {
            "Clay":  {"wins": 28, "losses": 14},
            "Hard":  {"wins": 22, "losses": 18},
            "Grass": {"wins":  8, "losses":  9},
        },
        "break_points":       {"opportunities": 64, "converted": 28},
        "break_points_saved": {"faced": 58, "saved": 32},
        "tiebreaks":          {"played": 24, "won": 11},
    },
    "Tsitsipas": {
        "full_name": "Stefanos Tsitsipas",
        "ranking": 12,
        "recent_matches": [
            {"opponent": "Rune",     "duration_min": 138, "result": "L", "surface": "Clay"},
            {"opponent": "Djokovic", "duration_min": 192, "result": "L", "surface": "Clay"},
            {"opponent": "Ruud",     "duration_min": 148, "result": "W", "surface": "Clay"},
        ],
        "surface_records": {
            "Clay":  {"wins": 48, "losses": 18},
            "Hard":  {"wins": 38, "losses": 22},
            "Grass": {"wins": 14, "losses": 16},
        },
        "break_points":       {"opportunities": 82, "converted": 34},
        "break_points_saved": {"faced": 78, "saved": 44},
        "tiebreaks":          {"played": 36, "won": 16},
    },
    "Ruud": {
        "full_name": "Casper Ruud",
        "ranking": 10,
        "recent_matches": [
            {"opponent": "Tsitsipas", "duration_min": 148, "result": "L", "surface": "Clay"},
            {"opponent": "Rune",      "duration_min": 124, "result": "W", "surface": "Clay"},
            {"opponent": "Zverev",    "duration_min": 189, "result": "L", "surface": "Clay"},
        ],
        "surface_records": {
            "Clay":  {"wins": 56, "losses": 16},
            "Hard":  {"wins": 28, "losses": 26},
            "Grass": {"wins":  9, "losses": 18},
        },
        "break_points":       {"opportunities": 72, "converted": 30},
        "break_points_saved": {"faced": 64, "saved": 36},
        "tiebreaks":          {"played": 28, "won": 12},
    },
}

# ── Tournament → Surface mapping ──────────────────────────────────────────────
TOURNAMENT_SURFACES: dict[str, str] = {
    "Roland Garros":      "Clay",
    "French Open":        "Clay",
    "Monte-Carlo":        "Clay",
    "Madrid Open":        "Clay",
    "Italian Open":       "Clay",
    "Rome":               "Clay",
    "Barcelona Open":     "Clay",
    "Wimbledon":          "Grass",
    "Queen's Club":       "Grass",
    "Halle":              "Grass",
    "US Open":            "Hard",
    "Australian Open":    "Hard",
    "Miami Open":         "Hard",
    "Indian Wells":       "Hard",
    "Cincinnati Masters": "Hard (Outdoor)",
    "Canada Masters":     "Hard (Outdoor)",
    "Stuttgart":          "Hard (Outdoor)",
    "ATP Finals":         "Hard (Indoor)",
    "Paris Masters":      "Hard (Indoor)",
    "Vienna Open":        "Hard (Indoor)",
    "Rotterdam":          "Hard (Indoor)",
    "Marseille":          "Hard (Indoor)",
}

# Keyword hints used by _infer_surface() to map raw API league names
_LEAGUE_SURFACE_HINTS: dict[str, str] = {
    "roland garros": "Clay", "french open": "Clay",
    "monte":  "Clay",  "madrid":   "Clay", "rome":  "Clay",
    "italian":"Clay",  "barcelona":"Clay", "clay":  "Clay",
    "wimbledon":"Grass","queen":"Grass",   "halle": "Grass", "grass":"Grass",
    "australian":"Hard","us open":  "Hard","miami": "Hard",  "indian wells":"Hard",
    "cincinnati":"Hard (Outdoor)","canada":"Hard (Outdoor)",
    "atp finals":"Hard (Indoor)","paris":"Hard (Indoor)",
    "vienna":"Hard (Indoor)",    "rotterdam":"Hard (Indoor)",
}

# ── Sample fixtures — shown when the schedule API is unavailable ──────────────
# Structured as realistic clay-season matches (late May).
_MOCK_SCHEDULE: list[dict] = [
    {
        "label":      "J. Sinner vs C. Ruud",
        "p1_name":    "Jannik Sinner",   "p1_key": None,
        "p2_name":    "Casper Ruud",     "p2_key": None,
        "tournament": "Roland Garros",   "surface": "Clay",
        "time":       "11:00",           "_source": "mock",
    },
    {
        "label":      "C. Alcaraz vs N. Djokovic",
        "p1_name":    "Carlos Alcaraz",  "p1_key": None,
        "p2_name":    "Novak Djokovic",  "p2_key": None,
        "tournament": "Roland Garros",   "surface": "Clay",
        "time":       "13:30",           "_source": "mock",
    },
    {
        "label":      "A. Zverev vs S. Tsitsipas",
        "p1_name":    "Alexander Zverev","p1_key": None,
        "p2_name":    "Stefanos Tsitsipas","p2_key": None,
        "tournament": "Roland Garros",   "surface": "Clay",
        "time":       "15:00",           "_source": "mock",
    },
    {
        "label":      "D. Medvedev vs H. Rune",
        "p1_name":    "Daniil Medvedev", "p1_key": None,
        "p2_name":    "Holger Rune",     "p2_key": None,
        "tournament": "Roland Garros",   "surface": "Clay",
        "time":       "17:00",           "_source": "mock",
    },
]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _api_headers() -> dict:
    """Build request headers, reading the key fresh each time from the env."""
    return {
        "x-rapidapi-key":  os.getenv("RAPIDAPI_KEY", ""),
        "x-rapidapi-host": _RAPIDAPI_HOST,
    }


def _infer_surface(league_name: str) -> str:
    """Map a raw API league/tournament name to one of our surface strings."""
    low = league_name.lower()
    for kw, surf in _LEAGUE_SURFACE_HINTS.items():
        if kw in low:
            return surf
    return "Hard"


def _abbreviate(full_name: str) -> str:
    """'Jannik Sinner' → 'J. Sinner'  (safe with single-word names)."""
    parts = full_name.strip().split()
    if len(parts) < 2:
        return full_name
    return f"{parts[0][0]}. {' '.join(parts[1:])}"


def _build_fixture(
    p1_name: str, p1_key: Optional[str],
    p2_name: str, p2_key: Optional[str],
    league: str,  time_str: str,
    source: str = "live",
) -> dict:
    """Assemble a normalised fixture dict from raw API field values."""
    surface = _infer_surface(league)
    label   = f"{_abbreviate(p1_name)} vs {_abbreviate(p2_name)}"
    return {
        "label":      label,
        "p1_name":    p1_name,
        "p1_key":     p1_key,
        "p2_name":    p2_name,
        "p2_key":     p2_key,
        "tournament": league or "Unknown Tournament",
        "surface":    surface,
        "time":       time_str or "TBD",
        "_source":    source,
    }


# ── Schedule API layer ────────────────────────────────────────────────────────

def _fetch_schedule_from_api(
    date_str: str,
    tournament_id: Optional[str],
) -> Optional[list[dict]]:
    """
    Hit the /matches endpoint for scheduled (not-started) fixtures on
    a given date.  Returns a list of normalised fixture dicts, or None
    on any failure so get_daily_schedule() can fall back to mock data.
    """
    if not os.getenv("RAPIDAPI_KEY") or not _REQUESTS_OK:
        return None

    # tennisapi1 schedule format:
    #   GET /matches?status=NS&date=YYYY-MM-DD[&leagueId=ID]
    # Response: { "matches": [ { "homeTeam": {"name":...,"id":...},
    #             "awayTeam": {"name":...,"id":...},
    #             "league": {"name":..., "id":...},
    #             "startTime": "11:00", "status": "NS" }, ... ] }
    params: dict = {"status": "NS", "date": date_str}
    if tournament_id:
        params["leagueId"] = tournament_id

    try:
        resp = _req.get(
            f"{_API_BASE}/matches",
            headers=_api_headers(),
            params=params,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()

        # tennisapi1 wraps results in "matches"; fall back to "result" for
        # forward-compatibility in case the schema changes.
        body = resp.json()
        raw  = body.get("matches") or body.get("result") or []

        fixtures: list[dict] = []
        for m in raw:
            # tennisapi1 nests teams as objects; also handle flat legacy shape
            home_obj = m.get("homeTeam") or {}
            away_obj = m.get("awayTeam") or {}
            league_obj = m.get("league") or {}

            home     = str(home_obj.get("name") or m.get("event_home_team") or "").strip()
            away     = str(away_obj.get("name") or m.get("event_away_team") or "").strip()
            home_key = str(home_obj.get("id")   or m.get("event_home_team_key") or "")
            away_key = str(away_obj.get("id")   or m.get("event_away_team_key") or "")
            league   = str(league_obj.get("name") or m.get("league_name") or "")
            evt_time = str(m.get("startTime")   or m.get("event_time") or "")

            if not home or not away:
                continue

            fixtures.append(
                _build_fixture(home, home_key, away, away_key, league, evt_time)
            )

        return fixtures if fixtures else None

    except Exception as exc:
        warnings.warn(
            f"[TennisIQ] Schedule fetch failed for {date_str}: {exc!r}. "
            "Using sample fixtures.",
            RuntimeWarning,
            stacklevel=3,
        )
        return None


# ── Schedule public API ───────────────────────────────────────────────────────

def get_daily_schedule(
    date: str,
    tournament_id: Optional[str] = None,
) -> list[dict]:
    """
    Return a list of fixture dicts for the given date.

    Each dict contains:
        label      — display string  e.g. "J. Sinner vs C. Ruud"
        p1_name    — full first-player name
        p1_key     — RapidAPI player key (None for mock fixtures)
        p2_name    — full second-player name
        p2_key     — RapidAPI player key (None for mock fixtures)
        tournament — tournament name string
        surface    — inferred surface string
        time       — scheduled time string or "TBD"
        _source    — "live" or "mock"

    Falls back to _MOCK_SCHEDULE when the API is unavailable or returns
    no fixtures.  Result is cached in _SCHEDULE_CACHE for the session.
    """
    cache_key = f"{date}|{tournament_id or 'all'}"
    if cache_key in _SCHEDULE_CACHE:
        return _SCHEDULE_CACHE[cache_key]

    live = _fetch_schedule_from_api(date, tournament_id)
    if live is not None and len(live) > 0:
        _SCHEDULE_CACHE[cache_key] = live
        return live

    # Fallback: return mock schedule (not cached — always fresh sample)
    return list(_MOCK_SCHEDULE)


# ── Player public API ─────────────────────────────────────────────────────────

def get_player(name: str) -> dict:
    """
    Return a player data dict suitable for analytics.compute_all().

    Tries the RapidAPI live feed first; falls back to the mock dataset.
    Raises ValueError only when no match is found in either source.
    """
    live = _fetch_live_player(name)
    if live is not None:
        return live

    key = _fuzzy_match(name)
    if key is None:
        raise ValueError(
            f"Player '{name}' not found. "
            f"Available: {', '.join(PLAYERS.keys())}"
        )
    record = dict(PLAYERS[key])
    record.setdefault("_data_source", "mock")
    return record


def list_players() -> list[str]:
    """Player short-keys from the mock dataset (used for fallback UI only)."""
    return list(PLAYERS.keys())


# ── Player API layer ──────────────────────────────────────────────────────────

def _fetch_player_meta(name: str) -> Optional[tuple[str, str, int]]:
    """Search API → (player_key, full_name, ranking) or None.

    tennisapi1 player search:
      GET /players?search=NAME
      Response: { "players": [ { "id": "...", "name": "...", "ranking": N } ] }
    Also handles legacy flat shape for forward-compat.
    """
    resp = _req.get(
        f"{_API_BASE}/players",
        headers=_api_headers(),
        params={"search": name},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    body    = resp.json()
    results = body.get("players") or body.get("result") or []
    if not results:
        return None
    hit      = results[0]
    key      = str(hit.get("id")          or hit.get("player_key")  or "")
    fullname = str(hit.get("name")        or hit.get("player_name") or name)
    ranking  = int(hit.get("ranking")     or hit.get("player_rank") or 0)
    return (key, fullname, ranking) if key else None


def _fetch_recent_matches(player_key: str, full_name: str) -> list[dict]:
    """Fetch last _RECENT_LIMIT finished matches for a player.

    tennisapi1:  GET /matches?playerId=ID&status=FT
    Response: { "matches": [ { "homeTeam": {name, id},
                                "awayTeam": {name, id},
                                "winner":   "home"|"away",
                                "duration": 120,
                                "league":   {name} } ] }
    """
    resp = _req.get(
        f"{_API_BASE}/matches",
        headers=_api_headers(),
        params={"playerId": player_key, "status": "FT"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    raw  = body.get("matches") or body.get("result") or []

    matches: list[dict] = []
    player_lower = full_name.lower()

    player_lower = full_name.lower()
    for m in raw:
        if len(matches) >= _RECENT_LIMIT:
            break

        # tennisapi1 nested shape
        home_obj    = m.get("homeTeam") or {}
        away_obj    = m.get("awayTeam") or {}
        league_obj  = m.get("league")   or {}
        home        = str(home_obj.get("name") or m.get("event_home_team") or "")
        away        = str(away_obj.get("name") or m.get("event_away_team") or "")
        winner_side = str(m.get("winner")      or m.get("event_winner")   or "")
        league_name = str(league_obj.get("name") or m.get("league_name")  or "")

        is_home  = player_lower in home.lower()
        opponent = away if is_home else home

        # Normalise winner token ("home"/"away" or "Home"/"Away")
        wl = winner_side.lower()
        if wl == "home":
            result = "W" if is_home else "L"
        elif wl == "away":
            result = "L" if is_home else "W"
        else:
            continue   # skip matches without a clear result

        raw_dur = (
            m.get("duration") or m.get("event_time")
            or m.get("match_duration") or m.get("event_length")
        )
        try:
            duration = max(30, int(raw_dur))
        except (TypeError, ValueError):
            duration = 95

        matches.append({
            "opponent":     opponent or "Unknown",
            "duration_min": duration,
            "result":       result,
            "surface":      _infer_surface(league_name),
        })

    return matches


def _fetch_live_player(name: str) -> Optional[dict]:
    """
    Full live-fetch pipeline: search → fetch matches → merge onto mock base.
    Returns player dict with '_data_source': 'live', or None on any failure.
    """
    if not os.getenv("RAPIDAPI_KEY") or not _REQUESTS_OK:
        return None

    cache_key = name.lower()
    if cache_key in _LIVE_CACHE:
        return _LIVE_CACHE[cache_key]

    try:
        meta = _fetch_player_meta(name)
        if not meta:
            return None
        player_key, full_name, ranking = meta

        recent = _fetch_recent_matches(player_key, full_name)
        if not recent:
            return None

        mock_key = _fuzzy_match(name)
        base     = dict(PLAYERS[mock_key]) if mock_key else {}
        record   = {
            **base,
            "full_name":      full_name,
            "ranking":        ranking or base.get("ranking", 0),
            "recent_matches": recent,
            "_data_source":   "live",
        }
        _LIVE_CACHE[cache_key] = record
        return record

    except Exception as exc:
        warnings.warn(
            f"[TennisIQ] Player fetch failed for '{name}': {exc!r}. "
            "Using mock data.",
            RuntimeWarning,
            stacklevel=2,
        )
        return None


# ── Shared internal helper ────────────────────────────────────────────────────

def _fuzzy_match(name: str) -> Optional[str]:
    """Case-insensitive partial match on PLAYERS keys and full_names."""
    nl = name.lower()
    for key in PLAYERS:
        if key.lower() == nl:
            return key
    for key, data in PLAYERS.items():
        if nl in key.lower() or nl in data["full_name"].lower():
            return key
    return None
