# CLAUDE.md — Persistent Brain

Last updated: April 2, 2026 (iOS warmup prefetch)

This file is the single source of truth for any Claude session — chat or Claude Code.
Read this before touching anything. It covers not just *what* the system does but *why* it's built this way, common failure modes, and how to debug them.

---

## What This Project Is

A personal daily news app called **Briefing**. The core motivation is unbiased news — not just aggregating headlines but making ideological framing transparent. Left/right takes are surfaced explicitly so Jacob can see how different outlets are spinning the same story.

**Stack:** Python pipeline → Redis → FastAPI (Render) → iOS (SwiftUI)

---

## The Most Important Architectural Decision

**The server never runs the pipeline. Ever.**

This is the foundational constraint everything else flows from. The Render free tier has ephemeral containers — any in-memory or `/tmp` state is wiped on sleep or redeploy. So:

- The pipeline runs at 6am CT (primary) and 2pm/6pm CT (secondary top-only refreshes) via GitHub Actions
- It writes everything to Upstash Redis (external, persistent)
- The FastAPI server is read-only — it only reads from Redis
- If Redis is empty or stale, the server returns nothing — it does NOT fall back to running the pipeline

**Why:** Running the pipeline on an HTTP request would cause 30-60 second timeouts, burn OpenAI API credits on every cold start, and fail unpredictably on Render's free tier. Pre-generating and caching is the only viable pattern here.

**Consequence for debugging:** If the iOS app is showing stale or missing data, the problem is almost always one of:
1. The GitHub Actions cron didn't run (check Actions tab)
2. The pipeline ran but Redis wasn't written (check pipeline logs for errors)
3. The server's in-memory cache is stale from a mid-day manual run (redeploy Render to flush it)

---

## System Architecture

```
GitHub Actions (primary: 6am CT / 11:00 UTC; secondary: 2pm + 6pm CT)
  └── cron_pipeline.py
        ├── fetch_news.py        — parallel RSS fetch (~80 articles, 20 feeds)
        ├── cluster.py           — TF-IDF + entity deduplication → Stories
        ├── categorize.py        — keyword/source rules → section assignment
        ├── quality.py           — filters vague/low-value stories
        ├── rank.py              — weighted importance scoring
        ├── nba_social.py        — live X search via Grok API
        ├── summarize.py         — OpenAI gpt-4o-mini summaries + left/right takes
        └── redis_cache.py       — writes sections + summaries to Upstash Redis

Render (newsletter-app, free tier, Ohio)
  └── server.py (FastAPI)
        ├── GET /sections        — reads from Redis (or in-memory cache)
        ├── POST /summary        — reads pre-generated summaries from Redis
        ├── GET /warmup          — wakes server, preloads Redis into memory
        └── GET /health          — liveness check

iOS App (Briefing, SwiftUI, iOS 16+)
  └── APIService → HomeViewModel → HomeView
        ├── SectionTabBar        — top / markets / ai / finance_market_structure / nba
        ├── StoryCard            — headline, source, bias flags
        ├── SocialBuzzCard       — NBA tab, renders nba_social_buzz
        └── SummarySheet         — per-story AI summary on tap
```

---

## Two-Layer Cache (and Why It Matters for Debugging)

**Layer 1 — In-memory dict on the Render server:**
- Loaded from Redis once per day on first request after midnight
- Valid while `_sections_mem_date == str(date.today())`
- Never reloads mid-day even if Redis is updated

**Layer 2 — Upstash Redis:**
- Written by the cron pipeline
- 28-hour TTL
- Survives Render sleep and redeploys

**The gotcha:** If you manually trigger the GitHub Actions workflow mid-day to test a fix, the server will still serve the old in-memory data until tomorrow — OR until you force-redeploy Render. Always redeploy after a manual pipeline run.

---

## Pre-Deploy Checklist (MANDATORY)

**Run this before every GitHub Actions trigger or Render deploy — no exceptions.**

These steps must all pass before proceeding. Self-correct up to 3 attempts per step. If any step still fails after 3 attempts, stop and report to the user. Do not proceed to GitHub Actions or Render until all steps pass.

### Step 1 — Syntax Check All Pipeline Modules

```bash
python -m py_compile cron_pipeline.py news_pipeline/fetch_news.py news_pipeline/cluster.py news_pipeline/categorize.py news_pipeline/quality.py news_pipeline/rank.py news_pipeline/nba_social.py news_pipeline/summarize.py news_pipeline/redis_cache.py news_pipeline/nba_stats.py
```

Run from the repo root. Any `SyntaxError` must be fixed before moving on.

### Step 2 — Dry Run With All APIs Disabled

Run the pipeline with all external API calls disabled:

```bash
OPENAI_ENABLED=false GROK_ENABLED=false AI_SOCIAL_ENABLED=false \
  UPSTASH_REDIS_REST_URL=disabled UPSTASH_REDIS_REST_TOKEN=disabled \
  python cron_pipeline.py --dry-run 2>&1 | tail -40
```

Expected: pipeline completes without crashing (Redis writes and API calls are no-ops). Any unhandled exception is a blocker.

> **Note:** If `--dry-run` is not yet implemented, run with env vars above and verify no exceptions reach top-level. A `ConnectionError` or `AuthenticationError` on disabled services is expected and acceptable — an unhandled crash is not.

### Step 3 — Isolated Module Test for Any File Touched This Session

For each pipeline module edited this session, run its standalone self-test or import check:

```bash
python -c "import <module_name>; print('OK')"
```

If the module has a `if __name__ == '__main__'` block or a `--test` flag, use that instead. Fix any `ImportError`, `AttributeError`, or runtime exception before proceeding.

### Step 4 — Inspect Dry-Run Output for Data Quality

Run the dry run again (same env vars as Step 2) and capture full output for inspection:

```bash
OPENAI_ENABLED=false GROK_ENABLED=false AI_SOCIAL_ENABLED=false \
  UPSTASH_REDIS_REST_URL=disabled UPSTASH_REDIS_REST_TOKEN=disabled \
  python cron_pipeline.py 2>&1
```

Read the full output and check every item below. Flag any that look wrong — do not treat this as pass/fail, treat it as a sanity check that requires human judgment:

**Article fetch:**
- Did it fetch at least 40 raw articles? (normal: 60–80; below 40 suggests feeds are failing)
- Did it log any feed-level errors or timeouts? (a few are acceptable; >5 is a problem)

**Clustering:**
- Did it form at least 10 clusters? (normal: 20–35; below 10 means similarity threshold is too strict or source overlap is too low)
- Did any section end up with 0 stories after clustering? That section will be empty in the app.

**Per-section story counts (from `pipeline_api: pipeline complete` log line):**

| Section | Minimum acceptable | Expected |
|---|---|---|
| `top` | 3 | 5 |
| `markets` | 1 | 2 |
| `ai` | 1 | 3 |
| `finance_market_structure` | 1 | 3 |
| `nba` | 1 | 3 |

If any section is below the minimum, investigate before deploying — the app will show a visibly thin or empty section.

**Story quality (scan the story titles in the log output):**
- Are headlines concrete and specific, or vague/listicle-y? (e.g. "5 things to know about..." is a quality filter miss)
- Are the top stories actually top stories, or filler?
- Are NBA stories actually NBA stories, or did sports bleed into `top`?

If anything looks off, investigate the relevant module (`cluster.py`, `quality.py`, `categorize.py`) before proceeding.

### Checklist Summary

- [ ] Step 1: All modules compile without syntax errors
- [ ] Step 2: Dry run completes without unhandled exceptions
- [ ] Step 3: Every touched module imports/runs cleanly in isolation
- [ ] Step 4: Output inspected — article counts, cluster counts, per-section story counts, and story quality all look reasonable
- [ ] All 4 steps passed → safe to proceed to Deploy Sequence

---

## Full Session Workflow (MANDATORY — follow exactly)

Every time code changes are made, execute these steps in order. Do not skip or reorder.

### Phase 1 — Pre-Deploy Tests (before any push)

Run the Pre-Deploy Checklist above. Self-correct up to 3 attempts per failing step. If any step still fails after 3 attempts, **stop and report to the user — do not push or deploy**.

All 4 checklist steps must pass before moving to Phase 2.

### Phase 2 — Push to GitHub

```bash
git add <specific files>
git commit -m "..."
git push origin main
```

### Phase 3 — Run GitHub Actions Pipeline

Always run the pipeline after a push, unless the change is server-only (no pipeline logic touched):

```bash
gh workflow run daily_newsletter.yml
```

Poll until status is `completed`:
```bash
gh run list --workflow=daily_newsletter.yml --limit=1
```

Do not proceed to Phase 4 until the run shows `completed / success`. If it fails, check the logs and fix before redeploying.

### Phase 4 — Deploy to Render

Render redeploys automatically at the end of the GitHub Actions pipeline (curl step in workflow). Confirm via `/health` ~2 min after the pipeline completes — no manual trigger needed.

If a mid-day manual deploy is still required (e.g., server-only change), bump `DEPLOY_TIMESTAMP` via MCP:

```python
mcp__render__update_environment_variables(
    serviceId="srv-d6tbca0gjchc73cb5fd0",
    envVars=[{"key": "DEPLOY_TIMESTAMP", "value": "<current UTC datetime>"}]
)
```

Poll via `mcp__render__get_deploy` until `status == "live"`. Do not proceed until live.

### Phase 5 — Notify via Telegram + Launch Xcode Deploy

Send a message to Jacob through the Telegram MCP tool (`mcp__plugin_telegram_telegram__reply`, chat_id `8657007613`) summarizing what was deployed. Always do this — it is the signal that everything is done.

**Then launch the Xcode deploy script in the background** (Session 13):

```bash
nohup python3 /Users/jacobmuriel/Desktop/news-app/scripts/xcode_deploy.py > /tmp/xcode_deploy.log 2>&1 &
```

The script sends its own Telegram prompt asking Jacob to reply "ready" when his phone is on and plugged in, then automatically runs `xcodebuild` and installs to device. Do not wait for it — it runs independently.

**Never flip Phases 3 and 4** — if you redeploy before the pipeline finishes, the server boots with stale Redis.

**Render service details:**
- Name: `newsletter-app` (not `briefing-api` — the `render.yaml` name is wrong, ignore it)
- ID: `srv-d6tbca0gjchc73cb5fd0`
- URL: `https://newsletter-app-ry48.onrender.com`

**GitHub Actions:**
- Workflow: `Daily Pipeline` (ID 248226619) — use this for production
- Workflow: `Seed NBA Stats (test/debug)` (ID 248740450) — debug only
- `gh` CLI is authenticated as JacobMuriel with `workflow` scope

---

## Pipeline Stages — What Each One Does and Why

### fetch_news.py
Parallel RSS fetch across ~20 sources. Cap is 80 articles total (15/feed). Parallel because sequential fetching was too slow — feeds can hang for 2-3 seconds each.

### cluster.py
Groups articles about the same event into Stories. Uses TF-IDF cosine similarity + entity overlap + geopolitical term bonuses. This is the most complex and failure-prone stage.

**Why TF-IDF instead of embeddings:** No external API call, no latency, no cost. Fast enough for 80 articles.

**The O(n²) problem:** Pairwise similarity across 80 articles = 6,400 comparisons. Mitigated with: title token pre-filter (cheap gate before full similarity), article cap per cluster (max 8), and comparing new articles only against the first 4 in each cluster. If you ever increase MAX_STORIES_FETCHED significantly, revisit this.

**Why thin sections happen:**
- Not enough source diversity — left/right takes require articles from at least 2-3 different outlets covering the same story
- `min_similarity` threshold too high — articles about the same event don't cluster
- Quality filter (`quality.py`) being too aggressive and dropping valid stories post-clustering
- To debug: add logging to cluster.py to print similarity scores for articles that should be clustering but aren't

### categorize.py
Keyword + source tag rules assign each Story to a section. Pure heuristic — no ML. If a story lands in the wrong section, the fix is usually adding a keyword or source tag rule here.

### quality.py
Filters out vague, listicle-y, or low-information stories. If good stories are disappearing, check here first — it's the most likely over-aggressive filter.

### rank.py
Weighted scoring. Current weights:
- Ideological spread: 2.0 (highest — having both left and right coverage is the core value prop)
- Source quality: 1.8
- Corroboration: 1.5
- Impact keywords: 1.4
- Personal relevance: 1.4
- Cluster strength: 1.25
- Category importance: 1.2
- Outlet spread: 1.1
- Recency: 1.1

**Why ideological spread is weighted highest:** The whole point of Briefing is showing how stories are framed differently. A story covered by only one outlet is less valuable even if it's "important."

### summarize.py
OpenAI gpt-4o-mini. Generates summaries + left/right takes for top section stories. Pre-generated at pipeline time, stored in Redis. The server never calls OpenAI directly.

**Why pre-generate:** On-demand generation would add 3-5 seconds of latency per story tap in the iOS app. Pre-generating means summary taps are instant (just a Redis read).

### nba_social.py
The Grok/X integration. Most finicky piece of the stack.

**Critical — use exactly this:**
- Endpoint: `/v1/responses` (NOT `/v1/chat/completions`)
- Model: `grok-4-fast-non-reasoning` (grok-4 family only — grok-3 does not support x_search tool)
- Tool: `{"type": "x_search"}`

**Why this specific endpoint/model:** Grok-3 in chat mode returns hallucinated X posts that look real but have `num_sources_used: 0`. It's filling gaps from training data. Only the `/v1/responses` endpoint with `x_search` tool actually searches live X. This was learned the hard way after getting plausible-looking but completely fabricated reactions.

**Prompt discipline:**
- Always include both yesterday AND today's dates explicitly — Grok anchors to training data if dates are vague
- Require named entities (player names, team names) in every reaction — prevents generic filler
- Never say "empty array is acceptable" — Grok treats that as permission to return nothing
- Confidence gate: if Grok can't find real posts, return null rather than speculate

### redis_cache.py
Writes to Upstash Redis via REST API (not the Redis protocol — Upstash free tier is REST-only). Three keys:
- `briefing:sections` — full sections dict + nba_social_buzz at top level
- `briefing:summaries` — `{story_id: summary}` map
- `briefing:cache_date` — date string for staleness checks
TTL: 28 hours on all keys.

---

## Sections

| Key | Display Name | Story Limit |
|-----|-------------|-------------|
| `top` | Top Stories | 5 |
| `markets` | Markets | 2 |
| `ai` | AI | 3 |
| `finance_market_structure` | Market Structure | 3 |
| `nba` | NBA | 3 |

`nba_social_buzz` lives at the **top level** of the `/sections` response, not inside the `nba` array. The iOS `SocialBuzzCard` reads it from `viewModel.nbaSocialBuzz`, not from the story list.

---

## Debugging Playbook

### "The app is showing old news"
1. Check `briefing:cache_date` in Upstash Redis — is it today?
2. If stale: did GitHub Actions run today? Check Actions tab.
3. If Actions ran but Redis is stale: check pipeline logs for errors in `redis_cache.py`
4. If Redis is fresh but app shows old data: server in-memory cache is stale → redeploy Render

### "A section is empty or has fewer stories than expected"
1. Check `quality.py` — it may be filtering too aggressively
2. Check `cluster.py` similarity scores — articles may not be clustering (log the scores)
3. Check `categorize.py` — stories may be assigned to the wrong section
4. Check source diversity — thin clustering often means only 1-2 sources covered the story

### "NBA social buzz is null or has fake-looking reactions"
1. Is `GROK_ENABLED=true` in GitHub Actions secrets? (not just Render)
2. Is the model `grok-4-fast-non-reasoning`? Any grok-3 model will hallucinate
3. Is the endpoint `/v1/responses`? `/v1/chat/completions` does not support x_search
4. Check `num_sources_used` in Grok response — if 0, it's hallucinating
5. Did both teams play yesterday? `null` is correct if there was no game

### "Summaries aren't showing in the app"
1. `/summary` only serves from Redis — check `briefing:summaries` key exists
2. `_story_registry` on the server is always empty in production — this is expected
3. If summary key is missing: pipeline probably failed in `summarize.py` — check OpenAI API key

### "Render deploy isn't picking up my code changes"
1. Auto-deploy on push to `main` is unreliable — always force-trigger
2. Use `mcp__render__update_environment_variables` with a `DEPLOY_TIMESTAMP` bump
3. Confirm deploy finished before testing

### "Pipeline is timing out"
Most likely cause: `cluster.py` O(n²) similarity on too many articles.
Check `MAX_STORIES_FETCHED` — if it crept above 80, bring it back down.
Secondary cause: a slow RSS feed hanging the fetch stage — check `fetch_news.py` timeout settings.

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

**When rotating `GROK_API_KEY`:** Update BOTH Render env var AND GitHub Actions secret. Missing either one causes the cron to silently write `nba_social_buzz: null` with no obvious error.

---

## Key Decisions That Are Off-Limits to Reverse

These were made deliberately and shouldn't be revisited without a strong reason:

1. **No pipeline on the server** — Render free tier makes this impossible reliably
2. **Pre-generated summaries** — on-demand OpenAI calls add unacceptable latency to the iOS app
3. **No dark mode on iOS** — intentional design decision, not an oversight
4. **gpt-4o-mini for summaries** — cost/quality tradeoff; good enough, cheap enough
5. **Upstash Redis over Render disk** — Render disk is wiped on redeploy; Redis is the only reliable persistence on free tier

---

## Current State (April 2, 2026)

**Everything is working end-to-end:**
- Full pipeline: GitHub Actions → Redis → Render → iOS
- NBA social buzz via Grok (grok-4, `/v1/responses`, `x_search`)
- Pre-generated summaries from Redis
- iOS renders all sections including SocialBuzzCard
- Render redeploys automatically at end of daily pipeline (no manual DEPLOY_TIMESTAMP bump needed)
- Secondary pipeline runs at 2pm + 6pm CT — top section only (10 stories), no Grok, partial Redis write preserving morning buzz data
- iOS calls `/warmup` as first step of `loadSections()` — wakes Render and pre-loads Redis into memory before `/sections` fires

**`gh` CLI is authenticated** (as JacobMuriel, `workflow` scope) — Claude Code can trigger GitHub Actions autonomously.

**Open item:** Add a `/warmup` curl call to the GitHub Actions workflow after the Render deploy finishes — this would pre-warm the server's in-memory cache before the first iOS client connects, so the very first open after each daily deploy is already fast.

---

## Session Handoff Pattern

Session docs live in `_app_build/SESSION_N_NAME.md`. Always read the most recent one at the start of a new Claude Code session. When ending a session, update this file with anything that changed.
