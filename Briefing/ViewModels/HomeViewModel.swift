import Foundation

@MainActor
class HomeViewModel: ObservableObject {
    @Published var sections: [String: [Story]] = [:]
    @Published var isLoading = true
    @Published var errorMessage: String? = nil
    @Published var selectedSection: String = "all"

    let sectionOrder = ["top", "markets", "ai", "finance_market_structure", "nba"]
    let sectionLabels: [String: String] = [
        "all": "All",
        "top": "Top",
        "markets": "Markets",
        "ai": "AI",
        "finance_market_structure": "Finance",
        "nba": "NBA"
    ]

    func loadSections() async {
        isLoading = true
        errorMessage = nil
        await APIService.shared.warmup()
        do {
            sections = try await APIService.shared.fetchSections()
            isLoading = false
            // Fire summary for the lead story immediately — don't wait for scroll
            if let lead = displayedStories.first {
                Task { await loadSummaryIfNeeded(for: lead) }
            }
        } catch {
            print("[ViewModel] fetchSections failed: \(error)")
            errorMessage = error.localizedDescription
            isLoading = false
        }
    }

    func loadSummaryIfNeeded(for story: Story) async {
        guard currentState(of: story) == .idle else { return }
        updateStory(story.id, section: story.section) { $0.summaryState = .loading }
        do {
            let response = try await APIService.shared.fetchSummary(storyId: story.id)
            updateStory(story.id, section: story.section) {
                $0.summary = response.summary
                $0.leftTake = response.leftTake
                $0.rightTake = response.rightTake
                $0.summaryState = .loaded
            }
        } catch {
            print("[ViewModel] fetchSummary failed for \(story.id): \(error)")
            updateStory(story.id, section: story.section) { $0.summaryState = .failed }
        }
    }

    var displayedStories: [Story] {
        if selectedSection == "all" {
            return sectionOrder.flatMap { sections[$0] ?? [] }
        }
        return sections[selectedSection] ?? []
    }

    // MARK: - Private helpers

    private func currentState(of story: Story) -> SummaryState {
        sections[story.section]?.first(where: { $0.id == story.id })?.summaryState ?? .idle
    }

    private func updateStory(_ id: String, section: String, update: (inout Story) -> Void) {
        guard var list = sections[section],
              let idx = list.firstIndex(where: { $0.id == id }) else { return }
        update(&list[idx])
        sections[section] = list
    }
}
