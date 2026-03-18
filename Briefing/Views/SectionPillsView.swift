import SwiftUI

struct SectionPillsView: View {
    @Binding var selected: String
    let labels: [String: String]
    let order: [String]

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                pill("all")
                ForEach(order, id: \.self) { section in
                    pill(section)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
        }
    }

    @ViewBuilder
    private func pill(_ section: String) -> some View {
        let isSelected = selected == section
        Button {
            selected = section
        } label: {
            Text(labels[section] ?? section)
                .font(Theme.sans(12, weight: .medium))
                .tracking(0.4)
                .foregroundColor(isSelected ? .white : Theme.ink)
                .padding(.horizontal, 14)
                .padding(.vertical, 6)
                .background(isSelected ? Theme.ink : Color.clear)
                .overlay(
                    Capsule().stroke(isSelected ? Color.clear : Theme.rule, lineWidth: 1)
                )
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
    }
}
