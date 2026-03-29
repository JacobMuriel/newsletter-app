"""Fetch real NBA box-score data via ESPN's public API.

Uses ESPN's undocumented but stable public endpoints — no API key required,
works reliably in CI environments unlike stats.nba.com (which blocks GitHub
Actions IPs). All public function signatures are unchanged so nba.py works as-is.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

_ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
_ESPN_SUMMARY    = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
_ESPN_STANDINGS  = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"

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
# ESPN data-fetching
# ---------------------------------------------------------------------------

def get_yesterday_games(target_date=None) -> list[dict[str, Any]]:
    """Fetch all NBA games for a given date via ESPN scoreboard API.

    If target_date is None, defaults to yesterday (UTC).
    """
    from datetime import date as date_type
    if target_date is None:
        target_date = datetime.now().date() - timedelta(days=1)
    try:
        date_str = target_date.strftime("%Y%m%d")
        logger.info("Fetching ESPN NBA scoreboard for %s", date_str)

        resp = httpx.get(_ESPN_SCOREBOARD, params={"dates": date_str}, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        games: list[dict[str, Any]] = []
        for event in data.get("events", []):
            comp = (event.get("competitions") or [{}])[0]
            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                continue

            home = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue

            # Only include games with actual scores (skips future/postponed games)
            home_score = int(home.get("score") or 0)
            away_score = int(away.get("score") or 0)
            if home_score + away_score == 0:
                logger.info("Skipping scoreless game %s (not yet played)", event.get("id"))
                continue

            games.append({
                "game_id": event["id"],
                "home_team": home["team"].get("displayName", ""),
                "away_team": away["team"].get("displayName", ""),
                "home_abbr": home["team"].get("abbreviation", ""),
                "away_abbr": away["team"].get("abbreviation", ""),
                "home_score": home_score,
                "away_score": away_score,
            })

        logger.info("Found %d completed games for %s", len(games), date_str)
        return games

    except Exception as exc:
        logger.warning("ESPN scoreboard fetch failed — %s: %s", type(exc).__name__, exc)
        return []


def get_box_score(game_id: str) -> list[dict[str, Any]]:
    """Fetch player box-score stats for a single game via ESPN summary API."""
    try:
        resp = httpx.get(_ESPN_SUMMARY, params={"event": game_id}, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        players: list[dict[str, Any]] = []
        for team_data in data.get("boxscore", {}).get("players", []):
            team_abbr = team_data.get("team", {}).get("abbreviation", "")
            for stat_group in team_data.get("statistics", []):
                labels = stat_group.get("labels", [])
                for ath_data in stat_group.get("athletes", []):
                    athlete = ath_data.get("athlete", {})
                    stats = ath_data.get("stats", [])
                    if not stats:
                        continue

                    sd = dict(zip(labels, stats))

                    # Minutes
                    min_raw = str(sd.get("MIN", "0") or "0")
                    if ":" in min_raw:
                        minutes = int(min_raw.split(":")[0])
                    else:
                        try:
                            minutes = int(float(min_raw))
                        except ValueError:
                            minutes = 0

                    if minutes == 0:
                        continue

                    # FG (format "9-17")
                    fg_raw = str(sd.get("FG", "0-0") or "0-0")
                    try:
                        fgm, fga = [int(x) for x in fg_raw.split("-")]
                    except (ValueError, AttributeError):
                        fgm, fga = 0, 0

                    name = athlete.get("displayName", "Unknown")
                    players.append({
                        "player_name": name,
                        "name_short": athlete.get("shortName", name),
                        "team_abbr": team_abbr,
                        "points":   int(sd.get("PTS", 0) or 0),
                        "rebounds": int(sd.get("REB", 0) or 0),
                        "assists":  int(sd.get("AST", 0) or 0),
                        "steals":   int(sd.get("STL", 0) or 0),
                        "blocks":   int(sd.get("BLK", 0) or 0),
                        "fg_made":  fgm,
                        "fg_attempted": fga,
                        "minutes":  minutes,
                    })

        logger.info("game %s — %d player rows fetched", game_id, len(players))
        return players

    except Exception as exc:
        logger.warning("ESPN box score failed for game %s — %s: %s", game_id, type(exc).__name__, exc)
        return []


# ---------------------------------------------------------------------------
# Scoring / analysis  (unchanged — nba.py depends on these)
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
    candidates = box_score if not team_abbr else [p for p in box_score if p.get("team_abbr") == team_abbr]
    if not candidates:
        return None
    return max(candidates, key=score_player_performance)


def _is_big_performance(player: dict[str, Any]) -> bool:
    pts = player.get("points", 0)
    ast = player.get("assists", 0)
    blk = player.get("blocks", 0)
    stl = player.get("steals", 0)
    reb = player.get("rebounds", 0)
    minutes = player.get("minutes", 0)
    if minutes < 15:
        return False
    if pts >= 35:
        return True
    if reb >= 15:
        return True
    if ast >= 12:
        return True
    if blk >= 5 or stl >= 5:
        return True
    # Triple-double
    if pts >= 10 and reb >= 10 and ast >= 10:
        return True
    # 20/8/7 rule: sort [pts, reb, ast] descending; qualifies if [0]>=20, [1]>=8, [2]>=7
    sorted_stats = sorted([pts, reb, ast], reverse=True)
    if sorted_stats[0] >= 20 and sorted_stats[1] >= 8 and sorted_stats[2] >= 7:
        return True
    return False


# ---------------------------------------------------------------------------
# Orchestration  (unchanged signature — nba.py calls this)
# ---------------------------------------------------------------------------

def get_yesterday_nba_summary() -> dict[str, Any]:
    """Fetch yesterday's NBA results, box scores, and big performances.

    Returns a dict with keys: rockets_bulls_games, all_games, big_performances, game_date.
    Returns empty dict on failure.
    """
    try:
        yesterday = datetime.now().date() - timedelta(days=1)
        games = get_yesterday_games(yesterday)
        if not games:
            logger.info("No completed NBA games found for yesterday")
            return {}

        all_games: list[dict[str, Any]] = []
        rockets_bulls_games: list[dict[str, Any]] = []
        big_performances: list[dict[str, Any]] = []

        for i, game in enumerate(games):
            if i > 0:
                time.sleep(0.3)

            box_score = get_box_score(game["game_id"])
            top = get_top_performer(box_score)
            game_entry = {**game, "box_score": box_score, "top_performer": top}
            all_games.append(game_entry)

            if is_rockets_or_bulls(game["home_abbr"]) or is_rockets_or_bulls(game["away_abbr"]):
                rockets_bulls_games.append(game_entry)

            for player in box_score:
                if _is_big_performance(player):
                    big_performances.append(player)

        # If a featured team didn't play yesterday, look back one more day for their game
        featured_abbrs = {"HOU", "CHI"}
        found_abbrs = {g["home_abbr"] for g in rockets_bulls_games} | {g["away_abbr"] for g in rockets_bulls_games}
        missing = featured_abbrs - found_abbrs
        if missing:
            two_days_ago = yesterday - timedelta(days=1)
            logger.info("Featured teams %s not in yesterday's games — checking %s", missing, two_days_ago)
            older_games = get_yesterday_games(two_days_ago)
            for i, game in enumerate(older_games):
                if not (is_rockets_or_bulls(game["home_abbr"]) or is_rockets_or_bulls(game["away_abbr"])):
                    continue
                abbrs_in_game = {game["home_abbr"], game["away_abbr"]}
                if not (abbrs_in_game & missing):
                    continue
                time.sleep(0.3)
                box_score = get_box_score(game["game_id"])
                top = get_top_performer(box_score)
                game_entry = {**game, "box_score": box_score, "top_performer": top}
                rockets_bulls_games.append(game_entry)
                missing -= abbrs_in_game
                logger.info("Added %s fallback game from %s", abbrs_in_game & featured_abbrs, two_days_ago)

        logger.info(
            "NBA summary: %d games, %d Rockets/Bulls, %d big performances",
            len(all_games), len(rockets_bulls_games), len(big_performances),
        )
        return {
            "rockets_bulls_games": rockets_bulls_games,
            "all_games": all_games,
            "big_performances": big_performances,
            "game_date": yesterday,
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
    try:
        summary = get_yesterday_nba_summary()
        if not summary:
            logger.error("[nba_stats] get_yesterday_nba_summary() returned empty — no games or fetch failed")
            return None

        game_date = summary.get("game_date") or (datetime.now().date() - timedelta(days=1))
        data_date = f"{game_date.strftime('%B')} {game_date.day}, {game_date.year}"

        # all_games
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
                    "pts":  top["points"],
                    "reb":  top["rebounds"],
                    "ast":  top["assists"],
                } if top else None,
            })

        # Rockets
        rockets_game: dict = {"played": False}
        for game in summary.get("rockets_bulls_games", []):
            if game["home_abbr"] == "HOU" or game["away_abbr"] == "HOU":
                is_home = game["home_abbr"] == "HOU"
                my_score  = game["home_score"] if is_home else game["away_score"]
                opp_score = game["away_score"] if is_home else game["home_score"]
                opp_abbr  = game["away_abbr"]  if is_home else game["home_abbr"]
                box = game.get("box_score", [])
                top_players = [
                    {"name": p["player_name"], "pts": p["points"], "reb": p["rebounds"], "ast": p["assists"]}
                    for p in sorted(
                        [r for r in box if r.get("team_abbr") == "HOU"],
                        key=lambda x: x.get("minutes", 0), reverse=True
                    )[:5]
                ]
                rockets_game = {
                    "played": True, "opponent": opp_abbr,
                    "score": f"{my_score}-{opp_score}",
                    "result": "win" if my_score > opp_score else "loss",
                    "top_players": top_players,
                }
                break

        # Bulls
        bulls_game: dict = {"played": False}
        for game in summary.get("rockets_bulls_games", []):
            if game["home_abbr"] == "CHI" or game["away_abbr"] == "CHI":
                is_home = game["home_abbr"] == "CHI"
                my_score  = game["home_score"] if is_home else game["away_score"]
                opp_score = game["away_score"] if is_home else game["home_score"]
                opp_abbr  = game["away_abbr"]  if is_home else game["home_abbr"]
                box = game.get("box_score", [])
                top_players = [
                    {"name": p["player_name"], "pts": p["points"], "reb": p["rebounds"], "ast": p["assists"]}
                    for p in sorted(
                        [r for r in box if r.get("team_abbr") == "CHI"],
                        key=lambda x: x.get("minutes", 0), reverse=True
                    )[:5]
                ]
                bulls_game = {
                    "played": True, "opponent": opp_abbr,
                    "score": f"{my_score}-{opp_score}",
                    "result": "win" if my_score > opp_score else "loss",
                    "top_players": top_players,
                }
                break

        # Notable performances
        notable = []
        for p in summary.get("big_performances", [])[:10]:
            pts, reb, ast = p.get("points", 0), p.get("rebounds", 0), p.get("assists", 0)
            blk = p.get("blocks", 0)
            stl = p.get("steals", 0)
            triple_double = pts >= 10 and reb >= 10 and ast >= 10
            note = ("Triple-double" if triple_double else
                    "35+ points"    if pts >= 35   else
                    "30+ points"    if pts >= 30   else
                    "15+ rebounds"  if reb >= 15   else
                    "12+ assists"   if ast >= 12   else
                    "5+ blocks"     if blk >= 5    else
                    "5+ steals"     if stl >= 5    else
                    "Big game")
            notable.append({
                "player": p["player_name"], "team": p.get("team_abbr", ""),
                "pts": pts, "reb": reb, "ast": ast, "note": note,
            })

        standings = _get_standings()

        logger.info(
            "[nba_stats] success — %d games, %d notable, rockets=%s, bulls=%s",
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


def get_today_nba_summary() -> dict:
    """Fetch today's NBA slate from ESPN and compute team summaries + notable performances
    for any completed games. Single ESPN + box score pass.

    Returns:
      {
        "games": [...],                  # one per game, with status/scores/top_scorer
        "rockets_summary": {...},        # same shape as rockets_game in get_nba_game_stats(); played=False if no final game today
        "bulls_summary": {...},          # same
        "notable_performances": [...],   # big performances from today's completed games
      }
    """
    ct_tz = ZoneInfo("America/Chicago")
    today_str = datetime.now().strftime("%Y%m%d")
    empty = {
        "games": [],
        "rockets_summary": {"played": False},
        "bulls_summary": {"played": False},
        "notable_performances": [],
    }
    try:
        logger.info("Fetching ESPN NBA scoreboard for %s", today_str)
        resp = httpx.get(_ESPN_SCOREBOARD, params={"dates": today_str}, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        games: list[dict] = []
        rockets_summary: dict = {"played": False}
        bulls_summary: dict = {"played": False}
        notable: list[dict] = []
        box_score_index = 0  # track delay between box score calls

        for event in data.get("events", []):
            comp = (event.get("competitions") or [{}])[0]
            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                continue

            home = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue

            game_id = event["id"]
            home_abbr = home["team"].get("abbreviation", "")
            away_abbr = away["team"].get("abbreviation", "")
            home_score = int(home.get("score") or 0)
            away_score = int(away.get("score") or 0)

            status_obj = comp.get("status", {})
            status_type = status_obj.get("type", {}).get("name", "")

            if status_type == "STATUS_FINAL":
                status = "final"
            elif status_type in ("STATUS_IN_PROGRESS", "STATUS_HALFTIME"):
                status = "live"
            else:
                status = "upcoming"

            quarter: str | None = None
            clock: str | None = None
            start_time_ct: str | None = None
            top_scorer: dict | None = None

            if status == "upcoming":
                raw_date = event.get("date", "")
                try:
                    dt_utc = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    dt_ct = dt_utc.astimezone(ct_tz)
                    start_time_ct = dt_ct.strftime("%-I:%M %p CT")
                except Exception:
                    start_time_ct = None

            elif status in ("live", "final"):
                if status == "live":
                    period = status_obj.get("period", 0)
                    display_clock = status_obj.get("displayClock", "")
                    quarter = "Half" if status_type == "STATUS_HALFTIME" else (f"Q{period}" if period else None)
                    clock = display_clock or None
                else:
                    quarter = "Final"

                # Fetch box score (one call covers top_scorer + team detail + big perfs)
                if box_score_index > 0:
                    time.sleep(0.3)
                box_score = get_box_score(game_id)
                box_score_index += 1

                top = get_top_performer(box_score)
                if top:
                    top_scorer = {"name": top["player_name"], "pts": top["points"],
                                  "reb": top["rebounds"], "ast": top["assists"]}

                # For final games: build team summaries + notable performances
                if status == "final":
                    if (home_abbr == "HOU" or away_abbr == "HOU") and not rockets_summary.get("played"):
                        is_home = home_abbr == "HOU"
                        my_score  = home_score if is_home else away_score
                        opp_score = away_score if is_home else home_score
                        top_players = [
                            {"name": p["player_name"], "pts": p["points"], "reb": p["rebounds"], "ast": p["assists"]}
                            for p in sorted(
                                [r for r in box_score if r.get("team_abbr") == "HOU"],
                                key=lambda x: x.get("minutes", 0), reverse=True
                            )[:5]
                        ]
                        rockets_summary = {
                            "played": True, "opponent": away_abbr if is_home else home_abbr,
                            "score": f"{my_score}-{opp_score}",
                            "result": "win" if my_score > opp_score else "loss",
                            "top_players": top_players,
                        }

                    if (home_abbr == "CHI" or away_abbr == "CHI") and not bulls_summary.get("played"):
                        is_home = home_abbr == "CHI"
                        my_score  = home_score if is_home else away_score
                        opp_score = away_score if is_home else home_score
                        top_players = [
                            {"name": p["player_name"], "pts": p["points"], "reb": p["rebounds"], "ast": p["assists"]}
                            for p in sorted(
                                [r for r in box_score if r.get("team_abbr") == "CHI"],
                                key=lambda x: x.get("minutes", 0), reverse=True
                            )[:5]
                        ]
                        bulls_summary = {
                            "played": True, "opponent": away_abbr if is_home else home_abbr,
                            "score": f"{my_score}-{opp_score}",
                            "result": "win" if my_score > opp_score else "loss",
                            "top_players": top_players,
                        }

                    for player in box_score:
                        if _is_big_performance(player):
                            pts, reb, ast = player.get("points", 0), player.get("rebounds", 0), player.get("assists", 0)
                            blk, stl = player.get("blocks", 0), player.get("steals", 0)
                            triple_double = pts >= 10 and reb >= 10 and ast >= 10
                            note = ("Triple-double" if triple_double else
                                    "35+ points"    if pts >= 35   else
                                    "30+ points"    if pts >= 30   else
                                    "15+ rebounds"  if reb >= 15   else
                                    "12+ assists"   if ast >= 12   else
                                    "5+ blocks"     if blk >= 5    else
                                    "5+ steals"     if stl >= 5    else
                                    "Big game")
                            notable.append({
                                "player": player["player_name"], "team": player.get("team_abbr", ""),
                                "pts": pts, "reb": reb, "ast": ast, "note": note,
                            })

            games.append({
                "game_id": game_id,
                "home_team": home_abbr,
                "away_team": away_abbr,
                "home_score": home_score if status != "upcoming" else None,
                "away_score": away_score if status != "upcoming" else None,
                "status": status,
                "quarter": quarter,
                "clock": clock,
                "start_time_ct": start_time_ct,
                "top_scorer": top_scorer,
            })

        logger.info("get_today_nba_summary: %d games, rockets=%s, bulls=%s, %d notable",
                    len(games), rockets_summary.get("played"), bulls_summary.get("played"), len(notable))
        return {
            "games": games,
            "rockets_summary": rockets_summary,
            "bulls_summary": bulls_summary,
            "notable_performances": notable[:10],
        }

    except Exception as exc:
        logger.warning("get_today_nba_summary failed — %s: %s", type(exc).__name__, exc)
        return empty


def get_today_games() -> list[dict]:
    """Thin wrapper around get_today_nba_summary() — returns just the games list.
    Used by /nba/social/live for status checks."""
    return get_today_nba_summary()["games"]


def get_team_roster_and_injuries(team_abbr: str) -> dict[str, Any] | None:
    """Fetch current roster and injury status for a team from ESPN's public roster endpoint.

    Returns:
      {
        "active":  ["Player Name", ...],               # players with no injury designation
        "injured": [{"name": "...", "status": "Out"}, ...]
      }
    Returns None on failure so the caller can fall back gracefully.
    """
    try:
        url = (
            f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
            f"/teams/{team_abbr.lower()}/roster"
        )
        resp = httpx.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        active: list[str] = []
        injured: list[dict[str, str]] = []

        for athlete in data.get("athletes", []):
            name = athlete.get("displayName", "")
            if not name:
                continue
            injuries = athlete.get("injuries", [])
            if injuries:
                # The first entry is the current designation (Out, Day-To-Day, etc.)
                status = injuries[0].get("status", "Injured")
                injured.append({"name": name, "status": status})
            else:
                active.append(name)

        logger.info(
            "[nba_stats] %s roster: %d active, %d injured/out",
            team_abbr, len(active), len(injured),
        )
        return {"active": active, "injured": injured}

    except Exception as exc:
        logger.warning(
            "[nba_stats] Roster fetch failed for %s — %s: %s",
            team_abbr, type(exc).__name__, exc,
        )
        return None


def _get_standings() -> list[dict] | None:
    """Fetch current NBA standings via ESPN standings API."""
    try:
        resp = httpx.get(_ESPN_STANDINGS, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        rows = []
        for conference in data.get("children", []):
            conf_name = conference.get("abbreviation", "")
            conf_label = "West" if "west" in conf_name.lower() or "west" in conference.get("name", "").lower() else "East"
            for entry in conference.get("standings", {}).get("entries", []):
                abbr = entry.get("team", {}).get("abbreviation", "")
                stats = {s["name"]: s.get("value", 0) for s in entry.get("stats", [])}
                rows.append({
                    "team": abbr,
                    "conference": conf_label,
                    "rank": int(stats.get("playoffSeed", 0)),
                    "wins": int(stats.get("wins", 0)),
                    "losses": int(stats.get("losses", 0)),
                })

        rows.sort(key=lambda r: (r["conference"], r["rank"]))
        logger.info("[nba_stats] Standings loaded — %d teams", len(rows))
        return rows if rows else None

    except Exception as exc:
        logger.warning("[nba_stats] Standings fetch failed — %s: %s", type(exc).__name__, exc)
        return None
