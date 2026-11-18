import Foundation
import SwiftUI

enum ERPDisplay {
    static func money(_ amount: Decimal, currency: String = "USD") -> String {
        amount.formatted(.currency(code: currency).locale(Locale(identifier: "es_EC")))
    }
    static func decimal(_ amount: Decimal) -> String {
        NSDecimalNumber(decimal: amount).stringValue
    }
    static func fiscalDate(_ date: Date) -> String {
        let format = DateFormatter()
        format.locale = Locale(identifier: "en_US_POSIX")
        format.timeZone = TimeZone(identifier: "America/Guayaquil")
        format.dateFormat = "yyyy-MM-dd"
        return format.string(from: date)
    }
    static func fiscalDueDate(_ date: Date, days: Int) -> String? {
        guard (0...365).contains(days) else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/Guayaquil")!
        guard let dueDate = calendar.date(byAdding: .day, value: days, to: date) else { return nil }
        return fiscalDate(dueDate)
    }
    static func status(_ raw: String) -> String {
        switch raw {
        case "DRAFT": "Borrador"
        case "READY": "Lista para emitir"
        case "SIGNED": "Firmada"
        case "RECEIVED": "Recibida por el SRI"
        case "PENDING_AUTHORIZATION": "Pendiente de autorización"
        case "AUTHORIZED": "Autorizada"
        case "HISTORICAL_ISSUED": "Histórica"
        case "NOT_AUTHORIZED": "No autorizada"
        case "REJECTED": "Rechazada"
        case "FAILED": "Error de proceso"
        case "VOIDED": "Anulada"
        case "OPEN": "Pendiente de cobro"
        case "PARTIAL": "Cobro parcial"
        case "OVERDUE": "Vencida"
        case "SETTLED": "Saldada"
        default: "Estado no reconocido (\(raw))"
        }
    }
}

enum DecimalEntry {
    /// Accept a decimal separator, never grouping/exponents or binary floating point.
    static func parse(_ text: String, scale: Int = 6, positive: Bool = false) -> Decimal? {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let pattern = "^[0-9]{1,12}([.,][0-9]{1,\(scale)})?$"
        guard value.range(of: pattern, options: .regularExpression) != nil,
              let decimal = Decimal(string: value.replacingOccurrences(of: ",", with: "."), locale: Locale(identifier: "en_US_POSIX")),
              !decimal.isNaN, positive ? decimal > 0 : decimal >= 0 else { return nil }
        return decimal
    }
}

struct WorkspaceContextSection: View {
    let store: WorkspaceStore
    var body: some View {
        Section {
            VStack(alignment: .leading, spacing: 8) {
                if store.isDemo {
                    ERPStatusBadge(text: "Demo", systemImage: "testtube.2")
                        .accessibilityLabel("Modo de demostración")
                }
                Text(store.context?.name ?? "Empresa")
                    .font(.headline)
            }
            .foregroundStyle(Color.primary)
            .padding(.vertical, 4)
        } footer: {
            if store.isDemo {
                Text("Datos de prueba.").font(.footnote).fixedSize(horizontal: false, vertical: true)
                    .foregroundStyle(Color.primary)
            }
        }
    }
}

struct ERPErrorState: View {
    let message: String
    let retry: () async -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(message, systemImage: "exclamationmark.circle")
                .foregroundStyle(Color.primary)
            Button("Reintentar") { Task { await retry() } }
                .frame(minHeight: 44)
        }
        .padding(.vertical, 8)
        .accessibilityIdentifier("load-error")
    }
}

actor TemporaryDocuments {
    private let root: URL
    private var generation: UUID?
    init(root: URL = FileManager.default.temporaryDirectory.appendingPathComponent("IAERPDocuments", isDirectory: true)) {
        self.root = root
    }
    func store(data: Data, fileName: String, generation expected: UUID) throws -> URL {
        guard generation == expected else { throw CancellationError() }
        let ext = (fileName as NSString).pathExtension.lowercased()
        guard !fileName.isEmpty, fileName.utf8.count <= 180,
              !fileName.contains("/"), !fileName.contains("\\"),
              fileName.rangeOfCharacter(from: .controlCharacters) == nil,
              ["pdf", "xml"].contains(ext) else { throw CocoaError(.fileWriteInvalidFileName) }
        // Keep the fiscal filename when sharing. An isolated download folder
        // prevents two documents with the same name overwriting one another.
        let folder = root.appendingPathComponent(expected.uuidString, isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true,
                                                attributes: [.protectionKey: FileProtectionType.complete])
        var resourceURL = root
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        try resourceURL.setResourceValues(values)
        let url = folder.appendingPathComponent(fileName)
        try data.write(to: url, options: [.atomic, .completeFileProtection])
        return url
    }
    func reset(generation next: UUID) throws {
        // Stable, app-private root also removes remnants left by a crash/relaunch.
        generation = nil
        if FileManager.default.fileExists(atPath: root.path) { try FileManager.default.removeItem(at: root) }
        generation = next
    }
}
