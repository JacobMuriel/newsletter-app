import SwiftUI

struct LeadStoryCard: View {
    let story: Story

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            // Section tag
            Text(story.section.uppercased().replacingOccurrences(of: "_", with: " "))
                .font(Theme.sans(10, weight: .semibold))
                .tracking(1.5)
                .foregroundColor(Theme.accentRed)

            // Headline
            Text(story.headline)
                .font(Theme.serif(21))
                .foregroundColor(Theme.ink)
                .lineSpacing(3)

            // Summary area
            summaryContent

            // Source · time
            HStack(spacing: 4) {
                Text(story.source)
                Text("·")
                Text(timeAgo(from: story.publishedAt))
            }
            .font(Theme.sans(11))
            .foregroundColor(Theme.muted)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)

        Divider()
            .background(Theme.rule)
            .padding(.horizontal, 16)
    }

    @ViewBuilder
    private var summaryContent: some View {
        switch story.summaryState {
        case .idle:
            EmptyView()
        case .loading:
            VStack(alignment: .leading, spacing: 6) {
                SkeletonView().frame(height: 12)
                SkeletonView().frame(height: 12)
                SkeletonView().frame(width: 200, height: 12)
            }
            .padding(.top, 2)
        case .loaded:
            if let summary = story.summary {
                Text(summary)
                    .font(Theme.sans(14))
                    .foregroundColor(Theme.ink.opacity(0.85))
                    .lineSpacing(4)
            }
        case .failed:
            EmptyView()
        }
    }

    private func timeAgo(from publishedAt: String) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = formatter.date(from: publishedAt) ?? ISO8601DateFormatter().date(from: publishedAt)
        guard let date else { return publishedAt }
        let seconds = Int(Date().timeIntervalSince(date))
        if seconds < 3600  { return "\(seconds / 60)m ago" }
        if seconds < 86400 { return "\(seconds / 3600)h ago" }
        return "\(seconds / 86400)d ago"
    }
}
