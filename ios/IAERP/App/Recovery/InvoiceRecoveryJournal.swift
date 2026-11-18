import Foundation
import IAERPClient
import IAERPIdentity
import Security

nonisolated struct InvoiceRecoveryScope: Codable, Equatable, Sendable {
    let profileID: UUID
    let configuration: IdentityConfiguration
    let subject: String
    let organizationID: String
    let tenantID: UUID

    /// A fresh interactive login can assign another local profile UUID after
    /// logout. Only the exact same OIDC identity, organization and full public
    /// configuration may reconcile its operation; the original UUID is retained.
    func representsSameIdentity(as other: Self) -> Bool {
        configuration == other.configuration && subject == other.subject &&
            organizationID == other.organizationID && tenantID == other.tenantID
    }

    /// Financial uniqueness survives public OIDC/document settings changing.
    /// Those settings still bind authorization for replay; they cannot hide a
    /// previous uncertain write and permit another UUID against the same API.
    func representsSameFinancialIdentity(as other: Self) -> Bool {
        configuration.issuerURL == other.configuration.issuerURL && subject == other.subject &&
            organizationID == other.organizationID && tenantID == other.tenantID &&
            Self.canonicalAPI(configuration.apiBaseURL) == Self.canonicalAPI(other.configuration.apiBaseURL)
    }

    private static func canonicalAPI(_ url: URL) -> String {
        let path = url.path.replacingOccurrences(of: #"/+$"#, with: "", options: .regularExpression)
        return "\(url.scheme?.lowercased() ?? "")://\(url.host?.lowercased() ?? ""):\(url.port ?? 443)\(path)"
    }
}

nonisolated struct PendingInvoiceWrite: Codable, Equatable, Identifiable, Sendable {
    let id: UUID
    let scope: InvoiceRecoveryScope
    let createdAt: Date
    let requestPayload: Data
    var confirmedInvoiceID: UUID?
    var attemptCount = 0
    var idempotencyKey: String { id.uuidString }

    func input() throws -> ERPInvoiceInput {
        do {
            let input = try JSONDecoder().decode(ERPInvoiceInput.self, from: requestPayload)
            let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
            guard try encoder.encode(input) == requestPayload else { throw InvoiceRecoveryError.storageFailure }
            return input
        } catch { throw InvoiceRecoveryError.storageFailure }
    }
}

nonisolated enum InvoiceRecoveryError: Error, LocalizedError, Equatable, Sendable {
    case storageFailure, pendingOperation, wrongIdentity, permissionDenied
    case reconciliationRequired, invalidConfirmation, busy, missingOperation

    var errorDescription: String? {
        switch self {
        case .storageFailure: "No se pudo proteger el guardado pendiente. No se enviará otra operación."
        case .pendingOperation: "Hay una factura pendiente de confirmar en esta cuenta. Recupérala antes de crear otra."
        case .wrongIdentity: "Entra con el mismo usuario y empresa que inició este guardado."
        case .permissionDenied: "No tienes permiso vigente para recuperar este guardado en la empresa."
        case .reconciliationRequired: "El guardado necesita conciliación. Consulta Facturas. No se enviará otra operación."
        case .invalidConfirmation: "El servidor no confirmó la factura de esta operación. Se conserva el guardado pendiente."
        case .busy: "Ya se está comprobando este guardado. Espera a que termine."
        case .missingOperation: "El guardado pendiente ya no está disponible. Actualiza la cuenta."
        }
    }
}

@MainActor protocol InvoiceRecoveryVault: AnyObject {
    func read() throws -> Data?
    func write(_ data: Data) throws
}

/// This service never stores tokens, passwords or downloaded business files.
/// Keychain encrypts the minimal original request and keeps it on this device.
@MainActor final class KeychainInvoiceRecoveryVault: InvoiceRecoveryVault {
    private let service: String
    private let account = "invoice.pending-writes.v1"
    private(set) var lastOperationStatus: OSStatus?
    private(set) var lastOperation: String?
    init(service: String = "ec.com.b2b.iaerp.invoice-recovery") { self.service = service }

    func read() throws -> Data? {
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(request as CFDictionary, &item)
        lastOperation = "read"
        lastOperationStatus = status
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = item as? Data else { throw InvoiceRecoveryError.storageFailure }
        return data
    }

    func write(_ data: Data) throws {
        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        lastOperation = "update"
        lastOperationStatus = status
        if status == errSecItemNotFound {
            var insertion = query
            attributes.forEach { insertion[$0.key] = $0.value }
            let insertionStatus = SecItemAdd(insertion as CFDictionary, nil)
            lastOperation = "add"
            lastOperationStatus = insertionStatus
            guard insertionStatus == errSecSuccess else { throw InvoiceRecoveryError.storageFailure }
        } else if status != errSecSuccess { throw InvoiceRecoveryError.storageFailure }
    }

    private var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service, kSecAttrAccount as String: account,
         kSecAttrSynchronizable as String: false]
    }
}

/// One unresolved operation per authenticated identity/company. Every network
/// failure leaves the same UUID and original payload durable. There is no public
/// discard/reset method: a timeout, 401, 403 or 409 cannot make a new invoice safe.
@MainActor final class InvoiceRecoveryJournal {
    typealias Authorize = @MainActor () throws -> InvoiceRecoveryScope
    private let vault: any InvoiceRecoveryVault
    private let now: () -> Date
    private static var inFlight: Set<UUID> = []
    // Local wall time only limits the freshness of a never-submitted request.
    // It cannot establish server retention or authorize replay after restart.
    private let initialSubmissionWindow: TimeInterval = 23 * 60 * 60
    private let maximumBytes = 2 * 1_024 * 1_024

    init(vault: any InvoiceRecoveryVault = KeychainInvoiceRecoveryVault(), now: @escaping () -> Date = Date.init) {
        self.vault = vault; self.now = now
    }

    func pending(in scope: InvoiceRecoveryScope) throws -> PendingInvoiceWrite? {
        try records().first { $0.scope.representsSameFinancialIdentity(as: scope) }
    }

    func prepare(input: ERPInvoiceInput, in scope: InvoiceRecoveryScope) throws -> PendingInvoiceWrite {
        var all = try records()
        guard !all.contains(where: { $0.scope.representsSameFinancialIdentity(as: scope) }) else {
            throw InvoiceRecoveryError.pendingOperation
        }
        guard !scope.subject.isEmpty, !scope.organizationID.isEmpty else { throw InvoiceRecoveryError.wrongIdentity }
        let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
        let record = try PendingInvoiceWrite(id: UUID(), scope: scope, createdAt: now(),
            requestPayload: encoder.encode(input))
        all.append(record)
        try save(all) // Synchronous durable boundary, strictly before any POST.
        return record
    }

    func recover(in scope: InvoiceRecoveryScope, using service: any ERPService,
                 authorize: Authorize) async throws -> ERPInvoice {
        guard let record = try pending(in: scope) else { throw InvoiceRecoveryError.missingOperation }
        return try await execute(record, in: scope, using: service, authorize: authorize)
    }

    func execute(_ record: PendingInvoiceWrite, in scope: InvoiceRecoveryScope,
                 using service: any ERPService, authorize: Authorize) async throws -> ERPInvoice {
        try checkIdentity(scope, authorize: authorize)
        guard let stored = try pending(in: scope), stored == record else { throw InvoiceRecoveryError.missingOperation }
        guard Self.inFlight.insert(record.id).inserted else { throw InvoiceRecoveryError.busy }
        defer { Self.inFlight.remove(record.id) }
        let input = try record.input()
        let context = try await service.context()
        try checkIdentity(scope, authorize: authorize)
        guard context.tenantId == scope.tenantID, context.permits("invoices:read") else {
            throw InvoiceRecoveryError.permissionDenied
        }
        let memberships = try await service.memberships()
        try checkIdentity(scope, authorize: authorize)
        guard memberships.contains(where: {
            $0.tenantId == scope.tenantID && $0.active && $0.organizationId == scope.organizationID
        }) else { throw InvoiceRecoveryError.permissionDenied }

        var confirmed = record
        if confirmed.confirmedInvoiceID == nil {
            if let lookup = service as? any ERPInvoiceDraftLookup {
                let found = try await lookup.findDraft(idempotencyKey: record.idempotencyKey)
                try checkIdentity(scope, authorize: authorize)
                if let found {
                    confirmed.confirmedInvoiceID = found
                    try replace(confirmed)
                }
            }
        }
        if confirmed.confirmedInvoiceID == nil {
            // A persisted attempt may already have committed. Even a small
            // local-clock age cannot prove that its server key still exists.
            // Without positive lookup evidence, never send another POST.
            guard confirmed.attemptCount == 0 else { throw InvoiceRecoveryError.reconciliationRequired }
            guard record.scope.representsSameIdentity(as: scope) else {
                throw InvoiceRecoveryError.reconciliationRequired
            }
            guard context.permits("invoices:write") else { throw InvoiceRecoveryError.permissionDenied }
            let instant = now()
            guard instant >= record.createdAt, instant.timeIntervalSince(record.createdAt) < initialSubmissionWindow else {
                throw InvoiceRecoveryError.reconciliationRequired
            }
            let firstAttempt = confirmed.attemptCount == 0
            confirmed.attemptCount += 1
            try replace(confirmed) // A crash from here makes this attempt uncertain.
            let response: ERPInvoice
            do {
                response = try await service.createDraft(input, idempotencyKey: record.idempotencyKey)
            } catch {
                try checkIdentity(scope, authorize: authorize)
                if firstAttempt, let failure = error as? ERPClientError,
                   case .invalidInput = failure {
                    // The first request has a definitive validation rejection;
                    // no preceding uncertain POST exists. Let the user correct it.
                    try remove(confirmed)
                }
                throw error
            }
            // Validate the authoritative idempotency response before recording
            // its id. Do not publish a response belonging to another scope.
            try checkIdentity(scope, authorize: authorize)
            try validateConfirmation(response, input: input, requiresDraft: true)
            confirmed.confirmedInvoiceID = response.id
            try replace(confirmed)
        }
        guard let id = confirmed.confirmedInvoiceID else { throw InvoiceRecoveryError.invalidConfirmation }
        let current = try await service.invoice(id: id)
        try checkIdentity(scope, authorize: authorize)
        guard current.id == id else {
            throw InvoiceRecoveryError.invalidConfirmation
        }
        try validateConfirmation(current, input: input, requiresDraft: false)
        try remove(confirmed)
        return current
    }

    private func checkIdentity(_ expected: InvoiceRecoveryScope, authorize: Authorize) throws {
        try Task.checkCancellation()
        let active = try authorize()
        guard active.profileID == expected.profileID,
              active.representsSameIdentity(as: expected) else { throw InvoiceRecoveryError.wrongIdentity }
    }

    private func validateConfirmation(_ invoice: ERPInvoice, input: ERPInvoiceInput, requiresDraft: Bool) throws {
        guard invoice.type == "INVOICE", (!requiresDraft || invoice.status == "DRAFT"),
              invoice.currency.range(of: #"^[A-Z]{3}$"#, options: .regularExpression) != nil,
              invoice.partyId == input.customerId, invoice.establishmentId == input.establishmentId,
              invoice.emissionPointId == input.emissionPointId, invoice.issueDate == input.issueDate,
              invoice.collectionEnabled == input.collectionEnabled,
              (input.installments.isEmpty || invoice.installments == input.installments),
              invoice.lines.count == input.lines.count else {
            throw InvoiceRecoveryError.invalidConfirmation
        }
        for (line, expected) in zip(invoice.lines, input.lines) {
            guard line.productId == expected.productId, line.description == expected.description,
                  line.quantity == expected.quantity, line.unitPrice == expected.unitPrice,
                  line.discount == expected.discount, line.taxCode == expected.taxCode else {
                throw InvoiceRecoveryError.invalidConfirmation
            }
        }
    }

    private func records() throws -> [PendingInvoiceWrite] {
        do {
            guard let data = try vault.read() else { return [] }
            guard data.count <= maximumBytes else { throw InvoiceRecoveryError.storageFailure }
            let all = try JSONDecoder().decode([PendingInvoiceWrite].self, from: data)
            guard Set(all.map(\.id)).count == all.count else { throw InvoiceRecoveryError.storageFailure }
            for record in all { _ = try record.input() }
            return all
        } catch { throw InvoiceRecoveryError.storageFailure }
    }

    private func save(_ all: [PendingInvoiceWrite]) throws {
        do {
            let data = try JSONEncoder().encode(all)
            guard data.count <= maximumBytes else { throw InvoiceRecoveryError.storageFailure }
            try vault.write(data)
        } catch { throw InvoiceRecoveryError.storageFailure }
    }

    private func replace(_ record: PendingInvoiceWrite) throws {
        var all = try records()
        guard let index = all.firstIndex(where: { $0.id == record.id && $0.scope == record.scope }) else {
            throw InvoiceRecoveryError.missingOperation
        }
        all[index] = record
        try save(all)
    }

    private func remove(_ record: PendingInvoiceWrite) throws {
        var all = try records()
        guard all.contains(record) else { throw InvoiceRecoveryError.missingOperation }
        all.removeAll { $0.id == record.id }
        try save(all)
    }
}
