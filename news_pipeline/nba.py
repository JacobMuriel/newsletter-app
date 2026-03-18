"""Build the NBA Brief section using real box-score data from nba_api.

Falls back to ESPN RSS headline parsing if the stats API is unavailable.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from news_pipeline.models import NBABrief, Story
from news_pipeline.nba_stats import (
    TEAM_CITY_NAMES,
    TEAM_FULL_NAMES,
    get_top_performer,
    get_yesterday_nba_summary,
    is_rockets_or_bulls,
    score_player_performance,
)

logger = logging.getLogger(__name__)

# Hard gate kept for ESPN-RSS fallback path
_NBA_IDENTITY_PATTERN = re.compile(
    r"\b(nba|basketball|hoops|nba\s+playoffs?|nba\s+finals?|nba\s+game|nba\s+season|"
    r"wembanyama|jokic|doncic|giannis|embiid|sengun|vucevic|morant|"
    r"lebron\s+james|stephen\s+curry|steph\s+curry|jayson\s+tatum|jalen\s+brunson|"
    r"jalen\s+green|demar\s+derozan|zach\s+lavine|coby\s+white|amen\s+thompson|"
    r"reed\s+sheppard|cam\s+whitmore|kevin\s+durant|luka\s+doncic|"
    r"eastern\s+conference\s+(?:standings|finals?|playoffs?)|"
    r"western\s+conference\s+(?:standings|finals?|playoffs?))\b",
    re.I,
)


def build_nba_brief(stories: list[Story], max_items_per_bucket: int = 3) -> NBABrief | None:
    """Build NBA brief from real box-score data, falling back to ESPN RSS."""
    # Try nba_api first
    summary = get_yesterday_nba_summary()
    if summary:
        return _build_from_api(summary, max_items_per_bucket)

    # Fallback to ESPN RSS headlines
    logger.info("nba_api unavailable, falling back to ESPN RSS for NBA brief")
    return _build_from_rss(stories, max_items_per_bucket)


# ---------------------------------------------------------------------------
# Primary path: real box-score data from nba_api
# ---------------------------------------------------------------------------

def _build_from_api(summary: dict[str, Any], max_items: int) -> NBABrief:
    brief = NBABrief()

    # --- Rockets & Bulls recaps ---
    for game in summary.get("rockets_bulls_games", [])[:max_items]:
        recap = _format_game_recap_sentence(game)
        brief.rockets_bulls_recaps.append(recap)

        # Top performer stat line for the favorite team
        box = game.get("box_score", [])
        for abbr in ("HOU", "CHI"):
            top = get_top_performer(box, team_abbr=abbr)
            if top:
                line = _format_stat_line(top)
                brief.rockets_bulls_performers.append(line)

    # --- Big performances league-wide ---
    seen_names: set[str] = set()
    for player in summary.get("big_performances", []):
        name = player.get("player_name", "")
        if name in seen_names:
            continue
        seen_names.add(name)
        brief.big_performances.append(_format_stat_line(player))

    # --- All other game recaps ---
    rb_game_ids = {g["game_id"] for g in summary.get("rockets_bulls_games", [])}
    for game in summary.get("all_games", []):
        if game["game_id"] in rb_game_ids:
            continue  # Already covered in Rockets & Bulls section
        brief.game_recaps.append(_format_game_score_line(game))

    brief.source_names = ["nba_api (stats.nba.com)"]
    return brief


def _format_game_recap_sentence(game: dict[str, Any]) -> str:
    """Build a 2-sentence game recap from box score data."""
    home_abbr = game["home_abbr"]
    away_abbr = game["away_abbr"]
    home_score = game["home_score"]
    away_score = game["away_score"]

    home_city = TEAM_CITY_NAMES.get(home_abbr, home_abbr)
    away_city = TEAM_CITY_NAMES.get(away_abbr, away_abbr)
    home_name = TEAM_FULL_NAMES.get(home_abbr, home_abbr)
    away_name = TEAM_FULL_NAMES.get(away_abbr, away_abbr)

    if home_score > away_score:
        winner_city, winner_name = home_city, home_name
        loser_city, loser_name = away_city, away_name
        w_score, l_score = home_score, away_score
        winner_abbr = home_abbr
    else:
        winner_city, winner_name = away_city, away_name
        loser_city, loser_name = home_city, home_name
        w_score, l_score = away_score, home_score
        winner_abbr = away_abbr

    sentence1 = f"The {winner_name} defeated the {loser_name} {w_score}-{l_score}."

    # Find top performer for the winning team
    box = game.get("box_score", [])
    top = get_top_performer(box, team_abbr=winner_abbr)
    if top:
        sentence2 = (
            f"{top['player_name']} led {winner_city} with "
            f"{top['points']} pts, {top['rebounds']} reb, {top['assists']} ast."
        )
    else:
        sentence2 = ""

    return f"{sentence1} {sentence2}".strip()


def _format_stat_line(player: dict[str, Any]) -> str:
    """Format a player stat line: 'Nikola Jokic — 38 pts, 14 reb, 9 ast (DEN)'"""
    name = player.get("player_name", "Unknown")
    abbr = player.get("team_abbr", "")
    pts = player.get("points", 0)
    reb = player.get("rebounds", 0)
    ast = player.get("assists", 0)
    return f"{name} — {pts} pts, {reb} reb, {ast} ast ({abbr})"


def _format_game_score_line(game: dict[str, Any]) -> str:
    """Format: 'HOU 118, LAL 104 — Top: A. Sengun 24/11/4'"""
    home = game["home_abbr"]
    away = game["away_abbr"]
    hs = game["home_score"]
    aws = game["away_score"]

    # Winner first
    if hs >= aws:
        score_part = f"{home} {hs}, {away} {aws}"
    else:
        score_part = f"{away} {aws}, {home} {hs}"

    top = game.get("top_performer")
    if top:
        short_name = top.get("name_short", top.get("player_name", "?"))
        top_part = f"Top: {short_name} {top['points']}/{top['rebounds']}/{top['assists']}"
        return f"{score_part} — {top_part}"
    return score_part


# ---------------------------------------------------------------------------
# Fallback path: ESPN RSS headlines (existing logic)
# ---------------------------------------------------------------------------

def _build_from_rss(stories: list[Story], max_items: int) -> NBABrief | None:
    if not stories:
        return None

    ordered = sorted(
        stories,
        key=lambda s: (
            s.importance_score,
            s.latest_published_at.timestamp() if s.latest_published_at else 0.0,
        ),
        reverse=True,
    )
    brief = NBABrief()

    for story in ordered:
        combined_text = f"{story.title} {story.cleaned_summary}"
        if not _NBA_IDENTITY_PATTERN.search(combined_text):
            continue

        line = _to_bullet(story.newsletter_blurb or story.confirmed_facts or story.title)

        if len(brief.game_recaps) < max_items:
            brief.game_recaps.append(line)

    if not brief.game_recaps:
        brief.game_recaps = [
            _to_bullet(s.newsletter_blurb or s.confirmed_facts or s.title)
            for s in ordered[:max_items]
        ]

    brief.game_recaps = _unique(brief.game_recaps)
    brief.source_names = _unique(item for story in ordered for item in story.source_names)
    return brief


def _to_bullet(text: str) -> str:
    cleaned = " ".join(text.split()).strip().rstrip(".")
    return cleaned + "."


def _unique(items) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
