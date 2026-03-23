# Session 7 — Performance: Caching, Parallel Fetching & Cold Start Fix

> First, paste the MASTER_CONTEXT.md document, then paste this.

---

## What we're doing this session

Making the pipeline significantly faster and more resilient — without adding any paid infrastructure. By the end of this session:

- RSS feeds are fetched in parallel (not one at a time)
- Pipeline output is cached to disk so the server survives sleep/restart
- Summaries are cached to disk so the same story is never summarized twice in a day
- The app gets a warm-up endpoint to wake Render before the user opens the app
- Story and cluster caps are tuned to keep the expensive O(n²) clustering step fast

**Do NOT touch:** `newsletter.py`, `send_email.py`, `main.py` CLI flow

---

## Step 1 — Parallelize RSS feed fetching

### Problem
The pipeline currently fetches each RSS feed sequentially. With 10+ sources at 1–2s each, that's 15–25 seconds of pure I/O before any processing starts.

### Fix
Open `news_pipeline/` and find the module that does RSS fetching (likely in `cluster.py`, `dedupe.py`, or a fetch utility called from `main.py` — audit first). Wrap the per-feed fetch calls in a `ThreadPoolExecutor`.

The feeds are I/O-bound (waiting on HTTP), so threads work perfectly here. You don't need `asyncio`.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

logger = logging.getLogger(__name__)

def fetch_all_feeds(feed_configs: list[dict], max_workers: int = 12) -> list:
    """
    Fetches all RSS feeds in parallel using a thread pool.
    Each feed_config is a dict with at least a 'url' key.
    Returns a flat list of raw articles across all feeds.
    """
    all_articles = []

    def fetch_one(feed_config):
        try:
            # Replace this with whatever the existing single-feed fetch function is
            return fetch_single_feed(feed_config)
        except Exception as e:
            logger.warning(f"[fetch] Failed to fetch {feed_config.get('url')}: {e}")
            return []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_one, cfg): cfg for cfg in feed_configs}
        for future in as_completed(futures):
            articles = future.result()
            all_articles.extend(articles)

    logger.info(f"[fetch] Fetched {len(all_articles)} articles from {len(feed_configs)} feeds in parallel")
    return all_articles
```

Wire this into `pipeline_api.py`'s `get_ranked_stories()` in place of whatever sequential loop exists.

**Expected improvement:** 15–25s → 3–5s for the fetch phase.

---

## Step 2 — Disk-based sections cache

### Problem
`server.py` already has an in-memory cache (`_sections_cache`), but Render's free tier **sleeps after 15 minutes of inactivity**. When it wakes, memory is wiped. So every cold start re-runs the full pipeline (30–60s) even if it already ran earlier that day.

### Fix
Write the pipeline output to a JSON file on disk after each run. On startup or first request, check if a valid cache file exists for today before running the pipeline.

Create `news_pipeline/disk_cache.py`:

```python
# news_pipeline/disk_cache.py

import json
import logging
import os
from datetime import date

logger = logging.getLogger(__name__)

SECTIONS_CACHE_PATH = "/tmp/briefing_sections_cache.json"
SUMMARIES_CACHE_PATH = "/tmp/briefing_summaries_cache.json"


# ── Sections cache ────────────────────────────────────────────────────────────

def load_sections_cache() -> dict | None:
    """
    Returns cached sections dict if it exists and was generated today.
    Returns None if cache is missing, stale, or unreadable.
    """
    try:
        if not os.path.exists(SECTIONS_CACHE_PATH):
            return None
        with open(SECTIONS_CACHE_PATH) as f:
            data = json.load(f)
        if data.get("cache_date") != str(date.today()):
            logger.info("[disk_cache] Sections cache is stale — will re-run pipeline")
            return None
        logger.info("[disk_cache] Sections cache hit — skipping pipeline run")
        return data
    except Exception as e:
        logger.warning(f"[disk_cache] Could not read sections cache: {e}")
        return None


def save_sections_cache(data: dict) -> None:
    """
    Saves sections output to disk with today's date stamped in.
    """
    try:
        data["cache_date"] = str(date.today())
        with open(SECTIONS_CACHE_PATH, "w") as f:
            json.dump(data, f)
        logger.info(f"[disk_cache] Sections cache written to {SECTIONS_CACHE_PATH}")
    except Exception as e:
        logger.warning(f"[disk_cache] Could not write sections cache: {e}")


# ── Summaries cache ───────────────────────────────────────────────────────────

def load_summaries_cache() -> dict:
    """
    Returns the full summaries cache dict {story_id: summary_dict}.
    Returns empty dict if cache is missing, stale, or unreadable.
    """
    try:
        if not os.path.exists(SUMMARIES_CACHE_PATH):
            return {}
        with open(SUMMARIES_CACHE_PATH) as f:
            data = json.load(f)
        if data.get("cache_date") != str(date.today()):
            logger.info("[disk_cache] Summaries cache is stale — starting fresh")
            return {}
        summaries = data.get("summaries", {})
        logger.info(f"[disk_cache] Loaded {len(summaries)} cached summaries from disk")
        return summaries
    except Exception as e:
        logger.warning(f"[disk_cache] Could not read summaries cache: {e}")
        return {}


def save_summary_to_cache(story_id: str, summary_dict: dict, current_cache: dict) -> None:
    """
    Adds a single summary to the on-disk cache.
    Pass the current in-memory cache dict so we can write the full state.
    """
    try:
        current_cache[story_id] = summary_dict
        payload = {
            "cache_date": str(date.today()),
            "summaries": current_cache,
        }
        with open(SUMMARIES_CACHE_PATH, "w") as f:
            json.dump(payload, f)
    except Exception as e:
        logger.warning(f"[disk_cache] Could not write summary for {story_id}: {e}")
```

---

## Step 3 — Wire the disk cache into `server.py`

Update `server.py` to use the disk cache on every request. The in-memory cache is kept as a fast first-layer check (avoids even reading the file on repeated requests within the same process lifetime).

Replace the existing cache logic with this pattern:

```python
from news_pipeline.disk_cache import (
    load_sections_cache, save_sections_cache,
    load_summaries_cache, save_summary_to_cache,
)

# In-memory layer (fast, process-lifetime only)
_sections_cache: dict | None = None
_summary_cache: dict = {}  # populated from disk on first use
_summary_cache_loaded = False  # track whether we've hydrated from disk yet


@app.get("/sections")
async def sections():
    global _sections_cache

    # Layer 1: in-memory (fastest)
    if _sections_cache is not None:
        if _sections_cache.get("cache_date") == str(date.today()):
            return _sections_cache

    # Layer 2: disk cache (survives sleep/restart)
    cached = load_sections_cache()
    if cached is not None:
        _sections_cache = cached
        return cached

    # Layer 3: run the full pipeline
    logger.info("[server] Cache miss — running full pipeline")
    result = get_ranked_stories()   # from pipeline_api.py
    save_sections_cache(result)
    _sections_cache = result
    return result


@app.post("/summary")
async def summary(body: SummaryRequest):
    global _summary_cache, _summary_cache_loaded

    # Hydrate from disk on first summary request after a cold start
    if not _summary_cache_loaded:
        _summary_cache = load_summaries_cache()
        _summary_cache_loaded = True

    # Cache hit
    if body.story_id in _summary_cache:
        logger.info(f"[server] Summary cache hit for {body.story_id}")
        return _summary_cache[body.story_id]

    # Cache miss — generate and persist
    story_data = _get_story_data(body.story_id)  # look up from sections cache
    if story_data is None:
        raise HTTPException(status_code=404, detail="Story not found")

    result = get_story_summary(body.story_id, story_data)
    save_summary_to_cache(body.story_id, result, _summary_cache)
    return result
```

---

## Step 4 — Add a `/warmup` endpoint

Render free tier takes ~10–20s to wake from sleep. Rather than the user hitting that delay when they open the app, the iOS app can silently call `/warmup` in the background (e.g. on app foreground). The endpoint does nothing except wake the server and optionally pre-run the pipeline.

Add to `server.py`:

```python
@app.get("/warmup")
async def warmup():
    """
    Called by the iOS app to wake the server before the user needs data.
    Also pre-warms the sections cache if it's stale.
    Returns immediately with status — pipeline runs in background if needed.
    """
    import asyncio

    cache_status = "hit"
    if load_sections_cache() is None:
        # Don't block the response — run pipeline in background
        asyncio.create_task(_background_pipeline_run())
        cache_status = "miss_running"

    return {"status": "awake", "cache": cache_status}


async def _background_pipeline_run():
    """Runs the pipeline in a background task so /warmup returns immediately."""
    global _sections_cache
    import asyncio
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, get_ranked_stories)
    save_sections_cache(result)
    _sections_cache = result
    logger.info("[server] Background pipeline run complete")
```

### iOS side: call `/warmup` on app foreground

In `BriefingApp.swift` or `HomeViewModel`, add:

```swift
// Call this when the app comes to foreground (scenePhase == .active)
func warmUpServer() {
    Task {
        _ = try? await URLSession.shared.data(
            from: URL(string: "\(baseURL)/warmup")!
        )
    }
}
```

Wire it in `BriefingApp.swift`:

```swift
.onChange(of: scenePhase) { phase in
    if phase == .active {
        APIService.shared.warmUpServer()
    }
}
```

This means by the time the user taps anything, the server has already been awake for a few seconds.

---

## Step 5 — Tune clustering caps in `settings.yaml`

The clustering step in `cluster.py` compares every article against every other article — it's O(n²). With 200 articles that's 40,000 comparisons. With 100 it's 10,000. Halving article count cuts clustering time by 4x.

Open `config/settings.yaml` and verify these caps are set tightly:

```yaml
pipeline:
  max_total_stories_fetched: 120     # was this higher? Bring it down
  max_stories_to_rank: 60
  max_stories_to_summarize: 15       # only top stories get OpenAI calls

clustering:
  max_cluster_articles: 5            # don't let one cluster balloon
```

Also check `config/sources.yaml` — set `max_items_per_feed: 15` or lower on each feed. There's no point fetching 50 articles from a feed if you'll only use 3 of them.

---

## Step 6 — Add a pipeline timing log

This gives you visibility into where time is actually going so you can tune further if needed. Add to `pipeline_api.py` inside `get_ranked_stories()`:

```python
import time

def get_ranked_stories() -> dict:
    t0 = time.time()

    articles = fetch_all_feeds(feed_configs)
    logger.info(f"[perf] RSS fetch: {time.time() - t0:.1f}s ({len(articles)} articles)")
    t1 = time.time()

    stories = cluster_articles(articles, settings)
    logger.info(f"[perf] Clustering: {time.time() - t1:.1f}s ({len(stories)} clusters)")
    t2 = time.time()

    # ... categorize, rank, etc ...

    logger.info(f"[perf] Total pipeline: {time.time() - t0:.1f}s")
    return result
```

Check the Render logs after deploy — you'll immediately see which step is the bottleneck.

---

## Step 7 — Verify nothing is broken

```bash
# Dry run — should complete in under 10s now (vs 30–60s before)
OPENAI_ENABLED=false uvicorn server:app --reload

# First request — pipeline runs, cache writes to disk
curl http://localhost:8000/sections

# Second request — should return instantly from disk cache
curl http://localhost:8000/sections

# Kill and restart the server (simulates Render sleep/wake)
# Then hit sections again — should return from disk, not re-run pipeline
curl http://localhost:8000/sections

# Check warmup endpoint
curl http://localhost:8000/warmup
# Should return: {"status": "awake", "cache": "hit"}
```

Check logs for `[perf]` and `[disk_cache]` lines to confirm timing and cache behavior.

---

## Done when:
- [ ] RSS feeds are fetched in parallel — check logs show all feeds completing together, not sequentially
- [ ] `[disk_cache] Sections cache hit` appears in logs on second request and after server restart
- [ ] `[disk_cache] Summaries cache hit` appears for stories that were already summarized today
- [ ] `/warmup` returns immediately and triggers background pipeline run if cache is stale
- [ ] iOS app calls `/warmup` on app foreground (scenePhase `.active`)
- [ ] `[perf]` timing logs appear on every pipeline run
- [ ] `python main.py` still works exactly as before (no CLI regression)
- [ ] Total cold-start-to-data time is under 10 seconds on a warm cache
