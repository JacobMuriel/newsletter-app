"""
nba_stats.py — Fetches yesterday's NBA game stats from BallDontLie API v1.

Free tier, no auth required. Uses httpx (already in requirements).

Public API: get_nba_game_stats() -> dict | None
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)

BALLDONTLIE_BASE = "https://www.balldontlie.io/api/v1"
ROCKETS_TEAM_ID = 14
BULLS_TEAM_ID = 4


def get_nba_game_stats() -> dict | None:
    """
    Fetches yesterday's NBA game data from BallDontLie.
    Returns a structured dict or None on failure.
    Never fails silently — all errors are logged before returning None.
    """
    yesterday = date.today() - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    data_date = f"{yesterday.strftime('%B')} {yesterday.day}, {yesterday.year}"

    try:
        with httpx.Client(timeout=20.0) as client:
            result = _fetch_all(client, yesterday_str, data_date)
            if result is None:
                logger.error("[nba_stats] get_nba_game_stats returning None — see errors above")
            else:
                logger.info(
                    "[nba_stats] get_nba_game_stats success — %d games, %d notable performances",
                    len(result.get("all_games", [])),
                    len(result.get("notable_performances", [])),
                )
            return result
    except Exception as exc:
        logger.error("[nba_stats] get_nba_game_stats FAILED — %s: %s", type(exc).__name__, exc)
        return None


def _fetch_all(client: httpx.Client, date_str: str, data_date: str) -> dict | None:
    # 1. All games from yesterday
    resp = client.get(f"{BALLDONTLIE_BASE}/games", params={"dates[]": date_str})
    if resp.status_code != 200:
        logger.error("[nba_stats] GET /games returned %d — cannot fetch stats", resp.status_code)
        return None

    games = resp.json().get("data", [])
    logger.info("[nba_stats] Found %d games on %s", len(games), date_str)

    if not games:
        logger.info("[nba_stats] No NBA games on %s — returning empty result", date_str)
        return {
            "all_games": [],
            "notable_performances": [],
            "rockets_game": {"played": False},
            "bulls_game": {"played": False},
            "data_date": data_date,
        }

    # 2. Per-game player stats (one request per game)
    game_stats: dict[int, list] = {}
    for game in games:
        gid = game["id"]
        sresp = client.get(
            f"{BALLDONTLIE_BASE}/stats",
            params={"game_ids[]": gid, "per_page": 100},
        )
        if sresp.status_code == 200:
            rows = sresp.json().get("data", [])
            game_stats[gid] = rows
            logger.info("[nba_stats] game %d — %d player stat rows fetched", gid, len(rows))
        else:
            logger.warning(
                "[nba_stats] GET /stats for game %d returned %d — skipping that game's stats",
                gid, sresp.status_code,
            )
            game_stats[gid] = []

    all_stats = [s for rows in game_stats.values() for s in rows]

    # 3. Build all_games list; identify Rockets and Bulls games
    rockets_game: dict = {"played": False}
    bulls_game: dict = {"played": False}
    all_games: list[dict] = []

    for game in games:
        gid = game["id"]
        home_id = game["home_team"]["id"]
        away_id = game["visitor_team"]["id"]
        home_abbr = game["home_team"]["abbreviation"]
        away_abbr = game["visitor_team"]["abbreviation"]
        home_score = game.get("home_team_score") or 0
        away_score = game.get("visitor_team_score") or 0

        g_stats = game_stats.get(gid, [])
        all_games.append({
            "home_team": home_abbr,
            "away_team": away_abbr,
            "home_score": home_score,
            "away_score": away_score,
            "top_scorer": _top_scorer(g_stats),
        })

        # Rockets
        if home_id == ROCKETS_TEAM_ID or away_id == ROCKETS_TEAM_ID:
            is_home = home_id == ROCKETS_TEAM_ID
            my_score = home_score if is_home else away_score
            opp_score = away_score if is_home else home_score
            opp_abbr = away_abbr if is_home else home_abbr
            rockets_game = {
                "played": True,
                "opponent": opp_abbr,
                "score": f"{my_score}-{opp_score}",
                "result": "win" if my_score > opp_score else "loss",
                "record": None,
                "conference_rank": None,
                "top_players": _team_top_players(g_stats, ROCKETS_TEAM_ID),
            }
            logger.info(
                "[nba_stats] Rockets game found — %s vs %s, %d-%d (%s)",
                "HOU", opp_abbr, my_score, opp_score,
                rockets_game["result"],
            )

        # Bulls
        if home_id == BULLS_TEAM_ID or away_id == BULLS_TEAM_ID:
            is_home = home_id == BULLS_TEAM_ID
            my_score = home_score if is_home else away_score
            opp_score = away_score if is_home else home_score
            opp_abbr = away_abbr if is_home else home_abbr
            bulls_game = {
                "played": True,
                "opponent": opp_abbr,
                "score": f"{my_score}-{opp_score}",
                "result": "win" if my_score > opp_score else "loss",
                "record": None,
                "conference_rank": None,
                "top_players": _team_top_players(g_stats, BULLS_TEAM_ID),
            }
            logger.info(
                "[nba_stats] Bulls game found — CHI vs %s, %d-%d (%s)",
                opp_abbr, my_score, opp_score, bulls_game["result"],
            )

    # 4. Notable performances across all games
    notable = _notable_performances(all_stats)
    logger.info("[nba_stats] %d notable performances found", len(notable))

    # 5. Standings (best-effort; free tier may not support this endpoint)
    _try_standings(client, rockets_game, bulls_game)

    return {
        "all_games": all_games,
        "notable_performances": notable,
        "rockets_game": rockets_game,
        "bulls_game": bulls_game,
        "data_date": data_date,
    }


def _top_scorer(stats: list) -> dict | None:
    """Return the player with the most points in the given stat rows."""
    scored = [s for s in stats if (s.get("pts") or 0) > 0]
    if not scored:
        return None
    top = max(scored, key=lambda s: s.get("pts") or 0)
    return {
        "name": f"{top['player']['first_name']} {top['player']['last_name']}",
        "pts": top.get("pts") or 0,
        "reb": top.get("reb") or 0,
        "ast": top.get("ast") or 0,
    }


def _team_top_players(stats: list, team_id: int) -> list[dict]:
    """Return up to 5 players from team_id sorted by minutes played."""
    team_stats = [s for s in stats if s.get("team", {}).get("id") == team_id]
    team_stats.sort(key=lambda s: _parse_min(s.get("min", "")), reverse=True)
    result = []
    for s in team_stats[:5]:
        result.append({
            "name": f"{s['player']['first_name']} {s['player']['last_name']}",
            "pts": s.get("pts") or 0,
            "reb": s.get("reb") or 0,
            "ast": s.get("ast") or 0,
            "stl": s.get("stl") or 0,
            "blk": s.get("blk") or 0,
        })
    return result


def _parse_min(min_str: str) -> float:
    """Parse '32:15' or '32' into a float for sorting."""
    if not min_str:
        return 0.0
    if ":" in min_str:
        parts = min_str.split(":", 1)
        try:
            return int(parts[0]) + int(parts[1]) / 60
        except ValueError:
            return 0.0
    try:
        return float(min_str)
    except ValueError:
        return 0.0


def _notable_performances(all_stats: list) -> list[dict]:
    """
    Find players with 30+ pts, 20+ reb, 15+ ast, or a triple-double.
    Returns up to 10, deduplicated by player, sorted by pts descending.
    """
    candidates: list[dict] = []
    for s in all_stats:
        pts = s.get("pts") or 0
        reb = s.get("reb") or 0
        ast = s.get("ast") or 0
        triple_double = pts >= 10 and reb >= 10 and ast >= 10

        if not (triple_double or pts >= 30 or reb >= 20 or ast >= 15):
            continue

        # Most impressive note wins (triple-double > 30pts > 20reb > 15ast)
        if triple_double:
            note = "Triple-double"
        elif pts >= 30:
            note = "30+ points"
        elif reb >= 20:
            note = "20+ rebounds"
        else:
            note = "15+ assists"

        candidates.append({
            "player": f"{s['player']['first_name']} {s['player']['last_name']}",
            "team": s.get("team", {}).get("abbreviation", ""),
            "pts": pts,
            "reb": reb,
            "ast": ast,
            "note": note,
        })

    # Deduplicate: keep highest-pts entry per player, then sort
    seen: dict[str, dict] = {}
    for c in sorted(candidates, key=lambda x: x["pts"], reverse=True):
        if c["player"] not in seen:
            seen[c["player"]] = c
    return list(seen.values())[:10]


def _try_standings(client: httpx.Client, rockets_game: dict, bulls_game: dict) -> None:
    """
    Attempt to fetch standings and inject record/conference_rank into team dicts.
    Modifies rockets_game and bulls_game in-place.
    Logs a warning (not error) if the endpoint is unavailable on the free tier.
    """
    try:
        resp = client.get(f"{BALLDONTLIE_BASE}/standings", params={"season": 2024})
        if resp.status_code != 200:
            logger.warning(
                "[nba_stats] GET /standings returned %d — standings unavailable on this tier, skipping",
                resp.status_code,
            )
            return

        for entry in resp.json().get("data", []):
            team_id = entry.get("team", {}).get("id")
            wins = entry.get("wins", 0)
            losses = entry.get("losses", 0)
            rank = entry.get("conference_rank") or entry.get("rank")
            record = f"{wins}-{losses}"

            if team_id == ROCKETS_TEAM_ID:
                rockets_game["record"] = record
                rockets_game["conference_rank"] = rank
                logger.info("[nba_stats] Rockets standings: %s rank %s", record, rank)
            elif team_id == BULLS_TEAM_ID:
                bulls_game["record"] = record
                bulls_game["conference_rank"] = rank
                logger.info("[nba_stats] Bulls standings: %s rank %s", record, rank)

        logger.info("[nba_stats] Standings fetch complete")
    except Exception as exc:
        logger.warning("[nba_stats] Standings fetch failed — %s: %s", type(exc).__name__, exc)
