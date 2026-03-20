# Briefing App — Architecture Reference

Current as of March 19, 2026. Use this as context when starting a new Claude session.

---

## What This Is

A personalized daily news app with an iOS client. A Python pipeline runs once a day, fetches and ranks news from ~20 RSS feeds, pulls live NBA social buzz from X via Grok, generates AI summaries via OpenAI, and writes everything to Redis. A FastAPI server on Render reads from Redis and serves the iOS app.

---

## System Overview

```
GitHub Actions (daily cron, 7am CT)
  └── cron_pipeline.py
        ├── fetch_news.py        — RSS feeds (~80 articles)
        ├── cluster.py           — TF-IDF deduplication
        ├── categorize.py        — section assignment
        ├── quality.py           — low-value story filter
        ├── rank.py              — importance scoring
        ├── nba_social.py        — live X search via Grok API
        ├── summarize.py         — OpenAI story summaries
        └── redis_cache.py       — write sections + summaries to Upstash Redis

Render (newsletter-app, free tier, Ohio)
  └── server.py (FastAPI)
        ├── GET /sections        — reads sections + nba_social_buzz from Redis
        ├── POST /summary        — reads pre-generated summaries from Redis
        ├── GET /warmup          — wakes server, loads Redis into memory
        └── GET /health          — liveness check

iOS App (Briefing, Swift)
  └── APIService.fetchSections() → HomeViewModel → HomeView
        ├── SectionTabBar        — top / markets / ai / finance_market_structure / nba
        ├── StoryCard            — per-story headline, source, bias flags
        ├── SocialBuzzCard       — shown in NBA tab, renders nba_social_buzz
        └── SummarySheet         — per-story AI summary on tap
```

---

## Data Flow

1. **GitHub Actions** runs `cron_pipeline.py` daily at 12:00 UTC (7am CT)
2. Pipeline writes two Redis keys:
   - `briefing:sections` — full ranked sections dict including `nba_social_buzz`
   - `briefing:summaries` — `{story_id: summary_dict}` for all stories
   - `briefing:cache_date` — today's date for staleness checks
   - TTL: 28 hours
3. **iOS app** calls `/warmup` on foreground → loads Redis into server memory
4. `/sections` returns the full dict; server caches in memory for the rest of the day
5. `/summary` returns pre-generated summaries from Redis (no on-demand generation)

**Critical:** The server never runs the pipeline. It only reads from Redis. The only way to get fresh data is to run `cron_pipeline.py` (via GitHub Actions or locally).

---

## Sections

| Key | Display Name | Story Limit |
|-----|-------------|-------------|
| `top` | Top Stories | 5 |
| `markets` | Markets | 2 |
| `ai` | AI | 3 |
| `finance_market_structure` | Market Structure | 3 |
| `nba` | NBA | 3 |

Stories are ranked by a weighted score: ideological spread (2.0), source quality (1.8), corroboration (1.5), impact keywords (1.4), personal relevance (1.4), cluster strength (1.25), category importance (1.2), outlet spread (1.1), recency (1.1).

---

## NBA Social Buzz (nba_social.py)

The Twitter/X integration. Runs as part of the cron pipeline when `GROK_ENABLED=true`.

**API:** xAI `/v1/responses` endpoint (NOT `/v1/chat/completions` — that API does not search X)
**Model:** `grok-4-fast-non-reasoning` (only grok-4 family supports server-side tools)
**Tool:** `{"type": "x_search"}` — makes live X searches, typically 4–7 calls per run
**Key env var:** `GROK_API_KEY`

**What it returns (top-level key in /sections response):**
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
    {"topic": "Cade Cunningham Injury", "summary": "..."},
    {"topic": "Nuggets Loss to Grizzlies", "summary": "..."},
    {"topic": "Lakers Winning Streak", "summary": "..."}
  ],
  "data_date": "March 18, 2026"
}
```

`rockets_buzz` / `bulls_buzz` are null when the team had no game. `league_buzz` always has 2–3 items.

**This field lives at the top level of the `/sections` response**, not inside any section array. The iOS `SocialBuzzCard` renders it in the NBA tab when `viewModel.selectedSection == "nba"` and `viewModel.nbaSocialBuzz != nil`.

**Critical gotchas (learned the hard way):**
- `grok-3` with `search_parameters` → 410 Gone (deprecated)
- `grok-2-1212` does not exist
- `grok-3` in chat mode does NOT search X — `num_sources_used: 0`, returns hallucinated content that looks real
- Must use `/v1/responses` + `tools: [{"type": "x_search"}]` + a grok-4 model
- Do NOT say "an empty array is acceptable" in the prompt — Grok takes that as permission to return nothing
- Prompt covers yesterday AND today to capture post-game reactions and morning-after takes

---

## Server Caching (Two Layers)

**Layer 1 — In-memory:** Loaded once per day from Redis. Valid while `_sections_mem_date == str(date.today())`. Never reloads mid-day even if Redis is updated.

**Layer 2 — Upstash Redis:** Survives deploys and Render sleep. 28-hour TTL.

**Consequence:** After running the GitHub Actions workflow manually mid-day, the server must be redeployed to pick up new Redis data. The morning scheduled cron is fine — the server will have fresh memory after overnight sleep.

---

## Deployment

**Render service:** `newsletter-app` (`srv-d6tbca0gjchc73cb5fd0`)
- URL: `https://newsletter-app-ry48.onrender.com`
- Free tier — sleeps after inactivity, ~30s cold start
- Auto-deploys on push to `main` (unreliable — always force-trigger via MCP after push)
- Force-trigger method: call `mcp__render__update_environment_variables` with a `DEPLOY_TIMESTAMP` bump

**Cron:** GitHub Actions `.github/workflows/daily_newsletter.yml`
- Schedule: `0 12 * * *` (12:00 UTC / 7am CT)
- Has `workflow_dispatch` for manual runs
- Runs `cron_pipeline.py` on an Ubuntu runner
- Required GitHub Secrets: `OPENAI_API_KEY`, `GROK_API_KEY`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`

**Note:** `render.yaml` defines services named `briefing-api` and `briefing-cron` but the actual deployed service is named `newsletter-app` — the yaml is reference only.

---

## Environment Variables

| Variable | Where Set | Purpose |
|----------|-----------|---------|
| `OPENAI_API_KEY` | Render + GitHub Secret | Story summarization |
| `OPENAI_ENABLED` | Render + GitHub Actions | Toggle OpenAI (`true`) |
| `OPENAI_MODEL` | Render + GitHub Actions | Model (`gpt-4o-mini`) |
| `GROK_API_KEY` | Render + GitHub Secret | X social buzz (shared by NBA and AI social) |
| `GROK_ENABLED` | Render + GitHub Actions | Toggle NBA social buzz via Grok (`true`) |
| `AI_SOCIAL_ENABLED` | Render + GitHub Actions | Toggle AI social buzz via Grok (default `false`) |
| `UPSTASH_REDIS_REST_URL` | Render + GitHub Secret | Redis endpoint |
| `UPSTASH_REDIS_REST_TOKEN` | Render + GitHub Secret | Redis auth |
| `MAX_STORIES_FETCHED` | Render | RSS fetch cap (80) |

---

## Key Files

```
news-app/
├── server.py                        FastAPI server — reads Redis, serves iOS
├── cron_pipeline.py                 Daily job — runs pipeline, writes Redis
├── requirements.txt                 feedparser, openai, httpx, upstash-redis, fastapi, uvicorn
├── render.yaml                      Render config reference (service named differently in dashboard)
├── .github/workflows/
│   └── daily_newsletter.yml         GitHub Actions cron + workflow_dispatch
├── config/
│   ├── sources.yaml                 ~20 RSS feed definitions
│   └── settings.yaml                All pipeline thresholds and weights
└── news_pipeline/
    ├── pipeline_api.py              Orchestrates full pipeline; get_ranked_stories() + get_story_summary()
    ├── fetch_news.py                Parallel RSS fetch (15 items/feed, 80 total cap)
    ├── cluster.py                   TF-IDF + entity/storyline overlap deduplication
    ├── categorize.py                Keyword + source rules → section assignment
    ├── quality.py                   Filters vague/low-value stories
    ├── rank.py                      Weighted importance scoring
    ├── summarize.py                 OpenAI gpt-4o-mini summaries + left/right takes for top section
    ├── nba_social.py                Grok /v1/responses + x_search — live X NBA buzz
    ├── redis_cache.py               Upstash Redis read/write for sections and summaries
    ├── models.py                    Story, FeedSource dataclasses
    └── bias_detect.py               Charged language detection per source

Briefing/Briefing/Briefing/          iOS app (Swift, git submodule)
├── Models/
│   ├── Section.swift                SectionsResponse (decodes /sections JSON incl. nba_social_buzz)
│   └── NBASocialBuzz.swift          NBASocialBuzz, TeamBuzz, LeagueBuzzItem
├── Views/
│   ├── HomeView.swift               Main view — section tabs, story list, SocialBuzzCard
│   ├── SocialBuzzCard.swift         Renders rockets_buzz, bulls_buzz, league_buzz
│   └── SummarySheet.swift           Per-story summary modal
├── ViewModels/
│   └── HomeViewModel.swift          Holds sections, nbaSocialBuzz, selectedSection state
└── Services/
    └── APIService.swift             fetchSections(), fetchSummary()
```

---

## Known Issues / Watch Out For

- **Stale memory cache mid-day:** After a manual workflow run, redeploy the server to flush in-memory cache. Otherwise the server keeps serving the old data until tomorrow.
- **Bulls game detection:** Grok sometimes returns `bulls_buzz: null` even when the Bulls played. The X search just doesn't always find enough posts about their games.
- **`/summary` only works from Redis cache:** The server's `_story_registry` is never populated in production (only gets populated when `get_ranked_stories()` runs in-process, which only happens in cron). All summaries are pre-generated by `cron_pipeline.py` and served from Redis. If a summary isn't in Redis, `/summary` returns 202 (retry).
- **GitHub Secret rotation:** When rotating `GROK_API_KEY`, update BOTH the Render service env var AND the GitHub Actions secret. If only one is updated, the cron will silently fail and write `nba_social_buzz: null` to Redis with no obvious error.
- **Render free tier cold starts:** First request after inactivity takes ~30s. iOS app handles this via `/warmup` + retry loop.
