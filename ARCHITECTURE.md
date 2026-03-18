# Architecture

## System Overview

The project is a batch pipeline with one entry point: [main.py](/Users/jacobmuriel/Desktop/newsletter/main.py). It reads YAML config and environment variables, processes RSS stories through a fixed sequence of modules in [news_pipeline/](/Users/jacobmuriel/Desktop/newsletter/news_pipeline), writes one Markdown newsletter file, and optionally sends it over SMTP.

## Major Components

- [main.py](/Users/jacobmuriel/Desktop/newsletter/main.py): orchestration, runtime overrides, section selection, output writing, and optional email send.
- [news_pipeline/models.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/models.py): shared dataclasses for feed sources, stories, and run stats.
- [news_pipeline/fetch_news.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/fetch_news.py): RSS fetch and feed entry normalization via `feedparser`.
- [news_pipeline/dedupe.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/dedupe.py): pairwise similarity merge of stories into canonical items.
- [news_pipeline/categorize.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/categorize.py): keyword and source-based section assignment.
- [news_pipeline/quality.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/quality.py): drops weak stories based on title/summary/section heuristics.
- [news_pipeline/rank.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/rank.py): computes `importance_score` from source, keyword, recency, and category signals.
- [news_pipeline/summarize.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/summarize.py): OpenAI enrichment plus fallback content generation.
- [news_pipeline/newsletter.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/newsletter.py): Markdown rendering.
- [news_pipeline/send_email.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/send_email.py): SMTP delivery of the Markdown body as plain text.
- [config/settings.yaml](/Users/jacobmuriel/Desktop/newsletter/config/settings.yaml): pipeline caps, thresholds, section rules, ranking weights, summarization settings, delivery metadata.
- [config/sources.yaml](/Users/jacobmuriel/Desktop/newsletter/config/sources.yaml): feed inventory and source labels.

## Data Flow

1. `main.py` loads `.env`, `config/sources.yaml`, and `config/settings.yaml`.
2. Feed definitions are converted to `FeedSource` objects.
3. `fetch_news()` pulls RSS entries and converts them to `Story` objects.
4. `deduplicate_stories()` merges near-duplicate items and aggregates metadata.
5. `categorize_stories()` assigns each story to one newsletter section.
6. `filter_story_quality()` removes weak matches and low-information items.
7. `rank_stories()` assigns `importance_score` and sorts descending.
8. `main.py` caps ranked candidates, then selects stories per section using fixed section keys and configured limits.
9. Only the selected stories are summarized. Top-ranked selected stories go to OpenAI first, capped by `max_stories_to_summarize`; remaining selected stories get fallback summaries.
10. `build_markdown_newsletter()` renders the final newsletter.
11. `write_output()` saves the Markdown file to `output/`.
12. `send_markdown_email()` sends the Markdown as a plain-text email when enabled.

## Main Entry Points

- Local/manual run: `python main.py`
- Scheduled run candidate: [.github/workflows/daily_newsletter.yml](/Users/jacobmuriel/Desktop/newsletter/.github/workflows/daily_newsletter.yml)

## Fragile Areas And Technical Debt

- Fixed section keys are duplicated between [main.py](/Users/jacobmuriel/Desktop/newsletter/main.py) and [news_pipeline/newsletter.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/newsletter.py). Adding a new section requires coordinated edits in multiple places.
- Categorization uses substring keyword checks, so false positives happen. Example observed in a real run: non-AI content matched the `ai` section because of generic words like `training`.
- `finance_market_structure` rules can capture unrelated stories because keywords such as `ice`, `options`, or `treasury` are broad.
- Deduplication is O(n^2)-style pairwise matching and is intentionally marked for replacement in code comments.
- The summarization settings include `temperature`, but the current OpenAI call does not use it.
- Output code only writes Markdown, but `output/` contains an HTML artifact. Needs verification whether HTML generation existed in another branch or manual script.
- The checked-in `.venv` points to another workspace path. That is machine-specific and easy to break.
- There is no retry/backoff around RSS fetches beyond whatever `feedparser` does internally.
- No tests guard the ranking, categorization, or rendering heuristics.

## Where To Make Common Changes

### Add a new feature

Start in [main.py](/Users/jacobmuriel/Desktop/newsletter/main.py) to see where it belongs in the pipeline, then add or extend a module in [news_pipeline/](/Users/jacobmuriel/Desktop/newsletter/news_pipeline).

### Change UI / output format

Edit [news_pipeline/newsletter.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/newsletter.py). If email formatting should change too, also edit [news_pipeline/send_email.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/send_email.py).

### Change data fetching

Edit [news_pipeline/fetch_news.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/fetch_news.py) for parser behavior and [config/sources.yaml](/Users/jacobmuriel/Desktop/newsletter/config/sources.yaml) for the feed list.

### Change config

Edit [config/settings.yaml](/Users/jacobmuriel/Desktop/newsletter/config/settings.yaml) for thresholds, caps, and section rules. Edit [.env.example](/Users/jacobmuriel/Desktop/newsletter/.env.example) if a new environment variable is required.

### Fix deployment or scheduling issues

Inspect [.github/workflows/daily_newsletter.yml](/Users/jacobmuriel/Desktop/newsletter/.github/workflows/daily_newsletter.yml), then verify whether the actual project is still hosted in GitHub. In this checkout, Git metadata is missing, so workflow activation cannot be confirmed here.

## Recommended Cleanup

- Replace checked-in `.venv` with a documented local setup and ignore it consistently.
- Add tests around categorization, ranking, and markdown rendering.
- Centralize section definitions so config, selection, and rendering cannot drift.
- Decide whether HTML output is supported; if yes, add the generator to source control, otherwise remove stale HTML artifacts from `output/`.
- Introduce structured logging or a small run report file to make debugging easier.
