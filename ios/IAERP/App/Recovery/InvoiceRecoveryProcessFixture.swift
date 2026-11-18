#if DEBUG && targetEnvironment(simulator)
import Foundation
import IAERPClient
import IAERPIdentity
import Observation
import Security
import SwiftUI

/// A separate diagnostic surface for process-termination tests. It never
/// constructs an AuthenticationController, changes its gate, or calls a network
/// endpoint. Both the journal and its synthetic backend ledger use real Keychain
/// items under an isolated, per-run service UUID. This file cannot ship to iPhone.
struct InvoiceRecoveryProcessFixture: View {
    @State private var model = InvoiceRecoveryProcessModel(arguments: ProcessInfo.processInfo.arguments)

    var body: some View {
        NavigationStack {
            List {
                Text("Diagnóstico de recuperación. Sólo datos ficticios, sin acceso real.")
                Text("Proceso \(ProcessInfo.processInfo.processIdentifier)")
                    .accessibilityIdentifier("recovery-process-pid")
                Text(model.message).accessibilityIdentifier("recovery-process-status")
                if let key = model.originalKey {
                    Text(key).accessibilityIdentifier("recovery-process-original-key")
                }
                if model.checkpointReady {
                    Text("Punto de interrupción listo").accessibilityIdentifier("recovery-process-ready")
                }
                if model.canRecover {
                    Button("Recuperar guardado") { Task { await model.recover() } }
                        .accessibilityIdentifier("recovery-process-recover")
                        .disabled(model.working)
                }
                if model.completed {
                    Text("Recuperación completa").accessibilityIdentifier("recovery-process-complete")
                    Text("\(model.serverCount)").accessibilityIdentifier("recovery-process-server-count")
                    Text(model.keyMatches ? "true" : "false").accessibilityIdentifier("recovery-process-key-match")
                    Text(model.pendingAbsent ? "none" : "present").accessibilityIdentifier("recovery-process-pending")
                    Button("Limpiar datos ficticios de esta prueba") { model.cleanup() }
                        .accessibilityIdentifier("recovery-process-cleanup")
                }
                if model.cleaned {
                    Text("Datos ficticios eliminados").accessibilityIdentifier("recovery-process-cleaned")
                }
            }
            .navigationTitle("Prueba de proceso")
            .toolbarTitleDisplayMode(.inline)
        }
        .task { await model.start() }
    }
}

private enum RecoveryProcessStage: String, Sendable {
    case beforePost = "before-post", commitLost = "commit-lost", afterResponse = "after-response"
}

private enum RecoveryProcessPhase: String, Sendable { case start, recover }

nonisolated private struct RecoveryProcessOperation: Codable, Sendable {
    let key: String
    let payload: Data
    let invoice: ERPInvoice
}

nonisolated private struct RecoveryProcessLedger: Codable, Sendable {
    var operations: [RecoveryProcessOperation] = []
}

/// A synthetic server whose commit is independently durable across application
/// processes. Fiscal amounts come only from the existing fixed DemoERPService.
private actor RecoveryProcessERPService: ERPService, ERPInvoiceDraftLookup {
    private let demo = DemoERPService()
    private let ledgerVault: KeychainInvoiceRecoveryVault
    private let stage: RecoveryProcessStage
    private let phase: RecoveryProcessPhase
    private let checkpoint: @MainActor @Sendable () -> Void
    private var held: CheckedContinuation<Void, Never>?

    init(ledgerVault: KeychainInvoiceRecoveryVault, stage: RecoveryProcessStage,
         phase: RecoveryProcessPhase, checkpoint: @escaping @MainActor @Sendable () -> Void) {
        self.ledgerVault = ledgerVault; self.stage = stage; self.phase = phase; self.checkpoint = checkpoint
    }

    private func ledger() async throws -> RecoveryProcessLedger {
        guard let data = try await ledgerVault.read() else { return RecoveryProcessLedger() }
        return try JSONDecoder().decode(RecoveryProcessLedger.self, from: data)
    }
    private func persist(_ ledger: RecoveryProcessLedger) async throws {
        try await ledgerVault.write(JSONEncoder().encode(ledger))
    }
    func operationCount() async throws -> Int { try await ledger().operations.count }
    func keys() async throws -> [String] { try await ledger().operations.map(\.key) }
    func context() async throws -> ERPContext { try await demo.context() }
    func memberships() async throws -> [ERPMembership] { try await demo.memberships() }
    func customers(query: String) async throws -> [ERPParty] { try await demo.customers(query: query) }
    func products(query: String) async throws -> [ERPProduct] { try await demo.products(query: query) }
    func invoiceSetup() async throws -> ERPInvoiceSetup { try await demo.invoiceSetup() }
    func invoices(query: String, status: String?) async throws -> [ERPInvoice] {
        try await ledger().operations.map(\.invoice).filter { status == nil || $0.status == status }
    }
    func preview(_ input: ERPPreviewInput) async throws -> ERPInvoicePreview { try await demo.preview(input) }
    func findDraft(idempotencyKey: String) async throws -> UUID? {
        try await ledger().operations.first { $0.key == idempotencyKey }?.invoice.id
    }
    func createDraft(_ input: ERPInvoiceInput, idempotencyKey: String) async throws -> ERPInvoice {
        let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
        let payload = try encoder.encode(input)
        var saved = try await ledger()
        if let existing = saved.operations.first(where: { $0.key == idempotencyKey }) {
            guard existing.payload == payload else { throw ERPClientError.idempotencyConflict }
            return existing.invoice
        }
        let generated = try await demo.createDraft(input, idempotencyKey: idempotencyKey)
        let invoice = ERPInvoice(id: UUID(), type: generated.type, status: generated.status,
            sequential: generated.sequential, issueDate: generated.issueDate, subtotal: generated.subtotal,
            tax: generated.tax, total: generated.total, currency: generated.currency, partyId: generated.partyId,
            establishmentId: generated.establishmentId, emissionPointId: generated.emissionPointId,
            fiscalPolicyVersion: generated.fiscalPolicyVersion, collectionEnabled: generated.collectionEnabled,
            lines: generated.lines, installments: generated.installments)
        saved.operations.append(RecoveryProcessOperation(key: idempotencyKey, payload: payload, invoice: invoice))
        try await persist(saved)
        if phase == .start && stage == .commitLost {
            await checkpoint()
            // Deliberately never resume: XCUITest terminates this process after
            // observing the commit checkpoint, before the response can return.
            await withCheckedContinuation { held = $0 }
        }
        return invoice
    }
    func invoice(id: UUID) async throws -> ERPInvoice {
        if phase == .start && stage == .afterResponse {
            await checkpoint()
            // Journal already persisted the response id before requesting GET.
            await withCheckedContinuation { held = $0 }
        }
        guard let invoice = try await ledger().operations.first(where: { $0.invoice.id == id })?.invoice else {
            throw ERPClientError.notFound
        }
        return invoice
    }
    func artifacts(invoiceID: UUID) async throws -> [ERPArtifact] { [] }
    func document(invoiceID: UUID, artifact: ERPArtifact) async throws -> ERPDocument { throw ERPClientError.notFound }
}

@MainActor @Observable private final class InvoiceRecoveryProcessModel {
    var message = "Preparando diagnóstico…"
    var checkpointReady = false
    var completed = false
    var cleaned = false
    var working = false
    var serverCount = 0
    var keyMatches = false
    var pendingAbsent = false
    private var didStart = false
    private let runID: UUID?
    private let stage: RecoveryProcessStage?
    private let phase: RecoveryProcessPhase?
    private var scope: InvoiceRecoveryScope?
    private var journal: InvoiceRecoveryJournal?
    private var service: RecoveryProcessERPService?
    private(set) var originalKey: String?

    init(arguments: [String]) {
        func argument(_ name: String) -> String? {
            guard let index = arguments.firstIndex(of: name), arguments.indices.contains(index + 1) else { return nil }
            return arguments[index + 1]
        }
        runID = argument("-recovery-run").flatMap(UUID.init(uuidString:))
        stage = argument("-recovery-stage").flatMap(RecoveryProcessStage.init(rawValue:))
        phase = argument("-recovery-phase").flatMap(RecoveryProcessPhase.init(rawValue:))
    }

    var canRecover: Bool { phase == .recover && journal != nil && !completed }
    private var serviceNames: [String] {
        guard let runID else { return [] }
        return ["journal", "backend"].map { "ec.com.b2b.iaerp.process-fixture.\(runID.uuidString).\($0)" }
    }

    func start() async {
        guard !didStart else { return }
        didStart = true
        guard let runID, let stage, let phase else { message = "Parámetros de diagnóstico no válidos."; return }
        do {
            let scope = InvoiceRecoveryScope(profileID: runID,
                configuration: try IdentityConfiguration(apiBaseURL: URL(string: "https://api.example.invalid/api/v1")!,
                    issuerURL: URL(string: "https://identity.example.invalid/realms/process-test")!,
                    clientID: "iaerp-ios-process-fixture", organizationAlias: DemoCompany.primary.alias),
                subject: "synthetic-process-user", organizationID: DemoCompany.primary.alias,
                tenantID: DemoCompany.primary.tenantId)
            self.scope = scope
            let journal = InvoiceRecoveryJournal(vault: KeychainInvoiceRecoveryVault(service: serviceNames[0]))
            self.journal = journal
            let service = RecoveryProcessERPService(ledgerVault: KeychainInvoiceRecoveryVault(service: serviceNames[1]),
                stage: stage, phase: phase, checkpoint: { [weak self] in
                    self?.message = "Interrumpir ahora: \(stage.rawValue)"
                    self?.checkpointReady = true
                })
            self.service = service
            if phase == .recover {
                guard let pending = try journal.pending(in: scope) else { throw InvoiceRecoveryError.missingOperation }
                originalKey = pending.idempotencyKey
                message = "Operación conservada tras volver a iniciar la app."
                return
            }
            guard try journal.pending(in: scope) == nil else { throw InvoiceRecoveryError.pendingOperation }
            let setup = try await service.invoiceSetup()
            guard let customer = try await service.customers(query: "").first,
                  let product = try await service.products(query: "").first,
                  let establishment = setup.establishments.first,
                  let point = setup.emissionPoints.first else { throw ERPClientError.invalidResponse }
            let line = ERPInvoiceLineInput(productId: product.id, description: product.name,
                quantity: 1, unitPrice: product.unitPrice, taxCode: "4")
            let date = "2026-11-18"
            let preview = try await service.preview(ERPPreviewInput(issueDate: date, lines: [line]))
            let input = ERPInvoiceInput(customerId: customer.id, establishmentId: establishment.id,
                emissionPointId: point.id, issueDate: date, lines: [line],
                installments: [ERPInstallment(dueDate: date, amount: preview.total)])
            let pending = try journal.prepare(input: input, in: scope)
            originalKey = pending.idempotencyKey
            if stage == .beforePost {
                message = "Interrumpir ahora: before-post"
                checkpointReady = true
            } else {
                _ = try await journal.execute(pending, in: scope, using: service) { scope }
                message = "No se alcanzó el punto de interrupción esperado."
            }
        } catch { message = "Fallo de diagnóstico: \(friendlyError(error))" }
    }

    func recover() async {
        guard !working, !completed, let journal, let service, let scope, let originalKey else { return }
        working = true
        defer { working = false }
        do {
            _ = try await journal.recover(in: scope, using: service) { scope }
            serverCount = try await service.operationCount()
            keyMatches = try await service.keys() == [originalKey]
            pendingAbsent = try journal.pending(in: scope) == nil
            completed = true
            message = "Recuperación comprobada con un solo borrador."
        } catch { message = "Fallo de diagnóstico: \(friendlyError(error))" }
    }

    func cleanup() {
        guard completed, pendingAbsent, serviceNames.count == 2 else { return }
        for service in serviceNames {
            let status = SecItemDelete([kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service] as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else {
                message = "No se pudieron retirar los datos ficticios de esta prueba."
                return
            }
        }
        cleaned = true
    }
}
#endif
