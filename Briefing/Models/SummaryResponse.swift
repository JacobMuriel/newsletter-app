import Foundation

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
