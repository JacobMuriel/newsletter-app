"""
server.py — FastAPI server exposing the Briefing news pipeline as an HTTP API.

Endpoints:
  GET  /sections   — returns all ranked stories grouped by section (no summaries)
  POST /summary    — generates a summary for a single story on demand
  GET  /health     — liveness + pipeline status

Caching:
  /sections result is cached for the calendar day (UTC). Re-runs pipeline after midnight.
  /summary results are cached in memory for the lifetime of the process.

Startup:
  Pipeline runs as a background task at server startup via FastAPI lifespan.
  /sections returns 202 "warming_up" until the pipeline finishes.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

from news_pipeline.pipeline_api import get_ranked_stories, get_story_summary  # noqa: E402

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------
_sections_cache: dict | None = None
_sections_cache_date: date | None = None
_summary_cache: dict[str, dict] = {}
_pipeline_ready: bool = False
_pipeline_error: str | None = None


# ---------------------------------------------------------------------------
# Background pipeline task
# ---------------------------------------------------------------------------
async def _run_pipeline_background() -> None:
    global _sections_cache, _sections_cache_date, _pipeline_ready, _pipeline_error
    try:
        logger.info("[server] pipeline starting in background...")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, get_ranked_stories)
        _sections_cache = result
        _sections_cache_date = date.today()
        _pipeline_ready = True
        logger.info(
            "[server] pipeline ready — sections: %s",
            {k: len(v) for k, v in result.get("sections", {}).items()},
        )
    except Exception as exc:
        _pipeline_error = str(exc)
        logger.exception("[server] pipeline failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_run_pipeline_background())
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Briefing API", lifespan=lifespan)

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

@app.get("/sections")
async def sections():
    """Return all ranked stories grouped by section."""
    global _sections_cache, _sections_cache_date

    if not _pipeline_ready:
        logger.info("GET /sections — pipeline not ready yet")
        return JSONResponse(
            status_code=202,
            content={
                "status": "warming_up",
                "message": "Pipeline is loading, please retry in 30–60 seconds",
                "error": _pipeline_error,
            },
        )

    # Re-run pipeline if it's a new day
    today = datetime.now(timezone.utc).date()
    if _sections_cache_date != today:
        logger.info("GET /sections — new day, re-running pipeline (date=%s)", today)
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, get_ranked_stories)
            _sections_cache = result
            _sections_cache_date = today
        except Exception as exc:
            logger.exception("Pipeline refresh failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}")

    logger.info("GET /sections — returning cached result (date=%s)", _sections_cache_date)
    return _sections_cache


@app.post("/summary")
async def summary(body: SummaryRequest):
    """Generate a summary for a single story. Returns cached result if already generated."""
    story_id = body.story_id

    if story_id in _summary_cache:
        logger.info("POST /summary — cache hit (story_id=%s)", story_id)
        return _summary_cache[story_id]

    if not _pipeline_ready:
        raise HTTPException(status_code=503, detail="Pipeline not ready yet. Retry after /sections returns 200.")

    story_data: dict = {}
    for section_stories in _sections_cache.get("sections", {}).values():  # type: ignore[union-attr]
        for s in section_stories:
            if s["id"] == story_id:
                story_data = s
                break
        if story_data:
            break

    if not story_data:
        raise HTTPException(status_code=404, detail=f"Story '{story_id}' not found. Refresh /sections.")

    logger.info("POST /summary — generating (story_id=%s)", story_id)
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
async def health():
    return {
        "status": "ok",
        "pipeline_ready": _pipeline_ready,
        "cached_date": str(_sections_cache_date),
        "error": _pipeline_error,
    }
