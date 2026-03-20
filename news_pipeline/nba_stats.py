"""Fetch real NBA box-score data via nba_api.

All public functions are wrapped in try/except so the caller can fall back
to ESPN RSS headlines when the NBA stats API is unavailable or slow.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Team helpers
# ---------------------------------------------------------------------------

TEAM_FULL_NAMES: dict[str, str] = {
    "ATL": "Hawks", "BOS": "Celtics", "BKN": "Nets", "CHA": "Hornets",
    "CHI": "Bulls", "CLE": "Cavaliers", "DAL": "Mavericks", "DEN": "Nuggets",
    "DET": "Pistons", "GSW": "Warriors", "HOU": "Rockets", "IND": "Pacers",
    "LAC": "Clippers", "LAL": "Lakers", "MEM": "Grizzlies", "MIA": "Heat",
    "MIL": "Bucks", "MIN": "Timberwolves", "NOP": "Pelicans", "NYK": "Knicks",
    "OKC": "Thunder", "ORL": "Magic", "PHI": "76ers", "PHX": "Suns",
    "POR": "Trail Blazers", "SAC": "Kings", "SAS": "Spurs", "TOR": "Raptors",
    "UTA": "Jazz", "WAS": "Wizards",
}

TEAM_CITY_NAMES: dict[str, str] = {
    "ATL": "Atlanta", "BOS": "Boston", "BKN": "Brooklyn", "CHA": "Charlotte",
    "CHI": "Chicago", "CLE": "Cleveland", "DAL": "Dallas", "DEN": "Denver",
    "DET": "Detroit", "GSW": "Golden State", "HOU": "Houston", "IND": "Indiana",
    "LAC": "LA Clippers", "LAL": "LA Lakers", "MEM": "Memphis", "MIA": "Miami",
    "MIL": "Milwaukee", "MIN": "Minnesota", "NOP": "New Orleans", "NYK": "New York",
    "OKC": "Oklahoma City", "ORL": "Orlando", "PHI": "Philadelphia", "PHX": "Phoenix",
    "POR": "Portland", "SAC": "Sacramento", "SAS": "San Antonio", "TOR": "Toronto",
    "UTA": "Utah", "WAS": "Washington",
}


def is_rockets_or_bulls(team_abbr: str) -> bool:
    return team_abbr in {"HOU", "CHI"}


# ---------------------------------------------------------------------------
# Data-fetching functions
# ---------------------------------------------------------------------------

def get_yesterday_games() -> list[dict[str, Any]]:
    """Fetch all NBA games played yesterday via ScoreboardV2."""
    try:
        from nba_api.stats.endpoints import scoreboardv2

        # Use local time for "yesterday" — NBA games air in US timezones,
        # so UTC midnight can land on the wrong date.
        yesterday = datetime.now().date() - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")
        logger.info("Fetching NBA scoreboard for %s", date_str)

        board = scoreboardv2.ScoreboardV2(
            game_date=date_str,
            league_id="00",
            timeout=15,
        )
        data = board.get_dict()

        # Parse GameHeader for game IDs and team IDs
        game_header = _find_result_set(data, "GameHeader")
        line_score = _find_result_set(data, "LineScore")

        if not game_header or not line_score:
            logger.warning("ScoreboardV2 returned no GameHeader or LineScore data")
            return []

        # Build a lookup: game_id -> list of team rows from LineScore
        team_rows_by_game: dict[str, list[dict]] = {}
        ls_headers = line_score["headers"]
        for row in line_score["rowSet"]:
            row_dict = dict(zip(ls_headers, row))
            gid = str(row_dict.get("GAME_ID", ""))
            team_rows_by_game.setdefault(gid, []).append(row_dict)

        games: list[dict[str, Any]] = []
        seen_game_ids: set[str] = set()
        gh_headers = game_header["headers"]
        for row in game_header["rowSet"]:
            gh = dict(zip(gh_headers, row))
            game_id = str(gh.get("GAME_ID", ""))
            if game_id in seen_game_ids:
                continue
            seen_game_ids.add(game_id)

            teams = team_rows_by_game.get(game_id, [])
            if len(teams) < 2:
                continue

            # LineScore rows: first row = visitor, second row = home
            visitor, home = teams[0], teams[1]
            games.append({
                "game_id": game_id,
                "home_team": home.get("TEAM_NAME", ""),
                "away_team": visitor.get("TEAM_NAME", ""),
                "home_abbr": home.get("TEAM_ABBREVIATION", ""),
                "away_abbr": visitor.get("TEAM_ABBREVIATION", ""),
                "home_score": int(home.get("PTS", 0) or 0),
                "away_score": int(visitor.get("PTS", 0) or 0),
            })

        logger.info("Found %d games for %s", len(games), date_str)
        return games

    except Exception as exc:
        logger.warning("nba_api ScoreboardV2 failed — %s: %s", type(exc).__name__, exc)
        return []


def get_box_score(game_id: str) -> list[dict[str, Any]]:
    """Fetch player box-score stats for a single game (V3 endpoint)."""
    try:
        from nba_api.stats.endpoints import boxscoretraditionalv3

        box = boxscoretraditionalv3.BoxScoreTraditionalV3(
            game_id=game_id,
            timeout=15,
        )
        data = box.get_dict()
        bs = data.get("boxScoreTraditional", {})

        players: list[dict[str, Any]] = []
        for team_key in ("homeTeam", "awayTeam"):
            team_data = bs.get(team_key, {})
            team_abbr = team_data.get("teamTricode", "")
            for p in team_data.get("players", []):
                stats = p.get("statistics", {})
                minutes_raw = stats.get("minutes", "0") or "0"
                if isinstance(minutes_raw, str) and ":" in minutes_raw:
                    minutes = int(minutes_raw.split(":")[0])
                else:
                    minutes = int(float(minutes_raw or 0))

                if minutes == 0:
                    continue  # Skip DNPs

                name = f"{p.get('firstName', '')} {p.get('familyName', '')}".strip()
                players.append({
                    "player_name": name or "Unknown",
                    "name_short": p.get("nameI", name),
                    "team_abbr": team_abbr,
                    "points": int(stats.get("points", 0) or 0),
                    "rebounds": int(stats.get("reboundsTotal", 0) or 0),
                    "assists": int(stats.get("assists", 0) or 0),
                    "steals": int(stats.get("steals", 0) or 0),
                    "blocks": int(stats.get("blocks", 0) or 0),
                    "fg_made": int(stats.get("fieldGoalsMade", 0) or 0),
                    "fg_attempted": int(stats.get("fieldGoalsAttempted", 0) or 0),
                    "minutes": minutes,
                })

        return players

    except Exception as exc:
        logger.warning("nba_api BoxScore failed for game %s — %s: %s", game_id, type(exc).__name__, exc)
        return []


# ---------------------------------------------------------------------------
# Scoring / analysis
# ---------------------------------------------------------------------------

def score_player_performance(player: dict[str, Any]) -> float:
    """Compute a single performance score for ranking who had the best game."""
    pts = player.get("points", 0)
    reb = player.get("rebounds", 0)
    ast = player.get("assists", 0)
    stl = player.get("steals", 0)
    blk = player.get("blocks", 0)
    fga = player.get("fg_attempted", 0)
    fgm = player.get("fg_made", 0)
    return pts + (reb * 1.2) + (ast * 1.5) + (stl * 2) + (blk * 2) - ((fga - fgm) * 0.5)


def get_top_performer(
    box_score: list[dict[str, Any]],
    team_abbr: str | None = None,
) -> dict[str, Any] | None:
    """Return the player with the highest performance score, optionally filtered by team."""
    candidates = box_score
    if team_abbr:
        candidates = [p for p in box_score if p.get("team_abbr") == team_abbr]
    if not candidates:
        return None
    return max(candidates, key=score_player_performance)


def _is_big_performance(player: dict[str, Any]) -> bool:
    """Check if a player hit any big-performance threshold."""
    pts = player.get("points", 0)
    ast = player.get("assists", 0)
    blk = player.get("blocks", 0)
    stl = player.get("steals", 0)
    reb = player.get("rebounds", 0)

    if pts >= 35:
        return True
    if ast >= 12:
        return True
    if blk >= 5:
        return True
    if stl >= 5:
        return True
    # Triple-double: 10+ in three of pts/reb/ast
    double_digits = sum(1 for v in [pts, reb, ast] if v >= 10)
    if double_digits >= 3:
        return True
    return False


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def get_yesterday_nba_summary() -> dict[str, Any]:
    """Fetch yesterday's NBA results, box scores, and big performances.

    Returns a dict with keys:
        rockets_bulls_games, all_games, big_performances
    Returns empty dict on failure.
    """
    try:
        games = get_yesterday_games()
        if not games:
            logger.info("No NBA games found for yesterday")
            return {}

        all_games: list[dict[str, Any]] = []
        rockets_bulls_games: list[dict[str, Any]] = []
        big_performances: list[dict[str, Any]] = []

        for i, game in enumerate(games):
            if i > 0:
                time.sleep(0.6)  # Rate-limit between API calls

            game_id = game["game_id"]
            box_score = get_box_score(game_id)

            top = get_top_performer(box_score)
            game_entry = {**game, "box_score": box_score, "top_performer": top}
            all_games.append(game_entry)

            # Check for Rockets / Bulls involvement
            if is_rockets_or_bulls(game["home_abbr"]) or is_rockets_or_bulls(game["away_abbr"]):
                rockets_bulls_games.append(game_entry)

            # Check for big individual performances
            for player in box_score:
                if _is_big_performance(player):
                    big_performances.append(player)

        logger.info(
            "NBA summary: %d games, %d Rockets/Bulls games, %d big performances",
            len(all_games),
            len(rockets_bulls_games),
            len(big_performances),
        )

        return {
            "rockets_bulls_games": rockets_bulls_games,
            "all_games": all_games,
            "big_performances": big_performances,
        }

    except Exception as exc:
        logger.warning("get_yesterday_nba_summary failed — %s: %s", type(exc).__name__, exc)
        return {}


# ---------------------------------------------------------------------------
# Redis-compatible shape for the iOS app
# ---------------------------------------------------------------------------

def get_nba_game_stats() -> dict | None:
    """
    Wrapper around get_yesterday_nba_summary() that returns the Redis-compatible shape.
    Called by cron_pipeline.py and saved to briefing:nba_stats.
    """
    from datetime import date, timedelta
    yesterday = date.today() - timedelta(days=1)
    data_date = f"{yesterday.strftime('%B')} {yesterday.day}, {yesterday.year}"

    try:
        summary = get_yesterday_nba_summary()
        if not summary:
            logger.error("[nba_stats] get_yesterday_nba_summary() returned empty/None")
            return None

        # Build all_games list
        all_games = []
        for game in summary.get("all_games", []):
            top = game.get("top_performer")
            all_games.append({
                "home_team": game["home_abbr"],
                "away_team": game["away_abbr"],
                "home_score": game["home_score"],
                "away_score": game["away_score"],
                "top_scorer": {
                    "name": top["player_name"],
                    "pts": top["points"],
                    "reb": top["rebounds"],
                    "ast": top["assists"],
                } if top else None,
            })

        # Rockets game detail
        rockets_game: dict = {"played": False}
        for game in summary.get("rockets_bulls_games", []):
            if game["home_abbr"] == "HOU" or game["away_abbr"] == "HOU":
                is_home = game["home_abbr"] == "HOU"
                my_score = game["home_score"] if is_home else game["away_score"]
                opp_score = game["away_score"] if is_home else game["home_score"]
                opp_abbr = game["away_abbr"] if is_home else game["home_abbr"]
                box = game.get("box_score", [])
                top_players = [
                    {"name": p["player_name"], "pts": p["points"], "reb": p["rebounds"], "ast": p["assists"]}
                    for p in sorted(
                        [r for r in box if r.get("team_abbr") == "HOU"],
                        key=lambda x: x.get("minutes", 0), reverse=True
                    )[:5]
                ]
                rockets_game = {
                    "played": True,
                    "opponent": opp_abbr,
                    "score": f"{my_score}-{opp_score}",
                    "result": "win" if my_score > opp_score else "loss",
                    "top_players": top_players,
                }
                break

        # Bulls game detail
        bulls_game: dict = {"played": False}
        for game in summary.get("rockets_bulls_games", []):
            if game["home_abbr"] == "CHI" or game["away_abbr"] == "CHI":
                is_home = game["home_abbr"] == "CHI"
                my_score = game["home_score"] if is_home else game["away_score"]
                opp_score = game["away_score"] if is_home else game["home_score"]
                opp_abbr = game["away_abbr"] if is_home else game["home_abbr"]
                box = game.get("box_score", [])
                top_players = [
                    {"name": p["player_name"], "pts": p["points"], "reb": p["rebounds"], "ast": p["assists"]}
                    for p in sorted(
                        [r for r in box if r.get("team_abbr") == "CHI"],
                        key=lambda x: x.get("minutes", 0), reverse=True
                    )[:5]
                ]
                bulls_game = {
                    "played": True,
                    "opponent": opp_abbr,
                    "score": f"{my_score}-{opp_score}",
                    "result": "win" if my_score > opp_score else "loss",
                    "top_players": top_players,
                }
                break

        # Notable performances
        notable = []
        for p in summary.get("big_performances", [])[:10]:
            pts = p.get("points", 0)
            reb = p.get("rebounds", 0)
            ast = p.get("assists", 0)
            triple_double = pts >= 10 and reb >= 10 and ast >= 10
            if triple_double:
                note = "Triple-double"
            elif pts >= 30:
                note = "30+ points"
            elif reb >= 20:
                note = "20+ rebounds"
            else:
                note = "15+ assists"
            notable.append({
                "player": p["player_name"],
                "team": p.get("team_abbr", ""),
                "pts": pts, "reb": reb, "ast": ast,
                "note": note,
            })

        standings = _get_standings()

        logger.info(
            "[nba_stats] get_nba_game_stats success — %d games, %d notable, "
            "rockets played: %s, bulls played: %s",
            len(all_games), len(notable),
            rockets_game.get("played"), bulls_game.get("played"),
        )
        return {
            "all_games": all_games,
            "notable_performances": notable,
            "rockets_game": rockets_game,
            "bulls_game": bulls_game,
            "standings": standings,
            "data_date": data_date,
        }

    except Exception as exc:
        logger.error("[nba_stats] get_nba_game_stats FAILED — %s: %s", type(exc).__name__, exc)
        return None


def _get_standings() -> list[dict] | None:
    """Fetch current NBA standings via LeagueStandingsV3."""
    try:
        from nba_api.stats.endpoints import leaguestandingsv3
        standings_ep = leaguestandingsv3.LeagueStandingsV3(
            season="2024-25", timeout=30
        )
        df = standings_ep.get_data_frames()[0]
        rows = []
        for _, row in df.iterrows():
            abbr = row.get("TeamAbbreviation", "")
            conference = "West" if str(row.get("Conference", "")).upper().startswith("W") else "East"
            rows.append({
                "team": abbr,
                "conference": conference,
                "rank": int(row.get("PlayoffRank", 0)),
                "wins": int(row.get("WINS", 0)),
                "losses": int(row.get("LOSSES", 0)),
            })
        rows.sort(key=lambda r: (r["conference"], r["rank"]))
        logger.info("[nba_stats] Standings loaded — %d teams", len(rows))
        return rows if rows else None
    except Exception as exc:
        logger.warning("[nba_stats] Standings fetch failed — %s: %s", type(exc).__name__, exc)
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_result_set(data: dict, name: str) -> dict | None:
    """Find a named resultSet in the nba_api response dict."""
    for rs in data.get("resultSets", []):
        if rs.get("name") == name:
            return rs
    return None
