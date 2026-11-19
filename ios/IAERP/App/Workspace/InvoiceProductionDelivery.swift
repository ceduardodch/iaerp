import IAERPClient
import SwiftUI

enum ProductionDeliveryStep: Equatable {
    case issue, email, receipt, waitingForSRI, waitingForEmail, needsReconciliation
    case unavailable(String)

    static func resolve(environment: String, document: String, email: String, hasReceipt: Bool,
                        pending: InvoiceTestAction?, canIssue: Bool, canEmail: Bool) -> Self {
        guard environment == "PRODUCTION" else {
            return .unavailable(environment == "TEST" ? "Esta empresa usa el ambiente de pruebas del SRI." :
                "Pide a quien administra la empresa que configure el ambiente de producción del SRI.")
        }
        if hasReceipt { return .receipt }
        if email == "PENDING" || email == "SENT" { return .waitingForEmail }
        guard email == "NOT_SENT" else { return .unavailable("Actualiza el estado para comprobar el envío.") }
        switch document {
        case "DRAFT":
            guard pending != .email else { return .waitingForEmail }
            return canIssue ? .issue : .unavailable("Pide permiso de emisión a quien administra tu empresa.")
        case "AUTHORIZED":
            return canEmail ? .email : .unavailable("Pide permiso de envío de facturas a quien administra tu empresa.")
        case "READY", "SIGNED", "RECEIVED", "PENDING_AUTHORIZATION": return .waitingForSRI
        case "REJECTED", "NOT_AUTHORIZED", "FAILED":
            return .unavailable("Revisa el motivo en Transmisión SRI antes de corregir la factura.")
        case "HISTORICAL_ISSUED", "VOIDED":
            return .unavailable("El envío de documentos requiere una factura con autorización vigente del SRI.")
        default: return .unavailable("Consulta el estado para comprobar la autorización del SRI.")
        }
    }
}

private struct ProductionDeliveryReview: Identifiable {
    let id = UUID()
    let generation: UUID
    let document: ERPInvoice
    let company: String
    let customer: String
    let number: String
    let preview: ERPInvoiceEmailPreview?

    var action: InvoiceTestAction { preview == nil ? .issue : .email }
}

struct InvoiceProductionDeliverySection: View {
    let store: WorkspaceStore
    let invoice: ERPInvoice
    let number: String
    let customer: String?
    let reloadDocument: () async -> ERPInvoice?

    @Environment(\.scenePhase) private var scenePhase
    @State private var state: ERPInvoiceDeliveryStatus?
    @State private var pending: InvoiceTestAction?
    @State private var needsReconciliation = false
    @State private var review: ProductionDeliveryReview?
    @State private var message: String?
    @State private var busy = false
    @AccessibilityFocusState private var feedbackFocused: Bool

    private var service: (any ERPProductionInvoiceService)? { store.service as? any ERPProductionInvoiceService }
    private func step(_ status: ERPInvoiceDeliveryStatus, _ document: ERPInvoice) -> ProductionDeliveryStep {
        if needsReconciliation { return .needsReconciliation }
        return .resolve(environment: status.fiscalEnvironment, document: document.status, email: status.emailStatus,
                 hasReceipt: status.receipt != nil, pending: pending,
                 canIssue: store.context?.permits("invoices:issue") == true,
                 canEmail: store.context?.permits("invoices:email") == true)
    }

    private var shouldPoll: Bool {
        guard let state, state.fiscalEnvironment == "PRODUCTION", scenePhase == .active, review == nil else { return false }
        let next = step(state, invoice)
        return pending != nil || next == .waitingForSRI || next == .waitingForEmail
    }

    var body: some View {
        Section {
            VStack(alignment: .leading, spacing: 10) {
                if let state {
                    switch step(state, invoice) {
                    case .issue, .email:
                        if let customer, !customer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            if pending != nil {
                                Text("Hay una solicitud sin confirmar. Al continuar se comprobará su estado y se usará la misma solicitud.")
                            }
                            let isIssue = step(state, invoice) == .issue
                            Button(isIssue ? "Revisar emisión" : "Preparar correo", systemImage: isIssue ? "doc.badge.arrow.up" : "envelope") {
                                Task { await prepare() }
                            }
                            .frame(minHeight: 44)
                            .accessibilityIdentifier(isIssue ? "real-review-issue" : "real-review-email")
                        } else {
                            Text("Falta el nombre del cliente. Abre la factura desde Clientes para comprobar a quién corresponde.")
                        }
                    case .receipt:
                        if let receipt = state.receipt {
                            VStack(alignment: .leading, spacing: 6) {
                                Label("Correo aceptado para envío", systemImage: "checkmark.circle").font(.headline)
                                Text(verbatim: receipt.recipient)
                                ForEach(receipt.attachmentNames, id: \.self) { Text(verbatim: $0) }
                                Text("Referencia: \(receipt.messageId)").font(.footnote).textSelection(.enabled)
                            }
                            .accessibilityElement(children: .combine)
                            .accessibilityIdentifier("real-email-receipt")
                        }
                    case .needsReconciliation:
                        Text("IAERP necesita comprobar la solicitud anterior. Consulta el estado. Si sigue pendiente, pide a quien administra tu empresa que revise esta factura.")
                    case .waitingForSRI:
                        Text("Emisión en curso. El correo estará disponible cuando el SRI autorice la factura.")
                    case .waitingForEmail:
                        Text("Hay un envío en curso. Consulta el estado para ver el comprobante del correo.")
                    case .unavailable(let reason):
                        Text(verbatim: reason)
                    }
                }
                if let message {
                    Text(verbatim: message)
                        .accessibilityIdentifier("real-delivery-feedback")
                        .accessibilityFocused($feedbackFocused)
                        .task(id: message) { feedbackFocused = true }
                }
                if busy || state == nil && message == nil { ProgressView("Consultando…") }
                if !busy, message != nil || shouldPoll || state == nil {
                    Button("Consultar estado", systemImage: "arrow.clockwise") { Task { await refresh() } }
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("real-delivery-refresh")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .buttonStyle(.borderless)
            .sheet(item: $review) { step in
                ProductionInvoiceReviewSheet(review: step) { await submit(step) }
            }
        } header: {
            Text("Emisión y correo")
        }
        .disabled(busy)
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            await refresh(reload: false)
        }
        .task(id: shouldPoll) {
            guard shouldPoll else { return }
            for seconds in [2, 3, 5, 8, 13] {
                do { try await Task.sleep(for: .seconds(seconds)) } catch { return }
                guard !Task.isCancelled else { return }
                if !busy, review == nil { await refresh() }
            }
        }
    }

    private func readState(service: any ERPProductionInvoiceService, document: ERPInvoice,
                           generation: UUID) async throws -> ERPInvoiceDeliveryStatus {
        let result = try await service.deliveryStatus(invoiceID: document.id)
        try checkSession(generation)
        let scope = try store.currentProductionDeliveryScope()
        let journal = store.productionDeliveryJournal
        let previous = try journal.pending(invoiceID: document.id, scope: scope)
        if previous == .email, result.receipt != nil {
            try journal.finish(.email, invoiceID: document.id, scope: scope)
        } else if previous == .issue, ["AUTHORIZED", "REJECTED", "NOT_AUTHORIZED", "VOIDED", "FAILED"].contains(document.status) {
            try journal.finish(.issue, invoiceID: document.id, scope: scope)
        }
        pending = try journal.pending(invoiceID: document.id, scope: scope)
        needsReconciliation = try journal.needsReconciliation(invoiceID: document.id, scope: scope)
        state = result
        return result
    }

    private func checkSession(_ generation: UUID) throws {
        guard generation == store.generation, !Task.isCancelled, !store.isDemo, scenePhase == .active else {
            throw CancellationError()
        }
    }

    private func refresh(reload: Bool = true) async {
        guard !busy, let service else { return }
        let generation = store.generation
        busy = true
        defer { if generation == store.generation { busy = false } }
        do {
            var current = invoice
            if reload {
                guard let updated = await reloadDocument() else { throw ERPClientError.invalidInput("No se pudo actualizar la factura. Consulta el estado de nuevo.") }
                current = updated
            }
            try checkSession(generation)
            _ = try await readState(service: service, document: current, generation: generation)
            if pending == nil { message = nil }
        } catch {
            guard generation == store.generation, !Task.isCancelled else { return }
            state = nil
            message = friendlyError(error)
        }
    }

    private func prepare() async {
        guard !busy, review == nil, let service, let customer, let company = store.context?.name else { return }
        let generation = store.generation
        busy = true
        defer { if generation == store.generation { busy = false } }
        do {
            guard let current = await reloadDocument(), current.partyId == invoice.partyId else {
                throw ERPClientError.invalidInput("Actualiza la ficha para comprobar el cliente y el total.")
            }
            try checkSession(generation)
            let status = try await readState(service: service, document: current, generation: generation)
            let preview: ERPInvoiceEmailPreview?
            switch step(status, current) {
            case .issue: preview = nil
            case .email:
                let value = try await service.invoiceEmailPreview(invoiceID: current.id)
                try checkSession(generation)
                guard let recipient = value.recipient, !recipient.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                    throw ERPClientError.invalidInput("Falta el correo del cliente. Pide a quien administra el catálogo que lo registre y vuelve a preparar el envío.")
                }
                let extensions = Set(value.attachmentNames.map { URL(fileURLWithPath: $0).pathExtension.lowercased() })
                guard extensions.isSuperset(of: ["pdf", "xml"]) else {
                    throw ERPClientError.invalidInput("Falta el RIDE o el XML autorizado. Consulta el estado de los documentos y vuelve a preparar el correo.")
                }
                preview = value
            default: return
            }
            review = ProductionDeliveryReview(generation: generation, document: current, company: company,
                                              customer: customer, number: number, preview: preview)
            message = nil
        } catch {
            if generation == store.generation, !Task.isCancelled { message = friendlyError(error) }
        }
    }

    private func submit(_ confirmed: ProductionDeliveryReview) async {
        guard !busy, review?.id == confirmed.id, let service else { return }
        let generation = confirmed.generation
        let id = confirmed.document.id
        review = nil
        busy = true
        defer { if generation == store.generation { busy = false } }
        do {
            try checkSession(generation)
            guard let current = await reloadDocument(), current == confirmed.document,
                  confirmed.company == store.context?.name, confirmed.customer == customer, confirmed.number == number else {
                throw ERPClientError.invalidInput("Los datos de la factura cambiaron o no se pudieron comprobar. Revisa la ficha de nuevo.")
            }
            try checkSession(generation)
            let status = try await readState(service: service, document: current, generation: generation)
            let action = confirmed.action
            guard step(status, current) == (action == .issue ? .issue : .email),
                  pending == nil || pending == action else { return }
            let scope = try store.currentProductionDeliveryScope()
            // Bind a retried email to the exact message and recipient approved on screen.
            let binding = confirmed.preview?.previewDigest
            let journal = store.productionDeliveryJournal
            let key = try pending == nil
                ? journal.begin(action, invoiceID: id, scope: scope, recipient: binding)
                : journal.retryKey(action, invoiceID: id, scope: scope, recipient: binding)
            pending = action
            if let preview = confirmed.preview, let recipient = preview.recipient {
                _ = try await service.sendInvoiceEmail(invoiceID: id, recipient: recipient, preview: preview, idempotencyKey: key)
            } else {
                _ = try await service.issueInvoice(invoiceID: id, idempotencyKey: key)
            }
            try checkSession(generation)
            if let current = await reloadDocument() {
                try checkSession(generation)
                _ = try await readState(service: service, document: current, generation: generation)
            }
            message = nil
        } catch {
            guard generation == store.generation, !Task.isCancelled else { return }
            if (error as? InvoiceRecoveryError) == .reconciliationRequired, pending == confirmed.action {
                needsReconciliation = true
                do {
                    let scope = try store.currentProductionDeliveryScope()
                    try store.productionDeliveryJournal.markForReconciliation(confirmed.action, invoiceID: id, scope: scope)
                    message = "Los datos cambiaron mientras se confirmaba el envío anterior. Consulta el estado antes de continuar."
                } catch { message = friendlyError(error) }
                return
            }
            if let known = error as? ERPClientError, pending == confirmed.action {
                do {
                    let scope = try store.currentProductionDeliveryScope()
                    switch known {
                    case .invoiceEmailPreviewChanged where confirmed.action == .email,
                         .invoiceEmailRejected where confirmed.action == .email,
                         .invoiceEmailPreparationFailed where confirmed.action == .email:
                        try store.productionDeliveryJournal.finish(.email, invoiceID: id, scope: scope)
                        pending = nil
                    case .invoiceDeliveryConflict, .invoiceEmailDeliveryPending:
                        needsReconciliation = true
                        try store.productionDeliveryJournal.markForReconciliation(confirmed.action, invoiceID: id, scope: scope)
                    default: break
                    }
                } catch { message = friendlyError(error); return }
            }
            message = friendlyError(error)
        }
    }
}

private struct ProductionInvoiceReviewSheet: View {
    let review: ProductionDeliveryReview
    let confirm: () async -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var submitting = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    detail("Empresa", review.company, "company")
                    detail("Cliente", review.customer, "customer")
                    detail(review.action == .issue ? "Borrador" : "Factura", review.number, "number")
                    detail("Total", ERPDisplay.money(review.document.total, currency: review.document.currency), "total")
                } header: { Text("Datos de la factura") }
                if let preview = review.preview {
                    Section {
                        detail("Para", preview.recipient ?? "", "recipient")
                        if let sender = preview.senderAddress { detail("De", sender, "sender") }
                        detail("Asunto", preview.subject, "subject")
                        Text(verbatim: preview.message)
                    } header: { Text("Correo al cliente") }
                    Section {
                        ForEach(preview.attachmentNames, id: \.self) { name in
                            Label { Text(verbatim: name) } icon: { Image(systemName: "paperclip") }
                                .accessibilityElement(children: .combine)
                                .accessibilityLabel(Text(verbatim: name))
                                .accessibilityIdentifier("real-attachment-\(name)")
                        }
                    } header: { Text("Adjuntos") }
                }
                Section {
                    if review.action == .issue {
                        Text("La empresa enviará esta factura al SRI de producción para su autorización.")
                    }
                    Button {
                        guard !submitting else { return }
                        submitting = true
                        Task { await confirm() }
                    } label: {
                        Text(review.action == .issue ? "Emitir factura al SRI" : "Enviar correo al cliente")
                            .frame(maxWidth: .infinity, minHeight: 44)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(submitting)
                    .accessibilityIdentifier(review.action == .issue ? "real-confirm-issue" : "real-confirm-email")
                }
            }
            .navigationTitle(review.action == .issue ? "Revisar emisión" : "Revisar correo")
            .toolbarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancelar") { dismiss() }.accessibilityIdentifier("real-cancel-review")
                }
            }
        }
    }

    private func detail(_ title: LocalizedStringKey, _ value: String, _ identifier: String) -> some View {
        ERPDetailRow(title: title, value: value)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("real-delivery-\(identifier)")
    }
}
