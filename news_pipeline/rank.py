from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from news_pipeline.models import Story

logger = logging.getLogger(__name__)

_TOP_MIN_SOURCES = 2


def rank_stories(stories: list[Story], settings: dict[str, Any]) -> list[Story]:
    weights: dict[str, float] = settings["weights"]
    category_importance: dict[str, float] = settings["category_importance"]
    keyword_sets: dict[str, list[str]] = settings["keyword_sets"]
    source_priority_settings: dict[str, Any] = settings["source_priority"]
    now = datetime.now(timezone.utc)

    for story in stories:
        story_text = story.combined_text.lower()
        cluster_strength = min(story.cluster_size, 6)
        source_quality = _source_priority_score(story, source_priority_settings)
        outlet_spread = min(story.outlet_group_count, 4)
        corroboration = round(story.corroboration_score * 4, 2)
        major_outlet_presence = _major_outlet_bonus(story, source_priority_settings)
        category_score = float(category_importance.get(story.category, 1.0))
        impact_keywords = _count_keyword_hits(story_text, keyword_sets["high_impact"])
        personal_relevance = _count_keyword_hits(story_text, keyword_sets["personal_relevance"])
        recency = _compute_recency_bonus(story.latest_published_at, now)
        ideological_spread = _compute_ideological_spread(story)

        story.source_priority_score = source_quality
        story.importance_score = round(
            (cluster_strength * weights["cluster_strength"])
            + (source_quality * weights["source_quality"])
            + (outlet_spread * weights["outlet_spread"])
            + (corroboration * weights["corroboration"])
            + (major_outlet_presence * weights["major_outlet_presence"])
            + (category_score * weights["category_importance"])
            + (impact_keywords * weights["impact_keywords"])
            + (personal_relevance * weights["personal_relevance"])
            + (recency * weights["recency"])
            + (ideological_spread * weights.get("ideological_spread", 2.0)),
            2,
        )
        story.ranking_notes = [
            f"cluster_strength={cluster_strength}",
            f"source_quality={source_quality}",
            f"outlet_spread={outlet_spread}",
            f"corroboration={corroboration}",
            f"major_outlets={major_outlet_presence}",
            f"category_importance={category_score}",
            f"impact_keywords={impact_keywords}",
            f"personal_relevance={personal_relevance}",
            f"recency={recency}",
            f"ideological_spread={ideological_spread}",
        ]
        story.refresh_metadata()

    ranked = sorted(stories, key=lambda story: story.importance_score, reverse=True)

    filtered: list[Story] = []
    for story in ranked:
        if story.category == "top":
            unique_sources = len({a.source_name for a in story.articles})
            if unique_sources < _TOP_MIN_SOURCES:
                logger.info(
                    '[rank] dropping "%s" from top — only %d unique source%s',
                    story.title,
                    unique_sources,
                    "" if unique_sources == 1 else "s",
                )
                continue
        filtered.append(story)

    return filtered


def _count_keyword_hits(story_text: str, keywords: list[str]) -> int:
    hits = sum(1 for keyword in keywords if keyword.lower() in story_text)
    return min(hits, 5)


def _compute_recency_bonus(published_at: datetime | None, now: datetime) -> float:
    if published_at is None:
        return 0.2

    hours_old = max((now - published_at).total_seconds() / 3600, 0.0)
    if hours_old <= 6:
        return 3.0
    if hours_old <= 12:
        return 2.4
    if hours_old <= 24:
        return 1.8
    if hours_old <= 48:
        return 1.0
    return round(max(0.2, 1 / math.log(hours_old + 2)), 2)


def _source_priority_score(story: Story, settings: dict[str, Any]) -> float:
    priority_weights: dict[str, float] = settings["weights"]
    default_score = float(settings["default"])
    scores = [priority_weights.get(article.source_name, default_score) for article in story.articles]
    if not scores:
        return default_score
    return round(sum(scores) / len(scores), 2)


def _major_outlet_bonus(story: Story, settings: dict[str, Any]) -> float:
    bonus_sources = set(settings.get("major_outlets", []))
    if not bonus_sources:
        return 0.0
    matching = {article.source_name for article in story.articles if article.source_name in bonus_sources}
    return min(len(matching), 3)


def _compute_ideological_spread(story: Story) -> float:
    """Score cross-ideological corroboration.

    The more distinct political perspectives (left, center, right) represented
    in the cluster, the stronger the signal that a story is genuinely important
    rather than being amplified by a single ideological bubble.

    Scores:
      3 ideologies → 3.0  (strongest signal: left + center + right all covering it)
      2 ideologies → 1.5  (solid cross-aisle corroboration)
      1 ideology   → 0.5  (echo-chamber risk)
      0 labeled    → 0.0  (non-political sources only, e.g. finance/tech/sports)
    """
    distinct_ideologies = {
        label
        for label in story.source_labels
        if label in {"left", "center", "right"}
    }
    count = len(distinct_ideologies)
    if count >= 3:
        return 3.0
    if count == 2:
        return 1.5
    if count == 1:
        return 0.5
    return 0.0
