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
    Calls the Grok API to synthesize X/Twitter discourse about AI news from the last 24 hours.

    Returns up to 4 structured items covering new model/product releases, trending techniques,
    and community advice/tips. Returns None if the call fails or num_sources_used == 0.

    Requires env vars: GROK_API_KEY, AI_SOCIAL_ENABLED=true
    """
    if os.environ.get("AI_SOCIAL_ENABLED", "false").lower() != "true":
        logger.info("[ai_social] AI_SOCIAL_ENABLED is false — skipping AI social buzz")
        return None

    api_key = os.environ.get("GROK_API_KEY")
    if not api_key:
        logger.warning("[ai_social] GROK_API_KEY not set — skipping AI social buzz")
        return None

    today = date.today()
    yesterday = today - timedelta(days=1)

    # Explicit date strings — Grok needs these to anchor to the right day.
    # Do NOT use relative terms like "yesterday" alone; Grok can misinterpret
    # the reference frame and pull stale data or hallucinate from training data
    # instead of live X posts.
    today_str = today.strftime("%B %-d, %Y")
    yesterday_str = yesterday.strftime("%B %-d, %Y")
    today_iso = today.strftime("%Y-%m-%d")

    prompt = f"""
Today is {today_str}. Search X (Twitter) for what AI practitioners, developers, and researchers were talking about on {yesterday_str} and {today_str}.

Use your x_search tool to cast a wide net first — find the highest-volume AI discussions from the last 24 hours. Then narrow to the 4 most interesting items.

Then return ONLY a raw JSON object in exactly this format — no markdown, no prose, no explanation.

Rules:
- Return the 4 most relevant items you found. Do not return an empty array — if you found fewer than 4 strong matches, return the best ones you have.
- Each item must have a type. Pick the best fit from: "release" (new model or product launch), "trend" (concept or technique gaining traction), "advice" (tip or best practice being discussed), or "discussion" (anything significant that doesn't fit the other three cleanly).
- Include specific names — model names (e.g. GPT-4o, Gemini, Claude, Llama), company names (e.g. OpenAI, Google, Anthropic, Meta), people, or technique names — where they appear in the posts. A widely-discussed concept without a specific name is acceptable if it's genuinely trending.
- Each headline must be concise — under 12 words.
- Each blurb must be 2-3 sentences synthesizing what people were actually saying on X. Write in your own words — do not quote tweets.
- hours_ago is an approximate integer: how many hours ago the discussion peaked or the announcement was made.
- Exclude drama, lawsuits, politics, executive changes, and funding news. Focus on: releases, techniques, practitioner advice, and substantive technical discussions.

JSON format:
{{
  "items": [
    {{
      "type": "release",
      "headline": "OpenAI releases GPT-5 with extended context window",
      "blurb": "X erupted after OpenAI quietly dropped GPT-5 access to Plus subscribers. Practitioners are benchmarking it against Claude 3.7 Sonnet on coding tasks, with early results showing GPT-5 pulling ahead on multi-file edits. The thread from @simonw has over 2k retweets.",
      "hours_ago": 6
    }},
    {{
      "type": "trend",
      "headline": "Speculative decoding gains traction for inference speed",
      "blurb": "A thread explaining speculative decoding went viral among ML engineers, drawing comparisons to earlier KV-cache optimizations. Several practitioners shared benchmarks showing 2–3x speedups on Llama 3 inference with minimal quality loss. The technique is being framed as a must-know for anyone running local models.",
      "hours_ago": 14
    }},
    {{
      "type": "advice",
      "headline": "System prompt structuring tips for Claude projects",
      "blurb": "A popular thread broke down best practices for structuring system prompts in Claude Projects, emphasizing role framing and constraint ordering. Multiple replies confirmed the techniques cut hallucination rates noticeably on long-context tasks. The advice is being re-shared heavily in the indie hacker and solodev communities.",
      "hours_ago": 20
    }},
    {{
      "type": "discussion",
      "headline": "Debate over whether context length actually matters",
      "blurb": "A high-engagement thread argued that most practical use cases never exceed 32k tokens, making the context length arms race mostly marketing. Replies were split, with RAG practitioners pushing back hard. The discussion surfaced a broader tension between benchmark performance and real-world developer needs.",
      "hours_ago": 18
    }}
  ],
  "num_sources_used": 11,
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

        # Extract text from the final assistant message in the output list
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

        # Strip any accidental markdown fences Grok might add despite instructions
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        result = json.loads(raw)

        num_sources = result.get("num_sources_used", 0)
        if num_sources == 0:
            logger.warning("[ai_social] num_sources_used == 0 — Grok may be hallucinating, returning None")
            return None

        logger.info(f"[ai_social] AI buzz fetched for {today_iso} ({len(result.get('items', []))} items, {num_sources} sources)")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"[ai_social] Failed to parse Grok response as JSON: {e}")
        logger.error(f"[ai_social] Raw response was: {raw[:500]}")
        return None

    except Exception as e:
        logger.error(f"[ai_social] Grok API call failed: {e}")
        return None
