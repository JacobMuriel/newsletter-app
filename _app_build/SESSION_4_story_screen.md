# Session 4 — Story Screen + Summary Streaming

> First, paste the MASTER_CONTEXT.md document, then paste this.

---

## What we're doing this session

Building the story detail screen — what the user sees when they tap a headline. This includes the streaming summary effect (text appearing word by word with a blinking cursor) and the left/right perspective takes for Top Stories.

Session 3 must be complete. Story rows should already be tappable stubs.

---

## The story screen layout

```
┌─────────────────────────────┐
│ ← Back          AI          │  ← nav bar: back + section label
├─────────────────────────────┤
│                             │
│  Reuters                    │  ← source in accent red, small caps
│                             │
│  Fed signals pause as       │  ← large serif headline, 20–22pt
│  inflation data surprises   │
│  to the upside              │
│                             │
│  Reuters · 2h ago           │  ← muted, 10pt
│ ─────────────────────────── │  ← divider rule
│                             │
│  ●●● Generating summary     │  ← animated dots while loading
│                             │
│  Federal Reserve officials  │  ← summary streaming in
│  indicated they are in no   │
│  rush to adjust rates...█   │  ← blinking cursor at end
│                             │
├─────────────────────────────┤
│  Read original →            │  ← opens URL in Safari
└─────────────────────────────┘
```

For Top Stories with left/right takes, add below the summary:

```
┌─────────────────────────────┐
│  LEFT TAKE                  │  ← small label, muted
│  "Democrats argue the..."   │  ← italic, slightly smaller text
├─────────────────────────────┤
│  RIGHT TAKE                 │
│  "Conservatives contend..." │
└─────────────────────────────┘
```

---

## Summary streaming effect

The server returns the full summary text at once (not a real stream). Simulate streaming in the UI:

```swift
func simulateStreaming(text: String) async {
    displayedSummary = ""
    let words = text.split(separator: " ", omittingEmptySubsequences: false)
    for word in words {
        displayedSummary += (displayedSummary.isEmpty ? "" : " ") + word
        try? await Task.sleep(nanoseconds: 35_000_000) // 35ms per word
    }
    isStreaming = false
}
```

Show the blinking cursor while `isStreaming == true`. Cursor is a simple `|` character in a `Text` view with an opacity animation toggling 0↔1 every 0.5s.

---

## StoryDetailView

```swift
struct StoryDetailView: View {
    let story: Story
    @StateObject var viewModel: StoryDetailViewModel
    
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                // Source
                Text(story.source.uppercased())
                    .font(Theme.sans(10, weight: .medium))
                    .foregroundColor(Theme.accentRed)
                    .tracking(1.4)
                    .padding(.bottom, 8)
                
                // Headline
                Text(story.headline)
                    .font(Theme.serif(21))
                    .foregroundColor(Theme.ink)
                    .lineSpacing(4)
                    .padding(.bottom, 8)
                
                // Timestamp
                Text(story.source + " · " + story.relativeTime)
                    .font(Theme.sans(10, weight: .light))
                    .foregroundColor(Theme.muted)
                
                Divider()
                    .padding(.vertical, 14)
                
                // Summary area
                SummaryAreaView(viewModel: viewModel)
                
                // Left/Right takes (Top Stories only)
                if story.section == "top" {
                    PerspectiveTakesView(viewModel: viewModel)
                        .padding(.top, 20)
                }
                
                Divider()
                    .padding(.vertical, 14)
                
                // Read original
                Button("Read original →") {
                    if let url = URL(string: story.url) {
                        UIApplication.shared.open(url)
                    }
                }
                .font(Theme.sans(11, weight: .medium))
                .foregroundColor(Theme.accentBlue)
                .tracking(0.5)
            }
            .padding(20)
        }
        .background(Theme.background)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .navigationBarLeading) {
                // Back button handled by NavigationStack
            }
            ToolbarItem(placement: .principal) {
                Text(story.section.uppercased())
                    .font(Theme.sans(10, weight: .medium))
                    .foregroundColor(Theme.muted)
                    .tracking(1.2)
            }
        }
        .task {
            await viewModel.loadSummary(for: story)
        }
    }
}
```

---

## StoryDetailViewModel

```swift
@MainActor
class StoryDetailViewModel: ObservableObject {
    @Published var displayedSummary: String = ""
    @Published var leftTake: String? = nil
    @Published var rightTake: String? = nil
    @Published var summaryState: SummaryState = .idle
    @Published var isStreaming: Bool = false
    
    func loadSummary(for story: Story) async {
        // If summary already cached on the Story object, use that
        // and simulate streaming from cached text
        
        // Otherwise:
        // 1. Set state to .loading
        // 2. Call APIService.shared.fetchSummary(storyId: story.id)
        // 3. Set leftTake/rightTake
        // 4. Call simulateStreaming(text: response.summary)
        // 5. Set state to .loaded
        // Handle errors: set state to .failed, show a message
    }
    
    func simulateStreaming(text: String) async {
        isStreaming = true
        displayedSummary = ""
        let words = text.split(separator: " ", omittingEmptySubsequences: false)
        for word in words {
            displayedSummary += (displayedSummary.isEmpty ? "" : " ") + String(word)
            try? await Task.sleep(nanoseconds: 35_000_000)
        }
        isStreaming = false
    }
}
```

---

## SummaryAreaView

```swift
struct SummaryAreaView: View {
    @ObservedObject var viewModel: StoryDetailViewModel
    @State private var cursorVisible = true
    
    var body: some View {
        switch viewModel.summaryState {
        case .idle:
            EmptyView()
            
        case .loading:
            HStack(spacing: 6) {
                // Animated three-dot pulse
                DotsLoadingView()
                Text("Generating summary")
                    .font(Theme.sans(10, weight: .medium))
                    .foregroundColor(Theme.accentBlue)
                    .tracking(1.2)
                    .textCase(.uppercase)
            }
            
        case .loaded, .failed:
            if viewModel.summaryState == .failed {
                Text("Summary unavailable")
                    .font(Theme.sans(12, weight: .light))
                    .foregroundColor(Theme.muted)
                    .italic()
            } else {
                // Summary text + blinking cursor if still streaming
                (Text(viewModel.displayedSummary)
                    .font(Theme.sans(13, weight: .light))
                    .foregroundColor(Color(hex: "#3a3530"))
                + (viewModel.isStreaming ? 
                    Text(cursorVisible ? " |" : "  ")
                        .foregroundColor(Theme.ink) : 
                    Text("")))
                .lineSpacing(5)
                .onReceive(Timer.publish(every: 0.5, on: .main, in: .common).autoconnect()) { _ in
                    cursorVisible.toggle()
                }
            }
        }
    }
}
```

---

## Navigation wiring

In `HomeView`, make `StoryRowView` and `LeadStoryCard` navigate to `StoryDetailView`:

```swift
NavigationStack {
    // home content
    .navigationDestination(for: Story.self) { story in
        StoryDetailView(
            story: story,
            viewModel: StoryDetailViewModel()
        )
    }
}
```

Make story rows do `NavigationLink(value: story)`.

---

## Done when:
- [ ] Tapping any story row opens the story detail screen
- [ ] Summary animates in word by word with blinking cursor
- [ ] Loading state shows animated dots
- [ ] Failed state shows a graceful message (not a crash)
- [ ] Left/right takes appear below summary for Top Stories
- [ ] "Read original →" opens the article URL in Safari
- [ ] Back navigation works correctly
