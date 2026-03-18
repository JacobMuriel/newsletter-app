from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class FeedSource:
    """Configurable RSS source definition."""

    name: str
    feed_url: str
    ideology_label: str
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    outlet_group: str = ""
    reliability_weight: float = 1.0


@dataclass(frozen=True)
class Article:
    """Normalized article record captured during feed ingestion."""

    article_id: str
    title: str
    summary: str
    snippet: str
    source_name: str
    source_label: str
    source_tags: list[str] = field(default_factory=list)
    link: str = ""
    published_date: str = ""
    published_at: datetime | None = None
    outlet_group: str = ""
    reliability_weight: float = 1.0

    @property
    def combined_text(self) -> str:
        return " ".join(part for part in [self.title, self.snippet or self.summary] if part).strip()


@dataclass
class Story:
    """Clustered story object shared across the rest of the pipeline."""

    cluster_id: str
    articles: list[Article]

    title: str
    raw_summary: str
    cleaned_summary: str = ""
    representative_headline: str = ""
    topic: str = ""
    source_names: list[str] = field(default_factory=list)
    source_labels: list[str] = field(default_factory=list)
    source_labels_present: list[str] = field(default_factory=list)
    source_tags: list[str] = field(default_factory=list)
    outlet_groups: list[str] = field(default_factory=list)
    ideology_counts: dict[str, int] = field(default_factory=dict)
    links: list[str] = field(default_factory=list)
    published_dates: list[str] = field(default_factory=list)
    earliest_published_at: datetime | None = None
    latest_published_at: datetime | None = None
    cluster_size: int = 1
    category: str = "top"
    importance_score: float = 0.0
    source_priority_score: float = 0.0
    corroboration_score: float = 0.0
    newsletter_blurb: str = ""
    confirmed_facts: str = ""
    why_it_matters: str = ""
    section_note_label: str = ""
    section_note: str = ""
    left_take: str = ""
    right_take: str = ""
    confidence_label: str = "Low"
    confidence_reason: str = ""
    matched_keywords: list[str] = field(default_factory=list)
    ranking_notes: list[str] = field(default_factory=list)
    category_reason: str = ""
    category_score: int = 0
    quality_score: float = 0.0
    rejection_reason: str = ""
    charged_sources: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.refresh_metadata()

    @property
    def source_count(self) -> int:
        return len(set(self.source_names))

    @property
    def outlet_group_count(self) -> int:
        return len(set(self.outlet_groups))

    @property
    def primary_link(self) -> str:
        return self.links[0] if self.links else ""

    @property
    def combined_text(self) -> str:
        article_text = " ".join(article.combined_text for article in self.articles[:4])
        return " ".join(
            part for part in [self.title, self.cleaned_summary or self.raw_summary, article_text] if part
        ).strip()

    def refresh_metadata(self) -> None:
        self.cluster_size = len(self.articles) or self.cluster_size

        if self.articles:
            self.source_names = _unique_preserving_order(article.source_name for article in self.articles)
            self.source_labels = [article.source_label for article in self.articles]
            self.source_labels_present = _unique_preserving_order(self.source_labels)
            self.source_tags = _unique_preserving_order(
                tag for article in self.articles for tag in article.source_tags
            )
            self.outlet_groups = _unique_preserving_order(
                article.outlet_group or article.source_name for article in self.articles
            )
            self.links = _unique_preserving_order(article.link for article in self.articles)
            self.published_dates = _unique_preserving_order(article.published_date for article in self.articles)
            published_values = [article.published_at for article in self.articles if article.published_at]
            self.earliest_published_at = min(published_values) if published_values else None
            self.latest_published_at = max(published_values) if published_values else None

        self.ideology_counts = dict(Counter(self.source_labels))
        self.matched_keywords = _unique_preserving_order(self.matched_keywords)
        self.ranking_notes = _unique_preserving_order(self.ranking_notes)
        self.links = _unique_preserving_order(self.links)
        self.published_dates = _unique_preserving_order(self.published_dates)

        if not self.representative_headline:
            self.representative_headline = self.title
        if not self.cleaned_summary:
            self.cleaned_summary = self.raw_summary


@dataclass
class FetchStats:
    feeds_attempted: int = 0
    feeds_failed: list[str] = field(default_factory=list)


@dataclass
class SummarizationStats:
    stories_sent_to_openai: int = 0
    stories_using_fallback: int = 0
    estimated_openai_calls: int = 0
    openai_quota_exhausted: bool = False


@dataclass
class NBABrief:
    rockets_bulls_recaps: list[str] = field(default_factory=list)
    rockets_bulls_performers: list[str] = field(default_factory=list)
    big_performances: list[str] = field(default_factory=list)
    game_recaps: list[str] = field(default_factory=list)
    source_names: list[str] = field(default_factory=list)


def _unique_preserving_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    for item in items:
        if not item:
            continue
        if item not in seen:
            seen.add(item)
            ordered.append(item)

    return ordered
