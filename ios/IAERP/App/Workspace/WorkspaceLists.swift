import IAERPClient
import SwiftUI

struct WorkspaceClientsView: View {
    let store: WorkspaceStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var query = ""
    @State private var showingSearchSummary = false
    @State private var registering = false
    @State private var selectedCustomer: ERPParty?
    @State private var showingRegisteredCustomer = false
    private var visible: [ERPParty] {
        guard !query.isEmpty else { return store.customers }
        return store.customers.filter { [$0.name, $0.identificationNumber].contains { $0.localizedStandardContains(query) } }
    }
    var body: some View {
        List {
            Section {
                ERPSearchField(text: $query, prompt: "Buscar clientes")
            }
            Section {
                if store.loadingCustomers { ProgressView("Buscando clientes…") }
                if let error = store.customerError {
                    ERPErrorState(message: error) { await store.loadCustomers(query: query) }
                } else if visible.isEmpty && !store.loadingCustomers {
                    ContentUnavailableView(query.isEmpty ? "Sin clientes" : "Sin resultados", systemImage: "person.2",
                                           description: Text(query.isEmpty ? "Los clientes de tu empresa aparecerán aquí." : "Prueba otro nombre o identificación."))
                } else {
                    ForEach(visible) { customer in
                        NavigationLink {
                            WorkspaceCustomerDetail(store: store, customer: customer)
                        } label: {
                            VStack(alignment: .leading, spacing: 5) {
                                title(for: customer)
                                if !dynamicTypeSize.isAccessibilitySize {
                                    Text(customer.identificationNumber).font(.subheadline)
                                }
                            }
                            .foregroundStyle(Color.primary)
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(minHeight: 44, alignment: .leading)
                        }
                        .accessibilityIdentifier("workspace-client-\(customer.id.uuidString)")
                    }
                }
            }
        }
        .listSectionSpacing(.compact)
        .clipped()
        .padding(.bottom, 1)
        .scrollEdgeEffectStyle(.hard, for: .all)
        .scrollEdgeEffectHidden(true, for: .all)
        .toolbarBackground(Color(uiColor: .systemBackground), for: .tabBar)
        .toolbarBackground(.visible, for: .tabBar)
        .navigationTitle("Clientes")
        .navigationSubtitle(Text(verbatim: store.displayCompany))
        .toolbarTitleDisplayMode(.inline)
        .sheet(isPresented: $registering, onDismiss: {
            if selectedCustomer != nil { showingRegisteredCustomer = true }
        }) {
            CustomerRegistrationView(store: store) { party in
                query = party.identificationNumber
                selectedCustomer = party
            }
        }
        .navigationDestination(isPresented: $showingRegisteredCustomer) {
            if let selectedCustomer { WorkspaceCustomerDetail(store: store, customer: selectedCustomer) }
        }
        .toolbar {
            if store.canRegisterCustomer {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Nuevo cliente", systemImage: "plus") {
                        selectedCustomer = nil
                        registering = true
                    }
                    .accessibilityIdentifier("clients-new-customer")
                }
            }
            if store.customerError == nil && !store.loadingCustomers {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showingSearchSummary = true } label: {
                        Label("Resultados: \(visible.count)", systemImage: "info.circle")
                            .labelStyle(.iconOnly)
                    }
                    .help("Ver resultados y límite de búsqueda")
                    .accessibilityIdentifier("client-search-summary")
                    .popover(isPresented: $showingSearchSummary) {
                        VStack(alignment: .leading, spacing: 12) {
                            ERPListSummary(count: visible.count)
                            Button("Cerrar") { showingSearchSummary = false }
                        }
                        .padding()
                        .presentationCompactAdaptation(.popover)
                    }
                }
            }
        }
        .task(id: query) {
            do { try await Task.sleep(for: .milliseconds(300)) } catch { return }
            await store.loadCustomers(query: query)
        }
        .refreshable { await store.loadCustomers(query: query) }
    }

    private func title(for customer: ERPParty) -> Text {
        let name = Text(verbatim: customer.name).font(.headline)
        guard dynamicTypeSize.isAccessibilitySize else { return name }
        let identification = Text(verbatim: customer.identificationNumber).font(.subheadline)
        return Text("\(name)\n\(identification)")
    }
}

struct SavedInvoiceLink: View {
    let store: WorkspaceStore
    let saved: ERPInvoice
    let linkIdentifier: String

    var body: some View {
        let invoice = store.invoices.first { $0.id == saved.id } ?? saved
        let isDraft = invoice.status == "DRAFT"
        let linkTitle: LocalizedStringKey = if !isDraft { "Ver factura" }
            else if !store.isDemo && store.context?.permits("invoices:issue") == true { "Revisar borrador para emitir" }
            else { "Ver borrador" }
        Text(isDraft ? "Borrador guardado. No se ha emitido al SRI." : "Factura guardada.")
            .accessibilityIdentifier("workspace-notice")
        NavigationLink {
            WorkspaceInvoiceDetail(store: store, invoiceId: invoice.id)
        } label: {
            VStack(alignment: .leading, spacing: 4) {
                Label(linkTitle, systemImage: "doc.text")
                Text(verbatim: store.customerName(invoice.partyId))
                Text(verbatim: ERPDisplay.money(invoice.total, currency: invoice.currency))
            }
            .fixedSize(horizontal: false, vertical: true)
            .frame(minHeight: 44, alignment: .leading)
        }
        .accessibilityIdentifier(linkIdentifier)
    }
}

struct WorkspaceCustomerDetail: View {
    let store: WorkspaceStore
    let customer: ERPParty
    @State private var composer: ComposerRoute?
    @State private var savedInvoice: ERPInvoice?
    var body: some View {
        List {
            WorkspaceContextSection(store: store)
            if let savedInvoice {
                Section { SavedInvoiceLink(store: store, saved: savedInvoice, linkIdentifier: "customer-open-draft") }
            }
            Section {
                ERPDetailRow(title: "Nombre", value: customer.name)
                ERPDetailRow(title: "Identificación", value: customer.identificationNumber)
                ERPDetailRow(title: "Tipo", value: customer.identificationType)
                if let value = customer.address, !value.isEmpty { ERPDetailRow(title: "Dirección", value: value) }
                if let value = customer.email, !value.isEmpty { ERPDetailRow(title: "Correo", value: value) }
                if let value = customer.phone, !value.isEmpty { ERPDetailRow(title: "Teléfono", value: value) }
            } header: { Text("Datos del cliente").foregroundStyle(Color.primary) }
            if store.canCreate {
                Section {
                    Button("Nueva factura", systemImage: "plus") { composer = ComposerRoute(customerId: customer.id) }
                        .frame(minHeight: 44)
                        .disabled(!store.canStartInvoice)
                        .accessibilityIdentifier("new-customer-invoice")
                    if store.canPrepareBTOBTestInvoice {
                        NavigationLink("Preparar factura de prueba") {
                            CustomerTestProductPicker(store: store, customer: customer)
                        }
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("customer-prepare-test-invoice")
                    }
                }
                if !store.canStartInvoice { InvoiceRecoverySection(store: store) }
            }
        }
        .scrollEdgeEffectStyle(.hard, for: .all)
        .scrollEdgeEffectHidden(for: .all)
        .navigationTitle("Cliente")
        .toolbarTitleDisplayMode(.inline)
        .toolbarBackground(Color(uiColor: .systemBackground), for: .navigationBar)
        .toolbarBackgroundVisibility(.visible, for: .navigationBar)
        .toolbarVisibility(.hidden, for: .tabBar)
        .sheet(item: $composer) { route in
            InvoiceComposerView(store: store, initialCustomerId: route.customerId) { savedInvoice = $0 }
        }
    }
}

struct ComposerRoute: Identifiable {
    let id = UUID()
    var customerId: UUID?
}

struct WorkspaceInvoicesView: View {
    let store: WorkspaceStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @FocusState private var searchIsFocused: Bool
    @State private var query = ""
    @State private var status = ""
    @State private var composer: ComposerRoute?
    @State private var savedInvoice: ERPInvoice?
    @State private var expandedMonths: [String: Bool] = [:]
    @State private var appliedRequest: InvoiceListRequest?
    @State private var unfocusedBottomInset: CGFloat?

    private struct InvoiceListRequest: Equatable {
        let query: String
        let status: String
        let revision: Int
    }

    private var request: InvoiceListRequest {
        InvoiceListRequest(query: query.trimmingCharacters(in: .whitespacesAndNewlines),
                           status: status, revision: store.invoiceListRevision)
    }

    var body: some View {
        GeometryReader { viewport in
            let bottomInset = viewport.safeAreaInsets.bottom
            let chromeInset = unfocusedBottomInset ?? bottomInset
            // With the software keyboard, SwiftUI already shortens the proposed height.
            let keyboardAvoidance = searchIsFocused && bottomInset > chromeInset + 1
            let reservedBottomInset = keyboardAvoidance ? 0 : bottomInset
            List {
                Section {
                    ERPSearchField(text: $query, prompt: "Número o clave de acceso")
                        .focused($searchIsFocused)
                    Picker("Estado", selection: $status) {
                        Text("Todos").tag("")
                        Text("Borradores").tag("DRAFT")
                        Text("Autorizadas").tag("AUTHORIZED")
                    }
                }
                InvoiceRecoverySection(store: store)
                if let savedInvoice {
                    Section { SavedInvoiceLink(store: store, saved: savedInvoice, linkIdentifier: "invoices-open-draft") }
                } else if let notice = store.notice {
                    Text(notice).accessibilityIdentifier("workspace-notice")
                }
                if request.query.count == 1 {
                    Text("Escribe al menos dos caracteres para buscar.")
                } else if appliedRequest == request, let error = store.invoiceError {
                    ERPErrorState(message: error) { await reload(request) }
                } else if appliedRequest != request || store.loadingInvoices {
                    ProgressView("Buscando facturas…")
                } else if store.invoiceMonths.isEmpty {
                    ContentUnavailableView(
                        request.query.isEmpty && status.isEmpty ? "Sin facturas" : "Sin resultados",
                        systemImage: "doc.text", description: Text("Revisa el filtro o la búsqueda.")
                    )
                } else {
                    ForEach(store.invoiceMonths, id: \.id) { month in
                        monthSection(month)
                    }
                }
            }
            .accessibilityIdentifier("invoice-list")
            .frame(width: viewport.size.width,
                   height: max(0, viewport.size.height - reservedBottomInset), alignment: .top)
            .clipped()
            .padding(.bottom, reservedBottomInset)
            .scrollEdgeEffectStyle(.hard, for: .all)
            .scrollEdgeEffectHidden(true, for: .all)
            .onChange(of: bottomInset, initial: true) { _, inset in
                if !searchIsFocused { unfocusedBottomInset = inset }
            }
        }
        .navigationTitle("Facturas")
        .navigationSubtitle(Text(verbatim: store.displayCompany))
        .toolbarTitleDisplayMode(.inline)
        .toolbarBackground(Color(uiColor: .systemBackground), for: .tabBar)
        .toolbarBackground(.visible, for: .tabBar)
        .toolbar {
            if store.canCreate {
                ToolbarItem(placement: .primaryAction) {
                    Button("Nuevo", systemImage: "plus") { composer = ComposerRoute() }
                        .disabled(!store.canStartInvoice)
                        .accessibilityIdentifier("new-invoice")
                }
            }
        }
        .sheet(item: $composer) { route in
            InvoiceComposerView(store: store, initialCustomerId: route.customerId) { savedInvoice = $0 }
        }
        .task(id: request) {
            let next = request
            guard next != appliedRequest, next.query.count != 1 else { return }
            do { try await Task.sleep(for: .milliseconds(300)) } catch { return }
            await reload(next)
        }
        .refreshable { if request.query.count != 1 { await reload(request) } }
    }

    private func reload(_ next: InvoiceListRequest) async {
        if next.query != appliedRequest?.query || next.status != appliedRequest?.status {
            expandedMonths.removeAll()
        }
        appliedRequest = nil
        await store.loadInvoices(query: next.query, status: next.status.isEmpty ? nil : next.status)
        if !Task.isCancelled, request == next { appliedRequest = next }
    }

    private func monthSection(_ group: ERPInvoiceMonth) -> some View {
        let month = group.month
        let key = group.id
        let accessibilityKey = group.currency == "USD" ? month : "\(month)-\(group.currency)"
        let expanded = expandedMonths[key] ?? (key == store.invoiceMonths.first?.id)
        let count = group.count == 1 ? "1 factura" : "\(group.count) facturas"
        let amount = ERPDisplay.money(group.total, currency: group.currency)
        let groupTotal = group.currency == "USD" ? amount : "\(amount) \(group.currency)"
        return Section {
            Button {
                expandedMonths[key] = !expanded
            } label: {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(ERPDisplay.longFiscalDate(month)).font(.headline)
                        Text("\(count) · \(groupTotal)")
                            .font(.subheadline)
                    }
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    Image(systemName: expanded ? "chevron.up" : "chevron.down").accessibilityHidden(true)
                }
                .foregroundStyle(Color.primary)
                .padding(.vertical, 4)
                .frame(minHeight: 44)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityValue(expanded ? "Expandido" : "Contraído")
            .accessibilityIdentifier("invoice-month-\(accessibilityKey)")
            if expanded {
                ForEach(store.monthRows[key] ?? [], id: \.id) { invoice in
                    let amount = ERPDisplay.money(invoice.total, currency: invoice.currency)
                    let status = ERPDisplay.status(invoice.status)
                    let collection = invoice.collectionStatus.map { "Cobro: \(ERPDisplay.status($0))" }
                    NavigationLink {
                        WorkspaceInvoiceDetail(store: store, invoiceId: invoice.id, listedNumber: invoice.number,
                                               listedCustomerName: invoice.customerName)
                    } label: {
                        VStack(alignment: .leading, spacing: 5) {
                            Text(invoice.number).font(.headline)
                            Text(invoice.customerName)
                            Text(dynamicTypeSize.isAccessibilitySize ? amount : "\(invoice.issueDate) · \(amount)")
                            if !dynamicTypeSize.isAccessibilitySize {
                                Text(status).font(.subheadline.weight(.medium))
                                if let collection { Text(collection).font(.subheadline) }
                            }
                        }
                        .fixedSize(horizontal: false, vertical: true)
                        .foregroundStyle(Color.primary)
                        .padding(.vertical, 4)
                    }
                    .accessibilityLabel([invoice.number, invoice.customerName, amount,
                                         ERPDisplay.longFiscalDate(invoice.issueDate), status, collection]
                        .compactMap { $0 }.joined(separator: ", "), isEnabled: dynamicTypeSize.isAccessibilitySize)
                    .accessibilityIdentifier("workspace-invoice-\(invoice.id.uuidString)")
                }
                if let error = store.monthErrors[key] {
                    ERPErrorState(message: error) {
                        await store.loadInvoiceMonth(group, more: !(store.monthRows[key] ?? []).isEmpty)
                    }
                } else if store.loadingMonths.contains(key) || store.monthRows[key] == nil {
                    ProgressView("Cargando facturas…")
                        .onAppear {
                            // A quick collapse or tab switch may hide this row while its page loads.
                            // Let the store finish the read for the active query and company.
                            guard store.monthRows[key] == nil, !store.loadingMonths.contains(key) else { return }
                            Task { await store.loadInvoiceMonth(group, more: false) }
                        }
                } else if store.moreMonths.contains(key) {
                    Button("Ver más facturas") {
                        Task { await store.loadInvoiceMonth(group, more: true) }
                    }
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("invoice-month-more-\(accessibilityKey)")
                }
            }
        }
    }
}

struct InvoiceRecoverySection: View {
    let store: WorkspaceStore

    var body: some View {
        if let pending = store.pendingInvoiceRecovery {
            Section {
                Text("Confirma el guardado pendiente antes de crear otra factura.")
                    .fixedSize(horizontal: false, vertical: true)
                Text(pending.attemptCount == 0 && pending.confirmedInvoiceID == nil
                     ? "Continuar intentará enviar este borrador a IAERP por primera vez."
                     : "Consulta el resultado en IAERP. No se enviará otra operación.")
                    .font(.footnote).fixedSize(horizontal: false, vertical: true)
                Button {
                    Task { await store.recoverPendingInvoice() }
                } label: {
                    if store.checkingInvoiceRecovery { ProgressView("Comprobando guardado…") }
                    else {
                        Text(pending.attemptCount == 0 && pending.confirmedInvoiceID == nil
                             ? "Continuar guardado" : "Consultar guardado")
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .frame(minHeight: 44)
                .disabled(store.checkingInvoiceRecovery)
                .accessibilityIdentifier("recover-pending-invoice")
                Text("Operación \(pending.idempotencyKey.prefix(8))")
                    .font(.caption).foregroundStyle(Color.primary)
            } header: { Text("Guardado pendiente").foregroundStyle(Color.primary) }
        }
        if let error = store.invoiceRecoveryError {
            Section {
                Text(error).fixedSize(horizontal: false, vertical: true)
                Button("Volver a comprobar") { store.refreshInvoiceRecovery() }
                    .frame(minHeight: 44)
            }
        }
    }
}
