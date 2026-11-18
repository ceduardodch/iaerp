import SwiftUI

struct ERPStatusBadge: View {
    let text: LocalizedStringKey
    let systemImage: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: systemImage)
                .foregroundStyle(.tint)
                .accessibilityHidden(true)
            Text(text)
                .fixedSize(horizontal: false, vertical: true)
        }
            .font(.subheadline.weight(.medium))
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(.tint.opacity(0.12), in: Capsule())
            .accessibilityElement(children: .combine)
    }
}

struct ERPDetailRow: View {
    let title: LocalizedStringKey
    let value: String

    var body: some View {
        LabeledContent {
            Text(value)
                .foregroundStyle(Color.primary)
                .fixedSize(horizontal: false, vertical: true)
        } label: {
            Text(title)
                .foregroundStyle(Color.primary)
                .fixedSize(horizontal: false, vertical: true)
        }
            .frame(minHeight: 44)
    }
}

/// Shared native input with explicit contrast in both appearances. Keeping the
/// prompt as SwiftUI Text avoids UISearchBar's placeholder color override.
struct ERPSearchField: View {
    @Binding var text: String
    var prompt = "Buscar"

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(Color.primary)
                .accessibilityHidden(true)
            TextField(prompt, text: $text, prompt: Text("Buscar").foregroundStyle(Color.primary))
                .font(.body)
                .foregroundStyle(Color.primary)
                .textFieldStyle(.plain)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.search)
                .frame(minHeight: 44)
                .accessibilityIdentifier("erp-search-field")
                .accessibilityLabel(prompt)
            if !text.isEmpty {
                Button("Borrar búsqueda", systemImage: "xmark.circle.fill") { text = "" }
                    .labelStyle(.iconOnly)
                    .foregroundStyle(Color.primary)
                    .frame(minWidth: 44, minHeight: 44)
            }
        }
        .font(.body)
    }
}

struct ERPListSummary: View {
    let count: Int
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Resultados: \(count)").font(.footnote).foregroundStyle(Color.primary)
            Text("Hasta 100 por consulta").font(.footnote).foregroundStyle(Color.primary)
        }
        .fixedSize(horizontal: false, vertical: true)
    }
}

struct ERPCloseButton: View {
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        Button("Cerrar", systemImage: "xmark") { dismiss() }
            .labelStyle(.iconOnly)
            .frame(minWidth: 44, minHeight: 44)
            .accessibilityLabel("Cerrar")
    }
}

/// A disabled action remains readable; the system prominent style faded the
/// label below the native audit's contrast threshold at accessibility sizes.
struct ERPPrimaryActionStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .foregroundStyle(isEnabled ? Color(uiColor: .systemBackground) : Color.primary)
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
            .frame(minHeight: 44)
            .background(isEnabled ? Color.primary : Color(uiColor: .secondarySystemFill), in: Capsule())
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
    }
}
