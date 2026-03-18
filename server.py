"""
server.py — FastAPI server exposing the Briefing news pipeline as an HTTP API.

Endpoints:
  GET  /sections   — returns all ranked stories grouped by section (no summaries)
  POST /summary    — generates a summary for a single story on demand

Caching:
  /sections result is cached for the calendar day (UTC). Re-runs pipeline after midnight.
  /summary results are cached in memory for the lifetime of the process.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

from news_pipeline.pipeline_api import get_ranked_stories, get_story_summary  # noqa: E402

app = FastAPI(title="Briefing API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------
_sections_cache: dict | None = None
_sections_cache_date: date | None = None
_summary_cache: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class SummaryRequest(BaseModel):
    story_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/sections")
def sections():
    """Return all ranked stories grouped by section. Re-runs the pipeline once per day."""
    global _sections_cache, _sections_cache_date

    today = datetime.now(timezone.utc).date()

    if _sections_cache is not None and _sections_cache_date == today:
        logger.info("GET /sections — cache hit (date=%s)", today)
        return _sections_cache

    logger.info("GET /sections — cache miss, running pipeline (date=%s)", today)
    try:
        result = get_ranked_stories()
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}")

    _sections_cache = result
    _sections_cache_date = today
    logger.info(
        "GET /sections — pipeline complete, sections: %s",
        {k: len(v) for k, v in result.get("sections", {}).items()},
    )
    return result


@app.post("/summary")
def summary(body: SummaryRequest):
    """Generate a summary for a single story. Returns cached result if already generated."""
    story_id = body.story_id

    if story_id in _summary_cache:
        logger.info("POST /summary — cache hit (story_id=%s)", story_id)
        return _summary_cache[story_id]

    # Ensure sections have been loaded so the story registry is populated
    if _sections_cache is None:
        logger.info("POST /summary — no sections cache, triggering pipeline (story_id=%s)", story_id)
        sections()  # populate cache + registry

    # Find the story metadata dict from the sections cache (passed through to response builder)
    story_data: dict = {}
    for section_stories in _sections_cache.get("sections", {}).values():  # type: ignore[union-attr]
        for s in section_stories:
            if s["id"] == story_id:
                story_data = s
                break
        if story_data:
            break

    if not story_data:
        logger.warning("POST /summary — story_id=%s not found in sections cache", story_id)
        raise HTTPException(status_code=404, detail=f"Story '{story_id}' not found. Refresh /sections.")

    logger.info("POST /summary — generating summary (story_id=%s)", story_id)
    try:
        result = get_story_summary(story_id, story_data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Summary generation failed (story_id=%s): %s", story_id, exc)
        raise HTTPException(status_code=500, detail=f"Summary error: {exc}")

    _summary_cache[story_id] = result
    logger.info("POST /summary — done (story_id=%s)", story_id)
    return result


@app.get("/health")
def health():
    return {"status": "ok", "cached_sections": str(_sections_cache_date) if _sections_cache_date else None}
