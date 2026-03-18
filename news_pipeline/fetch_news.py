from __future__ import annotations

import html
import hashlib
import logging
import re
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from time import struct_time
from typing import Iterable

import feedparser

from news_pipeline.models import Article, FeedSource, FetchStats

logger = logging.getLogger(__name__)

HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")

_FETCH_TIMEOUT = 15      # seconds per feed
_MAX_WORKERS   = 12      # parallel feed fetches


def fetch_news(
    sources: Iterable[FeedSource],
    max_items_per_feed: int,
    max_total_stories: int,
) -> tuple[list[Article], FetchStats]:
    """Fetch RSS feeds in parallel and normalize into article records."""

    source_list = [s for s in sources if s.enabled]
    stats = FetchStats()
    stats.feeds_attempted = len(source_list)

    # Fetch all feeds concurrently
    raw_results: list[tuple[FeedSource, list]] = []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one_feed, src): src for src in source_list}
        for future in as_completed(futures):
            src = futures[future]
            entries = future.result()
            if entries is None:
                stats.feeds_failed.append(src.name)
            else:
                raw_results.append((src, entries))

    # Preserve original source order for deterministic output
    order = {s.name: i for i, s in enumerate(source_list)}
    raw_results.sort(key=lambda t: order.get(t[0].name, 999))

    articles: list[Article] = []
    for source, entries in raw_results:
        if len(articles) >= max_total_stories:
            break
        for entry in entries[:max_items_per_feed]:
            if len(articles) >= max_total_stories:
                break
            article = _entry_to_article(entry, source)
            if article:
                articles.append(article)

    logger.info("Fetched %d raw articles from %d feeds (%d failed)",
                len(articles), len(raw_results), len(stats.feeds_failed))
    return articles, stats


def _fetch_one_feed(source: FeedSource) -> list | None:
    """Fetch and parse a single RSS feed. Returns entries list or None on failure."""
    try:
        req = urllib.request.Request(
            source.feed_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Briefing/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            feed_content = resp.read()
        parsed = feedparser.parse(feed_content)
        if getattr(parsed, "bozo", False) and not getattr(parsed, "entries", []):
            logger.warning("Malformed feed, no entries: %s", source.name)
            return None
        logger.info("Fetched %d entries from %s", len(parsed.entries), source.name)
        return list(parsed.entries)
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", source.name, exc)
        return None


def _entry_to_article(entry: dict, source: FeedSource) -> Article | None:
    title = _clean_text(entry.get("title", "Untitled story"))
    raw_summary = entry.get("summary") or entry.get("description") or ""
    cleaned_summary = _clean_text(raw_summary)
    link = entry.get("link", "")
    published_at = _parse_published_datetime(
        entry.get("published_parsed") or entry.get("updated_parsed")
    )
    published_date = published_at.isoformat() if published_at else entry.get("published", "")
    return Article(
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
