"""
pipeline_api.py — Callable wrappers around the existing pipeline for use by server.py.

Two public functions:
  get_ranked_stories() -> dict
  get_story_summary(story_id, story_data) -> dict
"""

from __future__ import annotations

import copy
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from news_pipeline.bias_detect import detect_charged_language
from news_pipeline.nba_social import get_nba_social_buzz
from news_pipeline.ai_social import fetch_ai_buzz
from news_pipeline.categorize import categorize_stories
from news_pipeline.cluster import cluster_articles
from news_pipeline.fetch_news import fetch_news
from news_pipeline.models import FeedSource, Story
from news_pipeline.quality import filter_story_quality
from news_pipeline.rank import rank_stories
from news_pipeline.summarize import summarize_stories
from news_pipeline.topic_group import group_stories_by_topic

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent

# Registry of story_id -> Story object, populated by get_ranked_stories().
# Needed so get_story_summary() can call into summarize.py with the real Story object.
_story_registry: dict[str, Story] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_ranked_stories() -> dict:
    """
    Runs the full pipeline (fetch → cluster → categorize → rank).
    Returns stories grouped by section, with metadata per story.
    Does NOT generate summaries.

    Each story dict includes: id, headline, source, url,
    published_at, section, bias_flags, has_left_right.
    Story ID is a stable sha1 hash of the primary URL.
    """
    global _story_registry

    sources, settings = _load_config()

    t0 = time.time()

    logger.info("pipeline_api: fetching news…")
    raw_articles, fetch_stats = fetch_news(
        sources=sources,
        max_items_per_feed=int(settings["pipeline"]["max_items_per_feed"]),
        max_total_stories=int(settings["pipeline"]["max_total_stories_fetched"]),
    )
    logger.info("pipeline_api: fetched %d raw articles", len(raw_articles))
    logger.info("[perf] RSS fetch: %.1fs (%d articles)", time.time() - t0, len(raw_articles))
    t1 = time.time()

    clustered = cluster_articles(raw_articles, settings["clustering"])
    logger.info("[perf] Clustering: %.1fs (%d clusters)", time.time() - t1, len(clustered))

    clustered = group_stories_by_topic(clustered, settings, os.getenv("OPENAI_API_KEY"))
    logger.info("[perf] Topic grouping: %d clusters after merge", len(clustered))
    t2 = time.time()

    categorized = categorize_stories(clustered, settings["categorization"])

    for story in categorized:
        story.charged_sources = detect_charged_language(story.articles)

    quality = filter_story_quality(
        categorized,
        {**settings["quality_filter"], "section_rules": settings["categorization"]["rules"]},
    )
    ranked = rank_stories(quality, settings["ranking"])
    logger.info("[perf] Categorize+rank: %.1fs (%d ranked)", time.time() - t2, len(ranked))

    nba_in_ranked = [s for s in ranked if s.category == "nba"]
    logger.info("pipeline_api: %d NBA stories in ranked list (pre-cap)", len(nba_in_ranked))
    candidates = _select_stories_with_section_guarantees(
        ranked,
        section_limits=settings["section_limits"],
        global_cap=int(settings["pipeline"]["max_stories_to_rank"]),
    )
    stories_by_section = _select_stories_by_section(candidates, settings["section_limits"])

    new_registry: dict[str, Story] = {}
    result_sections: dict[str, list[dict]] = {}

    for section, stories in stories_by_section.items():
        result_sections[section] = []
        for story in stories:
            sid = _make_story_id(story)
            new_registry[sid] = story
            result_sections[section].append(_story_to_dict(story, sid))

    _story_registry = new_registry
    logger.info(
        "pipeline_api: pipeline complete — %d stories across %d sections, %d in registry",
        sum(len(v) for v in result_sections.values()),
        len(result_sections),
        len(_story_registry),
    )
    logger.info("[perf] Total pipeline: %.1fs", time.time() - t0)

    nba_buzz = None
    if os.environ.get("GROK_ENABLED", "false").lower() == "true":
        logger.info("[pipeline] Fetching NBA social buzz from Grok...")
        nba_buzz = get_nba_social_buzz()
        if nba_buzz is None:
            logger.warning("[pipeline] NBA social buzz unavailable — Grok call returned None")
    else:
        logger.info("[pipeline] GROK_ENABLED is false — skipping NBA social buzz")

    # AI_SOCIAL_ENABLED gates this; fetch_ai_buzz() handles its own env check
    logger.info("[pipeline] Fetching AI social buzz from Grok...")
    ai_buzz = fetch_ai_buzz()
    if ai_buzz is None:
        logger.info("[pipeline] AI social buzz unavailable or disabled")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": result_sections,
        "nba_social_buzz": nba_buzz,
        "ai_social_buzz": ai_buzz,
    }


def get_story_summary(story_id: str, story_data: dict) -> dict:
    """
    Generates a summary for a single story using the existing summarize.py logic.
    Returns summary text, and left_take/right_take if the story is in the 'top' section.

    story_data is the dict returned by get_ranked_stories() for this story (used
    for the response shape only — the actual Story object is looked up from the registry).
    """
    story = _story_registry.get(story_id)
    if story is None:
        raise KeyError(f"Story {story_id!r} not found in registry. Call /sections first.")

    _, settings = _load_config()

    summarize_stories(
        stories=[story],
        settings=settings["summarization"],
        api_key=os.getenv("OPENAI_API_KEY"),
    )

    result: dict[str, Any] = {
        "story_id": story_id,
        "summary": story.newsletter_blurb,
        "confirmed_facts": story.confirmed_facts,
        "why_it_matters": story.why_it_matters,
        "sources": story.source_names,
    }

    if story.category == "top":
        result["left_take"] = story.left_take
        result["right_take"] = story.right_take

    logger.info(
        "pipeline_api: summary generated for story_id=%s (section=%s, openai_enabled=%s)",
        story_id,
        story.category,
        settings["summarization"].get("openai_enabled"),
    )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_story_id(story: Story) -> str:
    url = story.primary_link or story.cluster_id
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def _story_to_dict(story: Story, sid: str) -> dict:
    return {
        "id": sid,
        "headline": story.representative_headline or story.title,
        "source": story.source_names[0] if story.source_names else "",
        "sources": list({a.source_name for a in story.articles}),
        "url": story.primary_link,
        "published_at": story.latest_published_at.isoformat() if story.latest_published_at else None,
        "section": story.category,
        "bias_flags": list(story.charged_sources.keys()) if story.charged_sources else [],
        "has_left_right": story.category == "top",
        "source_balance": story.source_balance,
    }


def _select_stories_with_section_guarantees(
    ranked: list[Story],
    section_limits: dict,
    global_cap: int,
) -> list[Story]:
    """
    Take the top `global_cap` stories by rank, then guarantee each section
    gets at least its limit by reaching into the cut tail for underfilled sections.
    """
    candidates = ranked[:global_cap]
    section_counts: dict[str, int] = {}
    for story in candidates:
        section_counts[story.category] = section_counts.get(story.category, 0) + 1

    already_included = {id(s) for s in candidates}
    extras: list[Story] = []

    for section, limit in section_limits.items():
        needed = int(limit) - section_counts.get(section, 0)
        if needed <= 0:
            continue
        for story in ranked[global_cap:]:
            if needed <= 0:
                break
            if story.category == section and id(story) not in already_included:
                extras.append(story)
                already_included.add(id(story))
                needed -= 1

    return candidates + extras


def _select_stories_by_section(
    stories: list[Story],
    section_limits: dict,
) -> dict[str, list[Story]]:
    result: dict[str, list[Story]] = {
        s: [] for s in ["top", "markets", "ai", "finance_market_structure", "nba"]
    }
    for story in stories:
        if story.category not in result:
            continue
        limit = int(section_limits.get(story.category, 0))
        if len(result[story.category]) >= limit:
            continue
        result[story.category].append(story)
    return result


def _load_config() -> tuple[list[FeedSource], dict]:
    load_dotenv()
    sources_cfg = _load_yaml(_ROOT / "config" / "sources.yaml")
    settings = _apply_runtime_overrides(_load_yaml(_ROOT / "config" / "settings.yaml"))
    sources = [FeedSource(**item) for item in sources_cfg["sources"]]
    return sources, settings


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _apply_runtime_overrides(settings: dict) -> dict:
    s = copy.deepcopy(settings)
    p = s["pipeline"]
    summ = s["summarization"]

    p["openai_enabled"] = _env_bool("OPENAI_ENABLED", p["openai_enabled"])
    p["max_total_stories_fetched"] = _env_int("MAX_STORIES_FETCHED", p["max_total_stories_fetched"])
    p["max_stories_to_rank"] = _env_int("MAX_STORIES_TO_RANK", p["max_stories_to_rank"])
    p["max_stories_to_summarize"] = _env_int("MAX_STORIES_TO_SUMMARIZE", p.get("max_stories_to_summarize", 10))

    summ["openai_enabled"] = p["openai_enabled"]
    summ["model"] = os.getenv("OPENAI_MODEL", summ["model"])

    return s


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return bool(default) if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    return int(default) if v is None else int(v)


