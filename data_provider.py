"""
Data provider for TennisIQ Analytics.

Data-source ladder — evaluated in order on every call:
  1. api-sports.io live  — schedule + player data   (requires APISPORTS_KEY env var)
  2. Mock fallback       — static dataset + sample fixtures, always available

Two independent caches live at module level:
  _LIVE_CACHE      — player dicts,  keyed by name.lower()
  _SCHEDULE_CACHE  — fixture lists, keyed by "date|tournament_id"

Both caches survive Streamlit rerenders within a single session and are
cleared automatically when the process restarts (deploy / dyno restart).

Every public return value carries a '_data_source' key ("live" or "mock")
so app.py can render a status badge without touching analytics.py.

API: api-sports.io Tennis
  Register free (no credit card) at: https://dashboard.api-sports.io/register
  Base URL: https://v1.tennis.api-sports.io
  Auth header: x-apisports-key: <YOUR_KEY>
  Free plan: 100 requests / day
"""

import json
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
# Host: v1.tennis.api-sports.io  (api-sports.io Tennis)
#   Register free at: https://dashboard.api-sports.io/register
#   Endpoint used for schedule:  GET /games?date=YYYY-MM-DD
#   Endpoint used for players:   GET /players?search=NAME
_API_HOST = "v1.tennis.api-sports.io"
_API_BASE = f"https://{_API_HOST}"
_TIMEOUT  = 8    # seconds
_RECENT_LIMIT = 3  # recent matches to pull per player

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

# ── Real dataset overlay ──────────────────────────────────────────────────────
# players_data.json (generato da build_dataset.py sui match ATP reali di
# Sackmann) sovrascrive i mock qui sopra. Se il file non esiste, il tool resta
# funzionante con gli 8 giocatori d'esempio finche' non lo si genera.
_DATASET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "players_data.json")
# "sackmann" quando i record provengono dal dataset reale, "mock" altrimenti.
STATIC_DATA_SOURCE = "mock"


def _load_real_dataset() -> None:
    global STATIC_DATA_SOURCE
    if not os.path.exists(_DATASET_PATH):
        return
    try:
        with open(_DATASET_PATH, encoding="utf-8") as fh:
            real = json.load(fh)
    except Exception as exc:
        warnings.warn(f"[TennisIQ] players_data.json illeggibile: {exc!r}. Uso i mock.",
                      RuntimeWarning, stacklevel=2)
        return
    if isinstance(real, dict) and real:
        PLAYERS.update(real)         # i dati reali hanno la precedenza sui mock
        STATIC_DATA_SOURCE = "sackmann"


_load_real_dataset()

# Campi che analytics.compute_all() richiede sempre presenti.
_REQUIRED_PLAYER_KEYS = {
    "recent_matches":     list,
    "surface_records":    dict,
    "break_points":       lambda: {"opportunities": 0, "converted": 0},
    "break_points_saved": lambda: {"faced": 0, "saved": 0},
    "tiebreaks":          lambda: {"played": 0, "won": 0},
}


def _ensure_player_shape(record: dict) -> dict:
    """Riempie i campi mancanti con default sicuri: evita KeyError in analytics
    quando un giocatore live non ha una base mock corrispondente."""
    for key, factory in _REQUIRED_PLAYER_KEYS.items():
        if not isinstance(record.get(key), (list, dict)):
            record[key] = factory()
    record.setdefault("full_name", "Unknown")
    record.setdefault("ranking", 0)
    return record


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

# Keyword hints used by _infer_surface() to map raw API tournament names
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
    """Build request headers for api-sports.io, reading the key fresh each time."""
    return {
        "x-apisports-key": os.getenv("APISPORTS_KEY", ""),
    }


def _has_key() -> bool:
    """Return True if a non-empty API key is configured."""
    return bool(os.getenv("APISPORTS_KEY")) and _REQUESTS_OK


def _infer_surface(tournament_name: str, api_surface: str = "") -> str:
    """
    Determine surface from api-sports.io 'surface' field (preferred) or
    keyword-match the tournament name as fallback.
    """
    # api-sports.io sometimes provides surface directly on the tournament object
    if api_surface:
        s = api_surface.strip().title()
        if s in ("Clay", "Grass", "Hard", "Hard (Indoor)", "Hard (Outdoor)", "Carpet"):
            return s

    low = tournament_name.lower()
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
    tournament: str, surface: str, time_str: str,
    source: str = "live",
) -> dict:
    """Assemble a normalised fixture dict from raw API field values."""
    label = f"{_abbreviate(p1_name)} vs {_abbreviate(p2_name)}"
    return {
        "label":      label,
        "p1_name":    p1_name,
        "p1_key":     p1_key,
        "p2_name":    p2_name,
        "p2_key":     p2_key,
        "tournament": tournament or "Unknown Tournament",
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
    Hit the api-sports.io /games endpoint for not-started fixtures on a
    given date.  Returns a list of normalised fixture dicts, or None on
    any failure so get_daily_schedule() can fall back to mock data.

    api-sports.io Tennis schedule:
      GET /games?date=YYYY-MM-DD[&tournament=ID]
      Auth: x-apisports-key header
      Response:
        {
          "response": [
            {
              "id": 123,
              "date": "2025-05-28T11:00:00+00:00",
              "time": "11:00",
              "tournament": {
                "id": 1,
                "name": "Roland Garros",
                "surface": "Clay"
              },
              "teams": {
                "home": {"id": 10, "name": "Jannik Sinner"},
                "away": {"id": 20, "name": "Casper Ruud"}
              },
              "status": {"short": "NS", "long": "Not Started"}
            }
          ]
        }
    """
    if not _has_key():
        return None

    params: dict = {"date": date_str}
    if tournament_id:
        params["tournament"] = tournament_id

    try:
        resp = _req.get(
            f"{_API_BASE}/games",
            headers=_api_headers(),
            params=params,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()

        body = resp.json()
        raw  = body.get("response") or []

        fixtures: list[dict] = []
        for m in raw:
            # Skip matches that have already started or finished
            status_short = str((m.get("status") or {}).get("short") or "")
            if status_short not in ("NS", "", "TBD"):
                continue

            teams   = m.get("teams") or {}
            home    = teams.get("home") or {}
            away    = teams.get("away") or {}
            tourn   = m.get("tournament") or {}

            home_name = str(home.get("name") or "").strip()
            away_name = str(away.get("name") or "").strip()
            home_id   = str(home.get("id") or "")
            away_id   = str(away.get("id") or "")
            tourn_name = str(tourn.get("name") or "")
            api_surf   = str(tourn.get("surface") or "")
            time_str   = str(m.get("time") or "")

            if not home_name or not away_name:
                continue

            surface = _infer_surface(tourn_name, api_surf)
            fixtures.append(
                _build_fixture(
                    home_name, home_id,
                    away_name, away_id,
                    tourn_name, surface, time_str,
                )
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
        p1_key     — api-sports.io player ID (None for mock fixtures)
        p2_name    — full second-player name
        p2_key     — api-sports.io player ID (None for mock fixtures)
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
    if live:
        _SCHEDULE_CACHE[cache_key] = live
        return live

    # Fallback: return mock schedule (not cached — always fresh sample)
    return list(_MOCK_SCHEDULE)


# ── Player public API ─────────────────────────────────────────────────────────

def get_player(name: str) -> dict:
    """
    Return a player data dict suitable for analytics.compute_all().

    Tries the api-sports.io live feed first; falls back to the mock dataset.
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
    record.setdefault("_data_source", STATIC_DATA_SOURCE)
    return _ensure_player_shape(record)


def list_players() -> list[str]:
    """Player short-keys from the mock dataset (used for fallback UI only)."""
    return list(PLAYERS.keys())


# ── Player API layer ──────────────────────────────────────────────────────────

def _fetch_player_meta(name: str) -> Optional[tuple[str, str, int]]:
    """
    Search api-sports.io for a player → (player_id, full_name, ranking) or None.

    GET /players?search=NAME
    Response:
      {
        "response": [
          {
            "id": 1,
            "name": "Jannik Sinner",
            "ranking": 1,
            "country": {"name": "Italy", "code": "IT"}
          }
        ]
      }
    """
    resp = _req.get(
        f"{_API_BASE}/players",
        headers=_api_headers(),
        params={"search": name},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    body    = resp.json()
    results = body.get("response") or []
    if not results:
        return None
    hit      = results[0]
    pid      = str(hit.get("id") or "")
    fullname = str(hit.get("name") or name)
    ranking  = int(hit.get("ranking") or 0)
    return (pid, fullname, ranking) if pid else None


def _fetch_recent_matches(player_id: str, full_name: str) -> list[dict]:
    """
    Fetch last _RECENT_LIMIT finished matches for a player.

    GET /games?player=PLAYER_ID&status=FT   (api-sports.io uses "FT" = full time)
    Response:
      {
        "response": [
          {
            "teams": {
              "home": {"id": 10, "name": "Jannik Sinner"},
              "away": {"id": 20, "name": "Casper Ruud"}
            },
            "winner": {"id": 10, "name": "Jannik Sinner"},
            "scores": {...},
            "tournament": {"name": "Roland Garros", "surface": "Clay"},
            "time": "11:00"
          }
        ]
      }
    """
    resp = _req.get(
        f"{_API_BASE}/games",
        headers=_api_headers(),
        params={"player": player_id, "status": "FT"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    raw  = body.get("response") or []

    matches: list[dict] = []
    player_lower = full_name.lower()

    for m in raw:
        if len(matches) >= _RECENT_LIMIT:
            break

        teams  = m.get("teams") or {}
        home   = teams.get("home") or {}
        away   = teams.get("away") or {}
        winner = m.get("winner") or {}
        tourn  = m.get("tournament") or {}

        home_name = str(home.get("name") or "")
        away_name = str(away.get("name") or "")
        win_id    = str(winner.get("id") or "")
        home_id   = str(home.get("id") or "")
        tourn_name = str(tourn.get("name") or "")
        api_surf   = str(tourn.get("surface") or "")

        is_home  = player_lower in home_name.lower()
        opponent = away_name if is_home else home_name

        # Determine win/loss from winner id
        if not win_id or not (home_id or away_name):
            continue
        result = "W" if win_id == (home_id if is_home else str(away.get("id") or "")) else "L"

        # Duration: api-sports.io may provide it in the game body
        raw_dur = m.get("duration") or m.get("match_duration")
        try:
            duration = max(30, int(raw_dur))
        except (TypeError, ValueError):
            duration = 95

        matches.append({
            "opponent":     opponent or "Unknown",
            "duration_min": duration,
            "result":       result,
            "surface":      _infer_surface(tourn_name, api_surf),
        })

    return matches


def _fetch_live_player(name: str) -> Optional[dict]:
    """
    Full live-fetch pipeline: search → fetch matches → merge onto mock base.
    Returns player dict with '_data_source': 'live', or None on any failure.
    """
    if not _has_key():
        return None

    cache_key = name.lower()
    if cache_key in _LIVE_CACHE:
        return _LIVE_CACHE[cache_key]

    try:
        meta = _fetch_player_meta(name)
        if not meta:
            return None
        player_id, full_name, ranking = meta

        recent = _fetch_recent_matches(player_id, full_name)
        if not recent:
            return None

        mock_key = _fuzzy_match(name)
        base     = dict(PLAYERS[mock_key]) if mock_key else {}
        record   = _ensure_player_shape({
            **base,
            "full_name":      full_name,
            "ranking":        ranking or base.get("ranking", 0),
            "recent_matches": recent,
            # 'live' = calendario+forma recente dall'API; i record storici
            # (superficie, clutch) restano dal dataset se il giocatore c'e',
            # altrimenti sono vuoti (nuovo entrato non ancora nel dataset).
            "_data_source":   "live",
            "_stats_source":  base.get("_data_source", "none") if base else "none",
        })
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
