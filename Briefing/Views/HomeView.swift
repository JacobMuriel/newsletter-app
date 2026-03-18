import SwiftUI

struct HomeView: View {
    @StateObject private var viewModel = HomeViewModel()

    var body: some View {
        VStack(spacing: 0) {
            HomeHeaderView()

            SectionPillsView(
                selected: $viewModel.selectedSection,
                labels: viewModel.sectionLabels,
                order: viewModel.sectionOrder
            )

            Divider().background(Theme.rule)

            contentArea

            BottomNavView()
        }
        .background(Theme.background)
        .ignoresSafeArea(edges: .bottom)
        .task { await viewModel.loadSections() }
    }

    @ViewBuilder
    private var contentArea: some View {
        if let error = viewModel.errorMessage {
            Spacer()
            VStack(spacing: 12) {
                Text("Couldn't load stories")
                    .font(Theme.serif(18))
                    .foregroundColor(Theme.ink)
                Text(error)
                    .font(Theme.sans(13))
                    .foregroundColor(Theme.muted)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
                Button("Retry") {
                    Task { await viewModel.loadSections() }
                }
                .font(Theme.sans(14, weight: .medium))
                .foregroundColor(Theme.accentBlue)
            }
            Spacer()
        } else {
            ScrollView {
                LazyVStack(spacing: 0) {
                    if viewModel.isLoading {
                        ForEach(0..<7, id: \.self) { _ in SkeletonRowView() }
                    } else {
                        let stories = viewModel.displayedStories
                        if stories.isEmpty {
                            Text("No stories available.")
                                .font(Theme.sans(14))
                                .foregroundColor(Theme.muted)
                                .padding(32)
                        } else {
                            LeadStoryCard(story: stories[0])

                            ForEach(Array(stories.dropFirst().enumerated()), id: \.element.id) { index, story in
                                StoryRowView(story: story, number: index + 2)
                                    .onAppear {
                                        Task { await viewModel.loadSummaryIfNeeded(for: story) }
                                    }
                            }
                        }
                    }
                }
            }
        }
    }
}

struct HomeHeaderView: View {
    var body: some View {
        VStack(spacing: 4) {
            Text(todayString())
                .font(Theme.sans(10, weight: .medium))
                .tracking(2)
                .foregroundColor(Theme.muted)
                .textCase(.uppercase)

            Text("Briefing")
                .font(Theme.serif(36))
                .foregroundColor(Theme.ink)

            Text("Your daily intelligence")
                .font(Theme.sans(12))
                .foregroundColor(Theme.muted)
        }
        .padding(.top, 12)
        .padding(.bottom, 8)
        .frame(maxWidth: .infinity)
        .background(Theme.background)
    }

    private func todayString() -> String {
        let f = DateFormatter()
        f.dateFormat = "EEEE, MMMM d"
        return f.string(from: Date())
    }
}
