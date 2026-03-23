# Session 3 — SwiftUI App: Skeleton, Navigation, Home Feed

> First, paste the MASTER_CONTEXT.md document, then paste this.

---

## What we're doing this session

Building the iOS SwiftUI app from scratch. By the end of this session the app should launch on your phone, fetch real data from the Render backend, and display the home feed with story headlines. No summaries yet — that's Session 4.

Sessions 1 and 2 must be complete. You need your Render URL ready.

---

## Setup

Create a new Xcode project:
- Template: iOS App
- Name: `Briefing`
- Interface: SwiftUI
- Language: Swift
- Minimum deployment target: iOS 16.0

Create the following file structure inside the Xcode project:

```
Briefing/
  App/
    BriefingApp.swift
  Models/
    Story.swift
    Section.swift
    SummaryResponse.swift
  Services/
    APIService.swift
  Views/
    HomeView.swift
    SectionPillsView.swift
    LeadStoryCard.swift
    StoryRowView.swift
    SkeletonView.swift
    BottomNavView.swift
  ViewModels/
    HomeViewModel.swift
```

---

## Models

### `Story.swift`
```swift
struct Story: Identifiable, Codable {
    let id: String
    let headline: String
    let source: String
    let url: String
    let publishedAt: String
    let section: String
    let biasFlags: [String]
    let hasLeftRight: Bool
    
    // Added client-side after summary loads
    var summary: String? = nil
    var leftTake: String? = nil
    var rightTake: String? = nil
    var summaryState: SummaryState = .idle
    
    enum CodingKeys: String, CodingKey {
        case id, headline, source, url, section
        case publishedAt = "published_at"
        case biasFlags = "bias_flags"
        case hasLeftRight = "has_left_right"
    }
}

enum SummaryState {
    case idle, loading, loaded, failed
}
```

### `SummaryResponse.swift`
```swift
struct SummaryResponse: Codable {
    let storyId: String
    let summary: String
    let leftTake: String?
    let rightTake: String?
    
    enum CodingKeys: String, CodingKey {
        case storyId = "story_id"
        case summary
        case leftTake = "left_take"
        case rightTake = "right_take"
    }
}
```

---

## APIService

### `APIService.swift`

```swift
class APIService {
    static let shared = APIService()
    
    // REPLACE THIS with your actual Render URL from Session 2
    private let baseURL = "https://YOUR-APP.onrender.com"
    
    func fetchSections() async throws -> [String: [Story]] {
        // GET /sections
        // Parse response into [sectionName: [Story]]
    }
    
    func fetchSummary(storyId: String) async throws -> SummaryResponse {
        // POST /summary with {"story_id": storyId}
    }
}
```

Handle errors clearly — if the server is asleep (Render cold start), the request will just take longer. Do not timeout too aggressively — give it at least 60 seconds.

---

## HomeViewModel

### `HomeViewModel.swift`

```swift
@MainActor
class HomeViewModel: ObservableObject {
    @Published var sections: [String: [Story]] = [:]
    @Published var isLoading = true
    @Published var selectedSection: String = "all"
    
    let sectionOrder = ["top", "markets", "ai", "finance_market_structure", "nba"]
    let sectionLabels = [
        "all": "All",
        "top": "Top", 
        "markets": "Markets",
        "ai": "AI",
        "finance_market_structure": "Finance",
        "nba": "NBA"
    ]
    
    func loadSections() async {
        // Call APIService.shared.fetchSections()
        // Set isLoading = false when done
        // Fire summary load for story #1 immediately after sections load
    }
    
    func loadSummaryIfNeeded(for story: Story) async {
        // Check if summary already loaded or loading
        // If idle, set state to .loading, call APIService, update story
    }
    
    var displayedStories: [Story] {
        // If selectedSection == "all", return all stories in section order
        // Otherwise return just that section's stories
    }
}
```

---

## Views

### Design tokens (add to a `Theme.swift` file)

```swift
enum Theme {
    static let background = Color(hex: "#f5f2ec")
    static let ink = Color(hex: "#0f0e0c")
    static let accentRed = Color(hex: "#c8410a")
    static let accentBlue = Color(hex: "#1a4a6b")
    static let muted = Color(hex: "#7a7570")
    static let rule = Color(hex: "#d4cfc5")
    
    // Fonts
    static func serif(_ size: CGFloat, weight: Font.Weight = .bold) -> Font {
        .custom("Georgia", size: size).weight(weight)
    }
    static func sans(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .default)
    }
}

extension Color {
    init(hex: String) { /* standard hex init */ }
}
```

Note: Playfair Display requires bundling the font file. Use Georgia as a fallback for now — it reads very similarly on iOS. We can swap in the actual font in Session 5 polish.

### `HomeView.swift`

Top-level view structure:
```
VStack(spacing: 0) {
    // Header: date + "Briefing" title
    HomeHeaderView()
    
    // Section pills
    SectionPillsView(selected: $viewModel.selectedSection)
    
    Divider()
    
    // Story list
    ScrollView {
        LazyVStack(spacing: 0) {
            if isLoading {
                // Show 5 skeleton rows
            } else {
                LeadStoryCard(story: displayedStories[0])
                
                // Markets mini-section (if "all" or "markets" selected)
                if shouldShowMarkets {
                    MarketsMiniView(stories: sections["markets"] ?? [])
                }
                
                // Remaining stories
                ForEach(remainingStories) { story in
                    StoryRowView(story: story)
                        .onAppear {
                            Task { await viewModel.loadSummaryIfNeeded(for: story) }
                        }
                }
            }
        }
    }
    
    BottomNavView()
}
.background(Theme.background)
.task { await viewModel.loadSections() }
```

### `LeadStoryCard.swift`

- Section tag in accent red, uppercase small caps
- Large serif headline (19–21pt)
- Summary text if loaded, skeleton shimmer if loading, nothing if idle
- Source · time ago in muted small text

### `StoryRowView.swift`

- Number on left (large light serif, muted color)
- Headline (13pt serif medium) + source/time (9pt muted)
- Tappable — navigates to story screen (Session 4)

### `SkeletonView.swift`

Animated shimmer using a `LinearGradient` sweeping left to right. Use for:
- Full row skeletons while sections load
- Summary area while summary is loading

---

## Done when:
- [ ] App builds and runs in Xcode simulator
- [ ] App installs and runs on your physical iPhone
- [ ] Home feed shows real headlines from your pipeline
- [ ] Section pills filter the feed correctly
- [ ] Skeleton shows while data loads
- [ ] Lead story fires a summary request on load (even if summary screen isn't built yet)
- [ ] Console shows API calls being made — no silent failures
