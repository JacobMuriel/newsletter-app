# news_pipeline/markets_social.py
#
# Generates macro-level market pulse from X/FinTwit:
# broad sentiment on indices, rates, sectors, and macro events.
#
# Distinct from finance_social.py which focuses on specific company events
# (earnings, M&A, regulatory). This file is for the "Markets" section;
# finance_social.py is for the "Finance" section.

import json
import logging
import os
import re
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)


def fetch_markets_buzz() -> dict | None:
    """
    Searches X (FinTwit) for broad market macro sentiment from the last 24 hours.
    Covers: indices (S&P, Nasdaq, Dow), interest rates/Fed, sector rotation,
    commodities, bonds, and overall market mood.

    Returns { "items": [{"headline": "..."}], "num_sources_used": N, "date": "YYYY-MM-DD" }
    or None on failure / zero sources.

    Gated by FINANCE_SOCIAL_ENABLED — same toggle as finance_social.py.
    """
    if os.environ.get("FINANCE_SOCIAL_ENABLED", "false").lower() != "true":
        logger.info("[markets_social] FINANCE_SOCIAL_ENABLED is false — skipping")
        return None

    api_key = os.environ.get("GROK_API_KEY")
    if not api_key:
        logger.warning("[markets_social] GROK_API_KEY not set — skipping")
        return None

    today = date.today()
    yesterday = today - timedelta(days=1)
    today_str = today.strftime("%B %-d, %Y")
    yesterday_str = yesterday.strftime("%B %-d, %Y")
    today_iso = today.strftime("%Y-%m-%d")

    prompt = f"""
Today is {today_str}. Search X for macro market sentiment and broad market commentary from {yesterday_str} and {today_str}.

Focus specifically on macro and market-wide themes — NOT individual company news or earnings.
Search posts from macro-focused accounts: @zerohedge, @WSJmarkets, @markets, @financialjuice,
@elerianm, @LizAnnSonders, @bondvigilantes, prominent macro traders, and Fed watchers.

Cover these areas — prioritize by X volume:
- Major indices: S&P 500, Nasdaq, Dow Jones — moves, momentum, technical levels
- Interest rates and Fed: Fed commentary, Treasury yields, rate expectations
- Sector rotation: which sectors are leading or lagging and why
- Macro data: jobs, CPI, GDP, PMI, or any other economic releases
- Commodities and currencies: oil, gold, dollar index if generating significant chatter
- Overall market mood: is FinTwit bullish, bearish, or uncertain — and what's driving it

Return ONLY a raw JSON object — no markdown, no prose, no explanation.

Rules:
- Every headline must reflect MACRO or MARKET-WIDE sentiment — no single-stock earnings, no company M&A.
- Each headline is one sentence, under 15 words, lowercase (except proper nouns/tickers/$ amounts).
- Include specific numbers: index levels, yield percentages, basis points, percentage moves.
- Be direct about sentiment: include words like "surges", "tumbles", "fears", "bets", "signals".
- Return 7-10 headlines covering different macro angles.
- If markets were closed (weekend/holiday), report on futures, crypto, or any macro news that broke.

JSON format:
{{
  "items": [
    {{"headline": "s&p 500 reclaims 5,200 as rate-cut bets revive after soft CPI print"}},
    {{"headline": "10-year treasury yield drops 12bps — bond market pricing in two 2025 cuts"}},
    {{"headline": "tech leads sector rotation as defensive names lag for third straight session"}},
    {{"headline": "dollar index falls to 3-month low on softer-than-expected jobs data"}},
    {{"headline": "oil holds above $80 despite demand concerns — macro traders eye OPEC meeting"}}
  ],
  "num_sources_used": 14,
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
        logger.info(f"[markets_social] Grok made {x_calls} X search calls")

        message = next(
            (item for item in reversed(data.get("output", []))
             if item.get("type") == "message" and item.get("role") == "assistant"),
            None,
        )
        if not message:
            logger.error("[markets_social] No assistant message in Grok response")
            return None

        raw = message["content"][0]["text"].strip()
        logger.info(f"[markets_social] Raw Grok response:\n{raw}")

        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        result = json.loads(raw)

        num_sources = result.get("num_sources_used", 0)
        if num_sources == 0:
            logger.warning("[markets_social] num_sources_used == 0 — Grok may be hallucinating, returning None")
            return None

        logger.info(f"[markets_social] Markets buzz fetched ({len(result.get('items', []))} items, {num_sources} sources)")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"[markets_social] Failed to parse Grok response as JSON: {e}")
        logger.error(f"[markets_social] Raw response was: {raw[:500]}")
        return None
    except Exception as e:
        logger.error(f"[markets_social] Grok API call failed: {e}")
        return None
