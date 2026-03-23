# news_pipeline/ai_social.py

import json
import logging
import os
import re
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)


def fetch_ai_buzz() -> dict | None:
    """
    Searches X for @cgtwts daily AI recap posts. If found, extracts their bullet-point
    headlines. Falls back to Grok generating its own terse one-liner list if @cgtwts
    hasn't posted today or yesterday.

    Returns { "items": [{"headline": "..."}], "num_sources_used": N, "date": "YYYY-MM-DD" }
    or None on failure / zero sources.

    Requires env vars: GROK_API_KEY, AI_SOCIAL_ENABLED=true
    """
    if os.environ.get("AI_SOCIAL_ENABLED", "false").lower() != "true":
        logger.info("[ai_social] AI_SOCIAL_ENABLED is false — skipping")
        return None

    api_key = os.environ.get("GROK_API_KEY")
    if not api_key:
        logger.warning("[ai_social] GROK_API_KEY not set — skipping")
        return None

    today = date.today()
    yesterday = today - timedelta(days=1)
    today_str = today.strftime("%B %-d, %Y")
    yesterday_str = yesterday.strftime("%B %-d, %Y")
    today_iso = today.strftime("%Y-%m-%d")

    prompt = f"""
Today is {today_str}.

STEP 1: Search X for posts by @cgtwts from {yesterday_str} or {today_str}.
@cgtwts posts daily AI recaps as a bullet list of short one-liner headlines (e.g. "- openai acquires astral").
If you find a post like this from them on {yesterday_str} or {today_str}, extract all bullet points as headlines.

STEP 2: If @cgtwts has NOT posted a recap for {yesterday_str} or {today_str}, generate your own list
in exactly the same style — terse, lowercase (except proper nouns), punchy, one sentence each,
covering the biggest AI news from {yesterday_str} and {today_str}.

Return ONLY a raw JSON object — no markdown, no prose, no explanation.

Rules:
- Each headline must be one sentence, under 15 words, lowercase (except proper nouns/$ amounts).
- Include specific names: model names, company names, dollar figures where relevant.
- Exclude drama, lawsuits, politics, and executive changes.
- Return all headlines you found/generated — do not cap the count.
- source_was_cgtwts: true if you found and used @cgtwts posts, false if you generated.

JSON format:
{{
  "items": [
    {{"headline": "openai acquires astral"}},
    {{"headline": "goldman sachs says $450B in AI spend added basically zero to US growth"}},
    {{"headline": "cursor's fifty person team drops a model beating top labs on coding"}}
  ],
  "source_was_cgtwts": true,
  "num_sources_used": 8,
  "date": "{today_iso}"
}}
"""

    raw = ""
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
        logger.info(f"[ai_social] Grok made {x_calls} X search calls")

        message = next(
            (item for item in reversed(data.get("output", []))
             if item.get("type") == "message" and item.get("role") == "assistant"),
            None,
        )
        if not message:
            logger.error("[ai_social] No assistant message in Grok response")
            return None

        raw = message["content"][0]["text"].strip()
        logger.info(f"[ai_social] Raw Grok response:\n{raw}")

        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        result = json.loads(raw)

        num_sources = result.get("num_sources_used", 0)
        if num_sources == 0:
            logger.warning("[ai_social] num_sources_used == 0 — Grok may be hallucinating, returning None")
            return None

        source = "cgtwts" if result.get("source_was_cgtwts") else "generated"
        logger.info(f"[ai_social] AI buzz fetched ({source}, {len(result.get('items', []))} items, {num_sources} sources)")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"[ai_social] Failed to parse Grok response as JSON: {e}")
        logger.error(f"[ai_social] Raw response was: {raw[:500]}")
        return None
    except Exception as e:
        logger.error(f"[ai_social] Grok API call failed: {e}")
        return None
