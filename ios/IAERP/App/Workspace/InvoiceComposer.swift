import Foundation
import IAERPClient
import Observation
import OSLog
import SwiftUI

struct DraftLine: Identifiable, Equatable {
    let id = UUID()
    let productId: UUID
    var description: String
    var quantity = "1"
    var unitPrice: String
    var discount = "0"
    var taxCode: String

    func input() throws -> ERPInvoiceLineInput {
        guard let quantity = DecimalEntry.parse(quantity, positive: true),
              let price = DecimalEntry.parse(unitPrice),
              let discount = DecimalEntry.parse(discount, scale: 2),
              !description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw ERPClientError.invalidInput("Revisa descripción, cantidad, precio y descuento. Usa hasta 6 decimales en cantidad y precio, y 2 en descuento.")
        }
        return ERPInvoiceLineInput(productId: productId, description: description,
                                   quantity: quantity, unitPrice: price, discount: discount, taxCode: taxCode)
    }
}

@MainActor @Observable
final class InvoiceComposer {
    var customerId: UUID?
    var establishmentId: UUID?
    var emissionPointId: UUID?
    var issueDate = Date()
    var paymentTermsDays = 0
    var lines: [DraftLine] = []
    var preview: ERPInvoicePreview?
    var error: String?
    var working = false
    private(set) var pendingInput: ERPInvoiceInput?
    private(set) var pendingKey: String?
    private(set) var previewInput: ERPPreviewInput?
    private(set) var saved: ERPInvoice?
    private(set) var hasUncertainResult = false
    private var requestID = UUID()

    init(customerId: UUID? = nil) { self.customerId = customerId }
    var dueDateString: String? { ERPDisplay.fiscalDueDate(issueDate, days: paymentTermsDays) }
    func configurePaymentTerms(customer: ERPParty?, context: ERPContext?) {
        guard canEdit else { return }
        paymentTermsDays = customer?.paymentTermsDays ?? context?.defaultPaymentTermsDays ?? 0
    }
    var canEdit: Bool { !working && pendingInput == nil }
    var fingerprint: String {
        "\(customerId?.uuidString ?? "")|\(establishmentId?.uuidString ?? "")|\(emissionPointId?.uuidString ?? "")|\(ERPDisplay.fiscalDate(issueDate))|\(paymentTermsDays)|" +
        lines.map { "\($0.id)|\($0.description)|\($0.quantity)|\($0.unitPrice)|\($0.discount)|\($0.taxCode)" }.joined(separator: "|")
    }
    func invalidatePreview() {
        guard pendingInput == nil else { return }
        requestID = UUID()
        preview = nil; previewInput = nil; error = nil
    }
    func add(_ product: ERPProduct, setup: ERPInvoiceSetup?) {
        guard canEdit else { return }
        let date = ERPDisplay.fiscalDate(issueDate)
        guard let tax = setup?.taxCategories.first(where: { $0.id == product.taxCategoryId && $0.isValid(on: date) }) else {
            error = "Este producto no tiene una tarifa vigente para la fecha elegida."
            return
        }
        lines.append(DraftLine(productId: product.id, description: product.name,
                               unitPrice: ERPDisplay.decimal(product.unitPrice), taxCode: tax.sriCode))
        invalidatePreview()
    }
    func buildInput(setup: ERPInvoiceSetup?, total: Decimal? = nil) throws -> ERPInvoiceInput {
        guard let customerId, let establishmentId, let emissionPointId, let setup,
              setup.establishments.contains(where: { $0.id == establishmentId && $0.active }),
              setup.emissionPoints.contains(where: { $0.id == emissionPointId && $0.establishmentId == establishmentId && $0.active }),
              !lines.isEmpty else {
            throw ERPClientError.invalidInput("Elige cliente, establecimiento, punto de emisión y al menos un producto.")
        }
        let date = ERPDisplay.fiscalDate(issueDate)
        guard (0...365).contains(paymentTermsDays), let dueDateString else {
            throw ERPClientError.invalidInput("Revisa el plazo de pago: debe estar entre 0 y 365 días.")
        }
        for line in lines {
            guard setup.taxCategories.contains(where: { $0.sriCode == line.taxCode && $0.isValid(on: date) }) else {
                throw ERPClientError.invalidInput("Hay una tarifa sin vigencia para la fecha elegida.")
            }
        }
        let installments = total.map { $0 > 0 ? [ERPInstallment(dueDate: dueDateString, amount: $0)] : [] } ?? []
        return try ERPInvoiceInput(customerId: customerId, establishmentId: establishmentId, emissionPointId: emissionPointId,
                                   issueDate: date, lines: lines.map { try $0.input() }, installments: installments)
    }
    func review(using service: any ERPService, setup: ERPInvoiceSetup?) async {
        guard canEdit else { return }
        working = true; error = nil
        let request = UUID(); requestID = request
        let snapshot = fingerprint
        defer { working = false }
        do {
            let input = try buildInput(setup: setup)
            let previewRequest = ERPPreviewInput(issueDate: input.issueDate, lines: input.lines)
            let result = try await service.preview(previewRequest)
            guard requestID == request, fingerprint == snapshot, !Task.isCancelled else { return }
            preview = result; previewInput = previewRequest
        } catch {
            guard requestID == request else { return }
            self.error = friendlyError(error)
        }
    }
    func save(using service: any ERPService, setup: ERPInvoiceSetup?,
              recoveryJournal: InvoiceRecoveryJournal? = nil, recoveryScope: InvoiceRecoveryScope? = nil,
              authorizeRecoveryScope: InvoiceRecoveryJournal.Authorize? = nil) async -> ERPInvoice? {
        guard !working, saved == nil else { return nil }
        working = true; error = nil
        let alreadyUncertain = hasUncertainResult
        defer { working = false }
        do {
            if service is LiveERPService, recoveryJournal == nil {
                throw InvoiceRecoveryError.storageFailure
            }
            let input: ERPInvoiceInput
            let key: String
            if let pendingInput, let pendingKey {
                input = pendingInput; key = pendingKey
            } else {
                guard let preview else { throw ERPClientError.invalidInput("Revisa los importes antes de guardar.") }
                input = try buildInput(setup: setup, total: preview.total)
                guard previewInput == ERPPreviewInput(issueDate: input.issueDate, lines: input.lines) else {
                    throw ERPClientError.invalidInput("Revisa los importes antes de guardar.")
                }
                if let recoveryJournal {
                    guard let recoveryScope, let authorizeRecoveryScope,
                          try authorizeRecoveryScope() == recoveryScope else { throw InvoiceRecoveryError.wrongIdentity }
                    let record = try recoveryJournal.prepare(input: input, in: recoveryScope)
                    key = record.idempotencyKey
                } else { key = UUID().uuidString }
                pendingInput = input; pendingKey = key
            }
            let result: ERPInvoice
            if let recoveryJournal {
                guard let recoveryScope, let authorizeRecoveryScope,
                      let record = try recoveryJournal.pending(in: recoveryScope),
                      record.idempotencyKey == key, try record.input() == input else {
                    throw InvoiceRecoveryError.wrongIdentity
                }
                result = try await recoveryJournal.execute(record, in: recoveryScope, using: service,
                                                          authorize: authorizeRecoveryScope)
            } else { result = try await service.createDraft(input, idempotencyKey: key) }
            guard (recoveryJournal != nil || result.status == "DRAFT"), result.partyId == input.customerId else {
                throw ERPClientError.invalidResponse
            }
            saved = result
            hasUncertainResult = false
            return result
        } catch {
            if let recoveryJournal, let recoveryScope, let failure = error as? ERPClientError,
               case .invalidInput = failure {
                do {
                    if try recoveryJournal.pending(in: recoveryScope) == nil {
                        pendingInput = nil; pendingKey = nil
                    }
                } catch { /* An unreadable journal is still an unresolved operation. */ }
            }
            if recoveryJournal == nil, !alreadyUncertain, let failure = error as? ERPClientError {
                switch failure {
                case .invalidInput, .forbidden, .authenticationRequired, .notFound, .fixtureUnsupported:
                    pendingInput = nil; pendingKey = nil
                default: break
                }
            }
            hasUncertainResult = pendingInput != nil
            let message = (error as? InvoiceRecoveryError)?.localizedDescription ?? friendlyError(error)
            if pendingInput == nil { self.error = message }
            else if recoveryJournal != nil {
                self.error = "No se confirmó el guardado. \(message) Se conserva la referencia pendiente."
            } else {
                self.error = "No se confirmó el guardado. \(message) Reintentar conserva la misma operación."
            }
            return nil
        }
    }
}

enum InvoiceInputFocus: Hashable {
    case paymentTerms
    case description(UUID)
    case quantity(UUID)
    case price(UUID)
    case discount(UUID)
}

struct InvoiceComposerView: View {
    let store: WorkspaceStore
    let onSaved: ((ERPInvoice) -> Void)?
    @State private var draft: InvoiceComposer
    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var confirmDiscard = false
    @State private var pickingCustomer = false
    @State private var pickingProduct = false
    @State private var didConfigure = false
    @State private var isAtEnd = false
    @State private var measuredAtEnd = false
    @State private var userScrollInFlight = false
    @FocusState private var focusedInput: InvoiceInputFocus?

    init(store: WorkspaceStore, initialCustomerId: UUID?, onSaved: ((ERPInvoice) -> Void)? = nil) {
        self.store = store
        self.onSaved = onSaved
        draft = InvoiceComposer(customerId: initialCustomerId)
    }
    var body: some View {
        @Bindable var draft = draft
        NavigationStack {
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    Form {
                        if let error = store.catalogError {
                            Section { ERPErrorState(message: error) { await store.loadCatalog() } }
                        }
                        Section {
                            Button { pickingCustomer = true } label: {
                                HStack(spacing: 12) {
                                    VStack(alignment: .leading, spacing: 4) {
                                        if draft.customerId != nil { Text("Cliente").font(.subheadline) }
                                        Text(draft.customerId.map(store.customerName) ?? "Elegir cliente")
                                            .font(.headline)
                                    }
                                    .fixedSize(horizontal: false, vertical: true)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    Image(systemName: "chevron.right").accessibilityHidden(true)
                                }
                                .foregroundStyle(Color.primary)
                                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .disabled(!draft.canEdit)
                            .accessibilityIdentifier("draft-customer")
                        } header: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(store.context?.name ?? "Empresa").font(.headline)
                                if store.isDemo { Text("Datos de prueba.").font(.footnote) }
                            }
                            .textCase(nil)
                            .foregroundStyle(Color.primary)
                        }
                        Section {
                            LabeledContent("Plazo de pago (días)") {
                                TextField("Días de plazo", value: $draft.paymentTermsDays, format: .number.grouping(.never))
                                    .focused($focusedInput, equals: .paymentTerms)
                                    .keyboardType(.numberPad)
                                    .multilineTextAlignment(.trailing)
                                    .accessibilityIdentifier("payment-terms-days")
                            }
                            .frame(minHeight: 44)
                            .contentShape(Rectangle())
                            .onTapGesture { focusedInput = .paymentTerms }
                            ERPDetailRow(title: "Vencimiento", value: draft.dueDateString ?? "Revisar plazo")
                            Text("0 días es al contado. El plazo inicial procede del cliente o de la empresa.")
                                .font(.footnote).foregroundStyle(Color.primary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .disabled(!draft.canEdit)
                        Section {
                            DatePicker("Fecha", selection: $draft.issueDate, displayedComponents: .date)
                                .environment(\.timeZone, TimeZone(identifier: "America/Guayaquil")!)
                            Picker("Establecimiento", selection: $draft.establishmentId) {
                                Text("Seleccionar").tag(nil as UUID?)
                                ForEach(store.setup?.establishments ?? []) { item in
                                    Text("\(item.code) · \(item.name)").tag(Optional(item.id))
                                }
                            }
                            Picker("Punto de emisión", selection: $draft.emissionPointId) {
                                Text("Seleccionar").tag(nil as UUID?)
                                ForEach((store.setup?.emissionPoints ?? []).filter { $0.establishmentId == draft.establishmentId }) { item in
                                    Text(item.code).tag(Optional(item.id))
                                }
                            }
                        } header: { Text("Emisión").foregroundStyle(Color.primary) }
                        .disabled(!draft.canEdit)
                        ForEach($draft.lines) { $line in
                            Section {
                                TextField("Descripción", text: $line.description)
                                    .focused($focusedInput, equals: .description(line.id))
                                ERPDecimalField(title: "Cantidad", text: $line.quantity, focus: $focusedInput, key: .quantity(line.id))
                                ERPDecimalField(title: "Precio unitario", text: $line.unitPrice, focus: $focusedInput, key: .price(line.id))
                                ERPDecimalField(title: "Descuento", text: $line.discount, focus: $focusedInput, key: .discount(line.id))
                                Button("Quitar producto", role: .destructive) { draft.lines.removeAll { $0.id == line.id } }
                                    .frame(minHeight: 44)
                            } header: { Text("Detalle").foregroundStyle(Color.primary) }
                            .disabled(!draft.canEdit)
                        }
                        Section {
                            Button {
                                pickingProduct = true
                            } label: {
                                Label("Añadir producto", systemImage: "plus")
                                    .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                                    .contentShape(Rectangle())
                            }
                            .accessibilityIdentifier("add-product")
                            .frame(minHeight: 44)
                            .disabled(!draft.canEdit || store.setup == nil)
                            if store.isDemo {
                                Text("Demo: usa cantidades 1, 2 o 3, precios originales y descuento cero.")
                                    .font(.footnote).fixedSize(horizontal: false, vertical: true)
                                    .foregroundStyle(Color.primary)
                            }
                        }
                        Section {
                            if let preview = draft.preview {
                                ERPDetailRow(title: "Subtotal", value: ERPDisplay.money(preview.subtotal))
                                ERPDetailRow(title: "IVA", value: ERPDisplay.money(preview.taxTotal))
                                ERPDetailRow(title: "Total", value: ERPDisplay.money(preview.total))
                                    .fontWeight(.semibold)
                                    .accessibilityIdentifier("draft-total")
                            }
                            Button {
                                guard let service = store.service else { return }
                                Task { await draft.review(using: service, setup: store.setup) }
                            } label: {
                                if draft.working { ProgressView("Revisando…") }
                                else {
                                    Text("Revisar importes")
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                            .frame(minHeight: 44)
                            .disabled(!draft.canEdit || draft.lines.isEmpty)
                            .accessibilityIdentifier("review-totals")
                            Text("Borrador, sin envío al SRI.")
                                .font(.footnote).foregroundStyle(Color.primary)
                                .fixedSize(horizontal: false, vertical: true)
                                .id("invoice-summary-end")
                        } header: { Text(store.isDemo ? "Totales de prueba" : "Totales del servidor").foregroundStyle(Color.primary) }
                        if let error = draft.error {
                            Section { Text(error).foregroundStyle(Color.primary).accessibilityIdentifier("draft-error").id("invoice-error-end") }
                        }
                    }
                    .accessibilityIdentifier("invoice-form")
                    .scrollDismissesKeyboard(.interactively)
                    .scrollEdgeEffectStyle(.hard, for: .all)
                    .scrollEdgeEffectHidden(for: .all)
                    .contentMargins(.bottom, 32, for: .scrollContent)
                    .defaultScrollAnchor(isAtEnd && focusedInput == nil ? .bottom : nil, for: .sizeChanges)
                    .onScrollGeometryChange(for: ScrollGeometry.self) { $0 } action: { _, geometry in
                        let atEnd = geometry.contentSize.height > 0 &&
                            geometry.visibleRect.maxY >= geometry.contentSize.height + geometry.contentInsets.bottom - 1
                        if measuredAtEnd != atEnd { measuredAtEnd = atEnd }
                        if userScrollInFlight && isAtEnd != atEnd { isAtEnd = atEnd }
                        let maximumOffset = max(-geometry.contentInsets.top,
                            geometry.contentSize.height + geometry.contentInsets.bottom - geometry.containerSize.height)
                        if isAtEnd && focusedInput == nil && !userScrollInFlight &&
                            geometry.contentSize.height.isFinite && geometry.contentSize.height > 0 &&
                            geometry.containerSize.height.isFinite && geometry.containerSize.height > 0 &&
                            geometry.contentInsets.top.isFinite && geometry.contentInsets.bottom.isFinite &&
                            geometry.contentOffset.y.isFinite && geometry.contentOffset.y > maximumOffset + 1 {
                            let target = draft.error == nil ? "invoice-summary-end" : "invoice-error-end"
                            withAnimation(nil) { proxy.scrollTo(target, anchor: .top) }
                            #if DEBUG && targetEnvironment(simulator)
                            if ProcessInfo.processInfo.arguments.contains("-trace-invoice-layout") {
                                Logger(subsystem: "ec.com.b2b.iaerp.layout", category: "InvoiceLayout")
                                    .notice("INVOICE_REPAIR \(target, privacy: .public)")
                            }
                            #endif
                        }
                        #if DEBUG && targetEnvironment(simulator)
                        if ProcessInfo.processInfo.arguments.contains("-trace-invoice-layout") {
                            let value = "offset=\(geometry.contentOffset) content=\(geometry.contentSize) container=\(geometry.containerSize) insets=\(geometry.contentInsets) visible=\(geometry.visibleRect) measuredAtEnd=\(atEnd) prefersEnd=\(isAtEnd) userScroll=\(userScrollInFlight)"
                            Logger(subsystem: "ec.com.b2b.iaerp.layout", category: "InvoiceLayout")
                                .notice("INVOICE_LAYOUT \(value, privacy: .public)")
                        }
                        #endif
                    }
                    .onScrollPhaseChange { oldPhase, newPhase, context in
                        switch newPhase {
                        case .tracking, .interacting, .decelerating:
                            if !userScrollInFlight { userScrollInFlight = true }
                        case .idle:
                            if userScrollInFlight {
                                let geometry = context.geometry
                                let atEnd = geometry.contentSize.height > 0 &&
                                    geometry.visibleRect.maxY >= geometry.contentSize.height + geometry.contentInsets.bottom - 1
                                if measuredAtEnd != atEnd { measuredAtEnd = atEnd }
                                if isAtEnd != atEnd { isAtEnd = atEnd }
                                userScrollInFlight = false
                            }
                        case .animating:
                            if userScrollInFlight { userScrollInFlight = false }
                        @unknown default:
                            if userScrollInFlight { userScrollInFlight = false }
                        }
                        #if DEBUG && targetEnvironment(simulator)
                        if ProcessInfo.processInfo.arguments.contains("-trace-invoice-layout") {
                            Logger(subsystem: "ec.com.b2b.iaerp.layout", category: "InvoiceLayout")
                                .notice("INVOICE_PHASE \(String(describing: oldPhase), privacy: .public) -> \(String(describing: newPhase), privacy: .public) measuredAtEnd=\(measuredAtEnd) prefersEnd=\(isAtEnd) userScroll=\(userScrollInFlight)")
                        }
                        #endif
                    }
                    #if DEBUG && targetEnvironment(simulator)
                    .onAppear {
                        if ProcessInfo.processInfo.arguments.contains("-trace-invoice-layout") {
                            Logger(subsystem: "ec.com.b2b.iaerp.layout", category: "InvoiceLayout")
                                .notice("TRACE_ENABLED")
                        }
                    }
                    .onChange(of: dynamicTypeSize) { oldValue, newValue in
                        if ProcessInfo.processInfo.arguments.contains("-trace-invoice-layout") {
                            Logger(subsystem: "ec.com.b2b.iaerp.layout", category: "InvoiceLayout")
                                .notice("INVOICE_TYPE \(String(describing: oldValue), privacy: .public) -> \(String(describing: newValue), privacy: .public)")
                        }
                    }
                    #endif
                }
                formActions
            }
            .navigationTitle("Nueva factura")
            .navigationDestination(isPresented: $pickingCustomer) {
                CustomerPicker(store: store, selection: $draft.customerId)
            }
            .sheet(isPresented: $pickingProduct) {
                NavigationStack { ProductPicker(store: store, draft: draft) }
            }
            .toolbarTitleDisplayMode(.inline)
            .toolbarBackground(Color(uiColor: .systemBackground), for: .navigationBar)
            .toolbarBackgroundVisibility(.visible, for: .navigationBar)
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Listo") { focusedInput = nil }
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("dismiss-keyboard")
                }
            }
            .interactiveDismissDisabled()
            .confirmationDialog(draft.pendingInput == nil ? "¿Descartar este borrador?" : "¿Cerrar el formulario?", isPresented: $confirmDiscard, titleVisibility: .visible) {
                Button(draft.pendingInput == nil ? "Descartar borrador" : "Cerrar formulario", role: draft.pendingInput == nil ? .destructive : nil) { dismiss() }
                Button("Seguir editando", role: .cancel) { }
            } message: {
                Text(draft.pendingInput == nil ? "Se perderán los cambios sin guardar." : "El guardado pendiente se conserva. Consulta su estado desde Facturas antes de continuar.")
            }
            .onChange(of: draft.fingerprint) { _, _ in draft.invalidatePreview() }
            .onChange(of: draft.establishmentId) { _, id in
                draft.emissionPointId = store.setup?.emissionPoints.first { $0.establishmentId == id }?.id
            }
            .onChange(of: draft.customerId) { _, id in
                draft.configurePaymentTerms(customer: id.flatMap(store.customer), context: store.context)
            }
            .task {
                guard !didConfigure else { return }
                didConfigure = true
                if store.setup == nil { await store.loadCatalog() }
                draft.establishmentId = store.setup?.establishments.first?.id
                draft.emissionPointId = store.setup?.emissionPoints.first { $0.establishmentId == draft.establishmentId }?.id
                draft.configurePaymentTerms(customer: draft.customerId.flatMap(store.customer), context: store.context)
            }
        }
    }

    private var formActions: some View {
        let layout = dynamicTypeSize.isAccessibilitySize ? AnyLayout(VStackLayout(spacing: 8)) : AnyLayout(HStackLayout(spacing: 12))
        return layout {
            Button("Cancelar", role: .cancel) { confirmDiscard = true }
                .buttonStyle(.bordered)
                .tint(Color.primary)
                .frame(maxWidth: .infinity, minHeight: 44)
                .disabled(draft.working)
            Button(saveActionTitle) { Task { await save() } }
                .buttonStyle(ERPPrimaryActionStyle())
                .frame(maxWidth: .infinity, minHeight: 44)
                .disabled(draft.working || draft.preview == nil)
                .accessibilityIdentifier("save-draft")
        }
        .padding().background(Color(uiColor: .systemBackground))
    }

    private var saveActionTitle: String {
        if draft.working && draft.pendingInput != nil { return "Guardando…" }
        guard draft.pendingInput != nil else { return "Guardar" }
        if store.isDemo { return "Reintentar guardado" }
        guard let pending = store.pendingInvoiceRecovery else { return "Guardar" }
        return pending.attemptCount == 0 && pending.confirmedInvoiceID == nil
            ? "Continuar guardado" : "Consultar guardado"
    }

    private func save() async {
        guard let service = store.service else { return }
        let epoch = store.generation
        let invoice: ERPInvoice?
        if store.isDemo {
            invoice = await draft.save(using: service, setup: store.setup)
        } else {
            do {
                let scope = try store.currentInvoiceRecoveryScope()
                invoice = await draft.save(using: service, setup: store.setup,
                    recoveryJournal: store.invoiceRecoveryJournal, recoveryScope: scope,
                    authorizeRecoveryScope: {
                        guard store.generation == epoch else { throw InvoiceRecoveryError.wrongIdentity }
                        return try store.currentInvoiceRecoveryScope()
                    })
                if epoch == store.generation { store.refreshInvoiceRecovery() }
            } catch {
                draft.error = (error as? InvoiceRecoveryError)?.localizedDescription ?? friendlyError(error)
                return
            }
        }
        if let invoice, epoch == store.generation {
            store.acceptSaved(invoice, generation: epoch)
            onSaved?(invoice)
            dismiss()
        }
    }
}

struct ERPDecimalField: View {
    let title: String
    @Binding var text: String
    @FocusState.Binding var focus: InvoiceInputFocus?
    let key: InvoiceInputFocus
    var body: some View {
        LabeledContent {
            HStack(spacing: 4) {
                TextField(title, text: $text).keyboardType(.decimalPad).multilineTextAlignment(.trailing)
                    .focused($focus, equals: key)
                    .accessibilityIdentifier("field-\(title)")
                if focus == key {
                    Button {
                        text = ""
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .frame(minWidth: 44, minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Borrar \(title.lowercased())")
                    .accessibilityIdentifier("clear-field-\(title)")
                    .disabled(text.isEmpty)
                }
            }
        } label: { Text(title).foregroundStyle(Color.primary) }
        .frame(minHeight: 44)
    }
}

struct CustomerPicker: View {
    let store: WorkspaceStore
    @Binding var selection: UUID?
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    var body: some View {
        List {
            Section { ERPSearchField(text: $query, prompt: "Buscar clientes") }
            if store.loadingCustomers { ProgressView("Buscando clientes…") }
            if let error = store.customerError {
                ERPErrorState(message: error) { await store.loadCustomers(query: query) }
            }
            ForEach(store.customers.filter { query.isEmpty || $0.name.localizedStandardContains(query) || $0.identificationNumber.localizedStandardContains(query) }) { customer in
                Button { selection = customer.id; dismiss() } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(customer.name).font(.headline)
                        Text(customer.identificationNumber).font(.subheadline)
                    }
                    .foregroundStyle(Color.primary)
                    .frame(minHeight: 44, alignment: .leading)
                }
                .accessibilityIdentifier("pick-customer-\(customer.id.uuidString)")
            }
            Text("Hasta 100 registros. Busca con al menos dos caracteres.").foregroundStyle(Color.primary)
        }
        .scrollEdgeEffectStyle(.hard, for: .all)
        .navigationTitle("Elegir cliente").toolbarTitleDisplayMode(.inline)
        .task(id: query) {
            do { try await Task.sleep(for: .milliseconds(300)) } catch { return }
            await store.loadCustomers(query: query)
        }
    }
}

struct ProductPicker: View {
    let store: WorkspaceStore
    let draft: InvoiceComposer
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    var body: some View {
        VStack(spacing: 0) {
            List {
                Section { ERPSearchField(text: $query, prompt: "Buscar productos") }
                if store.loadingProducts { ProgressView("Buscando productos…") }
                if let error = store.catalogError {
                    ERPErrorState(message: error) { await store.loadProducts(query: query) }
                }
                ForEach(store.products.filter { query.isEmpty || $0.name.localizedStandardContains(query) || ($0.code?.localizedStandardContains(query) == true) }) { product in
                    Button { draft.add(product, setup: store.setup); if draft.error == nil { dismiss() } } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(product.name).font(.headline)
                            Text(ERPDisplay.money(product.unitPrice)).font(.subheadline)
                        }
                        .foregroundStyle(Color.primary)
                        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                        .contentShape(Rectangle())
                    }
                    .accessibilityIdentifier("pick-product-\(product.id.uuidString)")
                }
                if let error = draft.error { Text(error).foregroundStyle(Color.primary) }
            }
            .scrollEdgeEffectStyle(.hard, for: .all)
            .clipped()
            VStack(spacing: 8) {
                Text("Hasta 100 productos del catálogo.")
                    .font(.footnote)
                    .foregroundStyle(Color.primary)
                    .fixedSize(horizontal: false, vertical: true)
                Button { dismiss() } label: {
                    Text("Cancelar")
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("cancel-product-picker")
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(Color(uiColor: .systemBackground))
        }
        .navigationTitle("Elegir producto").toolbarTitleDisplayMode(.inline)
        .task(id: query) {
            do { try await Task.sleep(for: .milliseconds(300)) } catch { return }
            await store.loadProducts(query: query)
        }
    }
}
