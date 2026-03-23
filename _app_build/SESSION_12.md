# SESSION 12 — NBA Section Overhaul

## Goals
1. Fix `_is_big_performance` thresholds everywhere in the codebase
2. Overhaul the NBA scoreboard: today/yesterday tab switcher, live game support, refresh button
3. Live Grok refresh for Rockets/Bulls games in progress

---

## Part 1 — Fix Big Performance Thresholds

### Files to update
Search the entire codebase for every place that references big performance thresholds. Known locations:
- `news_pipeline/nba_stats.py` — `_is_big_performance()` function and the `notable` label logic in `get_nba_game_stats()`

Replace all threshold logic with the following rules (apply consistently everywhere):

**A performance is "big" if the player meets ANY of:**
- pts >= 35
- reb >= 15
- ast >= 12
- blk >= 5
- stl >= 5
- Triple-double: pts >= 10 AND reb >= 10 AND ast >= 10
- Near-triple-double variant: at least two of {pts, reb, ast} >= 20, and the third >= 7 AND the third >= 8 — i.e. all three of pts/reb/ast must be >= 7, at least two must be >= 20. Actually the exact rule is: any combination where one stat is >= 20, another is >= 8, and the third is >= 7 across pts/reb/ast in any role order.

Wait — simpler statement of the 20/7/8 rule: sort [pts, reb, ast] descending. If the top value >= 20 AND the middle value >= 8 AND the bottom value >= 7 → qualifies.

**Also add a minimum minutes filter:** player must have played >= 15 minutes to qualify for any big performance label.

**Update the `note` label logic in `get_nba_game_stats()`** to match:
```python
triple_double = pts >= 10 and reb >= 10 and ast >= 10
note = ("Triple-double"  if triple_double      else
        "35+ points"     if pts >= 35           else
        "30+ points"     if pts >= 30           else
        "15+ rebounds"   if reb >= 15           else
        "12+ assists"    if ast >= 12           else
        "5+ blocks"      if blk >= 5            else
        "5+ steals"      if stl >= 5            else
        "Big game")
```

---

## Part 2 — Backend: Today's Game Slate Endpoint

### New server endpoint: `GET /nba/today`

Add to `server.py`. This endpoint:
- Calls ESPN scoreboard for **today's date** (not yesterday)
- Returns all games for today's slate, including:
  - Games not yet started: `{ status: "upcoming", start_time_ct: "7:00 PM CT" }`
  - Games in progress: `{ status: "live", home_score, away_score, quarter, clock }`
  - Games completed: `{ status: "final", home_score, away_score, top_scorer: { name, pts, reb, ast } }`
- Does NOT cache to Redis — always fetches live from ESPN on each call
- ESPN scoreboard endpoint already used: `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard`

### ESPN data parsing for today's games

Add a new function `get_today_games()` in `news_pipeline/nba_stats.py`:

```python
def get_today_games() -> list[dict]:
    """
    Fetch today's NBA slate from ESPN. Returns games with status:
    - 'upcoming': game hasn't started. Include start_time_ct (convert UTC to CT).
    - 'live': game in progress. Include quarter (e.g. "Q3") and clock (e.g. "4:32").
    - 'final': game completed. Include top_scorer fetched from box score.
    """
```

For each game in ESPN's response:
- Check `competitions[0].status.type.name`:
  - `"STATUS_SCHEDULED"` → upcoming
  - `"STATUS_IN_PROGRESS"` or `"STATUS_HALFTIME"` → live
  - `"STATUS_FINAL"` → final
- For upcoming: parse `competitions[0].date` (ISO UTC string) → convert to CT. Use `pytz` or `zoneinfo` (prefer `zoneinfo` — stdlib in Python 3.9+). Format as `"7:00 PM CT"`.
- For live: parse `competitions[0].status.displayClock` for the clock string, and `competitions[0].status.period` for the quarter number. Format quarter as `"Q1"`, `"Q2"`, etc. Halftime → `"Half"`.
- For final: call `get_box_score(game_id)` and `get_top_performer(box_score)` to get top scorer.
- For live games: still call `get_box_score(game_id)` to get current top scorer — show it alongside the live indicator.

Return shape per game:
```json
{
  "game_id": "...",
  "home_team": "LAL",
  "away_team": "GSW",
  "home_score": 54,
  "away_score": 48,
  "status": "live",
  "quarter": "Q3",
  "clock": "4:32",
  "start_time_ct": null,
  "top_scorer": { "name": "LeBron James", "pts": 18, "reb": 6, "ast": 4 }
}
```

For upcoming games, `home_score`, `away_score`, `top_scorer`, `quarter`, `clock` are all null. `start_time_ct` is populated.
For live games, `start_time_ct` is null. `top_scorer` shows current leader.
For final games, `quarter` = `"Final"`, `clock` = null, `start_time_ct` = null.

### New server endpoint

```python
@app.get("/nba/today")
async def nba_today():
    """Live today's NBA slate — always fetches fresh from ESPN, no cache."""
    from news_pipeline.nba_stats import get_today_games
    games = get_today_games()
    return { "games": games, "fetched_at": datetime.now(timezone.utc).isoformat() }
```

---

## Part 3 — Backend: Live Grok Refresh for Active Rockets/Bulls Games

### New server endpoint: `POST /nba/social/live`

Add to `server.py`. Called by iOS when the user taps refresh and a Rockets or Bulls game is currently live.

```python
@app.post("/nba/social/live")
async def nba_social_live():
    """
    Fetches live Grok social buzz for an in-progress Rockets or Bulls game.
    Only called when at least one of those teams has status == 'live' in today's slate.
    Returns same shape as nba_social_buzz in the /sections response.
    """
```

Implementation:
- Call `get_today_games()` to get current game state
- Find Rockets game (HOU) and Bulls game (CHI) if live
- Build `rockets_game` and `bulls_game` dicts in the same shape that `get_nba_social_buzz()` expects:
  ```python
  { "played": True, "opponent": "LAL", "score": "54-48", "result": "unknown" }
  ```
  Use `"result": "unknown"` since game is in progress. Score should be current live score.
- Call `get_nba_social_buzz(rockets_game=..., bulls_game=...)` and return the result
- If neither HOU nor CHI is live, return `{ "buzz": null, "reason": "no_live_featured_game" }`
- Timeout: Grok call is slow (~30s) — set FastAPI timeout header, don't let iOS hang forever

---

## Part 4 — iOS: NBAStats Model Updates

### Update `NBAStats` model (wherever it's defined — find it)

Add a field for today's games. If the model is in a file not provided, find it via grep.

The existing `NBAStats` model comes from the Redis-cached `briefing:nba_stats` key (yesterday's data). Today's slate is fetched separately from `/nba/today`. These are two separate data sources — don't mix them.

---

## Part 5 — iOS: Scoreboard Tab Switcher

### Update `NBAStatsCard` (find the file — it's not in the provided files, locate it)

Replace the current scoreboard display with a tab switcher: **Yesterday | Today**

**Tab switcher behavior:**
- Always show both tabs regardless of time of day
- **Default tab logic** (evaluated when the view appears):
  - Get current time in US Central timezone
  - If current time < 6:00 PM CT → default to "Yesterday" tab
  - If current time >= 6:00 PM CT → default to "Today" tab
- Tabs are pill-shaped, right-aligned — match the style of `SocialBuzzCard` tabs exactly

**Yesterday tab:**
- Shows the existing `NBAStats` data already loaded (from Redis via `/sections`)
- Displays: all games with final scores and top scorer per game
- Rockets and Bulls games shown first if they played, then rest of league
- No refresh needed — this data is static for the day

**Today tab:**
- On first appearance, calls `/nba/today` to fetch the slate
- Shows each game with:
  - **Upcoming**: team abbreviations + start time CT in place of score
  - **Live**: team abbreviations + current score, and below the score in small text: quarter + clock (e.g. `"Q3 · 4:32"`)
  - **Final**: team abbreviations + final score + top scorer name/line
- Shows a **Refresh button** (small, top-right of the card or bottom) — tapping it:
  1. Re-fetches `/nba/today` (always)
  2. If any Rockets or Bulls game has `status == "live"`: also calls `POST /nba/social/live` and updates the `SocialBuzzCard` rockets section with the live data
  3. Does NOT wipe existing content while fetching — overlay a subtle loading indicator instead
- Today's data is NOT cached between app launches. It's fetched fresh each time the Today tab is first shown, and again on each manual refresh.

**Loading state for Today tab:**
- While fetching, show skeleton rows (same `SkeletonRowView` pattern used elsewhere)
- On error, show inline error message with a retry button

---

## Part 6 — iOS: SocialBuzzCard Live Update

When `POST /nba/social/live` returns data, update the `SocialBuzzCard`'s rockets section in place. The other tabs (Bulls, General) remain unchanged. The card should show a small `"LIVE"` badge next to the Rockets tab label while live data is displayed.

---

## Implementation Order

Do these in order — each step is testable before the next:

1. **`nba_stats.py`** — fix `_is_big_performance()` and note labels. Grep for any other threshold references in the codebase and fix those too.
2. **`nba_stats.py`** — add `get_today_games()` function.
3. **`server.py`** — add `GET /nba/today` endpoint.
4. **`server.py`** — add `POST /nba/social/live` endpoint.
5. **iOS models** — add `TodayGame` model and `NBAToday` response model.
6. **iOS APIService** — add `fetchTodayGames()` and `fetchLiveSocialBuzz()` calls.
7. **iOS `NBAStatsCard`** — add Yesterday/Today tab switcher with default logic.
8. **iOS `NBAStatsCard`** — Today tab UI (upcoming/live/final display).
9. **iOS `NBAStatsCard`** — Refresh button wired to both endpoints.
10. **iOS `SocialBuzzCard`** — accept optional live buzz override for rockets section + LIVE badge.

---

## Key Constraints / Gotchas

- **Central time**: All 6pm logic must use `America/Chicago` timezone, not device local time. In Swift use `TimeZone(identifier: "America/Chicago")` with a `Calendar` or `DateFormatter`.
- **Today tab never auto-refreshes** — only refreshes on explicit user tap. No timer-based polling.
- **Don't wipe content on refresh** — maintain existing data visible while new fetch is in progress.
- **Live box scores are slow** — `get_today_games()` calls `get_box_score()` for each live/final game. For today's slate this could be 5-10 games. Consider fetching box scores only for live games (to get current top scorer), and skipping box score for upcoming games entirely. For final games, box score is needed for top scorer — accept the latency since this is user-triggered.
- **`/nba/today` has no Redis cache** — it's always live. Do not add caching here; freshness is the point.
- **Grok live call is slow** — `POST /nba/social/live` can take 20-30s. Show a loading state in the SocialBuzzCard rockets section while it's in flight. Don't block the scoreboard refresh on it.
- **`_is_big_performance` minimum minutes**: add `minutes >= 15` check to filter garbage-time noise.
- **20/7/8 rule**: sort [pts, reb, ast] descending → qualifies if sorted[0] >= 20 AND sorted[1] >= 8 AND sorted[2] >= 7.

---

## Files Expected to Change

**Backend:**
- `news_pipeline/nba_stats.py` — `_is_big_performance()`, note labels, new `get_today_games()`
- `server.py` — two new endpoints

**iOS (find these files via their likely names):**
- `Models/NBAStats.swift` or wherever `NBAStats` struct is defined — add `TodayGame` model
- `APIService.swift` — add two new fetch methods
- `Views/NBAStatsCard.swift` — full tab switcher overhaul
- `Views/SocialBuzzCard.swift` — LIVE badge + live buzz injection

**Grep hint:** Run `grep -r "_is_big_performance\|big_performance\|35.*point\|13.*assist\|triple.double" --include="*.py" .` to find every threshold reference before editing.
