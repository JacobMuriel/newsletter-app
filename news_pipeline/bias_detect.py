from __future__ import annotations

import re

from news_pipeline.models import Article

# Unconditionally charged/loaded words — their mere presence signals framing bias
CHARGED_WORDS: list[str] = [
    "slammed",
    "blasted",
    "pounced",
    "weaponized",
    "radical",
    "extreme",
    "shocking",
    "outrageous",
    "alarming",
    "disgraceful",
    "corrupt",
    "failing",
    "destroyed",
    "crushed",
    "humiliated",
    "lied",
    "betrayed",
    "elites",
    "regime",
    "propaganda",
    "meltdown",
    "bombshell",
    "explosive",
    "catastrophic",
    "disastrous",
    "shameful",
    "delusional",
    "unhinged",
    "woke",
    "fascist",
    "socialist",
    "rigged",
]

# Contextual patterns: flagged only when matched by the specific regex
_CONTEXTUAL: list[tuple[re.Pattern[str], str]] = [
    # "attack" when used metaphorically (not physical/military)
    (
        re.compile(
            r"\battacks?\b(?!\s+on\s+(?:pearl\s+harbor|fort|the\s+building|troops|military|base|compound))",
            re.I,
        ),
        "attack (metaphorical)",
    ),
    # "crisis" when paired with hyperbolic language
    (re.compile(r"\b(?:absolute|total|complete|full.blown|unprecedented)\s+crisis\b", re.I), "crisis (hyperbolic)"),
    # "chaos" in political/policy contexts (exclude weather/disaster uses)
    (re.compile(r"\b(?:political|administrative|white\s+house|government)\s+chaos\b", re.I), "chaos (political)"),
]


def detect_charged_language(articles: list[Article]) -> dict[str, list[str]]:
    """Scan article titles and summaries for charged/loaded language.

    Returns a dict mapping source_name → deduplicated list of flagged words/phrases
    found in that source's articles. Sources with no flagged language are omitted.
    """
    results: dict[str, list[str]] = {}

    for article in articles:
        text = f"{article.title} {article.summary}".lower()
        flagged: list[str] = []

        # Whole-word matches for charged words
        for word in CHARGED_WORDS:
            pattern = rf"\b{re.escape(word)}\b"
            if re.search(pattern, text, re.I):
                flagged.append(word)

        # Contextual pattern matches
        for regex, label in _CONTEXTUAL:
            if regex.search(text):
                flagged.append(label)

        if flagged:
            source = article.source_name
            existing = results.get(source, [])
            # Merge and deduplicate while preserving order
            seen = set(existing)
            merged = list(existing)
            for flag in flagged:
                if flag not in seen:
                    seen.add(flag)
                    merged.append(flag)
            results[source] = merged

    return results
