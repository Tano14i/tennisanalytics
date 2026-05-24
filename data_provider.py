"""
Data provider for TennisIQ Analytics.

Data-source ladder (evaluated in order every call):
  1. RapidAPI live  — recent matches + ranking (requires RAPIDAPI_KEY env var)
  2. Mock fallback  — complete static dataset, always available

When a RAPIDAPI_KEY is present, get_player() fetches the player's last three
matches and current ranking from api-tennis.p.rapidapi.com, then merges them
onto the mock base-record to fill fields the free-tier API doesn't expose
(surface_records, break_points, tiebreaks).  If the key is missing or any
network/HTTP/parse error occurs, the function falls back silently to the mock
data so the app never crashes.

Each returned dict carries a '_data_source' key ("live" or "mock") that
app.py can surface as a status badge without touching analytics.py.
"""

import os
import warnings
from typing import Optional

# requests is an optional dependency — the app works without it (mock only).
try:
    import requests as _req
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# ── API configuration ─────────────────────────────────────────────────────────
_RAPIDAPI_KEY  = os.getenv("RAPIDAPI_KEY", "")
_RAPIDAPI_HOST = "api-tennis.p.rapidapi.com"
_API_BASE      = f"https://{_RAPIDAPI_HOST}"
_TIMEOUT       = 5          # seconds per request
_RECENT_LIMIT  = 3          # how many recent matches to pull

# Session-level cache  { name_lower: player_dict }
# Prevents duplicate API calls on Streamlit rerenders.
_LIVE_CACHE: dict[str, dict] = {}

# ── Mock dataset ──────────────────────────────────────────────────────────────
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
        "break_points":       {"opportunities": 84, "converted": 38},
        "break_points_saved": {"faced": 72, "saved": 46},
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
        "break_points_saved": {"faced": 68, "saved": 44},
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

# Surface-to-tournament mapping.
# Hard courts split into "Hard (Outdoor)" and "Hard (Indoor)".
# Existing "Hard" entries kept for backwards compat; analytics.py
# falls back from the sub-type to "Hard" when player records don't
# carry the variant yet.
TOURNAMENT_SURFACES: dict[str, str] = {
    # Clay
    "Roland Garros":      "Clay",
    "French Open":        "Clay",
    "Monte-Carlo":        "Clay",
    "Madrid Open":        "Clay",
    "Italian Open":       "Clay",
    "Rome":               "Clay",
    "Barcelona Open":     "Clay",
    # Grass
    "Wimbledon":          "Grass",
    "Queen's Club":       "Grass",
    "Halle":              "Grass",
    # Hard (legacy parent key — player records use "Hard")
    "US Open":            "Hard",
    "Australian Open":    "Hard",
    "Miami Open":         "Hard",
    "Indian Wells":       "Hard",
    # Hard (Outdoor)
    "Cincinnati Masters": "Hard (Outdoor)",
    "Canada Masters":     "Hard (Outdoor)",
    "Stuttgart":          "Hard (Outdoor)",
    # Hard (Indoor)
    "ATP Finals":         "Hard (Indoor)",
    "Paris Masters":      "Hard (Indoor)",
    "Vienna Open":        "Hard (Indoor)",
    "Rotterdam":          "Hard (Indoor)",
    "Marseille":          "Hard (Indoor)",
}

# Reverse map: lowercase tournament keywords → surface.
# Used by _infer_surface() when mapping raw API league names.
_LEAGUE_SURFACE_HINTS: dict[str, str] = {
    "roland garros": "Clay", "french open": "Clay",
    "monte": "Clay", "madrid": "Clay", "rome": "Clay",
    "italian": "Clay", "barcelona": "Clay", "clay": "Clay",
    "wimbledon": "Grass", "queen": "Grass", "halle": "Grass", "grass": "Grass",
    "australian": "Hard", "us open": "Hard",
    "miami": "Hard", "indian wells": "Hard",
    "cincinnati": "Hard (Outdoor)", "canada": "Hard (Outdoor)",
    "atp finals": "Hard (Indoor)", "paris": "Hard (Indoor)",
    "vienna": "Hard (Indoor)", "rotterdam": "Hard (Indoor)",
}


# ── RapidAPI layer ────────────────────────────────────────────────────────────

def _api_headers() -> dict:
    return {
        "x-rapidapi-key":  _RAPIDAPI_KEY,
        "x-rapidapi-host": _RAPIDAPI_HOST,
    }


def _infer_surface(league_name: str) -> str:
    """Map a raw API league/tournament name to one of our surface strings."""
    league_lower = league_name.lower()
    for keyword, surface in _LEAGUE_SURFACE_HINTS.items():
        if keyword in league_lower:
            return surface
    return "Hard"  # safe default


def _fetch_player_meta(name: str) -> Optional[tuple[str, str, int]]:
    """
    Search the API for a player by name.
    Returns (player_key, full_name, ranking) or None on any failure.
    """
    resp = _req.get(
        f"{_API_BASE}/players",
        headers=_api_headers(),
        params={"search": name, "type": "single"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    results = resp.json().get("result") or []
    if not results:
        return None
    hit = results[0]
    key      = str(hit.get("player_key") or "")
    fullname = str(hit.get("player_name") or name)
    ranking  = int(hit.get("player_rank") or 0)
    return (key, fullname, ranking) if key else None


def _fetch_recent_matches(player_key: str, full_name: str) -> list[dict]:
    """
    Fetch the last _RECENT_LIMIT finished matches for a player from the API.
    Returns a list in our internal match-dict format.
    """
    resp = _req.get(
        f"{_API_BASE}/matches",
        headers=_api_headers(),
        params={"player_key": player_key, "status": "finished"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    raw_matches = resp.json().get("result") or []

    matches: list[dict] = []
    player_lower = full_name.lower()

    for m in raw_matches:
        if len(matches) >= _RECENT_LIMIT:
            break

        home = str(m.get("event_home_team") or "")
        away = str(m.get("event_away_team") or "")
        winner_side = str(m.get("event_winner") or "")

        is_home = player_lower in home.lower()
        opponent = away if is_home else home

        if winner_side == "Home":
            result = "W" if is_home else "L"
        elif winner_side == "Away":
            result = "L" if is_home else "W"
        else:
            continue  # skip matches without a clear result

        # Duration: try several field names the API may use
        raw_dur = (
            m.get("event_time")
            or m.get("match_duration")
            or m.get("event_length")
        )
        try:
            duration = max(30, int(raw_dur))
        except (TypeError, ValueError):
            duration = 95  # sensible default when API omits it

        surface = _infer_surface(str(m.get("league_name") or ""))

        matches.append({
            "opponent":    opponent or "Unknown",
            "duration_min": duration,
            "result":      result,
            "surface":     surface,
        })

    return matches


def _fetch_live_player(name: str) -> Optional[dict]:
    """
    Full live-fetch pipeline:
      1. Search player → get key + full_name + ranking
      2. Fetch last 3 matches
      3. Merge onto the mock base-record (preserves surface_records,
         break_points, tiebreaks which the free API tier doesn't expose)

    Returns a merged player dict with '_data_source': 'live', or None on
    any error so the caller can fall back to mock data.
    """
    if not _RAPIDAPI_KEY or not _REQUESTS_OK:
        return None

    cache_key = name.lower()
    if cache_key in _LIVE_CACHE:
        return _LIVE_CACHE[cache_key]

    try:
        meta = _fetch_player_meta(name)
        if meta is None:
            return None
        player_key, full_name, ranking = meta

        recent = _fetch_recent_matches(player_key, full_name)
        if not recent:
            return None  # no matches → live data not useful

        # Base: use the mock record for fields the API doesn't cover,
        # then overlay the fresh live values.
        mock_key = _fuzzy_match(name)
        base = dict(PLAYERS[mock_key]) if mock_key else {}

        live_record = {
            **base,
            "full_name":      full_name,
            "ranking":        ranking or base.get("ranking", 0),
            "recent_matches": recent,
            "_data_source":   "live",
        }

        _LIVE_CACHE[cache_key] = live_record
        return live_record

    except Exception as exc:
        warnings.warn(
            f"[TennisIQ] RapidAPI fetch failed for '{name}': {exc!r}. "
            "Falling back to mock data.",
            RuntimeWarning,
            stacklevel=2,
        )
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def get_player(name: str) -> dict:
    """
    Return a player data dict for analytics.

    Tries the RapidAPI live feed first; falls back to the built-in mock
    dataset on any failure.  Raises ValueError only when the name can't be
    matched at all (live + mock both miss).
    """
    # 1. Try live
    live = _fetch_live_player(name)
    if live is not None:
        return live

    # 2. Fall back to mock
    key = _fuzzy_match(name)
    if key is None:
        raise ValueError(
            f"Player '{name}' not found. "
            f"Available players: {', '.join(PLAYERS.keys())}"
        )
    record = dict(PLAYERS[key])
    record.setdefault("_data_source", "mock")
    return record


def list_players() -> list[str]:
    """Return the list of player short-keys from the mock dataset."""
    return list(PLAYERS.keys())


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fuzzy_match(name: str) -> Optional[str]:
    """Case-insensitive partial match against PLAYERS keys and full_names."""
    name_lower = name.lower()
    # Exact key match first
    for key in PLAYERS:
        if key.lower() == name_lower:
            return key
    # Partial match on key or full_name
    for key, data in PLAYERS.items():
        if name_lower in key.lower() or name_lower in data["full_name"].lower():
            return key
    return None
