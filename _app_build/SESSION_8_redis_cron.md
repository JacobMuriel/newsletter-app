# Session 8 — Upstash Redis Cache + Cron Job Pipeline

> First, paste the MASTER_CONTEXT.md document, then paste this.

---

## What we're doing this session

Splitting the pipeline into two separate concerns:

1. **A daily cron job** (`cron_pipeline.py`) that runs the full pipeline at 7am and writes results to Upstash Redis
2. **The FastAPI web server** (`server.py`) that only reads from Redis — it never runs the pipeline itself

The result:
- Deploys go from 5 minutes of downtime → 2–3 seconds with no interruption
- The morning briefing is pre-built before you open the app
- The server boots instantly because it has nothing heavy to do on startup
- Both sections and summaries survive deploys, server restarts, and Render sleep

**Prerequisites:**
- Upstash account created, Redis database created, `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` copied from the Upstash dashboard
- Both env vars added to Render web service and cron job (see manual setup instructions)

**Do NOT touch:** `newsletter.py`, `send_email.py`, `main.py` CLI flow

---

## Step 1 — Add Upstash Redis dependency

Add to `requirements.txt`:
```
upstash-redis
```

---

## Step 2 — Create `news_pipeline/redis_cache.py`

This module replaces `disk_cache.py` (if it exists from Session 7) or is the first cache layer if starting fresh. All reads and writes go through here.

```python
# news_pipeline/redis_cache.py

import json
import logging
import os
from datetime import date

logger = logging.getLogger(__name__)

SECTIONS_KEY = "briefing:sections"
SUMMARIES_KEY = "briefing:summaries"
CACHE_DATE_KEY = "briefing:cache_date"

# TTL of 28 hours — slightly more than a day so the cron job
# has time to run before stale data expires
CACHE_TTL_SECONDS = 28 * 60 * 60


def _get_client():
    """
    Returns an Upstash Redis client.
    Raises clearly if env vars are missing — no silent failures.
    """
    from upstash_redis import Redis

    url = os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

    if not url or not token:
        raise EnvironmentError(
            "[redis_cache] UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN "
            "must be set. Check your environment variables."
        )

    return Redis(url=url, token=token)


# ── Sections ──────────────────────────────────────────────────────────────────

def load_sections_cache() -> dict | None:
    """
    Returns cached sections dict if it exists and is from today.
    Returns None if missing, stale, or unreadable.
    """
    try:
        client = _get_client()
        cache_date = client.get(CACHE_DATE_KEY)

        if cache_date != str(date.today()):
            logger.info("[redis_cache] Sections cache is stale or missing")
            return None

        raw = client.get(SECTIONS_KEY)
        if not raw:
            return None

        data = json.loads(raw)
        logger.info("[redis_cache] Sections cache hit")
        return data

    except EnvironmentError:
        raise
    except Exception as e:
        logger.warning(f"[redis_cache] Could not load sections cache: {e}")
        return None


def save_sections_cache(data: dict) -> None:
    """
    Writes sections output to Redis with a 28-hour TTL.
    Also stamps today's date so staleness checks work.
    """
    try:
        client = _get_client()
        today = str(date.today())

        client.set(SECTIONS_KEY, json.dumps(data), ex=CACHE_TTL_SECONDS)
        client.set(CACHE_DATE_KEY, today, ex=CACHE_TTL_SECONDS)

        logger.info(f"[redis_cache] Sections cache written for {today}")

    except EnvironmentError:
        raise
    except Exception as e:
        logger.warning(f"[redis_cache] Could not write sections cache: {e}")


# ── Summaries ─────────────────────────────────────────────────────────────────

def load_summaries_cache() -> dict:
    """
    Returns the full summaries dict {story_id: summary_dict}.
    Returns empty dict if missing, stale, or unreadable.
    """
    try:
        client = _get_client()
        cache_date = client.get(CACHE_DATE_KEY)

        if cache_date != str(date.today()):
            return {}

        raw = client.get(SUMMARIES_KEY)
        if not raw:
            return {}

        summaries = json.loads(raw)
        logger.info(f"[redis_cache] Loaded {len(summaries)} cached summaries")
        return summaries

    except EnvironmentError:
        raise
    except Exception as e:
        logger.warning(f"[redis_cache] Could not load summaries cache: {e}")
        return {}


def save_summary_to_cache(story_id: str, summary_dict: dict, current_cache: dict) -> None:
    """
    Adds a single summary to the Redis cache.
    Rewrites the full summaries dict — Upstash doesn't support partial updates.
    """
    try:
        client = _get_client()
        current_cache[story_id] = summary_dict
        client.set(SUMMARIES_KEY, json.dumps(current_cache), ex=CACHE_TTL_SECONDS)

    except EnvironmentError:
        raise
    except Exception as e:
        logger.warning(f"[redis_cache] Could not save summary for {story_id}: {e}")
```

---

## Step 3 — Create `cron_pipeline.py`

This is the script the Render cron job runs every morning. It runs the full pipeline and writes results to Redis. It is NOT a server — it runs, finishes, and exits.

```python
# cron_pipeline.py

import logging
import sys
import time
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main():
    logger.info("=" * 60)
    logger.info(f"[cron] Pipeline run starting at {datetime.utcnow().isoformat()}Z")
    logger.info("=" * 60)

    t0 = time.time()

    try:
        from news_pipeline.pipeline_api import get_ranked_stories
        from news_pipeline.redis_cache import save_sections_cache

        logger.info("[cron] Running full pipeline...")
        result = get_ranked_stories()

        story_count = sum(len(v) for v in result.get("sections", {}).values())
        logger.info(f"[cron] Pipeline complete — {story_count} stories across {len(result.get('sections', {}))} sections")

        logger.info("[cron] Writing results to Redis...")
        save_sections_cache(result)

        elapsed = time.time() - t0
        logger.info(f"[cron] Done. Total time: {elapsed:.1f}s")
        logger.info("=" * 60)
        sys.exit(0)

    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"[cron] Pipeline failed after {elapsed:.1f}s: {e}", exc_info=True)
        logger.info("=" * 60)
        sys.exit(1)  # non-zero exit so Render marks the cron run as failed


if __name__ == "__main__":
    main()
```

---

## Step 4 — Update `server.py`

The server no longer runs the pipeline. It only reads from Redis and serves. The `/warmup` endpoint still exists but now just wakes the server — no background pipeline run needed.

Replace the cache and sections logic in `server.py` with:

```python
from datetime import date
from news_pipeline.redis_cache import (
    load_sections_cache,
    load_summaries_cache,
    save_summary_to_cache,
)
from news_pipeline.pipeline_api import get_story_summary

# In-memory layer — avoids hitting Redis on every single request
_sections_mem_cache: dict | None = None
_sections_mem_date: str | None = None
_summary_mem_cache: dict = {}
_summary_cache_loaded: bool = False


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

    cached = load_sections_cache()
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
    global _sections_mem_cache, _sections_mem_date

    # Layer 1: memory
    if _sections_mem_cache and _sections_mem_date == str(date.today()):
        return _sections_mem_cache

    # Layer 2: Redis
    cached = load_sections_cache()
    if cached:
        _sections_mem_cache = cached
        _sections_mem_date = str(date.today())
        return cached

    # No data available — cron job hasn't run yet today
    raise HTTPException(
        status_code=503,
        detail="Pipeline data not available yet. The daily cron job may not have run. Try again shortly."
    )


@app.post("/summary")
async def summary(body: SummaryRequest):
    global _summary_mem_cache, _summary_cache_loaded

    # Hydrate from Redis on first request after boot
    if not _summary_cache_loaded:
        _summary_mem_cache = load_summaries_cache()
        _summary_cache_loaded = True

    # Memory hit
    if body.story_id in _summary_mem_cache:
        logger.info(f"[server] Summary memory hit for {body.story_id}")
        return _summary_mem_cache[body.story_id]

    # Generate and cache
    story_data = _find_story(body.story_id)
    if story_data is None:
        raise HTTPException(status_code=404, detail="Story not found")

    result = get_story_summary(body.story_id, story_data)
    save_summary_to_cache(body.story_id, result, _summary_mem_cache)
    return result


def _find_story(story_id: str) -> dict | None:
    """Look up a story by ID from the in-memory sections cache."""
    if not _sections_mem_cache:
        return None
    for section_stories in _sections_mem_cache.get("sections", {}).values():
        for story in section_stories:
            if story.get("id") == story_id:
                return story
    return None
```

---

## Step 5 — Update `render.yaml`

Add the cron job service alongside the existing web service:

```yaml
services:
  - type: web
    name: briefing-api
    env: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn server:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: OPENAI_ENABLED
        value: "true"
      - key: OPENAI_MODEL
        value: "gpt-4o-mini"
      - key: GROK_ENABLED
        value: "true"
      - key: OPENAI_API_KEY
        sync: false
      - key: GROK_API_KEY
        sync: false
      - key: UPSTASH_REDIS_REST_URL
        sync: false
      - key: UPSTASH_REDIS_REST_TOKEN
        sync: false

  - type: cron
    name: briefing-cron
    env: python
    schedule: "0 12 * * *"   # 7am US Central (UTC-5). Adjust if needed:
                               # 0 12 = 7am Central, 0 13 = 8am Central
                               # 0 11 = 6am Central
    buildCommand: pip install -r requirements.txt
    startCommand: python cron_pipeline.py
    envVars:
      - key: OPENAI_ENABLED
        value: "true"
      - key: OPENAI_MODEL
        value: "gpt-4o-mini"
      - key: GROK_ENABLED
        value: "true"
      - key: OPENAI_API_KEY
        sync: false
      - key: GROK_API_KEY
        sync: false
      - key: UPSTASH_REDIS_REST_URL
        sync: false
      - key: UPSTASH_REDIS_REST_TOKEN
        sync: false
```

---

## Step 6 — Update `.env.example`

```
OPENAI_API_KEY=
OPENAI_ENABLED=false
OPENAI_MODEL=gpt-4o-mini
GROK_ENABLED=false
GROK_API_KEY=
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
```

---

## Step 7 — Test locally

**Test the cron job runs and writes to Redis:**
```bash
OPENAI_ENABLED=false GROK_ENABLED=false \
UPSTASH_REDIS_REST_URL=... UPSTASH_REDIS_REST_TOKEN=... \
python cron_pipeline.py
```
Check logs for `[cron] Done` and no errors. Then check Upstash dashboard — you should see the `briefing:sections` key appear.

**Test the server reads from Redis:**
```bash
UPSTASH_REDIS_REST_URL=... UPSTASH_REDIS_REST_TOKEN=... \
uvicorn server:app --reload
```
```bash
curl http://localhost:8000/sections
# Should return data immediately — no pipeline run
curl http://localhost:8000/warmup
# Should return: {"status": "awake", "cache": "redis_hit"}
```

**Test deploy behavior:**
Kill and restart the server. Hit `/sections` again — should still return data from Redis instantly, confirming restarts and redeploys no longer cause downtime.

**Test the 503 fallback:**
Temporarily set `CACHE_DATE_KEY` to a past date in Upstash (or just delete it from the dashboard) and hit `/sections`. Should return a clear 503 with a message, not a crash.

---

## Done when:
- [ ] `cron_pipeline.py` runs cleanly and writes to Upstash Redis
- [ ] `GET /sections` reads from Redis — no pipeline logic in the server
- [ ] Server boots in under 5 seconds with data immediately available
- [ ] Restarting the server doesn't cause any data loss or downtime
- [ ] `/warmup` returns `redis_hit` after cron has run
- [ ] `/sections` returns a clean 503 with message when cron hasn't run yet (not a crash)
- [ ] `render.yaml` includes both the web service and cron job
- [ ] `python main.py` CLI still works exactly as before
- [ ] Upstash dashboard shows `briefing:sections` and `briefing:summaries` keys after a run
