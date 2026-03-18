from __future__ import annotations

import copy
import logging
import os
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from news_pipeline.bias_detect import detect_charged_language
from news_pipeline.categorize import categorize_stories
from news_pipeline.cluster import cluster_articles
from news_pipeline.fetch_news import fetch_news
from news_pipeline.models import FeedSource, Story
from news_pipeline.nba import build_nba_brief
from news_pipeline.newsletter import build_html_newsletter
from news_pipeline.newsletter import build_markdown_newsletter
from news_pipeline.quality import filter_story_quality
from news_pipeline.rank import rank_stories
from news_pipeline.send_email import send_markdown_email
from news_pipeline.summarize import populate_fallback_summary, summarize_stories


def main() -> None:
    configure_logging()
    load_dotenv()

    root = Path(__file__).resolve().parent
    sources_config = load_yaml(root / "config" / "sources.yaml")
    settings = apply_runtime_overrides(load_yaml(root / "config" / "settings.yaml"))

    sources = [FeedSource(**item) for item in sources_config["sources"]]
    raw_articles, fetch_stats = fetch_news(
        sources=sources,
        max_items_per_feed=int(settings["pipeline"]["max_items_per_feed"]),
        max_total_stories=int(settings["pipeline"]["max_total_stories_fetched"]),
    )
    clustered_stories = cluster_articles(raw_articles, settings["clustering"])
    categorized_stories = categorize_stories(clustered_stories, settings["categorization"])

    # Detect charged/loaded language in each story cluster and store on the story object
    for story in categorized_stories:
        story.charged_sources = detect_charged_language(story.articles)

    quality_stories = filter_story_quality(
        categorized_stories,
        {
            **settings["quality_filter"],
            "section_rules": settings["categorization"]["rules"],
        },
    )
    ranked_stories = rank_stories(quality_stories, settings["ranking"])
    ranked_candidates = ranked_stories[: int(settings["pipeline"]["max_stories_to_rank"])]

    stories_by_section = select_stories_by_section(
        stories=ranked_candidates,
        section_limits=settings["section_limits"],
    )
    selected_stories = [story for stories in stories_by_section.values() for story in stories]
    stories_for_openai = sorted(
        selected_stories,
        key=lambda story: story.importance_score,
        reverse=True,
    )[: int(settings["pipeline"]["max_stories_to_summarize"])]
    summarize_stats = summarize_stories(
        stories=stories_for_openai,
        settings=settings["summarization"],
        api_key=os.getenv("OPENAI_API_KEY"),
    )
    summarized_ids = {id(story) for story in stories_for_openai}
    capped_fallback_count = 0
    for story in selected_stories:
        if id(story) not in summarized_ids:
            capped_fallback_count += 1
            populate_fallback_summary(story, settings["summarization"])

    nba_story_pool = [
        story for story in ranked_stories if story.category == "nba"
    ][: int(settings["newsletter"].get("nba_story_pool", 6))]
    nba_brief = build_nba_brief(
        stories=nba_story_pool,
        max_items_per_bucket=int(settings["newsletter"].get("nba_items_per_bucket", 3)),
    )
    generated_at = datetime.now(timezone.utc)
    newsletter_html = build_html_newsletter(
        stories_by_section=stories_by_section,
        settings=settings["newsletter"],
        generated_at=generated_at,
        nba_brief=nba_brief,
    )
    output_path = write_output(
        newsletter_html,
        output_dir=root / settings["pipeline"]["output_directory"],
        generated_at=generated_at,
    )

    email_sent = False
    if settings["pipeline"]["dry_run"] or not settings["pipeline"]["send_email"]:
        logging.info("Dry run enabled or SEND_EMAIL disabled; skipping email send.")
    else:
        try:
            email_sent = send_markdown_email(
                subject=build_email_subject(settings=settings, generated_at=generated_at),
                markdown_body=build_markdown_newsletter(
                    stories_by_section=stories_by_section,
                    settings=settings["newsletter"],
                    generated_at=generated_at,
                    nba_brief=nba_brief,
                ),
                smtp_settings={
                    "sender": os.getenv("NEWSLETTER_EMAIL_FROM"),
                    "recipient": os.getenv("NEWSLETTER_EMAIL_TO"),
                    "host": os.getenv("SMTP_HOST"),
                    "port": os.getenv("SMTP_PORT", "587"),
                    "username": os.getenv("SMTP_USERNAME"),
                    "password": os.getenv("SMTP_PASSWORD"),
                    "use_tls": os.getenv("SMTP_USE_TLS", "true"),
                    "html_file": str(output_path),
                },
            )
        except Exception:
            logging.exception("Newsletter email delivery failed")

    logging.info("Newsletter written to %s", output_path)
    print(f"Newsletter output: {output_path}")

    # Open newsletter in default browser
    try:
        webbrowser.open(str(output_path))
    except Exception as e:
        logging.warning("Failed to open newsletter in browser: %s", e)
    log_run_summary(
        fetch_stats=fetch_stats,
        raw_story_count=len(raw_articles),
        clustered_story_count=len(clustered_stories),
        ranked_story_count=len(ranked_candidates),
        summarize_stats=summarize_stats,
        capped_fallback_count=capped_fallback_count,
        email_sent=email_sent,
    )


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file_handle:
        return yaml.safe_load(file_handle)


def apply_runtime_overrides(settings: dict[str, Any]) -> dict[str, Any]:
    runtime_settings = copy.deepcopy(settings)
    pipeline_settings = runtime_settings["pipeline"]
    summarization_settings = runtime_settings["summarization"]

    pipeline_settings["openai_enabled"] = env_bool("OPENAI_ENABLED", pipeline_settings["openai_enabled"])
    pipeline_settings["send_email"] = env_bool("SEND_EMAIL", pipeline_settings["send_email"])
    pipeline_settings["dry_run"] = env_bool("DRY_RUN", pipeline_settings["dry_run"])
    pipeline_settings["max_total_stories_fetched"] = env_int(
        "MAX_STORIES_FETCHED",
        pipeline_settings["max_total_stories_fetched"],
    )
    pipeline_settings["max_stories_to_rank"] = env_int(
        "MAX_STORIES_TO_RANK",
        pipeline_settings["max_stories_to_rank"],
    )
    pipeline_settings["max_stories_to_summarize"] = env_int(
        "MAX_STORIES_TO_SUMMARIZE",
        pipeline_settings["max_stories_to_summarize"],
    )
    summarization_settings["openai_enabled"] = pipeline_settings["openai_enabled"]
    summarization_settings["model"] = os.getenv("OPENAI_MODEL", summarization_settings["model"])

    return runtime_settings


def select_stories_by_section(
    *,
    stories: list[Story],
    section_limits: dict[str, int],
) -> dict[str, list[Story]]:
    stories_by_section: dict[str, list[Story]] = {
        section: [] for section in ["top", "markets", "ai", "finance_market_structure", "nba"]
    }

    for story in stories:
        if story.category not in stories_by_section:
            continue

        limit = int(section_limits.get(story.category, 0))
        if len(stories_by_section[story.category]) >= limit:
            continue

        stories_by_section[story.category].append(story)

    return stories_by_section


def write_output(html_body: str, output_dir: Path, generated_at: datetime) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"newsletter_{generated_at.strftime('%Y%m%d_%H%M%S')}.html"
    output_path = output_dir / filename
    output_path.write_text(html_body, encoding="utf-8")
    return output_path


def build_email_subject(*, settings: dict[str, Any], generated_at: datetime) -> str:
    prefix = settings["delivery"]["email_subject_prefix"]
    date_str = generated_at.strftime("%A, %B %d")
    return f"{prefix} — {date_str}"


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return bool(default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return int(default)
    return int(value)


def log_run_summary(
    *,
    fetch_stats: Any,
    raw_story_count: int,
    clustered_story_count: int,
    ranked_story_count: int,
    summarize_stats: Any,
    capped_fallback_count: int,
    email_sent: bool,
) -> None:
    logging.info("Run summary:")
    logging.info("  feeds attempted: %s", fetch_stats.feeds_attempted)
    logging.info("  feeds failed: %s", ", ".join(fetch_stats.feeds_failed) or "none")
    logging.info("  raw articles fetched: %s", raw_story_count)
    logging.info("  story clusters created: %s", clustered_story_count)
    logging.info("  stories ranked: %s", ranked_story_count)
    logging.info("  stories sent to OpenAI: %s", summarize_stats.stories_sent_to_openai)
    logging.info(
        "  stories using fallback: %s",
        summarize_stats.stories_using_fallback + capped_fallback_count,
    )
    logging.info("  email sent: %s", email_sent)
    logging.info("  total estimated OpenAI calls made: %s", summarize_stats.estimated_openai_calls)


if __name__ == "__main__":
    main()
