import Foundation

struct Story: Identifiable, Codable {
    let id: String
    let headline: String
    let source: String
    let url: String
    let publishedAt: String
    let section: String
    let biasFlags: [String]
    let hasLeftRight: Bool

    // Populated client-side after summary loads
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
