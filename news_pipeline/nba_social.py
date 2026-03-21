# news_pipeline/nba_social.py

import json
import logging
import os
import re
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)


def get_nba_social_buzz(rockets_game: dict | None = None, bulls_game: dict | None = None) -> dict | None:
    """
    Calls the Grok API to synthesize X/Twitter discourse about last night's NBA games.

    Checks specifically for Rockets and Bulls games, plus league-wide storylines.
    Returns structured JSON or None if the call fails.

    Requires env var: GROK_API_KEY
    """
    api_key = os.environ.get("GROK_API_KEY")
    if not api_key:
        logger.warning("[nba_social] GROK_API_KEY not set — skipping social buzz")
        return None

    today = date.today()
    yesterday = today - timedelta(days=1)

    # Explicit date strings — Grok needs these to anchor to the right day.
    # Do NOT use relative terms like "yesterday" alone; Grok can misinterpret
    # the reference frame and pull stale data or hallucinate game results
    # from training data instead of live X posts.
    today_str = today.strftime("%B %-d, %Y")
    yesterday_str = yesterday.strftime("%B %-d, %Y")

    # Build confirmed game context from ESPN stats (authoritative — never override these)
    def _game_line(game: dict | None, team: str) -> str:
        if not game or not game.get("played"):
            return f"- {team}: did NOT play on {yesterday_str}."
        opp = game.get("opponent", "unknown opponent")
        score = game.get("score", "?-?")
        result = game.get("result", "unknown")
        return (f"- {team}: PLAYED on {yesterday_str}. "
                f"{'Won' if result == 'win' else 'Lost'} to {opp}, final score {score}. "
                f"This is a confirmed ESPN fact — do NOT change the score or result.")

    confirmed_block = ""
    if rockets_game or bulls_game:
        confirmed_block = f"""
CONFIRMED GAME DATA (from official ESPN box score — treat as ground truth):
{_game_line(rockets_game, 'Houston Rockets')}
{_game_line(bulls_game, 'Chicago Bulls')}

For any team marked as PLAYED above, you MUST populate their buzz object — do NOT return null.
Search X specifically for fan reactions to that confirmed result.
If X posts are sparse (game ended recently), still populate the section using the confirmed score and whatever reactions you can find.
"""

    prompt = f"""
Today is {today_str}. Search X (Twitter) for NBA posts from {yesterday_str} and {today_str}.
{confirmed_block}

Use your x_search tool to find posts about:
- The Houston Rockets game on {yesterday_str}
- The Chicago Bulls game on {yesterday_str}
- The top NBA storylines from {yesterday_str}

Then return ONLY a raw JSON object in exactly this format — no markdown, no prose, no explanation.

Rules:
- Use specific player names, teams, and scores from what you find on X. Never use vague language like "a star player."
- The "score" field MUST be the verified official final score. Search for posts from @NBAcom, @ESPN, or the official team accounts (@HoustonRockets, @ChicagoBulls) to confirm the exact final score. Do NOT use fan posts or in-game score updates — only the confirmed final.
- If a team played on {yesterday_str}, you MUST populate their buzz object with the score, opponent, result, sentiment, and 5-6 distinct topics covering different angles of the game. Do NOT set to null if they played.
- Only set rockets_buzz or bulls_buzz to null if that team had no game scheduled on {yesterday_str}.
- Each topic covers a specific angle: the overall result reaction, a key player's performance, a controversial moment or call, playoff/standings implications, coaching decisions, etc.
- league_buzz must contain 4-5 items about other teams — there is always NBA news worth reporting. Good angles: standout performances, MVP/award races, injury news, trade rumors, anything generating significant X volume.
- Do not include trade deadline content (deadline has passed for 2025-26).
- Each summary must be 2-3 sentences synthesizing what X is saying about that specific angle.

JSON format:
{{
  "rockets_buzz": {{
    "played": true,
    "opponent": "Team Name",
    "score": "112-108",
    "result": "win",
    "sentiment": "positive",
    "topics": [
      {{
        "topic": "Sengun dominates the paint",
        "summary": "X is calling this Sengun's best two-way game of the season. Several accounts noted he held AD to 4-for-12 in the post while dropping 24/11/4. The consensus is this was a statement game for his MVP-adjacent case."
      }},
      {{
        "topic": "Jalen Green's clutch factor",
        "summary": "Fans are split on whether Green's fourth-quarter performance finally proves he can be trusted in close games. A minority of accounts pushed back, arguing the Lakers simply ran out of gas."
      }},
      {{
        "topic": "Playoff seeding implications",
        "summary": "With the win, Houston moves to 5th in the West and cuts the gap to 4th to just one game. X is buzzing about a potential top-4 finish and home court advantage in the first round."
      }}
    ]
  }},
  "bulls_buzz": null,
  "league_buzz": [
    {{
      "topic": "SGA's MVP case after 40-point night",
      "summary": "After torching Orlando for 40, X is back to full SGA vs Jokic debate mode. Most analysts are leaning SGA given OKC's record. A few contrarian takes still argue Jokic's efficiency wins the argument."
    }},
    {{
      "topic": "Short topic label",
      "summary": "2-3 sentence summary of what people are saying on X about this storyline"
    }}
  ],
  "data_date": "{yesterday_str}"
}}

If rockets_buzz or bulls_buzz is null because no game was played, use JSON null (not the string "null").
"""

    try:
        resp = httpx.post(
            "https://api.x.ai/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "grok-4-fast-non-reasoning",
                "input": [{"role": "user", "content": prompt}],
                "tools": [{"type": "x_search"}],
                "temperature": 0.2,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        x_calls = data.get("usage", {}).get("server_side_tool_usage_details", {}).get("x_search_calls", 0)
        logger.info(f"[nba_social] Grok made {x_calls} X search calls")

        # Extract text from the final assistant message in the output list
        message = next(
            (item for item in reversed(data.get("output", []))
             if item.get("type") == "message" and item.get("role") == "assistant"),
            None,
        )
        if not message:
            logger.error("[nba_social] No assistant message in Grok response")
            return None

        raw = message["content"][0]["text"].strip()
        logger.info(f"[nba_social] Raw Grok response:\n{raw}")

        # Strip any accidental markdown fences Grok might add despite instructions
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        result = json.loads(raw)
        logger.info(f"[nba_social] Grok buzz fetched for {yesterday_str}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"[nba_social] Failed to parse Grok response as JSON: {e}")
        logger.error(f"[nba_social] Raw response was: {raw[:500]}")
        return None

    except Exception as e:
        logger.error(f"[nba_social] Grok API call failed: {e}")
        return None
