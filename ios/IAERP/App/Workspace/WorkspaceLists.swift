import IAERPClient
import SwiftUI

struct WorkspaceClientsView: View {
    let store: WorkspaceStore
    @State private var query = ""
    private var visible: [ERPParty] {
        guard !query.isEmpty else { return store.customers }
        return store.customers.filter { [$0.name, $0.identificationNumber].contains { $0.localizedStandardContains(query) } }
    }
    var body: some View {
        List {
            Section {
                ERPSearchField(text: $query, prompt: "Buscar clientes")
                if store.customerError == nil && !store.loadingCustomers { ERPListSummary(count: visible.count) }
            }
            WorkspaceContextSection(store: store)
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
                                Text(customer.name).font(.headline).foregroundStyle(Color.primary)
                                Text(customer.identificationNumber).font(.subheadline).foregroundStyle(Color.primary)
                            }
                            .foregroundStyle(Color.primary)
                            .frame(minHeight: 44, alignment: .leading)
                        }
                        .accessibilityIdentifier("workspace-client-\(customer.id.uuidString)")
                    }
                }
            }
        }
        .scrollEdgeEffectStyle(.hard, for: .all)
        .scrollEdgeEffectHidden(true, for: .bottom)
        .navigationTitle("Clientes")
        .toolbarTitleDisplayMode(.inline)
        .task(id: query) {
            do { try await Task.sleep(for: .milliseconds(300)) } catch { return }
            await store.loadCustomers(query: query)
        }
        .refreshable { await store.loadCustomers(query: query) }
    }
}

struct WorkspaceCustomerDetail: View {
    let store: WorkspaceStore
    let customer: ERPParty
    @State private var composer: ComposerRoute?
    var body: some View {
        List {
            WorkspaceContextSection(store: store)
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
                }
            }
        }
        .scrollEdgeEffectStyle(.hard, for: .all)
        .scrollEdgeEffectHidden(for: .all)
        .navigationTitle("Cliente")
        .toolbarTitleDisplayMode(.inline)
        .toolbarBackground(Color(uiColor: .systemBackground), for: .navigationBar)
        .toolbarBackgroundVisibility(.visible, for: .navigationBar)
        .toolbarVisibility(.hidden, for: .tabBar)
        .sheet(item: $composer) { InvoiceComposerView(store: store, initialCustomerId: $0.customerId) }
    }
}

struct ComposerRoute: Identifiable {
    let id = UUID()
    var customerId: UUID?
}

struct WorkspaceInvoicesView: View {
    let store: WorkspaceStore
    @State private var query = ""
    @State private var status = ""
    @State private var composer: ComposerRoute?
    @State private var expandedMonths: [String: Bool] = [:]
    @State private var appliedRequest: InvoiceListRequest?

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
        List {
            Section {
                ERPSearchField(text: $query, prompt: "Número o clave de acceso")
                Picker("Estado", selection: $status) {
                    Text("Todos").tag("")
                    Text("Borradores").tag("DRAFT")
                    Text("Autorizadas").tag("AUTHORIZED")
                }
            }
            WorkspaceContextSection(store: store)
            InvoiceRecoverySection(store: store)
            if let notice = store.notice {
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
        .scrollEdgeEffectStyle(.hard, for: .all)
        .scrollEdgeEffectHidden(true, for: .bottom)
        .navigationTitle("Facturas")
        .toolbarTitleDisplayMode(.inline)
        .toolbar {
            if store.canCreate {
                ToolbarItem(placement: .primaryAction) {
                    Button("Nuevo", systemImage: "plus") { composer = ComposerRoute() }
                        .disabled(!store.canStartInvoice)
                        .accessibilityIdentifier("new-invoice")
                }
            }
        }
        .sheet(item: $composer) { InvoiceComposerView(store: store, initialCustomerId: $0.customerId) }
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
                    Spacer()
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
                    NavigationLink {
                        WorkspaceInvoiceDetail(store: store, invoiceId: invoice.id, listedNumber: invoice.number,
                                               listedCustomerName: invoice.customerName)
                    } label: {
                        VStack(alignment: .leading, spacing: 5) {
                            Text(invoice.number).font(.headline)
                            Text(invoice.customerName)
                            Text("\(invoice.issueDate) · \(ERPDisplay.money(invoice.total, currency: invoice.currency))")
                            Text(ERPDisplay.status(invoice.status)).font(.subheadline.weight(.medium))
                            if let collection = invoice.collectionStatus {
                                Text("Cobro: \(ERPDisplay.status(collection))").font(.subheadline)
                            }
                        }
                        .foregroundStyle(Color.primary)
                        .padding(.vertical, 4)
                    }
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
                Text("Hay un guardado pendiente de confirmar en esta cuenta.")
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
