import SwiftUI

/// A single shimmer rectangle. Size it from outside with .frame().
struct SkeletonView: View {
    @State private var phase: CGFloat = 0

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Theme.rule.opacity(0.45)
                LinearGradient(
                    gradient: Gradient(stops: [
                        .init(color: .clear,                    location: 0),
                        .init(color: .white.opacity(0.55),      location: 0.5),
                        .init(color: .clear,                    location: 1),
                    ]),
                    startPoint: .leading,
                    endPoint: .trailing
                )
                .frame(width: geo.size.width * 2)
                .offset(x: -geo.size.width + phase * geo.size.width * 2)
            }
            .clipped()
        }
        .cornerRadius(4)
        .onAppear {
            withAnimation(.linear(duration: 1.3).repeatForever(autoreverses: false)) {
                phase = 1
            }
        }
    }
}

/// A full row skeleton used while sections are loading.
struct SkeletonRowView: View {
    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .top, spacing: 12) {
                SkeletonView().frame(width: 24, height: 20)
                VStack(alignment: .leading, spacing: 7) {
                    SkeletonView().frame(height: 13)
                    SkeletonView().frame(width: 130, height: 10)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)

            Divider()
                .background(Theme.rule)
                .padding(.leading, 56)
        }
    }
}
