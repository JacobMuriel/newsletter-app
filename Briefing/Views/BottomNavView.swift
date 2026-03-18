import SwiftUI

struct BottomNavView: View {
    var body: some View {
        VStack(spacing: 0) {
            Divider().background(Theme.rule)
            HStack {
                navItem(icon: "newspaper",          label: "Today")
                Spacer()
                navItem(icon: "square.grid.2x2",    label: "Sections")
                Spacer()
                navItem(icon: "magnifyingglass",    label: "Search")
            }
            .padding(.horizontal, 40)
            .padding(.top, 10)
            .padding(.bottom, 24) // extra for home indicator
            .background(Theme.background)
        }
    }

    @ViewBuilder
    private func navItem(icon: String, label: String) -> some View {
        VStack(spacing: 3) {
            Image(systemName: icon)
                .font(.system(size: 20))
            Text(label)
                .font(Theme.sans(9))
        }
        .foregroundColor(Theme.ink)
    }
}
