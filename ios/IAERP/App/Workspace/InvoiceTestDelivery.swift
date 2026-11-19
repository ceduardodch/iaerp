import Foundation
import IAERPClient
import SwiftUI

enum InvoiceTestAction: String, Codable {
    case issue, email
}

private struct InvoiceTestAttempt: Codable {
    let scope: InvoiceRecoveryScope
    let invoiceID: UUID
    let action: InvoiceTestAction
    let key: String
    let recipient: String?
    var needsReconciliation: Bool? = nil
}

/// Persist only unresolved action identifiers. A lost response or a relaunch
/// permits a status query, never an automatic replay of an external effect.
@MainActor final class InvoiceTestAttemptJournal {
    private let vault: any InvoiceRecoveryVault
    private var demoAttempts: [UUID: (action: InvoiceTestAction, key: String, recipient: String?)] = [:]

    init(vault: any InvoiceRecoveryVault = KeychainInvoiceRecoveryVault(service: "ec.com.b2b.iaerp.test-delivery")) {
        self.vault = vault
    }

    func clearDemo() { demoAttempts.removeAll() }

    func pending(invoiceID: UUID, scope: InvoiceRecoveryScope?) throws -> InvoiceTestAction? {
        guard let scope else { return demoAttempts[invoiceID]?.0 }
        return try entries().first { $0.invoiceID == invoiceID && $0.scope.representsSameFinancialIdentity(as: scope) }?.action
    }

    func begin(_ action: InvoiceTestAction, invoiceID: UUID, scope: InvoiceRecoveryScope?, recipient: String? = nil) throws -> String {
        guard try pending(invoiceID: invoiceID, scope: scope) == nil else { throw InvoiceRecoveryError.pendingOperation }
        let key = UUID().uuidString
        if let scope {
            var records = try entries()
            records.append(InvoiceTestAttempt(scope: scope, invoiceID: invoiceID, action: action, key: key, recipient: recipient))
            try vault.write(JSONEncoder().encode(records))
        } else {
            demoAttempts[invoiceID] = (action, key, recipient)
        }
        return key
    }

    func needsReconciliation(invoiceID: UUID, scope: InvoiceRecoveryScope) throws -> Bool {
        try entries().contains { $0.invoiceID == invoiceID && $0.scope.representsSameFinancialIdentity(as: scope) && $0.needsReconciliation == true }
    }

    func markForReconciliation(_ action: InvoiceTestAction, invoiceID: UUID, scope: InvoiceRecoveryScope) throws {
        var records = try entries()
        guard let index = records.firstIndex(where: {
            $0.invoiceID == invoiceID && $0.action == action && $0.scope.representsSameFinancialIdentity(as: scope)
        }) else { throw InvoiceRecoveryError.missingOperation }
        records[index].needsReconciliation = true
        try vault.write(JSONEncoder().encode(records))
    }

    func retryKey(_ action: InvoiceTestAction, invoiceID: UUID, scope: InvoiceRecoveryScope?, recipient: String?) throws -> String {
        if let scope {
            guard let record = try entries().first(where: { $0.invoiceID == invoiceID && $0.scope.representsSameIdentity(as: scope) }),
                  record.action == action, record.recipient == recipient, record.needsReconciliation != true else { throw InvoiceRecoveryError.reconciliationRequired }
            return record.key
        }
        guard let record = demoAttempts[invoiceID], record.action == action, record.recipient == recipient else {
            throw InvoiceRecoveryError.reconciliationRequired
        }
        return record.key
    }

    func finish(_ action: InvoiceTestAction, invoiceID: UUID, scope: InvoiceRecoveryScope?) throws {
        if let scope {
            var records = try entries()
            let before = records.count
            records.removeAll { $0.invoiceID == invoiceID && $0.action == action && $0.scope.representsSameFinancialIdentity(as: scope) }
            if records.count != before { try vault.write(JSONEncoder().encode(records)) }
        } else if demoAttempts[invoiceID]?.0 == action {
            demoAttempts.removeValue(forKey: invoiceID)
        }
    }

    private func entries() throws -> [InvoiceTestAttempt] {
        guard let data = try vault.read() else { return [] }
        return try JSONDecoder().decode([InvoiceTestAttempt].self, from: data)
    }
}

private enum InvoiceTestReview: Identifiable {
    case issue(retrying: Bool)
    case email(ERPTestEmailPreview, retrying: Bool)

    var retrying: Bool {
        switch self {
        case .issue(let retrying), .email(_, let retrying): retrying
        }
    }

    var recipient: String? {
        if case .email(let preview, _) = self { return preview.recipient }
        return nil
    }

    var id: InvoiceTestAction {
        switch self {
        case .issue: .issue
        case .email: .email
        }
    }
}

extension InvoiceTestAction {
    func serverAllowsRetry(status: String, actions: ERPTestInvoiceActions) -> Bool {
        guard actions.environment == "TEST", actions.transmissionMode == "simulator" else { return false }
        switch self {
        case .issue: return status == "DRAFT" && actions.canIssue
        case .email: return status == "AUTHORIZED" && actions.canEmail && actions.emailReceipt == nil
        }
    }
}

struct InvoiceTestDeliverySection: View {
    let store: WorkspaceStore
    let invoice: ERPInvoice
    let number: String
    let artifacts: [ERPArtifact]
    let reloadDocument: () async -> ERPInvoice?

    @State private var actions: ERPTestInvoiceActions?
    @State private var pending: InvoiceTestAction?
    @State private var canRetry = false
    @State private var review: InvoiceTestReview?
    @State private var receipt: ERPTestEmailReceipt?
    @State private var message: String?
    @State private var busy = false
    @State private var refreshVersion = 0
    @State private var actionReadID = UUID()

    private var hasAttachments: Bool {
        Set(artifacts.map(\.artifactType)).isSuperset(of: ["ride-pdf", "xml-signed"])
    }
    private var followsIssue: Bool {
        pending == .issue || ["READY", "SIGNED", "RECEIVED", "PENDING_AUTHORIZATION"].contains(invoice.status)
    }

    var body: some View {
        Section {
            VStack(alignment: .leading, spacing: 10) {
                if let actions {
                    if let receipt {
                        VStack(alignment: .leading, spacing: 6) {
                            Label("Correo capturado", systemImage: "checkmark.circle")
                                .font(.headline)
                            Text(verbatim: receipt.recipient)
                            ForEach(receipt.attachmentNames, id: \.self) { name in
                                Text(verbatim: name).font(.subheadline)
                            }
                        }
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("test-delivery-receipt")
                    } else if pending == .email {
                        Text(canRetry ? "El buzón aún no registra este correo." : "Comprobando si el buzón de pruebas recibió el correo.")
                    } else if followsIssue {
                        Text(canRetry ? "El simulador aún muestra el borrador. Revisa la emisión pendiente antes de reintentar." : "Esperando la autorización del simulador. Puedes consultar el estado de esta misma factura.")
                    } else if actions.canIssue && invoice.status == "DRAFT" {
                        Text("Para autorizar este borrador en el simulador, revisa y confirma la emisión.")
                            .accessibilityIdentifier("test-issue-guidance")
                        Button("Emitir en pruebas", systemImage: "doc.badge.arrow.up") { review = .issue(retrying: false) }
                            .frame(minHeight: 44)
                            .accessibilityIdentifier("test-issue-invoice")
                    } else if invoice.status == "AUTHORIZED" && actions.canEmail && hasAttachments {
                        Button("Enviar por correo", systemImage: "envelope") { Task { await prepareEmail(retrying: false) } }
                            .frame(minHeight: 44)
                            .accessibilityIdentifier("test-email-invoice")
                    } else if invoice.status == "AUTHORIZED" && !hasAttachments {
                        Text("Para enviar el correo hacen falta el RIDE y el XML. Toca Consultar estado para comprobar si ya están listos.")
                    } else if invoice.status == "AUTHORIZED" {
                        Text(store.context?.permits("invoices:test-email") == true
                             ? "El simulador todavía no habilita el envío de esta factura. Toca Consultar estado para actualizarla."
                             : "Tu cuenta necesita permiso de envío al buzón de pruebas. Pídelo a quien administra tu empresa.")
                    } else if invoice.status == "DRAFT" {
                        Text(store.context?.permits("invoices:test-issue") == true
                             ? "El simulador no habilita la emisión de este borrador. Toca Consultar estado antes de volver a intentarlo."
                             : "Tu cuenta necesita permiso de emisión en pruebas. Pídelo a quien administra tu empresa.")
                    } else if ["REJECTED", "NOT_AUTHORIZED", "FAILED"].contains(invoice.status) {
                        Text("Revisa el motivo en Estado antes de preparar otro ensayo. El correo requiere una factura autorizada.")
                    } else {
                        Text("Para enviar el correo de prueba, la factura debe estar autorizada y tener el RIDE y el XML.")
                    }
                    if let pending, canRetry {
                        Button(pending == .issue ? "Revisar emisión pendiente" : "Revisar envío pendiente") {
                            switch pending {
                            case .issue: review = .issue(retrying: true)
                            case .email: Task { await prepareEmail(retrying: true) }
                            }
                        }
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("test-retry-delivery")
                    }
                    if let message { Text(verbatim: message).accessibilityIdentifier("test-delivery-message") }
                    if busy { ProgressView("Consultando…") }
                    if shouldOfferRefresh(actions) { refreshButton }
                } else if let message {
                    Text(verbatim: message)
                    refreshButton
                } else {
                    ProgressView("Consultando acciones de prueba…")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .buttonStyle(.borderless)
            .sheet(item: $review) { step in
                InvoiceTestReviewSheet(step: step, company: store.context?.name ?? "", number: number,
                                       total: ERPDisplay.money(invoice.total, currency: invoice.currency),
                                       confirm: { await submit(step) })
            }
        } header: {
            Text("Simulador SRI · Pruebas").foregroundStyle(Color.primary)
        }
        .disabled(busy)
        .task { await fetchActions(currentInvoice: invoice) }
        .task(id: PollRequest(generation: store.generation, invoiceID: invoice.id,
                              pending: actions != nil && (followsIssue || pending == .email), version: refreshVersion)) {
            guard actions != nil, followsIssue || pending == .email else { return }
            // Stop network traffic when this view disappears. Returning to the
            // invoice or "Consultar estado" starts another read-only window.
            for delay in [1, 2, 3, 5, 8, 13] {
                do { try await Task.sleep(for: .seconds(delay)) } catch { return }
                guard !Task.isCancelled else { return }
                if !busy { await refresh() }
            }
        }

    }

    private struct PollRequest: Equatable {
        let generation: UUID
        let invoiceID: UUID
        let pending: Bool
        let version: Int
    }

    private func shouldOfferRefresh(_ actions: ERPTestInvoiceActions) -> Bool {
        if followsIssue || pending == .email || message != nil { return true }
        switch invoice.status {
        case "DRAFT":
            return !actions.canIssue && store.context?.permits("invoices:test-issue") == true
        case "AUTHORIZED":
            return receipt == nil && (!hasAttachments || (!actions.canEmail && store.context?.permits("invoices:test-email") == true))
        default:
            return false
        }
    }

    private var refreshButton: some View {
        Button("Consultar estado", systemImage: "arrow.clockwise") {
            Task {
                await refresh()
                refreshVersion += 1
            }
        }
        .frame(minHeight: 44)
        .accessibilityIdentifier("test-refresh-delivery")
    }

    private func recoveryScope() throws -> InvoiceRecoveryScope? {
        if store.isDemo { return nil }
        return try store.currentInvoiceRecoveryScope()
    }

    private func fetchActions(currentInvoice: ERPInvoice?) async {
        guard let api = store.service as? any ERPTestInvoiceService else { return }
        let generation = store.generation
        let request = UUID()
        actionReadID = request
        do {
            let state = try await api.testActions(invoiceID: invoice.id)
            guard generation == store.generation, actionReadID == request, !Task.isCancelled else { return }
            guard state.environment == "TEST", state.transmissionMode == "simulator" else {
                actions = nil; message = "Este ambiente no admite acciones del simulador."; review = nil
                return
            }
            let scope = try recoveryScope()
            let journal = store.testDeliveryJournal
            let previous = try journal.pending(invoiceID: invoice.id, scope: scope)
            if previous == .email, state.emailReceipt != nil || receipt != nil {
                try journal.finish(.email, invoiceID: invoice.id, scope: scope)
            } else if previous == .issue, ["AUTHORIZED", "REJECTED", "NOT_AUTHORIZED", "VOIDED"].contains((currentInvoice ?? invoice).status) {
                try journal.finish(.issue, invoiceID: invoice.id, scope: scope)
            }
            pending = try journal.pending(invoiceID: invoice.id, scope: scope)
            canRetry = false
            if let currentInvoice, let pending, pending.serverAllowsRetry(status: currentInvoice.status, actions: state) {
                let recipient = pending == .email ? state.captureRecipient : nil
                canRetry = (try? journal.retryKey(pending, invoiceID: invoice.id, scope: scope, recipient: recipient)) != nil
            }
            actions = state
            receipt = state.emailReceipt ?? receipt
            message = nil
        } catch {
            guard generation == store.generation, actionReadID == request, !Task.isCancelled else { return }
            actions = nil; review = nil
            message = friendlyError(error)
        }
    }

    private func refresh() async {
        let generation = store.generation
        let updated = await reloadDocument()
        guard generation == store.generation, !Task.isCancelled else { return }
        await fetchActions(currentInvoice: updated)
    }

    private func prepareEmail(retrying: Bool) async {
        guard !busy, (retrying ? pending == .email && canRetry : pending == nil), let api = store.service as? any ERPTestInvoiceService else { return }
        let generation = store.generation
        busy = true
        defer { if generation == store.generation { busy = false } }
        do {
            let preview = try await api.testEmailPreview(invoiceID: invoice.id)
            guard generation == store.generation, !Task.isCancelled else { return }
            guard preview.recipient == actions?.captureRecipient, !preview.recipient.isEmpty,
                  preview.attachmentNames.count == 2,
                  Set(preview.attachmentNames.map { URL(fileURLWithPath: $0).pathExtension.lowercased() }) == ["pdf", "xml"] else {
                throw ERPClientError.invalidResponse
            }
            message = nil
            review = .email(preview, retrying: retrying)
        } catch {
            if generation == store.generation { message = friendlyError(error) }
        }
    }

    private func submit(_ step: InvoiceTestReview) async {
        guard !busy, (step.retrying ? pending == step.id && canRetry : pending == nil),
              let service = store.service, let api = service as? any ERPTestInvoiceService,
              let actions, actions.environment == "TEST", actions.transmissionMode == "simulator" else { return }
        let generation = store.generation
        busy = true
        actionReadID = UUID()
        review = nil
        defer { if generation == store.generation { busy = false } }
        do {
            let scope = try recoveryScope()
            let key: String
            if step.retrying {
                // A status lookup is necessary again at confirmation time. An
                // earlier timeout might already have completed while the sheet was open.
                let current = try await service.invoice(id: invoice.id)
                guard generation == store.generation, !Task.isCancelled else { return }
                let state = try await api.testActions(invoiceID: invoice.id)
                guard generation == store.generation, !Task.isCancelled else { return }
                guard step.id.serverAllowsRetry(status: current.status, actions: state),
                      step.recipient == nil || step.recipient == state.captureRecipient else {
                    await refresh()
                    return
                }
                key = try store.testDeliveryJournal.retryKey(step.id, invoiceID: invoice.id, scope: recoveryScope(), recipient: step.recipient)
            } else {
                guard step.id.serverAllowsRetry(status: invoice.status, actions: actions),
                      step.recipient == nil || (hasAttachments && step.recipient == actions.captureRecipient) else { return }
                key = try store.testDeliveryJournal.begin(step.id, invoiceID: invoice.id, scope: scope, recipient: step.recipient)
            }
            pending = step.id
            canRetry = false
            switch step {
            case .issue:
                _ = try await api.issueTestInvoice(invoiceID: invoice.id, idempotencyKey: key)
            case .email(let preview, _):
                let result = try await api.sendTestEmail(invoiceID: invoice.id, recipient: preview.recipient, idempotencyKey: key)
                guard generation == store.generation else { return }
                receipt = result
                try store.testDeliveryJournal.finish(.email, invoiceID: invoice.id, scope: scope)
                pending = nil
            }
            guard generation == store.generation, !Task.isCancelled else { return }
            await refresh()
        } catch {
            guard generation == store.generation else { return }
            // A server rejection before an effect allows the user to correct
            // the draft. Network failures/unknown results remain read-only.
            if !step.retrying, let known = error as? ERPClientError {
                switch known {
                case .forbidden, .notFound, .invalidInput:
                    do {
                        try store.testDeliveryJournal.finish(step.id, invoiceID: invoice.id, scope: recoveryScope())
                        pending = nil
                    } catch { message = friendlyError(error); return }
                default: break
                }
            }
            message = friendlyError(error)
        }
    }
}

private struct InvoiceTestReviewSheet: View {
    let step: InvoiceTestReview
    let company: String
    let number: String
    let total: String
    let confirm: () async -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var submitting = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ERPDetailRow(title: "Empresa", value: company)
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("test-delivery-company")
                    ERPDetailRow(title: "Factura", value: number)
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("test-delivery-number")
                    ERPDetailRow(title: "Total", value: total)
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("test-delivery-total")
                    ERPDetailRow(title: "Ambiente", value: "Simulador SRI")
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("test-delivery-environment")
                }
                if case let .email(preview, _) = step {
                    Section {
                        ERPDetailRow(title: "Para", value: preview.recipient)
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("test-delivery-recipient")
                        ERPDetailRow(title: "Asunto", value: preview.subject)
                        Text(verbatim: preview.message)
                    } header: { Text("Correo de prueba") }
                    Section {
                        ForEach(preview.attachmentNames, id: \.self) { name in
                            Label { Text(verbatim: name) } icon: { Image(systemName: "paperclip").accessibilityHidden(true) }
                                .accessibilityElement(children: .combine)
                                .accessibilityLabel(Text(verbatim: name))
                                .accessibilityIdentifier("test-delivery-attachment-\(URL(fileURLWithPath: name).pathExtension.lowercased())")
                        }
                    } header: { Text("Adjuntos") }
                }
                Section {
                    Text(step.id == .issue ? "El simulador comprobará esta factura de prueba." : "El mensaje se entregará sólo al buzón de pruebas.")
                        .font(.subheadline)
                    if step.retrying {
                        Text("Se comprobará el estado y se usará la misma solicitud pendiente.")
                            .font(.subheadline)
                    }
                    Button {
                        guard !submitting else { return }
                        submitting = true
                        Task { await confirm() }
                    } label: {
                        Text(step.id == .issue ? "Confirmar emisión de prueba" : "Enviar al buzón de pruebas")
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .frame(minHeight: 44)
                    .disabled(submitting)
                    .accessibilityIdentifier(step.id == .issue ? "test-confirm-issue" : "test-confirm-email")
                    Button("Cancelar", role: .cancel) { dismiss() }
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("test-cancel-delivery")
                }
            }
            .foregroundStyle(.primary)
            .navigationTitle(step.id == .issue ? "Revisar emisión" : "Revisar correo")
            .toolbarTitleDisplayMode(.inline)
        }
    }
}
