from __future__ import annotations

import logging
from typing import Any

from news_pipeline.models import Story

logger = logging.getLogger(__name__)


def filter_story_quality(stories: list[Story], settings: dict[str, Any]) -> list[Story]:
    filtered: list[Story] = []
    minimum_score = float(settings["minimum_score"])
    vague_title_patterns: list[str] = settings["vague_title_patterns"]
    minimum_summary_length = int(settings["minimum_summary_length"])

    for story in stories:
        score = 6.0
        reasons: list[str] = []
        combined_text = story.combined_text.lower()

        if story.category != "top" and story.category_score <= 0:
            score -= float(settings["weak_section_match_penalty"])
            reasons.append("weak niche-section match")

        if any(pattern in story.title.lower() for pattern in vague_title_patterns):
            score -= float(settings["vague_title_penalty"])
            reasons.append("vague title")

        if len(story.cleaned_summary.strip()) < minimum_summary_length:
            score -= float(settings["empty_summary_penalty"])
            reasons.append("thin summary")

        if story.category != "top" and not _source_matches_section(story, story.category, settings):
            score -= float(settings["section_source_penalty"])
            reasons.append("off-topic source for section")

        if len(combined_text.split()) < 8:
            score -= 1
            reasons.append("too little source text")

        story.quality_score = round(score, 2)
        if score < minimum_score:
            story.rejection_reason = ", ".join(reasons) or "below quality threshold"
            logger.info("Rejected story '%s': %s", story.title, story.rejection_reason)
            continue

        logger.info(
            "Kept story '%s' with quality score %.2f for section %s",
            story.title,
            story.quality_score,
            story.category,
        )
        filtered.append(story)

    return filtered


def _source_matches_section(story: Story, category: str, settings: dict[str, Any]) -> bool:
    section_settings = settings.get("section_rules", {}).get(category, {})
    preferred_sources = set(section_settings.get("preferred_sources", []))
    if not preferred_sources:
        return True
    return any(source in preferred_sources for source in story.source_names)
