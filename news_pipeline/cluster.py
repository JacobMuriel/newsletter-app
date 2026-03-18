from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from news_pipeline.models import Article, Story

NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9\s]")
TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9\-/']+")
ENTITY_PATTERN = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "to",
    "with",
    "after",
    "amid",
    "over",
    "says",
    "say",
    "new",
    "latest",
    "update",
    "updates",
    "live",
}
GEOPOLITICAL_TERMS = {
    "ukraine",
    "russia",
    "gaza",
    "israel",
    "hamas",
    "china",
    "taiwan",
    "iran",
    "syria",
    "ceasefire",
    "sanctions",
    "military",
    "tariff",
    "tariffs",
    "talks",
    "summit",
}


@dataclass
class _ClusterCandidate:
    cluster_id: str
    articles: list[Article] = field(default_factory=list)
    similarity_samples: list[float] = field(default_factory=list)

    def add(self, article: Article, similarity: float | None = None) -> None:
        self.articles.append(article)
        if similarity is not None:
            self.similarity_samples.append(similarity)

    @property
    def representative_article(self) -> Article:
        return max(
            self.articles,
            key=lambda article: (
                article.reliability_weight,
                len(article.snippet),
                article.published_at.timestamp() if article.published_at else 0.0,
            ),
        )

    @property
    def corroboration_score(self) -> float:
        if not self.similarity_samples:
            return 0.0
        return round(sum(self.similarity_samples) / len(self.similarity_samples), 2)


def cluster_articles(articles: list[Article], settings: dict[str, Any]) -> list[Story]:
    """Group raw articles into event-level clusters using fuzzy + TF-IDF similarity."""

    if not articles:
        return []

    ordered_articles = sorted(
        articles,
        key=lambda article: article.published_at.timestamp() if article.published_at else 0.0,
        reverse=True,
    )
    tfidf_vectors, idf = _build_tfidf_vectors(ordered_articles)
    article_vectors = {article.article_id: tfidf_vectors[index] for index, article in enumerate(ordered_articles)}

    clusters: list[_ClusterCandidate] = []
    min_similarity = float(settings["min_similarity"])
    merge_similarity = float(settings["merge_similarity"])
    max_cluster_articles = int(settings.get("max_cluster_articles", 8))

    for article in ordered_articles:
        best_cluster: _ClusterCandidate | None = None
        best_similarity = 0.0

        for cluster in clusters:
            similarity = _article_cluster_similarity(
                article=article,
                cluster=cluster,
                article_vectors=article_vectors,
                settings=settings,
            )
            if similarity > best_similarity:
                best_similarity = similarity
                best_cluster = cluster

        if best_cluster is not None and best_similarity >= min_similarity:
            if len(best_cluster.articles) < max_cluster_articles:
                best_cluster.add(article, similarity=best_similarity)
            else:
                clusters.append(_ClusterCandidate(cluster_id=_cluster_id(len(clusters)), articles=[article]))
            continue

        clusters.append(_ClusterCandidate(cluster_id=_cluster_id(len(clusters)), articles=[article]))

    clusters = _merge_related_clusters(
        clusters=clusters,
        article_vectors=article_vectors,
        merge_similarity=merge_similarity,
        settings=settings,
    )
    return [_build_story(cluster, idf) for cluster in clusters]


def _merge_related_clusters(
    *,
    clusters: list[_ClusterCandidate],
    article_vectors: dict[str, dict[str, float]],
    merge_similarity: float,
    settings: dict[str, Any],
) -> list[_ClusterCandidate]:
    merged: list[_ClusterCandidate] = []

    for cluster in clusters:
        target: _ClusterCandidate | None = None
        best_similarity = 0.0

        for current in merged:
            similarity = _cluster_to_cluster_similarity(
                left=cluster,
                right=current,
                article_vectors=article_vectors,
                settings=settings,
            )
            if similarity > best_similarity:
                best_similarity = similarity
                target = current

        if target is not None and best_similarity >= merge_similarity:
            for article in cluster.articles:
                target.add(article, similarity=best_similarity)
            continue

        merged.append(cluster)

    return merged


def _build_story(cluster: _ClusterCandidate, idf: dict[str, float]) -> Story:
    articles = sorted(
        cluster.articles,
        key=lambda article: (
            article.published_at.timestamp() if article.published_at else 0.0,
            article.reliability_weight,
            len(article.snippet),
        ),
        reverse=True,
    )
    representative = max(
        articles,
        key=lambda article: (
            article.reliability_weight,
            len(article.snippet),
            article.published_at.timestamp() if article.published_at else 0.0,
        ),
    )
    raw_summary = " ".join(article.snippet for article in articles[:3] if article.snippet).strip()
    topic = _infer_topic_label(articles, idf)

    story = Story(
        cluster_id=cluster.cluster_id,
        articles=articles,
        title=representative.title,
        representative_headline=representative.title,
        raw_summary=raw_summary,
        cleaned_summary=raw_summary,
        topic=topic,
        corroboration_score=cluster.corroboration_score,
    )
    story.refresh_metadata()
    return story


def _article_cluster_similarity(
    *,
    article: Article,
    cluster: _ClusterCandidate,
    article_vectors: dict[str, dict[str, float]],
    settings: dict[str, Any],
) -> float:
    best = 0.0
    for existing in cluster.articles[:4]:
        best = max(
            best,
            _article_similarity(
                left=article,
                right=existing,
                left_vector=article_vectors[article.article_id],
                right_vector=article_vectors[existing.article_id],
                settings=settings,
            ),
        )
    return round(best, 3)


def _cluster_to_cluster_similarity(
    *,
    left: _ClusterCandidate,
    right: _ClusterCandidate,
    article_vectors: dict[str, dict[str, float]],
    settings: dict[str, Any],
) -> float:
    left_article = left.representative_article
    right_article = right.representative_article
    similarity = _article_similarity(
        left=left_article,
        right=right_article,
        left_vector=article_vectors[left_article.article_id],
        right_vector=article_vectors[right_article.article_id],
        settings=settings,
    )
    shared_entities = _shared_entities(left_article.combined_text, right_article.combined_text)
    if shared_entities >= int(settings.get("merge_entity_bonus_min", 2)):
        similarity += float(settings.get("merge_entity_bonus", 0.04))
    return round(min(similarity, 1.0), 3)


def _article_similarity(
    *,
    left: Article,
    right: Article,
    left_vector: dict[str, float],
    right_vector: dict[str, float],
    settings: dict[str, Any],
) -> float:
    title_similarity = _sequence_similarity(left.title, right.title)
    snippet_similarity = _sequence_similarity(left.snippet, right.snippet)
    token_overlap = _token_overlap(left.combined_text, right.combined_text)
    cosine_similarity = _cosine_similarity(left_vector, right_vector)
    shared_entities = _shared_entities(left.combined_text, right.combined_text)
    shared_geopolitics = _shared_geopolitics(left.combined_text, right.combined_text)
    shared_storyline_terms = _shared_storyline_terms(left.combined_text, right.combined_text)
    shared_keyphrases = _shared_keyphrases(left.combined_text, right.combined_text)

    score = (
        title_similarity * float(settings["weights"]["title"])
        + snippet_similarity * float(settings["weights"]["snippet"])
        + token_overlap * float(settings["weights"]["token_overlap"])
        + cosine_similarity * float(settings["weights"]["tfidf_cosine"])
    )

    if shared_entities >= int(settings.get("entity_overlap_min", 2)):
        score += float(settings.get("entity_bonus", 0.03))
    if shared_geopolitics:
        score += float(settings.get("geopolitics_bonus", 0.04))
    if shared_storyline_terms >= int(settings.get("storyline_overlap_min", 2)):
        score += float(settings.get("storyline_bonus", 0.06))
    if shared_keyphrases:
        score += float(settings.get("keyphrase_bonus", 0.08))

    return min(score, 1.0)


def _build_tfidf_vectors(articles: list[Article]) -> tuple[list[dict[str, float]], dict[str, float]]:
    tokenized = [_important_tokens(article.combined_text) for article in articles]
    document_frequency = Counter()

    for tokens in tokenized:
        document_frequency.update(set(tokens))

    article_count = max(len(articles), 1)
    idf = {
        token: math.log((1 + article_count) / (1 + frequency)) + 1
        for token, frequency in document_frequency.items()
    }
    vectors: list[dict[str, float]] = []

    for tokens in tokenized:
        counts = Counter(tokens)
        total = sum(counts.values()) or 1
        vector = {
            token: (count / total) * idf[token]
            for token, count in counts.items()
        }
        vectors.append(vector)

    return vectors, idf


def _infer_topic_label(articles: list[Article], idf: dict[str, float]) -> str:
    tag_counts = Counter(tag for article in articles for tag in article.source_tags if tag not in {"global", "national"})
    if tag_counts:
        return tag_counts.most_common(1)[0][0]

    token_scores = Counter()
    for article in articles:
        for token in _important_tokens(article.combined_text):
            token_scores[token] += idf.get(token, 1.0)

    if not token_scores:
        return "general"
    return token_scores.most_common(1)[0][0]


def _sequence_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, _normalize(left), _normalize(right)).ratio()


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(_important_tokens(left))
    right_tokens = set(_important_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def _shared_entities(left: str, right: str) -> int:
    left_entities = {value.lower() for value in ENTITY_PATTERN.findall(left)}
    right_entities = {value.lower() for value in ENTITY_PATTERN.findall(right)}
    return len(left_entities & right_entities)


def _shared_geopolitics(left: str, right: str) -> bool:
    left_tokens = set(_important_tokens(left))
    right_tokens = set(_important_tokens(right))
    return bool((left_tokens & right_tokens) & GEOPOLITICAL_TERMS)


def _shared_storyline_terms(left: str, right: str) -> int:
    left_tokens = set(_important_tokens(left))
    right_tokens = set(_important_tokens(right))
    return len(left_tokens & right_tokens)


def _shared_keyphrases(left: str, right: str) -> bool:
    left_phrases = set(_important_phrases(left))
    right_phrases = set(_important_phrases(right))
    return bool(left_phrases & right_phrases)


def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0

    shared = set(left) & set(right)
    numerator = sum(left[token] * right[token] for token in shared)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _important_tokens(text: str) -> list[str]:
    return [token for token in TOKEN_PATTERN.findall(_normalize(text)) if token not in STOPWORDS and len(token) > 2]


def _important_phrases(text: str) -> list[str]:
    tokens = _important_tokens(text)
    phrases: list[str] = []
    for size in (2, 3):
        for index in range(len(tokens) - size + 1):
            phrases.append(" ".join(tokens[index : index + size]))
    return phrases


def _normalize(text: str) -> str:
    lowered = text.lower().strip()
    return NON_ALNUM_PATTERN.sub(" ", lowered)


def _cluster_id(index: int) -> str:
    return f"cluster-{index + 1:03d}"
