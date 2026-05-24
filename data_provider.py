"""
Mock data provider for tennis player statistics.

Each player entry contains:
- recent_matches: last 3 matches with duration in minutes and result
- surface_records: win/loss per surface
- break_points: faced and saved/converted for ClutchFactor
- tiebreaks: played and won for ClutchFactor
"""

PLAYERS = {
    "Sinner": {
        "full_name": "Jannik Sinner",
        "ranking": 1,
        "recent_matches": [
            {"opponent": "Medvedev", "duration_min": 142, "result": "W", "surface": "Hard"},
            {"opponent": "Zverev", "duration_min": 178, "result": "W", "surface": "Clay"},
            {"opponent": "Rune", "duration_min": 95, "result": "W", "surface": "Clay"},
        ],
        "surface_records": {
            "Clay":  {"wins": 38, "losses": 12},
            "Hard":  {"wins": 61, "losses": 14},
            "Grass": {"wins": 18, "losses":  9},
        },
        "break_points": {"opportunities": 84, "converted": 38},
        "break_points_saved": {"faced": 72, "saved": 46},
        "tiebreaks": {"played": 34, "won": 22},
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
        "break_points": {"opportunities": 96, "converted": 48},
        "break_points_saved": {"faced": 68, "saved": 44},
        "tiebreaks": {"played": 38, "won": 23},
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
            "Clay":  {"wins": 93, "losses": 28},
            "Hard":  {"wins": 158, "losses": 39},
            "Grass": {"wins": 87,  "losses": 14},
        },
        "break_points": {"opportunities": 210, "converted": 98},
        "break_points_saved": {"faced": 178, "saved": 128},
        "tiebreaks": {"played": 124, "won": 82},
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
        "break_points": {"opportunities": 88, "converted": 36},
        "break_points_saved": {"faced": 94, "saved": 58},
        "tiebreaks": {"played": 52, "won": 29},
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
        "break_points": {"opportunities": 102, "converted": 44},
        "break_points_saved": {"faced": 86, "saved": 50},
        "tiebreaks": {"played": 46, "won": 24},
    },
    "Rune": {
        "full_name": "Holger Rune",
        "ranking": 14,
        "recent_matches": [
            {"opponent": "Sinner",  "duration_min": 95,  "result": "L", "surface": "Clay"},
            {"opponent": "Zverev",  "duration_min": 112, "result": "L", "surface": "Clay"},
            {"opponent": "Tsitsipas", "duration_min": 138, "result": "W", "surface": "Clay"},
        ],
        "surface_records": {
            "Clay":  {"wins": 28, "losses": 14},
            "Hard":  {"wins": 22, "losses": 18},
            "Grass": {"wins":  8, "losses":  9},
        },
        "break_points": {"opportunities": 64, "converted": 28},
        "break_points_saved": {"faced": 58, "saved": 32},
        "tiebreaks": {"played": 24, "won": 11},
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
        "break_points": {"opportunities": 82, "converted": 34},
        "break_points_saved": {"faced": 78, "saved": 44},
        "tiebreaks": {"played": 36, "won": 16},
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
        "break_points": {"opportunities": 72, "converted": 30},
        "break_points_saved": {"faced": 64, "saved": 36},
        "tiebreaks": {"played": 28, "won": 12},
    },
}

# Surface-to-tournament mapping.
# Hard courts are now split into "Hard (Outdoor)" and "Hard (Indoor)" as
# requested by Elena. Existing entries keep "Hard" for backwards compat;
# surface_win_rate() in analytics.py falls back from the specific variant
# to the parent "Hard" when a player's records don't carry the sub-type yet.
TOURNAMENT_SURFACES = {
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
    # Hard (legacy — player records use "Hard" as the parent key)
    "US Open":            "Hard",
    "Australian Open":    "Hard",
    "Miami Open":         "Hard",
    "Indian Wells":       "Hard",
    # Hard (Outdoor) — new sub-type
    "Cincinnati Masters": "Hard (Outdoor)",
    "Canada Masters":     "Hard (Outdoor)",
    "Stuttgart":          "Hard (Outdoor)",
    # Hard (Indoor) — new sub-type
    "ATP Finals":         "Hard (Indoor)",
    "Paris Masters":      "Hard (Indoor)",
    "Vienna Open":        "Hard (Indoor)",
    "Rotterdam":          "Hard (Indoor)",
    "Marseille":          "Hard (Indoor)",
}


def get_player(name: str) -> dict:
    """Return player data by name (case-insensitive partial match)."""
    key = _fuzzy_match(name)
    if key is None:
        raise ValueError(
            f"Player '{name}' not found. Available players: {', '.join(PLAYERS.keys())}"
        )
    return PLAYERS[key]


def list_players() -> list[str]:
    return list(PLAYERS.keys())


def _fuzzy_match(name: str) -> str | None:
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
