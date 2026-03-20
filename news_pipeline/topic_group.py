from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from news_pipeline.models import Story

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are grouping news headlines into mega-stories. "
    "Return only a JSON object with key 'groups': a list of lists of integer indices. "
    "Each inner list is a group of headlines about the exact same real-world event. "
    "Single headlines that don't match anything are their own group. "
    "Only group headlines that are clearly the same event — err on the side of NOT grouping if unsure."
)

_TOP_N = 35


def group_stories_by_topic(
    stories: list[Story],
    settings: dict[str, Any],
    api_key: str | None,
) -> list[Story]:
    if not settings.get("summarization", {}).get("openai_enabled", True):
        return stories
    if not api_key:
        return stories

    try:
        return _run(stories, api_key)
    except Exception as exc:
        logger.warning("[topic_group] failed, returning stories unchanged — %s: %s", type(exc).__name__, exc)
        return stories


def _run(stories: list[Story], api_key: str) -> list[Story]:
    top = sorted(stories, key=lambda s: s.corroboration_score, reverse=True)[:_TOP_N]
    rest = [s for s in stories if id(s) not in {id(x) for x in top}]

    headline_lines = "\n".join(f"{i}: {s.title}" for i, s in enumerate(top))

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": headline_lines},
        ],
    )
    raw = response.choices[0].message.content or ""
    groups: list[list[int]] = json.loads(raw).get("groups", [])

    merged_top = _apply_groups(top, groups)
    return merged_top + rest


def _apply_groups(top: list[Story], groups: list[list[int]]) -> list[Story]:
    absorbed: set[int] = set()
    replacements: dict[int, Story] = {}

    for group in groups:
        valid = [i for i in group if 0 <= i < len(top)]
        if len(valid) < 2:
            continue

        primary_idx = max(valid, key=lambda i: top[i].corroboration_score)
        secondary_idxs = [i for i in valid if i != primary_idx]

        primary = top[primary_idx]
        combined_articles = list(primary.articles)
        seen_ids = {a.article_id for a in combined_articles}

        for i in secondary_idxs:
            for article in top[i].articles:
                if article.article_id not in seen_ids:
                    combined_articles.append(article)
                    seen_ids.add(article.article_id)

        primary.articles = combined_articles
        primary.refresh_metadata()

        absorbed.update(secondary_idxs)
        replacements[primary_idx] = primary

        logger.info(
            '[topic_group] merged %d clusters → "%s" (%d total articles)',
            len(valid),
            primary.title,
            len(combined_articles),
        )

    result = []
    for i, story in enumerate(top):
        if i in absorbed:
            continue
        result.append(replacements.get(i, story))
    return result
