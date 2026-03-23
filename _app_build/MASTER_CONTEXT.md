# Briefing App — Master Context Document
> Paste this at the start of every Claude Code session before the session-specific prompt.

---

## What we're building

A personal iOS news app called **Briefing**. It replaces a Python pipeline that currently generates a static HTML newsletter. The app gives the same content but as a native iOS experience: scrollable sections, story cards, and AI-generated summaries that load on demand as the user scrolls.

This is a personal app — one user (the developer), sideloaded via Xcode, never published to the App Store. Free infrastructure only.

---

## The existing Python pipeline

The pipeline lives in a repo with this structure:

```
main.py                        # orchestration — runs everything top to bottom
config/
  sources.yaml                 # RSS feed list with source metadata
  settings.yaml                # caps, section rules, thresholds
news_pipeline/
  cluster.py                   # deduplicates similar articles
  dedupe.py                    # deduplication helpers
  categorize.py                # assigns stories to sections by keyword/source
  quality.py                   # filters low-value content
  rank.py                      # scores and ranks stories
  summarize.py                 # calls OpenAI API, falls back to heuristic
  newsletter.py                # renders HTML output (we are replacing this)
  send_email.py                # SMTP delivery (we are NOT using this)
  bias_detect.py               # detects charged/biased language
output/                        # generated HTML files (being replaced by API)
```

**Sections:** `top`, `markets`, `ai`, `finance_market_structure`, `nba`

**Key pipeline behavior:**
- Fetches RSS feeds, clusters/deduplicates stories
- Categorizes into sections using keyword + source rules
- Ranks stories with a scoring system (includes `ideological_spread` factor)
- Detects charged language via `bias_detect.py`
- Summarizes top stories via OpenAI API (model: `gpt-4o-mini`)
- Falls back to heuristic summary if OpenAI fails
- Left/right perspective takes are generated for Top Stories

**Environment variables the pipeline uses:**
- `OPENAI_API_KEY` — required for summarization
- `OPENAI_ENABLED` — toggle summarization on/off
- `OPENAI_MODEL` — override model name
- `MAX_STORIES_FETCHED`, `MAX_STORIES_TO_RANK`, `MAX_STORIES_TO_SUMMARIZE`
- `SEND_EMAIL`, `DRY_RUN`

---

## Target architecture

```
iPhone (SwiftUI app)
    ↕ HTTP JSON
Render.com free tier (FastAPI server)
    ↕ Python function calls
Existing pipeline modules (restructured to be callable)
    ↕ API calls
OpenAI API (summaries only, on demand)
```

**Two API endpoints:**

### GET /sections
Returns all ranked stories grouped by section. No summaries included — just metadata.

```json
{
  "generated_at": "2025-03-17T09:00:00Z",
  "sections": {
    "top": [
      {
        "id": "abc123",
        "headline": "Fed signals pause as inflation data surprises",
        "source": "Reuters",
        "url": "https://...",
        "published_at": "2025-03-17T07:30:00Z",
        "section": "top",
        "bias_flags": ["loaded language"],
        "has_left_right": true
      }
    ],
    "markets": [...],
    "ai": [...],
    "finance_market_structure": [...],
    "nba": [...]
  }
}
```

### POST /summary
Generates a summary for a single story on demand. Called by the app when a story card becomes visible during scrolling.

```json
// Request
{ "story_id": "abc123" }

// Response
{
  "story_id": "abc123",
  "summary": "Federal Reserve officials indicated...",
  "left_take": "...",      // only present if section == "top"
  "right_take": "...",     // only present if section == "top"
  "confirmed_facts": ["...", "..."]
}
```

**Caching:** The server should cache `/sections` results for the day (re-run pipeline once at startup or on first request after midnight). Summaries should be cached in memory so the same story isn't summarized twice.

---

## iOS app design

**Aesthetic:** Newspaper editorial. Clean, serious, typographic. Not a generic news app.

**Fonts:**
- Headlines: Playfair Display (serif), bold
- Body/UI: DM Sans, light/regular
- Section tags: DM Sans, uppercase, tight tracking

**Colors:**
- Background: `#f5f2ec` (warm off-white, like newsprint)
- Ink: `#0f0e0c`
- Accent red: `#c8410a` (section tags, Top label)
- Accent blue: `#1a4a6b` (links, read more)
- Muted: `#7a7570`
- Rules/borders: `#d4cfc5`

**App screens:**

### 1. Home feed
- Status bar (time)
- Header: date in small caps, "Briefing" in large serif, subtitle "Your daily intelligence"
- Horizontal section pill filter: All · Top · Markets · AI · Finance · NBA
- Lead story card (story #1): large serif headline, summary text already visible, source + timestamp
- Markets mini-row: S&P, NASDAQ, BTC — values from pipeline, not live
- Numbered story list (2, 3, 4...): headline + source, no summary until tapped/scrolled to
- Skeleton shimmer on stories still loading
- Bottom tab bar: Today · Sections · Search (icons + labels)

### 2. Story screen
- Back chevron + section label
- Source name in accent red
- Large serif headline
- Source + timestamp
- Summary streams in with blinking cursor while generating
- "Read original →" link at bottom
- For Top Stories: left take / right take cards below summary

### 3. Section screen (tapping a pill or Sections tab)
- Same layout as home feed but filtered to one section
- Section title at top in large serif

**Preloading behavior:**
- On app launch: fetch `/sections`, show skeletons immediately, populate as data arrives
- As user scrolls: when a story card is within ~2 cards of the viewport, fire `POST /summary` for that story
- Cache summaries locally so scrolling back doesn't re-fetch
- Story #1 (lead): fire summary request immediately on load, don't wait for scroll

---

## Infrastructure

**Backend hosting:** Render.com free tier
- Free tier sleeps after inactivity — acceptable, app shows loading state
- Pipeline runs on first request of the day, caches results
- Environment variables set in Render dashboard: `OPENAI_API_KEY`, `OPENAI_ENABLED=true`

**iOS app:** SwiftUI, targeting iOS 16+, sideloaded via Xcode personal team
- No App Store, no TestFlight, no $99 Apple Developer account needed
- Re-sign every 7 days in Xcode

**Cost:** ~$0–2/month in OpenAI API calls depending on reading volume. Everything else free.

---

## Constraints and preferences

- Do not modify `send_email.py` or `newsletter.py` — leave them intact
- Do not break the existing `python main.py` CLI flow — the FastAPI server is additive
- Keep the pipeline's existing config files (`sources.yaml`, `settings.yaml`) as the source of truth
- Prefer simple, readable code over clever abstractions
- All error states should be visible to the user (no silent failures)
- SwiftUI code should target iOS 16+ and use `async/await` for networking
