import Foundation

struct SectionsResponse: Codable {
    let generatedAt: String
    let sections: [String: [Story]]

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case sections
    }
}
