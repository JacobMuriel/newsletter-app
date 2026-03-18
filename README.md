# Daily Personalized News Briefing

This repository builds a daily, sectioned news briefing from RSS feeds, deduplicates and categorizes stories, ranks them, enriches with OpenAI summaries (or fallback text), renders an HTML newsletter, and optionally delivers an email copy.

## 🚀 Key Features

- Configurable RSS ingestion using `config/sources.yaml`
- Clustering/deduplication of similar articles (`news_pipeline/cluster.py`, `news_pipeline/dedupe.py`)
- Priority-based section categorization (`news_pipeline/categorize.py`)
- Quality filtering to avoid low-value content (`news_pipeline/quality.py`)
- Heuristic ranking and section-level limits (`news_pipeline/rank.py` + `config/settings.yaml`)
- OpenAI summarization with fallback route (`news_pipeline/summarize.py`)
- Markdown + HTML newsletter generation (`news_pipeline/newsletter.py`)
- Optional SMTP send for production use (`news_pipeline/send_email.py`)
- Run summary logging and optional browser launch

## 📁 Important files

- `main.py` - orchestration pipeline
- `config/settings.yaml` - pipeline caps, section rules, thresholds
- `config/sources.yaml` - feed list and metadata
- `news_pipeline/` - pipeline module stages
- `output/` - generated `newsletter_YYYYMMDD_HHMMSS.html` files

## 🧩 Sections

Hardcoded sections in `main.py` and in `config/settings.yaml`:

- `top`
- `markets`
- `ai`
- `finance_market_structure`
- `nba`

## ⚙️ Config + env overrides

`main.py` loads YAML configs then applies runtime overrides:

- ENV var `OPENAI_ENABLED` toggles OpenAI summarization
- ENV var `SEND_EMAIL` toggles SMTP delivery
- ENV var `DRY_RUN` disables email send and keeps dry-run behavior
- ENV var `MAX_STORIES_FETCHED`, `MAX_STORIES_TO_RANK`, `MAX_STORIES_TO_SUMMARIZE` override limits
- ENV var `OPENAI_MODEL` can set model used in summarization

`openai_enabled` is controlled in `pipeline` and mirrored into `summarization` settings.

## ▶️ Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Dry run (no email, no OpenAI):

```bash
DRY_RUN=true SEND_EMAIL=false OPENAI_ENABLED=false python main.py
```

Run with OpenAI summarization (no email):

```bash
OPENAI_API_KEY=... OPENAI_ENABLED=true DRY_RUN=true SEND_EMAIL=false python main.py
```

Run with SMTP delivery:

```bash
SEND_EMAIL=true DRY_RUN=false python main.py
```

## 🧠 Behavior details

1. load config + feedd list
2. fetch RSS stories (up to `max_items_per_feed`, total `max_total_stories_fetched`)
3. cluster/merge similar stories
4. categorize clusters into sections by keyword/source rules
5. detect charged/biased language (`news_pipeline/bias_detect.py`)
6. apply quality filters
7. rank stories and pick top candidates
8. select per-section limits
9. pick top stories for OpenAI summarization (cap `max_stories_to_summarize`)
10. fallback summaries for remaining selected stories
11. NBA brief from top NBA stories
12. build HTML newsletter and write to `output/`
13. send email using markdown newsletter if enabled

## 🛠️ Known limitations

- No unit tests in repository yet.
- Categorization is keyword-and-source based and may misassign broad content.
- Clustering/deduplication is heuristic; similar stories may slip through or over-merge.
- Feeds can have malformed XML; code handles it but may log warnings.
- This is a script pipeline (single-process) not a dedicated service.

## 📚 Reference docs

- `ARCHITECTURE.md`
- `PROJECT_MAP.md`
- `RUNBOOK.md`
- `AI_CONTEXT.md`

