# news_pipeline/redis_cache.py

import json
import logging
import os
from datetime import date

logger = logging.getLogger(__name__)

SECTIONS_KEY = "briefing:sections"
SUMMARIES_KEY = "briefing:summaries"
CACHE_DATE_KEY = "briefing:cache_date"
NBA_STATS_KEY = "briefing:nba_stats"

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


def save_summaries_cache(summaries: dict) -> None:
    """
    Writes the full summaries dict to Redis at once (used by cron for bulk pre-generation).
    """
    try:
        client = _get_client()
        client.set(SUMMARIES_KEY, json.dumps(summaries), ex=CACHE_TTL_SECONDS)
        logger.info(f"[redis_cache] Summaries cache written ({len(summaries)} stories)")

    except EnvironmentError:
        raise
    except Exception as e:
        logger.warning(f"[redis_cache] Could not write summaries cache: {e}")


# ── NBA Stats ──────────────────────────────────────────────────────────────────

def save_nba_stats_cache(data: dict) -> None:
    """Writes NBA game stats to Redis with a 28-hour TTL."""
    try:
        client = _get_client()
        client.set(NBA_STATS_KEY, json.dumps(data), ex=CACHE_TTL_SECONDS)
        logger.info("[redis_cache] NBA stats cache written")

    except EnvironmentError:
        raise
    except Exception as e:
        logger.warning(f"[redis_cache] Could not write NBA stats cache: {e}")


def load_nba_stats_cache() -> dict | None:
    """Returns cached NBA stats dict, or None if missing or unreadable."""
    try:
        client = _get_client()
        raw = client.get(NBA_STATS_KEY)
        if not raw:
            logger.info("[redis_cache] NBA stats cache miss")
            return None
        data = json.loads(raw)
        logger.info("[redis_cache] NBA stats cache hit")
        return data

    except EnvironmentError:
        raise
    except Exception as e:
        logger.warning(f"[redis_cache] Could not load NBA stats cache: {e}")
        return None
