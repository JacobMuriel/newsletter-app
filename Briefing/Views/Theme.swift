import SwiftUI

enum Theme {
    static let background = Color(hex: "#f5f2ec")
    static let ink        = Color(hex: "#0f0e0c")
    static let accentRed  = Color(hex: "#c8410a")
    static let accentBlue = Color(hex: "#1a4a6b")
    static let muted      = Color(hex: "#7a7570")
    static let rule       = Color(hex: "#d4cfc5")

    // Georgia reads very similarly to Playfair Display on iOS.
    // Swap in the real font in Session 5.
    static func serif(_ size: CGFloat, weight: Font.Weight = .bold) -> Font {
        .custom("Georgia", size: size).weight(weight)
    }

    static func sans(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .default)
    }
}

extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let a, r, g, b: UInt64
        switch hex.count {
        case 3:  (a, r, g, b) = (255, (int >> 8) * 17, (int >> 4 & 0xF) * 17, (int & 0xF) * 17)
        case 6:  (a, r, g, b) = (255, int >> 16, int >> 8 & 0xFF, int & 0xFF)
        case 8:  (a, r, g, b) = (int >> 24, int >> 16 & 0xFF, int >> 8 & 0xFF, int & 0xFF)
        default: (a, r, g, b) = (255, 200, 200, 200)
        }
        self.init(
            .sRGB,
            red:     Double(r) / 255,
            green:   Double(g) / 255,
            blue:    Double(b) / 255,
            opacity: Double(a) / 255
        )
    }
}
