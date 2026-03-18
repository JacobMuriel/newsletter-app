from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from news_pipeline.models import Story, SummarizationStats

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are writing entries for a daily personalized news briefing that synthesizes multiple sources into clean, informative summaries.

Return valid JSON with exactly these keys:
headline, confirmed_facts, why_it_matters, section_note_label, section_note, left_take, right_take, newsletter_blurb

Field guidelines:
- headline: A clean, specific title for this story (10–16 words). Do not start with "Breaking". Avoid vague words like "new", "latest", "update".
- confirmed_facts: 4–6 sentences of verified, wire-service-style reporting. Report only verifiable facts: specific names, numbers, dates, locations, and the sequence of events. Strip all evaluative or emotional language. Do not characterize motivations. Do not use words like "slammed", "failed", "radical", "alarming", or any loaded framing. Write as if you are a wire service reporter filing for the record. If only one source was supplied, begin with "Single-source early report:" and cover the key facts as fully as possible.
- why_it_matters: 2–3 sentences explaining the concrete real-world stakes. Be specific: name who is affected, what could change as a result, what decision or trend this is part of, and what comes next. Go beyond generic phrases—explain the actual consequence for markets, policy, people, or institutions.
- section_note_label / section_note: Use only for "markets", "finance_market_structure", and "ai" sections. Provide a short label and a specific note relevant to that section (e.g., regulatory impact, market reaction, competitive angle). Leave both empty for "top" and "nba".
- left_take / right_take: For "top" section stories, always provide both takes. For left_take: describe how left-leaning media would frame this story's significance and who they would say is responsible or at fault. For right_take: describe how right-leaning media would frame this story's significance and who they would say is responsible or at fault. Base this on the topic and well-established ideological patterns—do not fabricate quotes or attribute specific claims to specific outlets. Return an empty string only if the story is genuinely nonpartisan with no conceivable framing difference (extremely rare). NEVER populate for ai, markets, finance_market_structure, or nba sections.
- newsletter_blurb: 2–3 sentences synthesizing the main development in plain English. Write as if explaining to a smart friend who hasn't read the news. Must synthesize across the cluster, not simply paraphrase one article.

Synthesis rules:
- Base every claim in confirmed_facts only on information present in the supplied articles. Do not add facts not in the articles.
- confirmed_facts must reflect what multiple articles agree on, not one article's framing. If articles contradict each other on a key fact, note the discrepancy neutrally.
- newsletter_blurb must synthesize across the cluster, not restate a single source.

Return only valid JSON. No markdown fences, no extra text.
""".strip()

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
}


def summarize_stories(
    stories: list[Story],
    settings: dict[str, Any],
    api_key: str | None,
) -> SummarizationStats:
    stats = SummarizationStats()
    client = _build_client(
        api_key=api_key,
        openai_enabled=bool(settings.get("openai_enabled", True)),
    )

    for story in stories:
        if client is None:
            _apply_fallback_summary(story, settings)
            stats.stories_using_fallback += 1
            continue

        stats.stories_sent_to_openai += 1
        try:
            _summarize_with_openai(client=client, story=story, settings=settings)
            stats.estimated_openai_calls += 1
        except Exception as exc:
            stats.estimated_openai_calls += 1
            if _is_insufficient_quota_error(exc):
                logger.warning("OpenAI quota exhausted; switching remaining stories to fallback mode.")
                stats.openai_quota_exhausted = True
                _apply_fallback_summary(story, settings)
                stats.stories_using_fallback += 1
                for remaining_story in stories[stories.index(story) + 1 :]:
                    _apply_fallback_summary(remaining_story, settings)
                    stats.stories_using_fallback += 1
                break
            # Log full exception type + message so failures are never silent
            logger.error(
                "OpenAI summarization FAILED for story '%s' — %s: %s",
                story.title,
                type(exc).__name__,
                exc,
            )
            logger.exception("Full traceback:")
            _apply_fallback_summary(story, settings)
            stats.stories_using_fallback += 1

    return stats


def populate_fallback_summary(story: Story, settings: dict[str, Any]) -> None:
    _apply_fallback_summary(story, settings)


def _build_client(api_key: str | None, openai_enabled: bool) -> OpenAI | None:
    if not openai_enabled:
        logger.info("OPENAI_ENABLED is false. Falling back to heuristic summaries.")
        return None
    if not api_key:
        logger.warning("OPENAI_API_KEY is not set. Falling back to heuristic summaries.")
        return None

    return OpenAI(api_key=api_key)


def _summarize_with_openai(client: OpenAI, story: Story, settings: dict[str, Any]) -> None:
    model = settings["model"]
    max_output_tokens = int(settings["max_output_tokens"])
    max_retries = int(settings["max_retries"])
    prompt = _build_story_prompt(story)

    attempt = 0
    while True:
        try:
            response = client.responses.create(
                model=model,
                max_output_tokens=max_output_tokens,
                instructions=SYSTEM_PROMPT,
                input=prompt,
            )
            raw_text = _extract_response_text(response)
            if not raw_text or not raw_text.strip():
                raise ValueError(
                    f"OpenAI returned empty response text for story '{story.title}'. "
                    f"Model may be invalid or unsupported."
                )
            # Strip markdown fences if the model wrapped the JSON
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]  # drop opening ```json line
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            payload = json.loads(cleaned)

            story.title = payload.get("headline", "").strip() or story.representative_headline or story.title
            story.confirmed_facts = payload.get("confirmed_facts", "").strip() or _fallback_confirmed_facts(story)
            story.why_it_matters = payload.get("why_it_matters", "").strip() or _fallback_why_it_matters(story)
            story.section_note_label, story.section_note = _resolve_section_note(
                story=story,
                proposed_label=payload.get("section_note_label", "").strip(),
                proposed_note=payload.get("section_note", "").strip(),
            )
            story.left_take, story.right_take = _resolve_bias_fields(
                story=story,
                left_take=payload.get("left_take", "").strip(),
                right_take=payload.get("right_take", "").strip(),
            )
            story.newsletter_blurb = payload.get("newsletter_blurb", "").strip() or _fallback_blurb(story)
            story.confidence_label, story.confidence_reason = _score_confidence(story, settings)
            return
        except Exception as exc:
            if _should_retry(exc, attempt=attempt, max_retries=max_retries):
                attempt += 1
                time.sleep(1.0 * attempt)
                continue
            raise


_SECTION_GUIDANCE: dict[str, str] = {
    "top": (
        "This is a top news story. Focus on confirmed facts and real-world significance. "
        "You MUST always populate left_take and right_take. "
        "For left_take: in 2 sentences, describe how left-leaning media would frame this story—who they'd blame, what stakes they'd emphasize. "
        "For right_take: in 2 sentences, same for right-leaning media. "
        "Base this on the topic and known ideological patterns. Return empty string only if the story is genuinely nonpartisan with zero conceivable framing difference."
    ),
    "markets": (
        "This is a macro/markets story. Emphasize what moved, what the numbers are, and why it matters for the economy or investors. "
        "Leave left_take and right_take empty."
    ),
    "ai": (
        "This is an AI or technology story. Focus on what was announced or changed, whether it is hype or substance, "
        "and its practical relevance to the industry. Leave left_take, right_take empty."
    ),
    "finance_market_structure": (
        "This is a market structure or financial regulation story (e.g., SEC, CFTC, exchanges, derivatives, clearing). "
        "Focus on the regulatory or structural implication. Leave left_take, right_take empty."
    ),
    "nba": (
        "This is an NBA sports story. Write in a sports recap voice. "
        "For game results: include the final score, who played well (with stat lines if available), and any pivotal moments. "
        "For player news: include the specific stat lines or performance details that make it notable. "
        "For injuries: name the player, the team, the nature of the injury, and the timeline if known. "
        "Leave left_take, right_take, section_note_label, and section_note empty."
    ),
}


def _build_story_prompt(story: Story) -> str:
    cluster_articles = [
        {
            "source": article.source_name,
            "group": article.outlet_group or article.source_name,
            "published": article.published_date,
            "title": article.title,
            "summary": article.snippet[:320],
        }
        for article in story.articles[:6]
    ]
    context = {
        "cluster_id": story.cluster_id,
        "section": story.category,
        "section_guidance": _SECTION_GUIDANCE.get(story.category, ""),
        "topic": story.topic,
        "source_count": story.source_count,
        "source_labels_present": story.source_labels_present,
        "ranking_notes": story.ranking_notes,
        "articles": cluster_articles,
    }
    return json.dumps(context, indent=2)


def _apply_fallback_summary(story: Story, settings: dict[str, Any]) -> None:
    story.title = story.representative_headline or story.title
    story.confirmed_facts = _fallback_confirmed_facts(story)
    story.why_it_matters = _fallback_why_it_matters(story)
    story.section_note_label, story.section_note = _resolve_section_note(story=story, proposed_label="", proposed_note="")
    story.left_take, story.right_take = _resolve_bias_fields(story=story, left_take="", right_take="")
    story.newsletter_blurb = _fallback_blurb(story)
    story.confidence_label, story.confidence_reason = _score_confidence(story, settings)


def _fallback_blurb(story: Story) -> str:
    sources = ", ".join(story.source_names[:3]) or "current feeds"
    if story.source_count == 1:
        snippet = story.articles[0].snippet if story.articles else story.cleaned_summary
        return f"Single-source early reporting from {sources}: {_trim(snippet, 220)}"
    return (
        f"{story.source_count} sources including {sources} are covering this storyline. "
        f"{_trim(story.confirmed_facts or story.cleaned_summary or story.title, 220)}"
    )


def _fallback_confirmed_facts(story: Story) -> str:
    if story.source_count <= 1:
        source = story.source_names[0] if story.source_names else "one outlet"
        return f"Early single-source reporting from {source} says {_lower_first(_trim(story.title, 140))}."

    source_names = ", ".join(story.source_names[:3])
    shared_entities = _shared_entities(story)
    shared_terms = _shared_terms(story)
    descriptor = ", ".join(shared_entities[:2] or shared_terms[:3])
    if descriptor:
        return f"Across {source_names} and other outlets, reports align on {descriptor} as the core development."
    return f"Across {source_names} and other outlets, reports describe the same event with broadly matching details."


def _fallback_why_it_matters(story: Story) -> str:
    matched = ", ".join(story.matched_keywords[:2]).lower()
    if story.category == "top":
        if matched:
            return f"This could shape the public agenda and policy conversation around {matched}."
        return "This could shape the broader public agenda or geopolitical picture."
    if story.category == "markets":
        return "This could move rates, macro sentiment, or the next market narrative."
    if story.category == "ai":
        return "This matters for AI competition, infrastructure demand, or enterprise adoption."
    if story.category == "finance_market_structure":
        return "This is relevant to regulation, trading conditions, and market plumbing."
    if story.category == "nba":
        return "This affects league storylines, player availability, or the playoff race."
    return "This was important enough to make the daily briefing."


def _resolve_section_note(story: Story, proposed_label: str, proposed_note: str) -> tuple[str, str]:
    default_label = {
        "markets": "Market Impact",
        "finance_market_structure": "Trading Relevance",
        "ai": "Industry Angle",
    }.get(story.category, "")

    if not default_label:
        return "", ""

    if proposed_note:
        return proposed_label or default_label, proposed_note

    if story.category == "markets":
        return default_label, "Watch for spillover into rates, risk sentiment, and the next macro catalyst."
    if story.category == "finance_market_structure":
        return default_label, "Watch for regulatory follow-through, exchange response, or liquidity effects."
    if story.category == "ai":
        return default_label, "Watch for product rollout, compute demand, and how rivals respond."
    return default_label, ""


def _resolve_bias_fields(story: Story, left_take: str, right_take: str) -> tuple[str, str]:
    if not _allows_bias_framing(story):
        return "", ""

    # Pass through whatever the LLM returned. Since the prompt now explicitly
    # requests both takes for top-section stories, returning one or both is fine.
    # Empty string only if the LLM genuinely found no framing angle.
    return left_take, right_take


def _allows_bias_framing(story: Story) -> bool:
    # All top-section stories get framing takes — the LLM generates them from
    # topic patterns and known ideological tendencies, not just from labeled sources.
    # Non-top sections (ai, markets, finance, nba) never get ideological framing.
    return story.category == "top"


def _score_confidence(story: Story, settings: dict[str, Any]) -> tuple[str, str]:
    if story.source_count <= 1:
        return "Low", "Low (single-source report)"

    reliability_avg = (
        sum(article.reliability_weight for article in story.articles) / len(story.articles)
        if story.articles
        else 1.0
    )
    ideological_bonus = 0.0
    ideological_note = ""
    if story.category == "top":
        ideological_bonus = min(len([label for label in story.ideology_counts if label in {"left", "center", "right"}]), 3) * 0.35
        if ideological_bonus < 0.7:
            ideological_note = ", limited ideological diversity"

    score = (
        min(story.source_count, 5) * float(settings["confidence_weights"]["source_count"])
        + min(story.outlet_group_count, 4) * float(settings["confidence_weights"]["outlet_groups"])
        + reliability_avg * float(settings["confidence_weights"]["reliability"])
        + story.corroboration_score * float(settings["confidence_weights"]["corroboration"])
        + ideological_bonus
    )

    if score >= float(settings["confidence_thresholds"]["high"]):
        label = "High"
    elif score >= float(settings["confidence_thresholds"]["medium"]):
        label = "Medium"
    else:
        label = "Low"

    group_text = f"{story.source_count} corroborating sources across {story.outlet_group_count} outlet groups"
    if label == "Low" and story.source_count == 2:
        return label, f"Low ({group_text}{ideological_note})"
    return label, f"{label} ({group_text}{ideological_note})"


def _shared_entities(story: Story) -> list[str]:
    counts = Counter()
    for article in story.articles:
        counts.update({value.strip(): 1 for value in ENTITY_PATTERN.findall(article.combined_text)})
    return [entity for entity, count in counts.most_common() if count >= 2]


def _shared_terms(story: Story) -> list[str]:
    article_terms = []
    for article in story.articles:
        tokens = {
            token for token in TOKEN_PATTERN.findall(article.combined_text.lower())
            if token not in STOPWORDS and len(token) > 2
        }
        article_terms.append(tokens)

    counts = Counter()
    for terms in article_terms:
        counts.update(terms)
    minimum = 2 if story.source_count >= 2 else 1
    return [term for term, count in counts.most_common() if count >= minimum]


def _trim(text: str, max_length: int) -> str:
    compact = " ".join(text.split()).strip()
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 1].rstrip() + "..."


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _should_retry(exc: Exception, *, attempt: int, max_retries: int) -> bool:
    if attempt >= max_retries - 1:
        return False
    if _is_insufficient_quota_error(exc):
        return False
    return isinstance(exc, (APIConnectionError, APITimeoutError))


def _is_insufficient_quota_error(exc: Exception) -> bool:
    if isinstance(exc, RateLimitError):
        body = getattr(exc, "body", None) or {}
        error = body.get("error", {}) if isinstance(body, dict) else {}
        return error.get("code") == "insufficient_quota"
    if isinstance(exc, APIStatusError):
        body = getattr(exc, "body", None) or {}
        error = body.get("error", {}) if isinstance(body, dict) else {}
        return error.get("code") == "insufficient_quota"
    return False


def _extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    output_items = getattr(response, "output", []) or []
    parts: list[str] = []
    for item in output_items:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                parts.append(text)
    return "".join(parts)


if __name__ == "__main__":
    # Standalone API smoke-test: verify key + model work before running the full pipeline.
    # Usage: python -m news_pipeline.summarize
    import os
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY is not set in .env", file=sys.stderr)
        sys.exit(1)

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    print(f"Testing OpenAI API — model: {model}")
    client = OpenAI(api_key=api_key)

    try:
        response = client.responses.create(
            model=model,
            max_output_tokens=100,
            instructions="You are a test assistant. Respond only with valid JSON.",
            input='{"test": true}',
        )
        raw = _extract_response_text(response)
        print(f"SUCCESS — raw response text:\n{raw}")
    except Exception as exc:
        print(f"FAILED — {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
