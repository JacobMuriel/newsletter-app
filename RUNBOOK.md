# Runbook

## Environment Setup

Create a fresh virtual environment unless you intentionally want to use the checked-in `.venv`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Important:

- The bundled `.venv` currently points to `/Users/jacobmuriel/Desktop/roku_sports_channel/backend/.venv/bin/python3`.
- Needs verification whether that was intentional. It is safer to recreate `.venv` locally.

## Main Commands

Install dependencies:

```bash
pip install -r requirements.txt
```

Run dry without OpenAI or email:

```bash
DRY_RUN=true SEND_EMAIL=false OPENAI_ENABLED=false python main.py
```

Run with OpenAI enabled but no email:

```bash
OPENAI_API_KEY=... OPENAI_ENABLED=true DRY_RUN=true SEND_EMAIL=false python main.py
```

Run full pipeline with email:

```bash
SEND_EMAIL=true DRY_RUN=false python main.py
```

Verified local command in this audit:

```bash
DRY_RUN=true SEND_EMAIL=false OPENAI_ENABLED=false .venv/bin/python main.py
```

## Test, Lint, Deploy

- Test command: no test suite found
- Lint command: no lint configuration found
- Deploy command: none found
- Scheduled automation file present: [.github/workflows/daily_newsletter.yml](/Users/jacobmuriel/Desktop/newsletter/.github/workflows/daily_newsletter.yml)

Needs verification:

- Whether the GitHub Actions workflow is active in a real GitHub repository
- Whether any external scheduler also runs `main.py`

## Required Environment Variables

For OpenAI summarization:

```bash
OPENAI_API_KEY=
OPENAI_ENABLED=true
OPENAI_MODEL=gpt-5-nano
```

For SMTP delivery:

```bash
NEWSLETTER_EMAIL_FROM=
NEWSLETTER_EMAIL_TO=
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_TLS=true
SEND_EMAIL=true
DRY_RUN=false
```

Common optional overrides:

```bash
MAX_STORIES_FETCHED=120
MAX_STORIES_TO_RANK=30
MAX_STORIES_TO_SUMMARIZE=10
LOG_LEVEL=INFO
```

## Expected Outputs

- One Markdown file per run in [output/](/Users/jacobmuriel/Desktop/newsletter/output)
- Console log summary with feed failures, story counts, OpenAI usage, and email status

## Common Debugging Steps

Check that dependencies are installed:

```bash
python -c "import feedparser, yaml, dotenv, openai; print('deps-ok')"
```

Inspect effective config files:

```bash
sed -n '1,220p' config/settings.yaml
sed -n '1,220p' config/sources.yaml
```

Run with verbose logging:

```bash
LOG_LEVEL=DEBUG DRY_RUN=true SEND_EMAIL=false OPENAI_ENABLED=false python main.py
```

Inspect newest generated output:

```bash
ls -lt output
sed -n '1,220p' output/newsletter_YYYYMMDD_HHMMSS.md
```

## Common Failure Points

`ModuleNotFoundError: No module named 'feedparser'`

- Cause: dependencies not installed in the active Python environment.
- Fix: install [requirements.txt](/Users/jacobmuriel/Desktop/newsletter/requirements.txt) into the environment you are actually running.

Malformed feed warnings

- Observed during this audit for Reuters, VentureBeat AI, SEC, and CFTC feeds.
- The pipeline continues if entries are still parseable.
- Diagnose by checking the logs; feed failures are reported in the run summary.

No OpenAI summaries

- Cause: `OPENAI_ENABLED=false`, missing `OPENAI_API_KEY`, quota errors, or request failures.
- Behavior: pipeline falls back to heuristic summaries automatically.

Email not sent

- Cause: `DRY_RUN=true`, `SEND_EMAIL=false`, or missing SMTP fields.
- Diagnose from log output in [news_pipeline/send_email.py](/Users/jacobmuriel/Desktop/newsletter/news_pipeline/send_email.py).

Unexpected section matches

- Cause: substring-based keywords in categorization and ranking.
- Diagnose by reviewing [config/settings.yaml](/Users/jacobmuriel/Desktop/newsletter/config/settings.yaml) and the category log lines emitted during a run.

## Deployment / Scheduling Path

The only deployment-like path in the repository is the GitHub Actions workflow in [.github/workflows/daily_newsletter.yml](/Users/jacobmuriel/Desktop/newsletter/.github/workflows/daily_newsletter.yml):

- Triggered manually with `workflow_dispatch`
- Also scheduled for `0 12 * * *`
- Installs dependencies and runs `python main.py`
- Depends on repository secrets for OpenAI and SMTP

Needs verification:

- Whether the real upstream repository still contains this workflow
- Whether secret names and schedule are still correct
