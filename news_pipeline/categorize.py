from __future__ import annotations

import logging
import re
from typing import Any

from news_pipeline.models import Story

logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9\.\-&']+")

# Hard gate for NBA: story must contain "nba" / "basketball" explicitly, OR one of these
# unambiguous player/league names. Generic team nicknames alone (rockets, bulls) are NOT
# sufficient — they appear too often in non-sports contexts (rocket attacks, bull markets).
_NBA_HARD_GATE = re.compile(
    r"\b(nba|basketball|hoops|nba\s+playoffs?|nba\s+finals?|nba\s+game|nba\s+season|"
    r"wembanyama|jokic|doncic|giannis|embiid|sengun|vucevic|morant|"
    r"lebron\s+james|stephen\s+curry|steph\s+curry|jayson\s+tatum|jalen\s+brunson|"
    r"jalen\s+green|demar\s+derozan|zach\s+lavine|coby\s+white|amen\s+thompson|"
    r"reed\s+sheppard|cam\s+whitmore|kevin\s+durant|luka\s+doncic|"
    r"eastern\s+conference\s+(?:standings|finals?|playoffs?)|"
    r"western\s+conference\s+(?:standings|finals?|playoffs?))\b",
    re.I,
)

# Hard gate for finance_market_structure: story must contain at least one term that is
# unambiguously about financial market plumbing — not generic macro or political language.
_FINANCE_STRUCTURE_HARD_GATE = re.compile(
    r"\b(sec\b|cftc|derivatives|options\s+market|options\s+trading|market\s+structure|"
    r"clearinghouse|clearing\s+house|central\s+clearing|settlement\s+fail|"
    r"repo\s+market|treasury\s+market|margin\s+call|prime\s+brokerage|"
    r"cboe|cme\s+group|nasdaq\s+exchange|nyse\s+exchange|vix\b|"
    r"futures\s+(?:market|trading|contract)|"
    r"sec\s+(?:filing|charges?|enforcement|rule|order)|"
    r"cftc\s+(?:order|action|charges?|rule)|"
    r"exchange\s+(?:traded|clearing|settlement|operator))\b",
    re.I,
)


def categorize_stories(stories: list[Story], settings: dict[str, Any]) -> list[Story]:
    rules: dict[str, dict[str, Any]] = settings["rules"]
    priority_order: list[str] = settings["priority_order"]

    for story in stories:
        matched_category, score, reason, matched_keywords = _classify_story(story, rules, priority_order)
        story.category = matched_category
        story.category_score = score
        story.category_reason = reason
        story.matched_keywords = matched_keywords
        story.refresh_metadata()
        logger.info(
            "Assigned story '%s' to section %s (score=%s, reason=%s)",
            story.title,
            story.category,
            story.category_score,
            story.category_reason,
        )

    return stories


def _classify_story(
    story: Story,
    rules: dict[str, dict[str, Any]],
    priority_order: list[str],
) -> tuple[str, int, str, list[str]]:
    story_text = f"{story.title} {story.cleaned_summary}".lower()
    source_names = set(story.source_names)

    for category in priority_order:
        if category == "top":
            continue
        category_settings = rules[category]
        preferred_sources = set(category_settings.get("preferred_sources", []))
        strong_keywords = category_settings.get("strong_keywords", [])
        weak_keywords = category_settings.get("weak_keywords", [])
        exclusion_keywords = category_settings.get("exclusion_keywords", [])
        minimum_score = int(category_settings.get("minimum_score", 0))
        preferred_source_minimum_score = int(category_settings.get("preferred_source_minimum_score", minimum_score))

        # Skip category if any exclusion keyword appears in the story text
        if exclusion_keywords and any(kw.lower() in story_text for kw in exclusion_keywords):
            logger.debug("Skipping category '%s' for story '%s' due to exclusion keyword match", category, story_text[:80])
            continue

        strong_matches = [keyword for keyword in strong_keywords if keyword.lower() in story_text]
        weak_matches = [keyword for keyword in weak_keywords if keyword.lower() in story_text]
        preferred_source_hit = any(source in preferred_sources for source in source_names)

        score = (len(strong_matches) * 2) + len(weak_matches)
        if preferred_source_hit:
            score += 2

        # Hard gates: reject if the story lacks the core signal for the category,
        # regardless of keyword score. These prevent geopolitical/macro stories
        # from bleeding into finance/NBA sections via incidental keyword overlap.
        if category == "nba" and not _has_strong_nba_signal(story_text, preferred_source_hit):
            logger.debug("NBA hard gate rejected story '%s'", story.title)
            continue
        if category == "ai" and not _has_strong_ai_signal(story_text, strong_matches):
            continue
        if category == "finance_market_structure" and not _has_strong_finance_structure_signal(story_text):
            logger.debug("Finance hard gate rejected story '%s'", story.title)
            continue
        if category in {"markets", "finance_market_structure"} and not strong_matches:
            continue

        threshold = preferred_source_minimum_score if preferred_source_hit else minimum_score
        if score >= threshold:
            reason = "preferred source + strong match" if preferred_source_hit else "strong keyword match"
            return category, score, reason, _unique(strong_matches + weak_matches)

    top_reason = "fallback to top stories because niche-category confidence was weak"
    return "top", 0, top_reason, _unique(_collect_top_keywords(story_text, rules.get("top", {})))


def _has_strong_nba_signal(story_text: str, preferred_source_hit: bool) -> bool:
    """Require an unambiguous NBA signal.

    A preferred source (ESPN NBA) is sufficient on its own.
    Otherwise the story must contain 'nba', 'basketball', or an unambiguous
    player/league name — not just a team nickname that appears in non-sports contexts.
    """
    if preferred_source_hit:
        return True
    return bool(_NBA_HARD_GATE.search(story_text))


def _has_strong_finance_structure_signal(story_text: str) -> bool:
    """Require at least one term that is unambiguously about market plumbing.

    Prevents geopolitical stories that mention 'trading', 'exchange', or 'options'
    in a general/policy context from bleeding into the Finance / Market Structure section.
    """
    return bool(_FINANCE_STRUCTURE_HARD_GATE.search(story_text))


def _has_strong_ai_signal(story_text: str, strong_matches: list[str]) -> bool:
    """Require a genuinely AI/tech-specific signal before categorising as AI.

    Some strong keywords ("semiconductor", "chip", "training", "inference") are
    ambiguous — they appear routinely in geopolitical and supply-chain stories.
    A single ambiguous keyword is not enough; the story needs either:
      • at least one *unambiguous* AI keyword, OR
      • two or more strong matches (ambiguous or not), suggesting the story really
        is about tech rather than mentioning a tech term incidentally.
    """
    if not strong_matches:
        return False

    # Filter out "ai" if it only matched as a substring (e.g. inside "said", "strait")
    tokens = set(TOKEN_PATTERN.findall(story_text))
    if "ai" in strong_matches and "ai" not in tokens:
        effective_matches = [m for m in strong_matches if m != "ai"]
    else:
        effective_matches = strong_matches

    if not effective_matches:
        return False

    # Terms that are unambiguously about AI / tech — one is enough.
    _UNAMBIGUOUS_AI = {
        "artificial intelligence", "llm", "chatbot", "openai", "anthropic",
        "nvidia", "gpu", "data center", "datacenter", "enterprise ai",
    }
    # "ai" as a standalone token (not a substring) is also unambiguous.
    if "ai" in effective_matches:
        return True
    if any(m in _UNAMBIGUOUS_AI for m in effective_matches):
        return True

    # Ambiguous terms (chip, chips, semiconductor, training, inference) —
    # require at least 2 strong matches to confirm this is a tech story,
    # not an incidental mention in a geopolitical or supply-chain article.
    return len(effective_matches) >= 2


def _collect_top_keywords(story_text: str, top_settings: dict[str, Any]) -> list[str]:
    strong_keywords = top_settings.get("strong_keywords", [])
    weak_keywords = top_settings.get("weak_keywords", [])
    return [keyword for keyword in strong_keywords + weak_keywords if keyword.lower() in story_text]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)

    return ordered
