# news_pipeline/nba_social.py

import json
import logging
import os
import re
from datetime import date, timedelta

from openai import OpenAI  # xAI uses the same SDK interface as OpenAI

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

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.x.ai/v1",
    )

    today = date.today()
    yesterday = today - timedelta(days=1)

    # Explicit date strings — Grok needs these to anchor to the right day.
    # Do NOT use relative terms like "yesterday" alone; Grok can misinterpret
    # the reference frame and pull stale data or hallucinate game results
    # from training data instead of live X posts.
    today_str = today.strftime("%B %-d, %Y")
    yesterday_str = yesterday.strftime("%B %-d, %Y")

    prompt = f"""
Today's date is {today_str}. Search X (Twitter) specifically for posts made on {yesterday_str}.

Important: every game result, player name, and storyline you return must be verifiable \
from X posts dated {yesterday_str}. Do not infer, extrapolate, or fill gaps with training data.

Never use vague references like "a star player" or "a contending team." Always name the \
specific player, team, and game. If you cannot identify specific names from X posts on \
{yesterday_str}, omit that item entirely rather than generalizing.

The NBA trade deadline has already passed for the 2025-26 season. Do not include trade \
rumors or trade deadline content.

Do the following:

1. Check if the Houston Rockets played an NBA game on {yesterday_str}.
   - If yes: summarize what fans and analysts on X are saying about the game.
     Include the final score, 2-3 reactions (paraphrased, not verbatim quotes),
     and the overall sentiment (positive / negative / mixed).
   - If no game was played: set rockets_buzz to null.

2. Check if the Chicago Bulls played an NBA game on {yesterday_str}.
   - Same format as above.
   - If no game was played: set bulls_buzz to null.

3. Summarize the 2-3 most-discussed NBA storylines on X from {yesterday_str}
   that are NOT about the Rockets or Bulls.
   These could be a standout performance, injury news, controversy, or playoff
   standings movement generating significant discussion.
   For each item: if you are not confident it actually happened on {yesterday_str}
   based on real X posts, omit it. Return fewer items rather than speculating.
   An empty league_buzz array is acceptable.

Important: only report on games and events that actually occurred on {yesterday_str}.
Do not pull in results from other dates. If you are uncertain whether a game occurred,
set that team's field to null rather than guessing.

Return ONLY valid JSON. No markdown, no code fences, no explanation — raw JSON only.

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
        response = client.chat.completions.create(
            model="grok-2-1212",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,  # low temp = more factual, less hallucination risk
        )

        raw = response.choices[0].message.content.strip()
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
