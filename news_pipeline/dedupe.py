from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

from news_pipeline.models import Story

logger = logging.getLogger(__name__)

NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9\s]")
WHITESPACE_PATTERN = re.compile(r"\s+")
TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9\-']+")
ENTITY_PATTERN = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")


def deduplicate_stories(stories: list[Story], settings: dict[str, Any]) -> list[Story]:
    """Merge obviously similar items into a single canonical story."""

    if not stories:
        return []

    title_threshold = float(settings["title_similarity_threshold"])
    summary_threshold = float(settings["summary_similarity_threshold"])
    combined_threshold = float(settings["combined_similarity_threshold"])
    token_overlap_threshold = float(settings["token_overlap_threshold"])
    entity_overlap_min = int(settings["entity_overlap_min"])

    deduped: list[Story] = []

    # TODO: Replace this pairwise heuristic with stronger event clustering once V2 needs higher recall.
    for story in stories:
        canonical = _find_matching_story(
            candidate=story,
            existing=deduped,
            title_threshold=title_threshold,
            summary_threshold=summary_threshold,
            combined_threshold=combined_threshold,
            token_overlap_threshold=token_overlap_threshold,
            entity_overlap_min=entity_overlap_min,
        )

        if canonical is None:
            deduped.append(story)
            continue

        logger.info("Merging duplicate '%s' into '%s'", story.title, canonical.title)
        canonical.merge_from(story)

    logger.info("Reduced %s raw stories to %s deduplicated stories", len(stories), len(deduped))
    return deduped


def _find_matching_story(
    *,
    candidate: Story,
    existing: list[Story],
    title_threshold: float,
    summary_threshold: float,
    combined_threshold: float,
    token_overlap_threshold: float,
    entity_overlap_min: int,
) -> Story | None:
    for current in existing:
        title_similarity = _similarity(candidate.title, current.title)
        summary_similarity = _similarity(candidate.cleaned_summary, current.cleaned_summary)
        combined_similarity = (title_similarity * 0.7) + (summary_similarity * 0.3)
        token_overlap = _token_overlap(candidate.combined_text, current.combined_text)
        entity_overlap = _entity_overlap(candidate.title, current.title)

        if title_similarity >= title_threshold:
            return current
        if summary_similarity >= summary_threshold and combined_similarity >= combined_threshold:
            return current
        if combined_similarity >= combined_threshold:
            return current
        if token_overlap >= token_overlap_threshold and entity_overlap >= entity_overlap_min:
            return current

    return None


def _similarity(left: str, right: str) -> float:
    left_text = _normalize(left)
    right_text = _normalize(right)

    if not left_text or not right_text:
        return 0.0

    return SequenceMatcher(None, left_text, right_text).ratio()


def _normalize(text: str) -> str:
    lowered = text.lower().strip()
    without_symbols = NON_ALNUM_PATTERN.sub(" ", lowered)
    return WHITESPACE_PATTERN.sub(" ", without_symbols).strip()


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(TOKEN_PATTERN.findall(_normalize(left)))
    right_tokens = set(TOKEN_PATTERN.findall(_normalize(right)))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def _entity_overlap(left: str, right: str) -> int:
    left_entities = {entity.lower() for entity in ENTITY_PATTERN.findall(left)}
    right_entities = {entity.lower() for entity in ENTITY_PATTERN.findall(right)}
    return len(left_entities & right_entities)
