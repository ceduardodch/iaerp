import Foundation

struct DemoTestIssue: Codable {
    let key: String
    let operationID: UUID
    let source: ERPInvoice
    let readyAt: Date
    let reject: Bool
    let authorizedReplay: ERPInvoice?

    var operation: ERPTestIssueResult {
        ERPTestIssueResult(operationId: operationID, status: "PROCESSING")
    }

    var current: ERPInvoice {
        if !reject, Date() >= readyAt, let authorizedReplay { return authorizedReplay }
        var invoice = source
        invoice.accessKey = "DEMO-" + invoice.sequential
        let completed = Date() >= readyAt
        let date = readyAt.ISO8601Format()
        let message: String
        if !completed {
            invoice.status = "PENDING_AUTHORIZATION"
            message = "En espera del simulador SRI."
        } else if reject {
            invoice.status = "REJECTED"
            message = "El simulador rechazó los datos del comprobante de prueba."
        } else {
            invoice.status = "AUTHORIZED"
            invoice.authorizationNumber = "DEMO-AUT-" + invoice.sequential
            invoice.authorizedAt = date
            message = "Autorización simulada, sin validez fiscal."
        }
        invoice.sriTransmission = ERPSRITransmission(status: invoice.status, message: message,
            lastAttemptAt: date, authorizationNumber: invoice.authorizationNumber)
        return invoice
    }
}

struct DemoCapturedEmail: Codable {
    let key: String
    let subject: String
    let message: String
    let attachments: [ERPDocument]
    let receipt: ERPTestEmailReceipt
}

/// Only the demo owns this ledger. Its files are separate from live identities and draft recovery.
struct DemoProductRegistration: Codable {
    let requestDigest: Data
    let product: ERPProduct
}

struct DemoCustomerRegistration: Codable {
    let requestDigest: Data
    let party: ERPParty
}

struct DemoTestDeliveryLedger: Codable {
    var customerRequests: [String: DemoCustomerRegistration]?
    var productRequests: [String: DemoProductRegistration]?
    var issues: [UUID: DemoTestIssue] = [:]
    var captures: [UUID: DemoCapturedEmail] = [:]
    var files: [UUID: [ERPDocument]]?
}

final class DemoTestDeliveryStore {
    private static let lock = NSLock()
    private let file: URL?
    private var session = DemoTestDeliveryLedger()

    init(file: URL?) { self.file = file }

    func read() throws -> DemoTestDeliveryLedger {
        try Self.lock.withLock { try load() }
    }

    func update<T>(_ edit: (inout DemoTestDeliveryLedger) throws -> T) throws -> T {
        try Self.lock.withLock {
            var ledger = try load()
            let result = try edit(&ledger)
            if let file {
                let directory = file.deletingLastPathComponent()
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
                var resource = directory
                var options = URLResourceValues()
                options.isExcludedFromBackup = true
                try resource.setResourceValues(options)
                try JSONEncoder().encode(ledger).write(to: file, options: [.atomic, .completeFileProtection])
            } else {
                session = ledger
            }
            return result
        }
    }

    private func load() throws -> DemoTestDeliveryLedger {
        guard let file else { return session }
        do {
            return try JSONDecoder().decode(DemoTestDeliveryLedger.self, from: Data(contentsOf: file))
        } catch let error as CocoaError where error.code == .fileReadNoSuchFile {
            return DemoTestDeliveryLedger()
        }
    }
}
