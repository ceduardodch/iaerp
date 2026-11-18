import Foundation

/// Fixtures only. This module has no network, credentials or production data.
public struct DemoClient: Identifiable, Equatable, Sendable {
    public let id: UUID
    public let tenantID: UUID
    public let name: String
    public let city: String

    public init(id: UUID, tenantID: UUID, name: String, city: String) {
        self.id = id
        self.tenantID = tenantID
        self.name = name
        self.city = city
    }
}

public struct DemoDirectory: Sendable {
    public let tenantID: UUID
    private let records: [DemoClient]

    public init(tenantID: UUID, clients: [DemoClient]) {
        self.tenantID = tenantID
        self.records = clients
    }

    public func clients(matching query: String) -> [DemoClient] {
        let term = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return records.filter { client in
            guard client.tenantID == tenantID else { return false }
            return term.isEmpty || [client.name, client.city].contains { value in
                value.range(
                    of: term,
                    options: [.caseInsensitive, .diacriticInsensitive],
                    locale: Locale(identifier: "es_EC")
                ) != nil
            }
        }
    }

    public func client(id: UUID) -> DemoClient? {
        records.first { $0.id == id && $0.tenantID == tenantID }
    }

    public static let example: DemoDirectory = {
        let tenantID = UUID(uuidString: "00000000-0000-4000-8000-000000000001")!
        return DemoDirectory(tenantID: tenantID, clients: [
            DemoClient(
                id: UUID(uuidString: "00000000-0000-4000-8000-000000000101")!,
                tenantID: tenantID, name: "Cliente de ejemplo Álamo", city: "Quito"
            ),
            DemoClient(
                id: UUID(uuidString: "00000000-0000-4000-8000-000000000102")!,
                tenantID: tenantID, name: "Cliente de ejemplo Costa", city: "Guayaquil"
            ),
            DemoClient(
                id: UUID(uuidString: "00000000-0000-4000-8000-000000000103")!,
                tenantID: tenantID, name: "Cliente de ejemplo Sierra", city: "Cuenca"
            ),
        ])
    }()
}
