from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from news_pipeline.models import NBABrief, Story

SECTION_TITLES = {
    "top": "Top Stories",
    "markets": "Market Moving",
    "ai": "AI Watch",
    "finance_market_structure": "Finance / Market Structure",
    "nba": "NBA Brief",
}

SECTION_ORDER = ["top", "markets", "ai", "finance_market_structure", "nba"]


def build_markdown_newsletter(
    stories_by_section: dict[str, list[Story]],
    settings: dict[str, Any],
    generated_at: datetime,
    nba_brief: NBABrief | None = None,
) -> str:
    lines: list[str] = []
    title = settings["title"]
    date_format = settings["date_format"]

    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"_Generated {generated_at.strftime(date_format)}_")
    lines.append("")
    overview = _build_day_overview(stories_by_section)
    if overview:
        lines.append(f"_{overview}_")
        lines.append("")

    for section_key in SECTION_ORDER:
        stories = stories_by_section.get(section_key, [])
        lines.append(f"## {SECTION_TITLES[section_key]}")
        lines.append("")

        if section_key == "nba":
            _render_nba_brief(lines, nba_brief)
            lines.append("")
            continue

        if not stories:
            lines.append("_No qualifying stories for this section today._")
            lines.append("")
            continue

        for index, story in enumerate(stories, start=1):
            lines.append(f"### {index}. {story.title}")
            lines.append("")
            lines.append(f"**Confirmed Facts:** {story.confirmed_facts}")
            lines.append("")
            if story.why_it_matters:
                lines.append(f"**Why It Matters:** {story.why_it_matters}")
                lines.append("")
            if story.section_note_label and story.section_note:
                lines.append(f"**{story.section_note_label}:** {story.section_note}")
                lines.append("")
            show_takes = section_key == "top" or bool(story.left_take or story.right_take)
            if show_takes:
                if story.left_take:
                    lines.append(f"- **Left Take:** {story.left_take}")
                if story.right_take:
                    lines.append(f"- **Right Take:** {story.right_take}")
                if section_key == "top" and not story.left_take and not story.right_take:
                    lines.append("_No significant framing differences detected._")
                lines.append("")
            confidence_line = _confidence_line(story)
            lines.append(f"_{confidence_line}_")
            lines.append("")

        lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_html_newsletter(
    stories_by_section: dict[str, list[Story]],
    settings: dict[str, Any],
    generated_at: datetime,
    nba_brief: NBABrief | None = None,
) -> str:
    title = html.escape(settings["title"])
    generated_label = html.escape(generated_at.strftime(settings["date_format"]))

    overview = _build_day_overview(stories_by_section)
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        f"  <title>{title}</title>",
        "  <style>",
        "    body { font-family: Georgia, 'Times New Roman', serif; margin: 0; background: #f5f2eb; color: #1a1a1a; }",
        "    .wrap { max-width: 860px; margin: 0 auto; padding: 44px 28px 64px; }",
        "    h1 { font-size: 2.2rem; margin-bottom: 0.2rem; letter-spacing: -0.5px; }",
        "    .generated { color: #777; font-size: 0.9rem; margin-bottom: 0.5rem; }",
        "    .overview { color: #444; font-style: italic; margin: 0 0 2.2rem; border-left: 3px solid #c8b89a; padding-left: 1rem; line-height: 1.6; }",
        "    section { margin-top: 2.8rem; }",
        "    h2 { font-size: 1.15rem; text-transform: uppercase; letter-spacing: 0.08em; border-bottom: 2px solid #c8b89a; padding-bottom: 0.4rem; color: #3a3a3a; }",
        "    article { background: #fffef9; border: 1px solid #ddd4be; border-radius: 10px; padding: 22px 24px 18px; margin: 18px 0; }",
        "    h3 { margin: 0 0 0.9rem; font-size: 1.15rem; line-height: 1.4; color: #111; }",
        "    .facts { margin: 0 0 0.85rem; line-height: 1.75; font-size: 1rem; color: #1a1a1a; }",
        "    .matters { margin: 0 0 0.85rem; line-height: 1.7; font-size: 0.97rem; color: #2a2a2a; }",
        "    .matters strong { color: #333; }",
        "    .section-note { margin: 0 0 0.75rem; font-size: 0.94rem; color: #3a3a3a; }",
        "    .takes { margin: 0.6rem 0 0.85rem; padding: 10px 14px 12px; background: #f0ece2; border-radius: 7px; border-left: 3px solid #b8a880; }",
        "    .takes-header { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.07em; color: #8a7a5a; margin: 0 0 0.45rem; }",
        "    .takes p { margin: 0.3rem 0; font-size: 0.93rem; line-height: 1.6; }",
        "    .conf { margin: 0.6rem 0 0; font-size: 0.82rem; color: #777; font-style: italic; }",
        "    .charged { margin: 0.25rem 0 0; font-size: 0.8rem; color: #9a6c00; }",
        "    .nba-bucket { background: #fffef9; border: 1px solid #ddd4be; border-radius: 10px; padding: 16px 20px; margin: 14px 0; }",
        "    .nba-bucket h3 { margin: 0 0 0.6rem; font-size: 1rem; color: #2a2a2a; text-transform: uppercase; letter-spacing: 0.05em; }",
        "    .nba-bucket ul { margin: 0; padding-left: 1.2rem; }",
        "    .nba-bucket li { margin: 0.4rem 0; line-height: 1.65; font-size: 0.96rem; }",
        "    .nba-fav { background: #f0f7f0; border-color: #9abf9a; }",
        "    .nba-fav h3 { color: #2a5a2a; }",
        "    .nba-sources { font-size: 0.8rem; color: #888; margin-top: 0.5rem; }",
        "  </style>",
        "</head>",
        "<body>",
        '  <div class="wrap">',
        f"    <h1>{title}</h1>",
        f'    <p class="generated">Generated {generated_label}</p>',
    ]
    if overview:
        parts.append(f'    <p class="overview">{html.escape(overview)}</p>')

    for section_key in SECTION_ORDER:
        parts.append(f'    <section><h2>{html.escape(SECTION_TITLES[section_key])}</h2>')
        stories = stories_by_section.get(section_key, [])

        if section_key == "nba":
            parts.extend(_render_nba_brief_html(nba_brief))
            parts.append("    </section>")
            continue

        if not stories:
            parts.append("      <p><em>No qualifying stories for this section today.</em></p>")
            parts.append("    </section>")
            continue

        for index, story in enumerate(stories, start=1):
            parts.append("      <article>")
            parts.append(f"        <h3>{index}. {html.escape(story.title)}</h3>")

            # Confirmed facts — the main body block (no label, just the text)
            parts.append(f'        <p class="facts">{html.escape(story.confirmed_facts)}</p>')

            # Why it matters
            if story.why_it_matters:
                parts.append(
                    f'        <p class="matters"><strong>Why It Matters:</strong> {html.escape(story.why_it_matters)}</p>'
                )

            # Section-specific note (markets / ai / finance)
            if story.section_note_label and story.section_note:
                parts.append(
                    f'        <p class="section-note"><strong>{html.escape(story.section_note_label)}:</strong> {html.escape(story.section_note)}</p>'
                )

            # Left / right takes — always rendered for top-section stories;
            # other sections only when at least one take is present.
            show_takes = section_key == "top" or bool(story.left_take or story.right_take)
            if show_takes:
                parts.append('        <div class="takes">')
                parts.append('          <p class="takes-header">How it&#39;s likely being framed:</p>')
                if story.left_take:
                    parts.append(f'          <p><strong>Left:</strong> {html.escape(story.left_take)}</p>')
                if story.right_take:
                    parts.append(f'          <p><strong>Right:</strong> {html.escape(story.right_take)}</p>')
                if section_key == "top" and not story.left_take and not story.right_take:
                    parts.append('          <p><em>No significant framing differences detected.</em></p>')
                parts.append("        </div>")

            # Confidence + source count — one compact line at the bottom
            conf_line = _confidence_line(story)
            parts.append(f'        <p class="conf">{html.escape(conf_line)}</p>')

            # Charged language warning — shown only when flagged sources exist
            if story.charged_sources:
                flagged_names = html.escape(", ".join(sorted(story.charged_sources.keys())))
                parts.append(f'        <p class="charged">⚠️ Charged language detected in: {flagged_names}</p>')

            parts.append("      </article>")

        parts.append("    </section>")

    parts.extend(["  </div>", "</body>", "</html>"])
    return "\n".join(parts) + "\n"


def _render_nba_brief(lines: list[str], nba_brief: NBABrief | None) -> None:
    if nba_brief is None:
        lines.append("_No qualifying stories for this section today._")
        return

    # Rockets & Bulls — always shown
    lines.append("### 🏀 Rockets & Bulls")
    if nba_brief.rockets_bulls_recaps:
        for item in nba_brief.rockets_bulls_recaps:
            lines.append(f"- {item}")
        for item in nba_brief.rockets_bulls_performers:
            lines.append(f"- {item}")
    else:
        lines.append("_No game yesterday._")
    lines.append("")

    # Big Performances — only if non-empty
    if nba_brief.big_performances:
        _render_bucket(lines, "🔥 Big Performances", nba_brief.big_performances)

    # Game Recaps — all other games
    if nba_brief.game_recaps:
        _render_bucket(lines, "Game Recaps", nba_brief.game_recaps)

    if nba_brief.source_names:
        lines.append(f"_Sources: {', '.join(nba_brief.source_names)}_")


def _render_bucket(lines: list[str], heading: str, items: list[str]) -> None:
    lines.append(f"### {heading}")
    for item in items:
        lines.append(f"- {item}")
    lines.append("")


def _render_nba_brief_html(nba_brief: NBABrief | None) -> list[str]:
    if nba_brief is None:
        return ["      <p><em>No qualifying stories for this section today.</em></p>"]

    parts: list[str] = []

    # Rockets & Bulls — always shown (green highlight)
    parts.append('      <div class="nba-bucket nba-fav">')
    parts.append("        <h3>🏀 Rockets &amp; Bulls</h3>")
    if nba_brief.rockets_bulls_recaps:
        parts.append("        <ul>")
        for item in nba_brief.rockets_bulls_recaps:
            parts.append(f"          <li>{html.escape(item)}</li>")
        for item in nba_brief.rockets_bulls_performers:
            parts.append(f"          <li>{html.escape(item)}</li>")
        parts.append("        </ul>")
    else:
        parts.append("        <p><em>No game yesterday.</em></p>")
    parts.append("      </div>")

    # Big Performances — only if non-empty
    if nba_brief.big_performances:
        parts.append('      <div class="nba-bucket">')
        parts.append("        <h3>🔥 Big Performances</h3>")
        parts.append("        <ul>")
        for item in nba_brief.big_performances:
            parts.append(f"          <li>{html.escape(item)}</li>")
        parts.append("        </ul>")
        parts.append("      </div>")

    # Game Recaps — all other games
    if nba_brief.game_recaps:
        parts.append('      <div class="nba-bucket">')
        parts.append("        <h3>Game Recaps</h3>")
        parts.append("        <ul>")
        for item in nba_brief.game_recaps:
            parts.append(f"          <li>{html.escape(item)}</li>")
        parts.append("        </ul>")
        parts.append("      </div>")

    if nba_brief.source_names:
        parts.append(f'      <p class="nba-sources">Sources: {html.escape(", ".join(nba_brief.source_names))}</p>')

    return parts


def _confidence_line(story: Story) -> str:
    """Compact one-liner: 'Confidence: Medium · 4 sources' — omits source count if only 1."""
    label = story.confidence_label or "Low"
    if story.source_count > 1:
        return f"Confidence: {label} · {story.source_count} sources"
    return f"Confidence: {label} · single source"


def _build_day_overview(stories_by_section: dict[str, list[Story]]) -> str:
    """Build a 1–2 sentence day overview from the top stories."""
    top_stories = stories_by_section.get("top", [])
    if not top_stories:
        for section_key in SECTION_ORDER:
            if section_key != "nba" and stories_by_section.get(section_key):
                top_stories = stories_by_section[section_key][:1]
                break

    if not top_stories:
        return ""

    titles = [s.title for s in top_stories[:3] if s.title]
    if not titles:
        return ""

    if len(titles) == 1:
        return f"Today's top story: {titles[0]}."
    if len(titles) == 2:
        return f"Today's top stories: {titles[0]}, and {titles[1]}."
    return f"Today's top stories: {titles[0]}; {titles[1]}; and {titles[2]}."
