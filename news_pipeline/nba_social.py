# news_pipeline/nba_social.py

import json
import logging
import os
import re
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)


def get_nba_social_buzz() -> dict | None:
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

    prompt = f"""
Today is {today_str}. Search X (Twitter) for NBA posts from {yesterday_str} and {today_str}.

Use your x_search tool to find posts about:
- The Houston Rockets game on {yesterday_str}
- The Chicago Bulls game on {yesterday_str}
- The top NBA storylines from {yesterday_str}

Then return ONLY a raw JSON object in exactly this format — no markdown, no prose, no explanation.

Rules:
- Use specific player names, teams, and scores from what you find on X. Never use vague language like "a star player."
- If a team played on {yesterday_str}, you MUST populate their buzz object with the score, opponent, result, sentiment, and 2-3 paraphrased fan/analyst reactions. Do NOT set to null if they played.
- Only set rockets_buzz or bulls_buzz to null if that team had no game scheduled on {yesterday_str}.
- league_buzz must contain 2-3 items about other teams — there is always NBA news worth reporting.
- Do not include trade deadline content (deadline has passed for 2025-26).

JSON format:
{{
  "rockets_buzz": {{
    "played": true,
    "opponent": "Team Name",
    "score": "112-108",
    "result": "win",
    "sentiment": "positive",
    "reactions": [
      "Paraphrased fan or analyst reaction 1",
      "Paraphrased fan or analyst reaction 2",
      "Paraphrased hot take or notable comment"
    ]
  }},
  "bulls_buzz": {{
    "played": true,
    "opponent": "Team Name",
    "score": "98-104",
    "result": "loss",
    "sentiment": "negative",
    "reactions": [
      "Paraphrased reaction 1",
      "Paraphrased reaction 2",
      "Paraphrased reaction 3"
    ]
  }},
  "league_buzz": [
    {{
      "topic": "Short topic label",
      "summary": "2-3 sentence summary of what fans and analysts are saying on X"
    }},
    {{
      "topic": "Short topic label",
      "summary": "2-3 sentence summary"
    }}
  ],
  "data_date": "{yesterday_str}"
}}

{{
  "rockets_buzz": {{
    "played": true,
    "opponent": "Team Name",
    "score": "112-108",
    "result": "win",
    "sentiment": "positive",
    "reactions": [
      "Paraphrased fan or analyst reaction 1",
      "Paraphrased fan or analyst reaction 2",
      "Paraphrased hot take or notable comment"
    ]
  }},
  "bulls_buzz": {{
    "played": true,
    "opponent": "Team Name",
    "score": "98-104",
    "result": "loss",
    "sentiment": "negative",
    "reactions": [
      "Paraphrased reaction 1",
      "Paraphrased reaction 2",
      "Paraphrased reaction 3"
    ]
  }},
  "league_buzz": [
    {{
      "topic": "Short topic label",
      "summary": "2-3 sentence summary of what people are saying on X about this storyline"
    }},
    {{
      "topic": "Short topic label",
      "summary": "2-3 sentence summary"
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
