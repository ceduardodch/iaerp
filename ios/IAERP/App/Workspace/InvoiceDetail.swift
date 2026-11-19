import IAERPClient
import PDFKit
import SwiftUI

struct DocumentPresentation: Identifiable {
    let id = UUID()
    let document: ERPDocument
    let url: URL
}

struct InvoicePaymentRow: Identifiable {
    let id = UUID()
    let installment: ERPInstallment
}

struct WorkspaceInvoiceDetail: View {
    let store: WorkspaceStore
    let invoiceId: UUID
    var listedNumber: String? = nil
    var listedCustomerName: String? = nil
    @State private var invoice: ERPInvoice?
    @State private var artifacts: [ERPArtifact] = []
    @State private var error: String?
    @State private var documentError: String?
    @State private var loading = false
    @State private var downloading = false
    @State private var paymentSchedule: [InvoicePaymentRow] = []
    @State private var presentation: DocumentPresentation?

    private var showsTestActions: Bool {
        store.context?.permits("invoices:test-issue") == true || store.context?.permits("invoices:test-email") == true
    }

    private var showsProductionActions: Bool {
        !store.isDemo && !showsTestActions && store.service is any ERPProductionInvoiceService &&
        (store.context?.permits("invoices:issue") == true || store.context?.permits("invoices:email") == true)
    }

    var body: some View {
        List {
            if loading { ProgressView("Cargando factura…") }
            if let error { Section { ERPErrorState(message: error) { _ = await load() } } }
            if let invoice {
                Section {
                    summaryRow("Número", listedNumber ?? store.invoiceNumber(invoice))
                    summaryRow("Cliente", listedCustomerName ?? store.customerName(invoice.partyId))
                    summaryRow("Fecha", invoice.issueDate)
                    summaryRow("Total", ERPDisplay.money(invoice.total, currency: invoice.currency))
                }
                Section {
                    ERPDetailRow(title: "Documento", value: ERPDisplay.status(invoice.status))
                    if let transmission = invoice.sriTransmission {
                        ERPDetailRow(title: "Transmisión SRI", value: ERPDisplay.status(transmission.status))
                        if let message = transmission.message { Text(message).foregroundStyle(Color.primary) }
                    }
                    if let number = invoice.authorizationNumber {
                        ERPDetailRow(title: "Autorización", value: number)
                    }
                    if let status = invoice.collectionStatus { ERPDetailRow(title: "Cobro", value: ERPDisplay.status(status)) }
                    if invoice.status == "DRAFT" { Text("Borrador guardado. No se ha emitido al SRI.").foregroundStyle(Color.primary) }
                    if let guidance = statusGuidance(for: invoice.status) {
                        Text(guidance)
                            .foregroundStyle(Color.primary)
                            .accessibilityIdentifier("invoice-status-guidance")
                    }
                    if invoice.status == "HISTORICAL_ISSUED" { Text("Documento histórico. No equivale a una autorización SRI verificada por esta app.").foregroundStyle(Color.primary) }
                } header: { Text("Estado").foregroundStyle(Color.primary) }
                if showsTestActions {
                    InvoiceTestDeliverySection(store: store, invoice: invoice,
                                               number: listedNumber ?? store.invoiceNumber(invoice),
                                               artifacts: artifacts, reloadDocument: { await load(showProgress: false) })
                        .id(invoice.id)
                } else if showsProductionActions, invoice.type == "INVOICE" {
                    InvoiceProductionDeliverySection(store: store, invoice: invoice,
                        number: listedNumber ?? store.invoiceNumber(invoice),
                        customer: listedCustomerName ?? store.customer(invoice.partyId)?.name,
                        reloadDocument: { await load(showProgress: false) })
                        .id(invoice.id)
                }
                ForEach(invoice.lines) { line in
                    Section {
                        Text(line.description).font(.headline)
                        ERPDetailRow(title: "Cantidad", value: ERPDisplay.decimal(line.quantity))
                        ERPDetailRow(title: "Precio", value: ERPDisplay.money(line.unitPrice, currency: invoice.currency))
                        ERPDetailRow(title: "Descuento", value: ERPDisplay.money(line.discount, currency: invoice.currency))
                    } header: { Text("Detalle").foregroundStyle(Color.primary) }
                }
                Section {
                    ERPDetailRow(title: "Subtotal", value: ERPDisplay.money(invoice.subtotal, currency: invoice.currency))
                    ERPDetailRow(title: "IVA", value: ERPDisplay.money(invoice.tax, currency: invoice.currency))
                    ERPDetailRow(title: "Total", value: ERPDisplay.money(invoice.total, currency: invoice.currency))
                } header: { Text("Importes").foregroundStyle(Color.primary) }
                if !invoice.installments.isEmpty {
                    Section {
                        ForEach(paymentSchedule) { row in
                            ERPDetailRow(title: "Vencimiento", value: row.installment.dueDate)
                            ERPDetailRow(title: "Cuota", value: ERPDisplay.money(row.installment.amount, currency: invoice.currency))
                        }
                    } header: { Text("Plan de pago").foregroundStyle(Color.primary) }
                }
                Section {
                    if let documentError {
                        ERPErrorState(message: documentError) { await loadArtifacts() }
                    } else if artifacts.isEmpty {
                        Text(invoice.status == "DRAFT" ? "Los archivos estarán disponibles aquí cuando se generen durante la emisión." : "Todavía no hay archivos disponibles. Desliza hacia abajo para actualizar la ficha.")
                            .foregroundStyle(Color.primary)
                    }
                    ForEach(artifacts) { artifact in
                        Button {
                            Task { await open(artifact) }
                        } label: {
                            Label(artifact.artifactType == "ride-pdf" ? "Ver RIDE" : "Ver XML", systemImage: artifact.artifactType == "ride-pdf" ? "doc.richtext" : "chevron.left.forwardslash.chevron.right")
                        }
                        .frame(minHeight: 44)
                        .disabled(downloading)
                        .accessibilityIdentifier("open-\(artifact.artifactType)")
                    }
                    if downloading { ProgressView("Descargando documento…") }
                } header: { Text("Documentos").foregroundStyle(Color.primary) }
            }
        }
        .listSectionSpacing(.compact)
        .clipped()
        .padding(.bottom, 1)
        .scrollEdgeEffectStyle(.hard, for: .all)
        .scrollEdgeEffectHidden(for: .all)
        .navigationTitle("Factura")
        .navigationSubtitle(Text(verbatim: store.displayCompany))
        .toolbarTitleDisplayMode(.inline)
        .toolbarBackground(Color(uiColor: .systemBackground), for: .navigationBar)
        .toolbarBackgroundVisibility(.visible, for: .navigationBar)
        .toolbarVisibility(listedNumber == nil ? .hidden : .visible, for: .tabBar)
        .toolbarBackground(Color(uiColor: .systemBackground), for: .tabBar)
        .toolbarBackground(.visible, for: .tabBar)
        .task { _ = await load() }
        .refreshable { _ = await load() }
        .sheet(item: $presentation) { DocumentViewer(presentation: $0) }
    }

    func statusGuidance(for status: String) -> String? {
        guard !showsTestActions, !showsProductionActions else { return nil }
        if store.isDemo {
            return ["DRAFT", "AUTHORIZED"].contains(status) ? "Esta cuenta de prueba sólo permite consultar la factura." : nil
        }
        switch status {
        case "DRAFT":
            return "Para emitir este borrador, pide permiso de emisión a quien administra tu empresa y vuelve a iniciar sesión."
        case "READY", "SIGNED", "RECEIVED", "PENDING_AUTHORIZATION":
            return "Desliza hacia abajo para consultar el estado de esta emisión y comprobar si el SRI ya respondió."
        case "AUTHORIZED":
            return "Para enviar el RIDE y el XML, pide permiso de envío de facturas a quien administra tu empresa y vuelve a iniciar sesión."
        case "REJECTED", "NOT_AUTHORIZED", "FAILED":
            return "Revisa el mensaje de transmisión para corregir el problema antes de emitir."
        default:
            return nil
        }
    }

    private func summaryRow(_ title: String, _ value: String) -> some View {
        let label = Text(verbatim: title).fontWeight(.semibold)
        return Text("\(label) · \(value)")
            .foregroundStyle(Color.primary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
    }

    @discardableResult
    private func load(showProgress: Bool = true) async -> ERPInvoice? {
        guard let service = store.service else { return nil }
        let epoch = store.generation
        if showProgress { loading = true }
        defer { if epoch == store.generation { loading = false } }
        error = nil
        do {
            let value = try await service.invoice(id: invoiceId)
            guard epoch == store.generation, !Task.isCancelled else { return nil }
            let previous = invoice?.status
            invoice = value
            paymentSchedule = value.installments.map { InvoicePaymentRow(installment: $0) }
            await loadArtifacts()
            await store.acceptInvoiceStatus(value, previousStatus: previous, generation: epoch)
            return value
        } catch {
            if epoch == store.generation && !Task.isCancelled { self.error = friendlyError(error) }
            return nil
        }
    }
    private func loadArtifacts() async {
        guard let service = store.service else { return }
        let epoch = store.generation
        documentError = nil
        do {
            let result = try await service.artifacts(invoiceID: invoiceId)
            guard epoch == store.generation, !Task.isCancelled else { return }
            artifacts = result.filter { ["ride-pdf", "xml-signed"].contains($0.artifactType) }
        } catch {
            if epoch == store.generation && !Task.isCancelled { artifacts = []; documentError = friendlyError(error) }
        }
    }
    private func open(_ artifact: ERPArtifact) async {
        guard let service = store.service, !downloading else { return }
        let epoch = store.generation
        downloading = true; documentError = nil
        defer { if epoch == store.generation { downloading = false } }
        do {
            let data = try await service.document(invoiceID: invoiceId, artifact: artifact)
            guard epoch == store.generation, !Task.isCancelled else { return }
            let url = try await store.documents.store(data: data.data, fileName: data.fileName, generation: epoch)
            guard epoch == store.generation, !Task.isCancelled else { return }
            presentation = DocumentPresentation(document: data, url: url)
        } catch {
            if epoch == store.generation && !Task.isCancelled { documentError = friendlyError(error) }
        }
    }
}

struct DocumentViewer: View {
    let presentation: DocumentPresentation
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            Group {
                if presentation.document.mimeType == "application/pdf" {
                    NativePDFView(data: presentation.document.data)
                } else {
                    ScrollView {
                        Text(String(data: presentation.document.data, encoding: .utf8) ?? "No se pudo mostrar el XML.")
                            .font(.body.monospaced())
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding()
                            .accessibilityIdentifier("xml-document")
                    }
                }
            }
            .scrollEdgeEffectStyle(.hard, for: .all)
        .navigationTitle(presentation.document.mimeType == "application/pdf" ? "RIDE" : "XML")
            .toolbarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { ERPCloseButton() }
                ToolbarItem(placement: .primaryAction) {
                    ShareLink(item: presentation.url) { Label("Compartir", systemImage: "square.and.arrow.up") }
                }
            }
        }
    }
}

struct NativePDFView: UIViewRepresentable {
    let data: Data
    func makeUIView(context: Context) -> PDFView {
        let view = PDFView()
        view.autoScales = true
        view.displayMode = .singlePageContinuous
        view.document = PDFDocument(data: data)
        view.accessibilityIdentifier = "ride-document"
        return view
    }
    func updateUIView(_ uiView: PDFView, context: Context) { }
}
