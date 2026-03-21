"""
server.py — FastAPI server exposing the Briefing news pipeline as an HTTP API.

Endpoints:
  GET  /sections   — returns all ranked stories grouped by section (reads from Redis)
  POST /summary    — generates a summary for a single story on demand
  GET  /warmup     — wakes the server and pre-loads sections into memory
  GET  /health     — liveness + cache status

Caching (two layers):
  Layer 1 — in-memory: fastest, lives for the process lifetime.
  Layer 2 — Upstash Redis: survives deploys, restarts, and Render sleep.
  The pipeline itself never runs here — that's cron_pipeline.py's job.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

from news_pipeline.pipeline_api import get_story_summary  # noqa: E402
from news_pipeline.redis_cache import (  # noqa: E402
    load_sections_cache,
    load_nba_stats_cache,
    load_summaries_cache,
    save_summary_to_cache,
)

# ---------------------------------------------------------------------------
# In-memory layer — avoids hitting Redis on every single request
# ---------------------------------------------------------------------------
_sections_mem_cache: dict | None = None
_sections_mem_date: str | None = None
_summary_mem_cache: dict = {}
_summary_cache_loaded: bool = False

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Briefing API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class SummaryRequest(BaseModel):
    story_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    cache_date = _sections_mem_date or "not loaded in memory"
    return {"status": "ok", "cache_date": cache_date}


@app.get("/warmup")
async def warmup():
    """
    Called by the iOS app when it comes to foreground.
    Wakes the server and pre-loads sections into memory.
    """
    global _sections_mem_cache, _sections_mem_date

    if _sections_mem_cache and _sections_mem_date == str(date.today()):
        return {"status": "awake", "cache": "memory_hit"}

    cached = _load_sections_with_nba()
    if cached:
        _sections_mem_cache = cached
        _sections_mem_date = str(date.today())
        return {"status": "awake", "cache": "redis_hit"}

    return {
        "status": "awake",
        "cache": "miss",
        "message": "No pipeline data for today yet. Cron job may not have run."
    }


@app.get("/sections")
async def sections():
    """Return all ranked stories grouped by section."""
    global _sections_mem_cache, _sections_mem_date

    # Layer 1: memory
    if _sections_mem_cache and _sections_mem_date == str(date.today()):
        logger.info("GET /sections — memory hit")
        return _sections_mem_cache

    # Layer 2: Redis
    cached = _load_sections_with_nba()
    if cached:
        _sections_mem_cache = cached
        _sections_mem_date = str(date.today())
        logger.info("GET /sections — Redis hit")
        return cached

    # No data yet — return 202 so the iOS app retries instead of hard-failing
    return JSONResponse(
        status_code=202,
        content={
            "status": "warming_up",
            "message": "Pipeline data not available yet. Please retry in a moment.",
        },
    )


@app.post("/summary")
async def summary(body: SummaryRequest):
    """Generate a summary for a single story. Returns cached result if already generated."""
    global _summary_mem_cache, _summary_cache_loaded

    story_id = body.story_id

    # Hydrate from Redis on first request after boot
    if not _summary_cache_loaded:
        _summary_mem_cache = load_summaries_cache()
        _summary_cache_loaded = True

    if story_id in _summary_mem_cache:
        logger.info("POST /summary — cache hit (story_id=%s)", story_id)
        return _summary_mem_cache[story_id]

    story_data = _find_story(story_id)
    if story_data is None:
        raise HTTPException(status_code=404, detail=f"Story '{story_id}' not found. Refresh /sections.")

    logger.info("POST /summary — generating (story_id=%s)", story_id)
    try:
        result = get_story_summary(story_id, story_data)
    except KeyError:
        # Story not in in-process registry — summaries are pre-generated by cron.
        # Return 202 so the iOS app retries; next cron run will populate the cache.
        return JSONResponse(
            status_code=202,
            content={"status": "not_ready", "message": "Summary not ready yet. Please retry after the next pipeline run."},
        )
    except Exception as exc:
        logger.exception("Summary generation failed (story_id=%s): %s", story_id, exc)
        raise HTTPException(status_code=500, detail=f"Summary error: {exc}")

    save_summary_to_cache(story_id, result, _summary_mem_cache)
    logger.info("POST /summary — done (story_id=%s)", story_id)
    return result


@app.get("/nba/today")
async def nba_today():
    """Live today's NBA slate — always fetches fresh from ESPN, no cache."""
    from news_pipeline.nba_stats import get_today_games
    games = get_today_games()
    return {"games": games, "fetched_at": datetime.now(timezone.utc).isoformat()}


@app.post("/nba/social/live")
async def nba_social_live():
    """
    Fetches live Grok social buzz for an in-progress Rockets or Bulls game.
    Only called when at least one of those teams has status == 'live' in today's slate.
    Returns same shape as nba_social_buzz in the /sections response.
    """
    from news_pipeline.nba_stats import get_today_games
    from news_pipeline.nba_social import get_nba_social_buzz
    try:
        today_games = get_today_games()
        rockets_game_dict: dict | None = None
        bulls_game_dict: dict | None = None

        for g in today_games:
            if g["status"] == "live":
                home, away = g["home_team"], g["away_team"]
                if home == "HOU" or away == "HOU":
                    is_home = home == "HOU"
                    my_score  = (g["home_score"] or 0) if is_home else (g["away_score"] or 0)
                    opp_score = (g["away_score"] or 0) if is_home else (g["home_score"] or 0)
                    rockets_game_dict = {
                        "played": True,
                        "opponent": away if is_home else home,
                        "score": f"{my_score}-{opp_score}",
                        "result": "unknown",
                    }
                if home == "CHI" or away == "CHI":
                    is_home = home == "CHI"
                    my_score  = (g["home_score"] or 0) if is_home else (g["away_score"] or 0)
                    opp_score = (g["away_score"] or 0) if is_home else (g["home_score"] or 0)
                    bulls_game_dict = {
                        "played": True,
                        "opponent": away if is_home else home,
                        "score": f"{my_score}-{opp_score}",
                        "result": "unknown",
                    }

        if rockets_game_dict is None and bulls_game_dict is None:
            return {"buzz": None, "reason": "no_live_featured_game"}

        buzz = get_nba_social_buzz(
            rockets_game=rockets_game_dict or {"played": False},
            bulls_game=bulls_game_dict or {"played": False},
        )
        return {"buzz": buzz}
    except Exception as exc:
        logger.exception("POST /nba/social/live failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _load_sections_with_nba() -> dict | None:
    """Load sections from Redis and inject nba_stats as a top-level key.

    ai_social_buzz is already embedded in the briefing:sections payload by the pipeline,
    so no extra Redis read is needed for it here.
    """
    cached = load_sections_cache()
    if not cached:
        cached = load_sections_cache(key="briefing:sections:prev")
        if cached:
            cached["stale"] = True
            logger.warning("[server] serving stale fallback data from briefing:sections:prev")
    if not cached:
        return None
    nba_stats = load_nba_stats_cache()
    if nba_stats is not None:
        cached["nba_stats"] = nba_stats
        logger.info("[server] nba_stats merged into sections response")
    else:
        logger.info("[server] nba_stats not available — briefing:nba_stats key missing or empty")

    if cached.get("ai_social_buzz") is not None:
        logger.info("[server] ai_social_buzz present in sections payload")
    else:
        logger.info("[server] ai_social_buzz not in payload (disabled or unavailable)")

    return cached


def _find_story(story_id: str) -> dict | None:
    """Look up a story by ID from the in-memory sections cache."""
    if not _sections_mem_cache:
        return None
    for section_stories in _sections_mem_cache.get("sections", {}).values():
        for story in section_stories:
            if story.get("id") == story_id:
                return story
    return None
