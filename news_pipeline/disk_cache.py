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
