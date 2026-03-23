# Session 5 — Preloading, Polish + Final Details

> First, paste the MASTER_CONTEXT.md document, then paste this.

---

## What we're doing this session

Two things: (1) implementing background preloading so summaries are ready before the user taps, and (2) visual polish to make the app match the newspaper aesthetic from the design mockup.

Sessions 1–4 must be complete. The app should be fully functional before this session.

---

## Part 1 — Preloading

### The behavior we want:
- When the home feed loads, immediately start fetching the summary for story #1
- As the user scrolls down, when a story is ~2 rows away from being visible, fire its summary request in the background
- When the user taps a story whose summary is already loaded, the story screen skips the loading state and goes straight to streaming the cached text

### How to implement

In `HomeViewModel`, add a preload queue:

```swift
private var preloadedIds: Set<String> = []

func preloadSummary(for story: Story) {
    guard !preloadedIds.contains(story.id) else { return }
    guard story.summaryState == .idle else { return }
    preloadedIds.insert(story.id)
    
    Task {
        await loadSummaryIfNeeded(for: story)
    }
}
```

In `StoryRowView`, use `onAppear` to trigger preload for the next 2 stories in the list:

```swift
.onAppear {
    // Get index of this story in the displayed list
    // Preload this story + next 2
    let index = viewModel.displayedStories.firstIndex(where: { $0.id == story.id }) ?? 0
    let preloadRange = index...(index + 2)
    for i in preloadRange {
        if i < viewModel.displayedStories.count {
            viewModel.preloadSummary(for: viewModel.displayedStories[i])
        }
    }
}
```

### Passing preloaded summaries to the story screen

When navigating to `StoryDetailView`, pass the story object which now has `summary`, `leftTake`, `rightTake` already populated. `StoryDetailViewModel.loadSummary()` should check these fields first:

```swift
func loadSummary(for story: Story) async {
    if let cached = story.summary {
        // Skip API call, go straight to streaming
        summaryState = .loaded
        await simulateStreaming(text: cached)
        leftTake = story.leftTake
        rightTake = story.rightTake
        return
    }
    // Otherwise fetch from API...
}
```

---

## Part 2 — Visual Polish

Go through each screen and apply these fixes:

### Typography
- Make sure all headlines use Georgia (serif). Target: feels like a newspaper, not a tech app.
- Section tags (TOP STORY, AI, etc.): 9pt, tracking 1.4, DM Sans medium, accent red `#c8410a`
- Story numbers in the list: should be large (20pt) and very muted — color `#d4cfc5`, not gray
- "Read original →": accent blue `#1a4a6b`, tracking 0.5, no underline

### Spacing
- Header (date + Briefing title): 20pt horizontal padding, 12pt vertical
- Lead story card: 20pt padding all sides, 14pt bottom border before next section
- Story row: 14pt vertical padding, 20pt horizontal — feels generous, not cramped
- The rule/divider between sections should be `#d4cfc5` at 1pt — a hairline, not bold

### Section pills
- Active pill: ink background `#0f0e0c`, white text
- Inactive pill: transparent background, border `#d4cfc5`, muted text `#7a7570`
- Font: 10pt, tracking 0.6, uppercase, DM Sans medium
- Pill padding: 4pt vertical, 12pt horizontal

### Lead story card
- Section tag first, then headline, then summary (if loaded), then source/time
- Summary text: 12pt, weight light, line height 1.65, color `#3a3530` (slightly warm, not pure black)
- If summary is still loading (preload in progress), show a subtle 2-line skeleton shimmer instead of nothing

### Markets mini-section (home feed)
- Thin divider with "Markets" label left-aligned in small muted caps
- Three rows: name left-aligned, value right-aligned
- Up values: `#2a7a2a`, down values: accent red `#c8410a`
- No background, no card — just plain rows with dividers between them

### Bottom nav bar
- Top border: 1.5pt solid ink `#0f0e0c`
- Active item: ink color
- Inactive: muted `#7a7570`
- Labels: 8pt, tracking 1pt, uppercase
- Icons: SF Symbols — house, list.bullet, magnifyingglass

### Loading / skeleton
- Shimmer animation: gradient sweeps left-to-right over 1.4s, looping
- Shimmer colors: `#d4cfc5` → `#ede9e0` → `#d4cfc5`
- Skeleton headline: two lines, second line 60% width
- Skeleton source: one line, 40% width

### Story detail screen
- No navigation bar title — just the section label in small caps centered
- Back button: chevron only, ink color, no "Back" text
- Generous top padding (24pt) before the source name
- Divider between timestamp and summary: `#d4cfc5`, 1pt
- Left/Right take cards: subtle background `#ede9e0`, 12pt padding, 8pt corner radius, label in muted small caps above quote text in italic

---

## Part 3 — Edge cases to handle

- **Empty section:** if a section has 0 stories, don't show a blank section — skip it entirely in the feed
- **Very long headline:** serif headlines wrap naturally — make sure line spacing is right (4–5pt extra)
- **Render cold start:** if `/sections` takes >10 seconds, show a message: "Waking up server, this takes ~30 seconds on first load…" — better than a blank spinner
- **Summary failure:** show "Summary unavailable" in italic muted text — never crash, never blank
- **No internet:** catch URLError and show "Check your connection" message

---

## Done when:
- [ ] Scrolling through the feed preloads summaries in the background
- [ ] Tapping a preloaded story skips the loading state and streams immediately
- [ ] Typography matches the newspaper aesthetic throughout
- [ ] Spacing feels generous and editorial, not cramped
- [ ] Markets section renders correctly
- [ ] All edge cases handled gracefully (empty sections, slow server, no internet)
- [ ] The app feels complete — you'd be happy opening it every morning
