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
    private var visible: [ERPInvoice] {
        store.invoices.filter { invoice in
            (status.isEmpty || invoice.status == status) &&
            (query.count != 1 || invoice.sequential.localizedStandardContains(query))
        }
    }
    var body: some View {
        List {
            Section {
                ERPSearchField(text: $query, prompt: "Número o clave de acceso")
                if store.invoiceError == nil && !store.loadingInvoices { ERPListSummary(count: visible.count) }
            }
            WorkspaceContextSection(store: store)
            InvoiceRecoverySection(store: store)
            Section {
                Picker("Estado", selection: $status) {
                    Text("Todos").tag("")
                    Text("Borradores").tag("DRAFT")
                    Text("Autorizadas").tag("AUTHORIZED")
                }
                if let notice = store.notice { Text(notice).accessibilityIdentifier("workspace-notice") }
            }
            Section {
                if store.loadingInvoices { ProgressView("Buscando facturas…") }
                if let error = store.invoiceError {
                    ERPErrorState(message: error) { await store.loadInvoices(query: query, status: status.isEmpty ? nil : status) }
                } else if visible.isEmpty && !store.loadingInvoices {
                    ContentUnavailableView(query.isEmpty && status.isEmpty ? "Sin facturas" : "Sin resultados", systemImage: "doc.text",
                                           description: Text("Revisa el filtro o crea un borrador."))
                } else {
                    ForEach(visible) { invoice in
                        NavigationLink {
                            WorkspaceInvoiceDetail(store: store, invoiceId: invoice.id)
                        } label: {
                            VStack(alignment: .leading, spacing: 6) {
                                Text(store.invoiceNumber(invoice)).font(.headline).foregroundStyle(Color.primary)
                                Text(store.customerName(invoice.partyId)).foregroundStyle(Color.primary)
                                Text("\(invoice.issueDate) · \(ERPDisplay.money(invoice.total, currency: invoice.currency))").foregroundStyle(Color.primary)
                                Text(ERPDisplay.status(invoice.status)).font(.subheadline.weight(.medium)).foregroundStyle(Color.primary)
                            }
                            .foregroundStyle(Color.primary)
                            .padding(.vertical, 4)
                        }
                        .accessibilityIdentifier("workspace-invoice-\(invoice.id.uuidString)")
                    }
                }
            } header: { Text("Facturas").foregroundStyle(Color.primary) }
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
        .task(id: "\(query)|\(status)") {
            do { try await Task.sleep(for: .milliseconds(300)) } catch { return }
            await store.loadInvoices(query: query, status: status.isEmpty ? nil : status)
        }
        .refreshable { await store.loadInvoices(query: query, status: status.isEmpty ? nil : status) }
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
