"""
scripts/seed_nba_stats.py

Writes hardcoded-but-realistic NBA stats data directly to Redis.
Use this to verify the iOS app renders NBAStatsCard and StandingsCard
without depending on nba_api succeeding.

Usage:
    UPSTASH_REDIS_REST_URL=... UPSTASH_REDIS_REST_TOKEN=... python scripts/seed_nba_stats.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


TEST_NBA_STATS = {
    "all_games": [
        {"home_team": "HOU", "away_team": "LAL", "home_score": 118, "away_score": 104,
         "top_scorer": {"name": "Alperen Sengun", "pts": 26, "reb": 12, "ast": 5}},
        {"home_team": "BOS", "away_team": "NYK", "home_score": 112, "away_score": 108,
         "top_scorer": {"name": "Jayson Tatum", "pts": 34, "reb": 8, "ast": 6}},
        {"home_team": "CHI", "away_team": "MIL", "home_score": 99, "away_score": 115,
         "top_scorer": {"name": "Giannis Antetokounmpo", "pts": 38, "reb": 14, "ast": 7}},
        {"home_team": "DEN", "away_team": "OKC", "home_score": 121, "away_score": 116,
         "top_scorer": {"name": "Nikola Jokic", "pts": 31, "reb": 15, "ast": 11}},
    ],
    "rockets_game": {
        "played": True,
        "opponent": "LAL",
        "score": "118-104",
        "result": "win",
        "top_players": [
            {"name": "Alperen Sengun", "pts": 26, "reb": 12, "ast": 5},
            {"name": "Jalen Green", "pts": 22, "reb": 4, "ast": 6},
            {"name": "Amen Thompson", "pts": 14, "reb": 9, "ast": 3},
            {"name": "Fred VanVleet", "pts": 12, "reb": 3, "ast": 7},
            {"name": "Dillon Brooks", "pts": 10, "reb": 3, "ast": 1},
        ],
    },
    "bulls_game": {
        "played": True,
        "opponent": "MIL",
        "score": "99-115",
        "result": "loss",
        "top_players": [
            {"name": "Zach LaVine", "pts": 24, "reb": 5, "ast": 4},
            {"name": "Nikola Vucevic", "pts": 18, "reb": 11, "ast": 2},
            {"name": "Coby White", "pts": 16, "reb": 3, "ast": 5},
            {"name": "Patrick Williams", "pts": 9, "reb": 6, "ast": 1},
            {"name": "Josh Giddey", "pts": 8, "reb": 5, "ast": 4},
        ],
    },
    "notable_performances": [
        {"player": "Nikola Jokic", "team": "DEN", "pts": 31, "reb": 15, "ast": 11, "note": "Triple-double"},
        {"player": "Jayson Tatum", "team": "BOS", "pts": 34, "reb": 8, "ast": 6, "note": "30+ points"},
        {"player": "Giannis Antetokounmpo", "team": "MIL", "pts": 38, "reb": 14, "ast": 7, "note": "30+ points"},
    ],
    "standings": [
        {"team": "OKC", "conference": "West", "rank": 1, "wins": 58, "losses": 15},
        {"team": "HOU", "conference": "West", "rank": 2, "wins": 52, "losses": 21},
        {"team": "LAL", "conference": "West", "rank": 3, "wins": 49, "losses": 24},
        {"team": "MEM", "conference": "West", "rank": 4, "wins": 46, "losses": 27},
        {"team": "MIN", "conference": "West", "rank": 5, "wins": 44, "losses": 29},
        {"team": "DEN", "conference": "West", "rank": 6, "wins": 43, "losses": 30},
        {"team": "GSW", "conference": "West", "rank": 7, "wins": 38, "losses": 35},
        {"team": "LAC", "conference": "West", "rank": 8, "wins": 36, "losses": 37},
        {"team": "BOS", "conference": "East", "rank": 1, "wins": 55, "losses": 18},
        {"team": "CLE", "conference": "East", "rank": 2, "wins": 52, "losses": 21},
        {"team": "NYK", "conference": "East", "rank": 3, "wins": 48, "losses": 25},
        {"team": "MIL", "conference": "East", "rank": 4, "wins": 45, "losses": 28},
        {"team": "IND", "conference": "East", "rank": 5, "wins": 43, "losses": 30},
        {"team": "MIA", "conference": "East", "rank": 6, "wins": 40, "losses": 33},
        {"team": "ATL", "conference": "East", "rank": 7, "wins": 36, "losses": 37},
        {"team": "CHI", "conference": "East", "rank": 8, "wins": 34, "losses": 39},
    ],
    "data_date": "March 19, 2026",
}


def main():
    from news_pipeline.redis_cache import save_nba_stats_cache, load_nba_stats_cache

    print("Writing test NBA stats to Redis...")
    save_nba_stats_cache(TEST_NBA_STATS)

    print("Verifying write...")
    result = load_nba_stats_cache()
    if result:
        print(f"SUCCESS — {len(result['all_games'])} games, "
              f"rockets played={result['rockets_game']['played']}, "
              f"bulls played={result['bulls_game']['played']}, "
              f"standings={len(result.get('standings', []))} teams")
    else:
        print("FAILED — could not read back from Redis")
        sys.exit(1)


if __name__ == "__main__":
    main()
