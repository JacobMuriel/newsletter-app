# SESSION 10 — UI Polish + Cache Improvements

**Read before starting:** `CLAUDE.md`, `ARCHITECTURE.md`

**Guiding principle:** Every change in this session is additive only. Do not refactor existing logic, rename anything, or change behavior that already works. If a step requires touching a function that other things depend on, add a new parameter with a default value — never change an existing call site's behavior.

---

## Step 1 — Pull-to-Refresh (background, no content wipe)

**Files:** `HomeViewModel.swift`, `HomeView.swift`

**What to build:**
Pull-to-refresh that fetches in the background. Existing stories stay visible the entire time. Only swap in new content when the response arrives successfully.

**In `HomeViewModel.swift`:**

Add a new published property:
```swift
@Published var isRefreshing = false
```

Add a new method `refreshSections()`. Do NOT modify `loadSections()` at all — it must remain exactly as it is:
```swift
func refreshSections() async {
    guard !isRefreshing else { return }
    isRefreshing = true
    defer { isRefreshing = false }
    do {
        let response = try await APIService.shared.fetchSections()
        sections = response.sections
        nbaSocialBuzz = response.nbaSocialBuzz
        nbaStats = response.nbaStats
        aiSocialBuzz = response.aiSocialBuzz
        dataGeneratedAt = response.generatedAt   // added in Step 3 — wire this up then
        preloadedIds = []
        if let lead = displayedStories.first {
            preloadSummary(for: lead)
        }
    } catch {
        // Silent fail if we already have content. Only surface error if sections are empty.
        if sections.isEmpty {
            errorMessage = "Couldn't refresh. Pull to try again."
        }
    }
}
```

**In `HomeView.swift`:**

Add `.refreshable` to the `ScrollView` in `contentArea`. The only change to this file is adding one modifier — do not touch anything else:
```swift
ScrollView {
    // ... existing content unchanged ...
}
.refreshable {
    await viewModel.refreshSections()
}
```

**Safety check:** `isRefreshing` must never touch `isLoading`. The skeleton screen (`isLoading` branch in `contentArea`) must never appear during a pull-to-refresh. Verify this is true before moving on.

---

## Step 2 — "Breaking" Badge on Story Cards

**Files:** `StoryRowView.swift`, `LeadStoryCard.swift`

**What to build:**
Stories published within the last 2 hours show a small red `BREAKING` label. Stories 2–6 hours old show a grey `3h ago` label. Older than 6 hours: nothing added, nothing removed.

**Add this helper function** at the bottom of `StoryRowView.swift` (outside any struct):
```swift
private func freshnessLabel(for publishedAt: String?) -> (text: String, color: Color)? {
    guard let str = publishedAt,
          let date = ISO8601DateFormatter().date(from: str) else { return nil }
    let hours = Date().timeIntervalSince(date) / 3600
    if hours < 2 { return ("BREAKING", Theme.accentRed) }
    if hours < 6 { return ("\(Int(hours))h ago", Theme.muted) }
    return nil
}
```

In `StoryRowView`, find where the source name is rendered. If `freshnessLabel` returns a value, show it as a small label (font ~8pt, tracking ~1.0) inline with or directly below the source name — match the existing layout pattern in that view, don't invent a new one.

Apply the same logic in `LeadStoryCard` — find the source line, add the label there using the same helper (move `freshnessLabel` to a shared file or duplicate it, whichever is cleaner given the existing file structure).

**Safety check:** If `publishedAt` is nil or unparseable, `freshnessLabel` returns nil and nothing is shown. The layout must not shift or break for stories with no date.

---

## Step 3 — Staleness Banner

**Files:** `HomeViewModel.swift`, `HomeView.swift`

**What to build:**
A thin banner below the section pills when data is more than 20 hours old.

**In `HomeViewModel.swift`:**

Add a new published property:
```swift
@Published var dataGeneratedAt: String? = nil
```

Set it in `loadSections()` — add this line after the existing assignments (`sections = response.sections`, etc.):
```swift
dataGeneratedAt = response.generatedAt
```

Also set it in `refreshSections()` from Step 1 (already noted in that step).

Add a computed var:
```swift
var stalenessMessage: String? {
    guard let str = dataGeneratedAt,
          let date = ISO8601DateFormatter().date(from: str) else { return nil }
    let hours = Date().timeIntervalSince(date) / 3600
    if hours < 20 { return nil }
    if hours < 36 { return "Last updated yesterday" }
    return "Last updated \(Int(hours / 24)) days ago"
}
```

**In `HomeView.swift`:**

In the `selectedTab == .today` branch, insert this between `Divider().background(Theme.rule)` and `contentArea`. This is the only change to `HomeView.swift` in this step:
```swift
if let msg = viewModel.stalenessMessage {
    Text(msg)
        .font(Theme.sans(10, weight: .medium))
        .foregroundColor(Theme.muted)
        .tracking(0.5)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 5)
        .background(Theme.warm)
}
```

**Safety check:** When `stalenessMessage` is nil (the normal case — fresh data), this view renders nothing and takes up zero space. The layout must be pixel-identical to today when the banner is not shown.

---

## Step 4 — Source Count on Story Rows

**Files:** `StoryRowView.swift` only

**What to build:**
If a story has 2 or more sources, show `· 4 sources` inline with the source name. Single-source stories: no change whatsoever.

In `StoryRowView`, find where `story.source` (the primary source name) is rendered. After it, conditionally append:
```swift
if story.sources.count >= 2 {
    Text("· \(story.sources.count) sources")
        .font(/* match the source label font exactly */)
        .foregroundColor(Theme.muted)
}
```

Use an `HStack` if the source name and this label aren't already in one. Match the existing font and color of the source label precisely — this should look like a natural continuation of that line, not a new element.

**Do not touch `LeadStoryCard.swift` in this step.**

**Safety check:** `story.sources` is already populated from the API — do not add any network calls. If `story.sources` is empty or has 1 item, the view is pixel-identical to today.

---

## Step 5 — Cache Fallback (serve stale data over nothing)

**Files:** `news_pipeline/redis_cache.py`, `server.py`, `iOS/Briefing/Briefing/Models/Section.swift`, `iOS/Briefing/Briefing/ViewModels/HomeViewModel.swift`

**What to build:**
If today's Redis key is missing (pipeline didn't run), serve yesterday's data with a `stale: true` flag rather than returning 202. The staleness banner from Step 3 will handle the UI automatically.

**In `redis_cache.py`:**

First, read the file fully before editing anything.

Find the function that writes `briefing:sections` to Redis. After the existing write, add a second write — do not change anything else in that function:
```python
# Write a longer-lived fallback key every pipeline run
redis_set("briefing:sections:prev", payload, ttl=52 * 3600)
```
Use whatever `redis_set` / HTTP call pattern already exists in that file — match it exactly, do not introduce new helpers.

Find `load_sections_cache()`. Add an optional `key` parameter with a default so no existing call site needs to change:
```python
def load_sections_cache(key: str = "briefing:sections") -> dict | None:
    # existing implementation unchanged — just replace any hardcoded
    # "briefing:sections" string inside the function body with the `key` variable
```

Before editing, grep for all call sites of `load_sections_cache` to confirm the default covers them all:
```bash
grep -rn "load_sections_cache" .
```

**In `server.py`:**

Read `_load_sections_with_nba()` fully before editing. Replace the opening lines of that function with this pattern — do not change anything after the `if not cached` block:
```python
cached = load_sections_cache()
if not cached:
    cached = load_sections_cache(key="briefing:sections:prev")
    if cached:
        cached["stale"] = True
        logger.warning("[server] serving stale fallback data from briefing:sections:prev")
if not cached:
    return None
# ... rest of function unchanged ...
```

**In `Section.swift`:**

Add one optional field — do not change anything else in the file:
```swift
let stale: Bool?
// add "case stale" to CodingKeys
```

**In `HomeViewModel.swift`:**

No additional changes needed — `dataGeneratedAt` set in Step 3 already makes the staleness banner fire automatically when old data is served.

**Safety check:** After editing `redis_cache.py`, run:
```bash
grep -rn "load_sections_cache" .
```
Every call site must still work with the new default-parameter signature. If any call site passes a positional argument, verify it still resolves correctly.

---

## Final Step — Push, Run Pipeline, Deploy, Notify

Do these in order. Do not proceed to the next until the current one finishes.

**1. iOS submodule commit:**
```bash
cd Briefing/Briefing
git add -A
git commit -m "Session 10: breaking badge, source count, staleness banner, pull-to-refresh"
cd ../..
git add Briefing/Briefing
```

**2. Parent repo commit and push:**
```bash
git add -A
git commit -m "Session 10: cache fallback, staleness flag, iOS polish"
git push origin main
```

**3. Trigger the GitHub Actions pipeline:**
```bash
gh workflow run daily_newsletter.yml
```
Poll until it completes — do not move on until status is `completed`:
```bash
gh run list --workflow=daily_newsletter.yml --limit=1
```

**4. Force-trigger a Render redeploy** via the Render MCP server — bump `DEPLOY_TIMESTAMP` on service `srv-d6tbca0gjchc73cb5fd0`. Wait for the deploy status to reach `live` before proceeding.

**5. Send a Telegram message** using your configured bot token and chat ID. POST to:
```
https://api.telegram.org/bot{TOKEN}/sendMessage
```
Message text:
```
Session 10 deployed ✓
Pipeline ran, Render redeployed.
New: pull-to-refresh, breaking badge, source count, staleness banner, cache fallback.
```
