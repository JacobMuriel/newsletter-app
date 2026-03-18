from __future__ import annotations

import html
import hashlib
import logging
import re
from datetime import datetime, timezone
from time import struct_time
from typing import Iterable

import feedparser

from news_pipeline.models import Article, FeedSource, FetchStats

logger = logging.getLogger(__name__)

HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")


def fetch_news(
    sources: Iterable[FeedSource],
    max_items_per_feed: int,
    max_total_stories: int,
) -> tuple[list[Article], FetchStats]:
    """Fetch RSS entries and normalize them into article records."""

    articles: list[Article] = []
    stats = FetchStats()

    for source in sources:
        if len(articles) >= max_total_stories:
            logger.info("Reached total raw-story cap of %s stories", max_total_stories)
            break

        if not source.enabled:
            logger.info("Skipping disabled feed %s", source.name)
            continue

        stats.feeds_attempted += 1
        logger.info("Fetching RSS feed from %s", source.name)

        try:
            parsed_feed = feedparser.parse(source.feed_url)
        except Exception:
            logger.exception("Failed to fetch feed from %s", source.feed_url)
            stats.feeds_failed.append(source.name)
            continue

        if getattr(parsed_feed, "bozo", False):
            logger.warning("Feed parser reported a malformed feed for %s", source.name)
            if not getattr(parsed_feed, "entries", []):
                stats.feeds_failed.append(source.name)
                continue

        for entry in parsed_feed.entries[:max_items_per_feed]:
            if len(articles) >= max_total_stories:
                break

            title = _clean_text(entry.get("title", "Untitled story"))
            raw_summary = entry.get("summary") or entry.get("description") or ""
            cleaned_summary = _clean_text(raw_summary)
            link = entry.get("link", "")

            published_at = _parse_published_datetime(
                entry.get("published_parsed") or entry.get("updated_parsed")
            )
            published_date = published_at.isoformat() if published_at else entry.get("published", "")
            article = Article(
                article_id=_build_article_id(source_name=source.name, link=link, title=title),
                title=title,
                summary=_clean_text(raw_summary),
                snippet=cleaned_summary,
                source_name=source.name,
                source_label=source.ideology_label,
                source_tags=list(source.tags),
                link=link,
                published_date=published_date,
                published_at=published_at,
                outlet_group=source.outlet_group or source.name,
                reliability_weight=float(source.reliability_weight),
            )
            articles.append(article)

    logger.info("Fetched %s raw articles before clustering", len(articles))
    return articles, stats


def _clean_text(value: str) -> str:
    unescaped = html.unescape(value or "")
    without_tags = HTML_TAG_PATTERN.sub(" ", unescaped)
    return WHITESPACE_PATTERN.sub(" ", without_tags).strip()


def _parse_published_datetime(value: struct_time | None) -> datetime | None:
    if value is None:
        return None

    try:
        return datetime(*value[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _build_article_id(*, source_name: str, link: str, title: str) -> str:
    digest = hashlib.sha1(f"{source_name}|{link}|{title}".encode("utf-8")).hexdigest()
    return digest[:16]
