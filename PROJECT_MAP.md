# Project Map

## Important Tree

```text
.
├── main.py                        # Single entry point for the full newsletter pipeline
├── requirements.txt               # Runtime Python dependencies
├── .env.example                   # Example environment variables for OpenAI and SMTP
├── config/
│   ├── settings.yaml              # Pipeline caps, thresholds, section rules, ranking, delivery metadata
│   └── sources.yaml               # RSS feed list and source labels
├── news_pipeline/
│   ├── __init__.py                # Package marker
│   ├── models.py                  # Shared dataclasses for sources, stories, and run stats
│   ├── fetch_news.py              # RSS fetch and normalization
│   ├── dedupe.py                  # Similar-story merge logic
│   ├── categorize.py              # Section assignment heuristics
│   ├── quality.py                 # Quality scoring and rejection
│   ├── rank.py                    # Importance scoring and sorting
│   ├── summarize.py               # OpenAI/fallback summary generation
│   ├── newsletter.py              # Markdown rendering
│   └── send_email.py              # SMTP delivery
├── output/                        # Generated newsletters and other run artifacts
└── .github/
    └── workflows/
        └── daily_newsletter.yml   # Scheduled/manual GitHub Actions workflow file
```

## If You Need To Change X, Start Here

- Add or remove news sources: [config/sources.yaml](/Users/jacobmuriel/Desktop/newsletter/config/sources.yaml)
- Tune section assignment: [config/settings.yaml](/Users/jacobmuriel/Desktop/newsletter/config/settings.yaml) and [news_pipeline/categorize.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/categorize.py)
- Tune ranking logic: [config/settings.yaml](/Users/jacobmuriel/Desktop/newsletter/config/settings.yaml) and [news_pipeline/rank.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/rank.py)
- Change deduplication behavior: [news_pipeline/dedupe.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/dedupe.py)
- Change newsletter format: [news_pipeline/newsletter.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/newsletter.py)
- Change email sending behavior: [news_pipeline/send_email.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/send_email.py)
- Change runtime flags or limits: [main.py](/Users/jacobmuriel/Desktop/newsletter/main.py) and [config/settings.yaml](/Users/jacobmuriel/Desktop/newsletter/config/settings.yaml)
- Change OpenAI summarization behavior: [news_pipeline/summarize.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/summarize.py)

## Files That Seem Unused / Legacy / Suspicious

- [output/newsletter_20260316_140541.html](/Users/jacobmuriel/Desktop/newsletter/output/newsletter_20260316_140541.html): current source code does not generate HTML. Needs verification.
- [README.md](/Users/jacobmuriel/Desktop/newsletter/README.md): replaced during this audit because the prior version claimed structure that does not fully match this checkout.
- [__pycache__/](/Users/jacobmuriel/Desktop/newsletter/__pycache__): generated Python bytecode, not source.
- [news_pipeline/__pycache__/](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/__pycache__): generated Python bytecode, not source.
- [.venv/](/Users/jacobmuriel/Desktop/newsletter/.venv): local environment only; in this checkout its `python3` symlink points outside the repo, which is fragile.
- [.github/workflows/daily_newsletter.yml](/Users/jacobmuriel/Desktop/newsletter/.github/workflows/daily_newsletter.yml): valid workflow file, but whether it is actually used is uncertain because this folder is not a Git checkout.
