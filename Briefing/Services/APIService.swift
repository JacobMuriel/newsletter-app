import Foundation

class APIService {
    static let shared = APIService()
    private init() {}

    private let baseURL = "https://newsletter-app-ry48.onrender.com"

    // Render free tier can take 30–60s to wake up — don't timeout too early
    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 90
        config.timeoutIntervalForResource = 120
        return URLSession(configuration: config)
    }()

    func warmup() async {
        guard let url = URL(string: "\(baseURL)/warmup") else { return }
        print("[API] GET /warmup")
        _ = try? await session.data(from: url)
    }

    func fetchSections() async throws -> [String: [Story]] {
        guard let url = URL(string: "\(baseURL)/sections") else {
            throw URLError(.badURL)
        }
        print("[API] GET /sections")
        let (data, response) = try await session.data(from: url)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        let decoded = try JSONDecoder().decode(SectionsResponse.self, from: data)
        print("[API] /sections OK — \(decoded.sections.map { "\($0.key):\($0.value.count)" }.joined(separator: ", "))")
        return decoded.sections
    }

    func fetchSummary(storyId: String) async throws -> SummaryResponse {
        guard let url = URL(string: "\(baseURL)/summary") else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["story_id": storyId])

        print("[API] POST /summary story_id=\(storyId)")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        let decoded = try JSONDecoder().decode(SummaryResponse.self, from: data)
        print("[API] /summary OK story_id=\(storyId)")
        return decoded
    }
}
