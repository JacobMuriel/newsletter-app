# SESSION_14 — iOS Local Cache (Instant App Open)

**Goal:** Store the last `/sections` response on-device so the app renders instantly on open,
even while the Render server is cold-starting in the background.

---

## Problem

Render free tier sleeps after ~15 minutes of inactivity. Every cold start takes ~30 seconds.
The app currently shows skeletons and waits for the network before rendering anything.

## Solution

Persist the last successful `/sections` response to `UserDefaults` as JSON.
On next open: render cached data immediately, fire network call in background,
swap in fresh data when it arrives.

---

## Files to Edit

All iOS files live in `Briefing/Briefing/Briefing/`.

1. `Services/SectionsCache.swift` — **NEW FILE** — handles read/write to UserDefaults
2. `ViewModels/HomeViewModel.swift` — load cache on init, save after successful fetch, background-refresh pattern
3. `Views/HomeView.swift` — remove loading gate so cached data renders without `isLoading` check blocking it

---

## Step 1 — Create `Services/SectionsCache.swift`

New file. Handles serialization of `SectionsResponse` to/from `UserDefaults`.

```swift
import Foundation

struct SectionsCache {
    private static let key = "briefing.sectionsCache"

    static func save(_ response: SectionsResponse) {
        guard let data = try? JSONEncoder().encode(response) else { return }
        UserDefaults.standard.set(data, forKey: key)
    }

    static func load() -> SectionsResponse? {
        guard let data = UserDefaults.standard.data(forKey: key),
              let response = try? JSONDecoder().decode(SectionsResponse.self, from: data)
        else { return nil }
        return response
    }

    static func clear() {
        UserDefaults.standard.removeObject(forKey: key)
    }
}
```

`SectionsResponse` must already conform to `Codable` — verify this in `Models/`. If it only
conforms to `Decodable`, add `Encodable` (or change to `Codable`).

---

## Step 2 — Update `HomeViewModel.swift`

### 2a — On init, load cache immediately

Add an `init()` that hydrates state from `SectionsCache.load()` before any network call fires:

```swift
init() {
    if let cached = SectionsCache.load() {
        sections = cached.sections
        nbaSocialBuzz = cached.nbaSocialBuzz
        nbaStats = cached.nbaStats
        aiSocialBuzz = cached.aiSocialBuzz
        dataGeneratedAt = cached.generatedAt
        isLoading = false   // skip skeletons — we have real data
    }
}
```

### 2b — Save after every successful fetch

In `loadSections()`, after the successful `APIService.shared.fetchSections()` call, add:

```swift
SectionsCache.save(response)
```

Do the same inside `refreshSections()` after its successful fetch.

### 2c — Background refresh behavior

`loadSections()` is called from `.task { }` in `HomeView` on every app open.

- If cache was loaded in `init()`, `isLoading` is already `false` — the `.task` call will
  still fire the network request, but the UI shows cached content instead of skeletons.
- When the network response arrives, the `@Published` vars update and SwiftUI re-renders
  with fresh data automatically.
- No other changes needed to `loadSections()` — the existing logic handles the swap.

### 2d — Error handling with cache present

In the `catch` blocks of `loadSections()`, only set `errorMessage` if `sections.isEmpty`
(i.e. no cache was loaded). If we already have cached data showing, a background refresh
failure should be silent:

```swift
} catch APIError.warmingUp {
    if sections.isEmpty {
        isLoading = false
        errorMessage = "Server is still warming up. Pull to retry."
    }
} catch let error as URLError where error.code == .notConnectedToInternet {
    if sections.isEmpty {
        isLoading = false
        errorMessage = "Check your connection and retry."
    }
} catch {
    print("[ViewModel] fetchSections failed: \(error)")
    if sections.isEmpty {
        isLoading = false
        errorMessage = error.localizedDescription
    }
}
```

---

## Step 3 — Verify `SectionsResponse` is `Codable`

Find `Models/SectionsResponse.swift` (or wherever `SectionsResponse` is defined).
It needs to be `Codable` (not just `Decodable`) for `JSONEncoder` to work.

If it's currently `Decodable`, change it to `Codable`. All nested types it references
(`Story`, `NBASocialBuzz`, `NBAStats`, `AISocialBuzz`, etc.) must also be `Codable`.
Most likely they already are since they're decoded from JSON — just need `Encodable` added.

---

## Step 4 — Verify in HomeView (likely no change needed)

In `HomeView.swift`, the content area is gated on `viewModel.isLoading`. Since `isLoading`
is now `false` when cache exists, cached data will render immediately on open.

Confirm the `.task { await viewModel.loadSections() }` modifier is still present —
this fires the background network refresh. Do not remove it.

---

## Testing Checklist

1. Cold open with cache: stories render instantly, no skeletons
2. Background refresh completes: data silently updates (check `dataGeneratedAt` changes if pipeline ran)
3. Cold open with no cache (first ever install or after `SectionsCache.clear()`): skeletons show normally, data loads when network returns
4. No internet + cache present: cached data shows, no error banner
5. No internet + no cache: error banner shows as before
6. Pull-to-refresh still works and saves updated cache

---

## Notes

- `UserDefaults` has a practical limit of a few MB — your sections payload is well within that.
- Cache never expires explicitly; `dataGeneratedAt` / `stalenessMessage` already handles
  communicating age to the user.
- NBA stats (`nbaStats`) and social buzz are included in `SectionsResponse` so they cache for free.
- NBAStatsCard Today tab (`/nba/today`) is always-live and intentionally not cached — no change needed there.
