# news_pipeline/finance_social.py

import json
import logging
import os
import re
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)


def fetch_finance_buzz() -> dict | None:
    """
    Searches X (FinTwit) for the biggest finance and markets stories from the last 24 hours.
    Covers: stock market moves, macro/Fed/rates, crypto, and earnings.

    Returns { "items": [{"headline": "..."}], "num_sources_used": N, "date": "YYYY-MM-DD" }
    or None on failure / zero sources.

    Requires env vars: GROK_API_KEY, FINANCE_SOCIAL_ENABLED=true
    """
    if os.environ.get("FINANCE_SOCIAL_ENABLED", "false").lower() != "true":
        logger.info("[finance_social] FINANCE_SOCIAL_ENABLED is false — skipping")
        return None

    api_key = os.environ.get("GROK_API_KEY")
    if not api_key:
        logger.warning("[finance_social] GROK_API_KEY not set — skipping")
        return None

    today = date.today()
    yesterday = today - timedelta(days=1)
    today_str = today.strftime("%B %-d, %Y")
    yesterday_str = yesterday.strftime("%B %-d, %Y")
    today_iso = today.strftime("%Y-%m-%d")

    prompt = f"""
Today is {today_str}. Search X (FinTwit) for the biggest finance and markets news from {yesterday_str} and {today_str}.

Cast a wide net — search for posts from financial journalists, analysts, traders, and major accounts
like @unusual_whales, @financialjuice, @WSJmarkets, @markets, @CNBC, and prominent FinTwit voices.

Cover all four areas:
- Stock market moves: S&P 500, Nasdaq, notable individual stocks
- Macro / Fed / interest rates: Fed policy, inflation, economic data
- Crypto: Bitcoin, Ethereum, major moves or news
- Earnings: any notable earnings reports or guidance

Return ONLY a raw JSON object — no markdown, no prose, no explanation.

Rules:
- Each headline must be one sentence, under 15 words, lowercase (except proper nouns/tickers/$ amounts).
- Include specific names: tickers, companies, dollar figures, percentages where relevant.
- Be factual — only report what actually happened, not speculation.
- Return all headlines you found — do not cap the count. Aim for 8-12.
- If markets were closed (weekend/holiday), report on crypto moves and any major news that broke.

JSON format:
{{
  "items": [
    {{"headline": "s&p 500 drops 1.2% as fed signals rates higher for longer"}},
    {{"headline": "nvidia beats earnings, guides $28B next quarter — stock up 8% after hours"}},
    {{"headline": "bitcoin surges past $95k on ETF inflow data"}},
    {{"headline": "jpmorgan warns of recession risk if tariffs hold through q3"}}
  ],
  "num_sources_used": 12,
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
        logger.info(f"[finance_social] Grok made {x_calls} X search calls")

        message = next(
            (item for item in reversed(data.get("output", []))
             if item.get("type") == "message" and item.get("role") == "assistant"),
            None,
        )
        if not message:
            logger.error("[finance_social] No assistant message in Grok response")
            return None

        raw = message["content"][0]["text"].strip()
        logger.info(f"[finance_social] Raw Grok response:\n{raw}")

        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        result = json.loads(raw)

        num_sources = result.get("num_sources_used", 0)
        if num_sources == 0:
            logger.warning("[finance_social] num_sources_used == 0 — Grok may be hallucinating, returning None")
            return None

        logger.info(f"[finance_social] Finance buzz fetched ({len(result.get('items', []))} items, {num_sources} sources)")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"[finance_social] Failed to parse Grok response as JSON: {e}")
        logger.error(f"[finance_social] Raw response was: {raw[:500]}")
        return None
    except Exception as e:
        logger.error(f"[finance_social] Grok API call failed: {e}")
        return None
