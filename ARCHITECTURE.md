# Briefing App — Architecture Reference

Current as of April 2, 2026 (session 19). Use this as context when starting a new Claude session.

---

## What This Is

A personalized daily news app with an iOS client. A Python pipeline runs at 6am CT (primary) and again at 2pm + 6pm CT (top-stories-only refresh). It fetches and ranks news from ~20 RSS feeds, pulls live social buzz from X via Grok, generates AI summaries via OpenAI, and writes everything to Redis. A FastAPI server on Render reads from Redis and serves the iOS app.

---

## System Overview

```
GitHub Actions (primary: 6am CT / 11:00 UTC; secondary: 2pm + 6pm CT)
  └── cron_pipeline.py [--top-only]
        ├── nba_stats.py         — ESPN game stats (primary only)
        ├── nba_social.py        — live X search via Grok (primary only)
        ├── fetch_news.py        — RSS feeds (~80 articles)
        ├── cluster.py           — TF-IDF deduplication
        ├── categorize.py        — section assignment
        ├── quality.py           — low-value story filter
        ├── rank.py              — importance scoring
        ├── ai_social.py         — AI/tech X buzz via Grok (primary only)
        ├── finance_social.py    — finance X buzz via Grok (primary only)
        ├── markets_social.py    — markets X buzz via Grok (primary only)
        ├── summarize.py         — OpenAI story summaries
        └── redis_cache.py       — write sections + summaries to Upstash Redis

Render (newsletter-app, free tier, Ohio)
  └── server.py (FastAPI)
        ├── GET /sections        — reads sections + all buzz fields from Redis
        ├── POST /summary        — reads pre-generated summaries from Redis
        ├── GET /warmup          — wakes server, loads Redis into memory
        └── GET /health          — liveness check

iOS App (Briefing, Swift, git submodule)
  └── APIService → HomeViewModel → HomeView
        ├── warmup()             — GET /warmup fires first on every loadSections() call
        ├── SectionTabBar        — top / markets / ai / finance_market_structure / nba
        ├── StoryCard            — per-story headline, source, bias flags
        ├── SocialBuzzCard       — shown in NBA tab, renders nba_social_buzz
        └── SummarySheet         — per-story AI summary on tap
```

---

## Data Flow

### Primary run (6am CT)
1. **GitHub Actions** triggers `cron_pipeline.py` (no flags) at 11:00 UTC
2. NBA stats fetched from ESPN; saved to `briefing:nba_stats`
3. NBA social buzz fetched from Grok with game context; AI/finance/markets buzz also fetched
4. Full pipeline runs: fetch → cluster → categorize → quality → rank → summarize
5. All Redis keys written: `briefing:sections`, `briefing:summaries`, `briefing:cache_date` (TTL 28h)
6. Render auto-redeploys via curl step at end of workflow
7. Workflow polls `/health` every 15s (up to 5 min), then hits `/warmup` — in-memory cache is hot before any iOS client connects

### Secondary runs (2pm + 6pm CT)
1. GitHub Actions triggers `cron_pipeline.py --top-only`
2. Grok/NBA/stats all skipped — morning buzz data preserved
3. Full RSS fetch + cluster + rank pipeline runs (top section cap expanded to 10)
4. **Partial Redis write:** only `briefing:sections.top` is patched; summaries merged in
5. `briefing:cache_date` NOT updated — morning timestamp preserved
6. Render auto-redeploys; workflow polls + warms cache

**Critical:** The server never runs the pipeline. It only reads from Redis.

---

## Sections

| Key | Display Name | Primary Limit | Secondary Limit |
|-----|-------------|--------------|-----------------|
| `top` | Top Stories | 5 | 10 |
| `markets` | Markets | 2 | (unchanged) |
| `ai` | AI | 3 | (unchanged) |
| `finance_market_structure` | Market Structure | 3 | (unchanged) |
| `nba` | NBA | 3 | (unchanged) |

Stories ranked by weighted score: ideological spread (2.0), source quality (1.8), corroboration (1.5), impact keywords (1.4), personal relevance (1.4), cluster strength (1.25), category importance (1.2), outlet spread (1.1), recency (1.1).

---

## Grok Integration (nba_social.py + ai_social.py + finance_social.py + markets_social.py)

**API:** xAI `/v1/responses` (NOT `/v1/chat/completions` — that does not search X live)
**Model:** `grok-4-fast-non-reasoning` (grok-3 does not support `x_search` tool)
**Tool:** `{"type": "x_search"}` — makes live X searches, ~4–7 calls per run
**Runs:** Primary pipeline only — all Grok calls are skipped in `--top-only` mode

**nba_social_buzz response shape (top-level key in /sections):**
```json
{
  "rockets_buzz": {
    "played": true,
    "opponent": "Los Angeles Lakers",
    "score": "124-116",
    "result": "loss",
    "sentiment": "negative",
    "reactions": ["...", "...", "..."]
  },
  "bulls_buzz": null,
  "league_buzz": [
    {"topic": "Cade Cunningham Injury", "summary": "..."}
  ],
  "data_date": "March 18, 2026"
}
```

`nba_social_buzz` lives at the **top level** of `/sections` response, not inside the `nba` array.

**Critical gotchas:**
- grok-3 in chat mode returns `num_sources_used: 0` — hallucinated posts that look real
- Must use `/v1/responses` + `tools: [{"type": "x_search"}]` + a grok-4 model
- Do NOT say "empty array is acceptable" — Grok treats that as permission to return nothing
- Prompt must include yesterday AND today's dates explicitly

---

## Server Caching (Two Layers)

**Layer 1 — In-memory:** Loaded once per day from Redis on first request after midnight. Never reloads mid-day.

**Layer 2 — Upstash Redis:** Survives deploys and Render sleep. 28-hour TTL on all keys.

**Consequence:** After a manual workflow run mid-day, redeploy Render to flush the in-memory cache.

---

## Deployment

**Render service:** `newsletter-app` (`srv-d6tbca0gjchc73cb5fd0`)
- URL: `https://newsletter-app-ry48.onrender.com`
- Free tier — sleeps after inactivity, ~30s cold start
- **Auto-redeploys at the end of every GitHub Actions pipeline run** (curl step in workflow)
- After redeploy, workflow polls `/health` then hits `/warmup` — cache is pre-loaded before first iOS connect
- For mid-day manual deploys (no pipeline run): bump `DEPLOY_TIMESTAMP` via `mcp__render__update_environment_variables`, then hit `/warmup` manually

**Cron:** `.github/workflows/daily_newsletter.yml`
- Primary: `0 11 * * *` (11:00 UTC / 6am CT)
- Secondary: `0 19 * * *` (2pm CT) and `0 23 * * *` (6pm CT)
- `workflow_dispatch` always runs as primary (full pipeline)
- Run mode detected by `Set run mode` step checking UTC hour
- Required GitHub Secrets: `OPENAI_API_KEY`, `GROK_API_KEY`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`, `RENDER_API_KEY`

**Note:** `render.yaml` defines services named `briefing-api` and `briefing-cron` but the actual deployed service is named `newsletter-app` — the yaml is reference only.

---

## Environment Variables

| Variable | Where Set | Purpose |
|----------|-----------|---------|
| `OPENAI_API_KEY` | Render + GitHub Secret | Story summarization |
| `OPENAI_ENABLED` | Render + GitHub Actions | Toggle OpenAI (`true`) |
| `OPENAI_MODEL` | Render + GitHub Actions | Model (`gpt-4o-mini`) |
| `GROK_API_KEY` | Render + GitHub Secret | X social buzz (shared by all Grok modules) |
| `GROK_ENABLED` | Render + GitHub Actions | Toggle NBA social buzz via Grok (`true`) |
| `AI_SOCIAL_ENABLED` | Render + GitHub Actions | Toggle AI social buzz via Grok (`true`) |
| `FINANCE_SOCIAL_ENABLED` | Render + GitHub Actions | Toggle finance + markets buzz via Grok (`true`) |
| `NBA_STATS_ENABLED` | Render + GitHub Actions | Toggle ESPN NBA stats fetch (`true`) |
| `UPSTASH_REDIS_REST_URL` | Render + GitHub Secret | Redis endpoint |
| `UPSTASH_REDIS_REST_TOKEN` | Render + GitHub Secret | Redis auth |
| `RENDER_API_KEY` | GitHub Secret only | Render deploy trigger at end of pipeline |
| `MAX_STORIES_FETCHED` | Render | RSS fetch cap (80) |
| `TOP_SECTION_LIMIT` | Set by `--top-only` code | Overrides top section cap (10 in secondary runs) |

---

## Key Files

```
news-app/
├── server.py                        FastAPI server — reads Redis, serves iOS
├── cron_pipeline.py                 Pipeline entry point; --top-only flag for secondary runs
├── requirements.txt
├── render.yaml                      Render config reference (service name differs in dashboard)
├── .github/workflows/
│   └── daily_newsletter.yml         3 cron triggers + Set run mode + Render auto-deploy
├── config/
│   ├── sources.yaml                 ~20 RSS feed definitions
│   └── settings.yaml                Pipeline thresholds, weights, section_limits
└── news_pipeline/
    ├── pipeline_api.py              get_ranked_stories() — full pipeline orchestration
    ├── fetch_news.py                Parallel RSS fetch (15/feed, 80 total cap)
    ├── cluster.py                   TF-IDF + entity/storyline overlap deduplication
    ├── categorize.py                Keyword + source rules → section assignment
    ├── quality.py                   Filters vague/low-value stories
    ├── rank.py                      Weighted importance scoring
    ├── summarize.py                 OpenAI gpt-4o-mini summaries + left/right takes (top section)
    ├── nba_social.py                Grok /v1/responses + x_search — live X NBA buzz
    ├── nba_stats.py                 ESPN game stats — anchors Grok search with real game data
    ├── ai_social.py                 Grok — AI/tech X buzz
    ├── finance_social.py            Grok — finance X buzz
    ├── markets_social.py            Grok — markets X buzz
    ├── redis_cache.py               Upstash Redis read/write; write_top_section_only() for partial writes
    ├── models.py                    Story, FeedSource dataclasses
    └── bias_detect.py               Charged language detection per source

Briefing/Briefing/Briefing/          iOS app (Swift, git submodule)
├── Models/
│   ├── Section.swift                SectionsResponse (decodes /sections JSON incl. all buzz fields)
│   └── NBASocialBuzz.swift          NBASocialBuzz, TeamBuzz, LeagueBuzzItem
├── Views/
│   ├── HomeView.swift               Main view — section tabs, story list, SocialBuzzCard
│   ├── SocialBuzzCard.swift         Renders rockets_buzz, bulls_buzz, league_buzz
│   └── SummarySheet.swift           Per-story summary modal
├── ViewModels/
│   └── HomeViewModel.swift          Holds sections, nbaSocialBuzz, selectedSection state
└── Services/
    └── APIService.swift             warmup(), fetchSections(), fetchSummary()
```

---

## Known Issues / Watch Out For

- **Stale memory cache mid-day:** After a manual workflow run, redeploy Render to flush. The pipeline auto-deploys at end, but if you need to test mid-day without running the full pipeline, you still need a manual deploy bump.
- **Secondary run partial write:** `write_top_section_only()` reads the existing `briefing:sections` key, patches `top`, and writes it back. If Redis is cold when a secondary run fires (e.g. a manual run after Redis expired), it falls back to a bare write with only `top` — other sections will be missing until the next primary run.
- **Bulls game detection:** Grok sometimes returns `bulls_buzz: null` even when the Bulls played — X just doesn't always surface enough posts.
- **`/summary` only works from Redis:** `_story_registry` on the server is always empty in production. All summaries are pre-generated by `cron_pipeline.py`. If missing, `/summary` returns 202.
- **GitHub Secret rotation:** When rotating `GROK_API_KEY`, update BOTH Render env var AND GitHub Actions secret. Missing either one silently writes `nba_social_buzz: null`.
- **RENDER_API_KEY is GitHub-only:** It's only needed by the Actions curl step — no need to add it as a Render env var.
- **Render free tier cold starts:** First request after inactivity ~30s. iOS app handles via `/warmup` + retry.
- **Post-deploy warmup race (dev only):** During development sessions, a git push triggers Render's auto-deploy on push AND the workflow triggers its own deploy — if both race, the warmup may hit the first (old) instance which then gets replaced. Only happens when pushing code mid-session. The scheduled 6am cron has no competing push so warmup works cleanly.
