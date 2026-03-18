import SwiftUI

struct StoryRowView: View {
    let story: Story
    let number: Int

    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .top, spacing: 12) {
                Text("\(number)")
                    .font(Theme.serif(20, weight: .light))
                    .foregroundColor(Theme.muted)
                    .frame(width: 28, alignment: .leading)

                VStack(alignment: .leading, spacing: 4) {
                    Text(story.headline)
                        .font(Theme.serif(14, weight: .regular))
                        .foregroundColor(Theme.ink)
                        .lineSpacing(2)

                    HStack(spacing: 4) {
                        Text(story.source)
                        Text("·")
                        Text(timeAgo(from: story.publishedAt))
                    }
                    .font(Theme.sans(10))
                    .foregroundColor(Theme.muted)
                }

                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)

            Divider()
                .background(Theme.rule)
                .padding(.leading, 56)
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
