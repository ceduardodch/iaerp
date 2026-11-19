import IAERPClient
import SwiftUI

struct CustomerRegistrationView: View {
    let store: WorkspaceStore
    let onSelected: (ERPParty) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var type = "RUC"
    @State private var number = ""
    @State private var name = ""
    @State private var address = ""
    @State private var email = ""
    @State private var checked = false
    @State private var existing: ERPParty?
    @State private var pending: CustomerRegistrationAttempt?
    @State private var message: String?
    @State private var loading = false
    @State private var ready = false
    @State private var retryAvailable = false
    @FocusState private var focus: Field?

    private enum Field { case number, name, address, email }
    private var api: (any ERPCustomerRegistrationService)? { store.service as? any ERPCustomerRegistrationService }
    private var validNumber: Bool {
        number.utf8.count == (type == "RUC" ? 13 : 10) && number.utf8.allSatisfy { (48...57).contains($0) }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(verbatim: store.displayCompany).font(.headline)
                    Text(store.isDemo ? "El cliente se guardará en el catálogo de pruebas." : "Al guardar, el cliente quedará en el catálogo real de esta empresa.")
                        .font(.subheadline)
                } header: { Text("Empresa") }
                if let pending {
                    Section {
                        Text(verbatim: pending.input.name).font(.headline)
                        Text(verbatim: "\(pending.input.identificationType) \(pending.input.identificationNumber)")
                        Text("El guardado anterior necesita confirmación. Consulta si el cliente ya existe en esta empresa.")
                        Button("Consultar guardado") { Task { await lookup() } }
                            .accessibilityIdentifier("customer-recover")
                        if retryAvailable {
                            Button("Reintentar el mismo guardado") { Task { await save(retrying: true) } }
                                .accessibilityIdentifier("customer-retry")
                        }
                    } header: { Text("Alta pendiente") }
                } else if ready {
                    Section {
                        Picker("Documento", selection: Binding(get: { type }, set: { type = $0; resetLookup() })) {
                            Text("RUC").tag("RUC")
                            Text("Cédula").tag("CEDULA")
                        }
                        .accessibilityIdentifier("customer-id-type")
                        TextField(type == "RUC" ? "RUC de 13 dígitos" : "Cédula de 10 dígitos",
                                  text: Binding(get: { number }, set: { number = $0; resetLookup() }))
                            .keyboardType(.numberPad).focused($focus, equals: .number)
                            .accessibilityIdentifier("customer-id-number")
                        Button("Buscar identificación") { Task { await lookup() } }
                            .disabled(!validNumber)
                            .accessibilityIdentifier("customer-lookup")
                    } header: { Text("Identificación") }
                }
                if let existing {
                    Section {
                        Text(verbatim: existing.name).font(.headline)
                        Text(verbatim: "\(existing.identificationType) \(existing.identificationNumber)")
                        Button("Usar este cliente") { finish(existing) }
                            .accessibilityIdentifier("customer-use-existing")
                    } header: { Text("Cliente encontrado") }
                } else if checked && pending == nil {
                    Section {
                        TextField("Nombre o razón social", text: $name).focused($focus, equals: .name)
                            .accessibilityIdentifier("customer-name")
                        TextField("Dirección (opcional)", text: $address, axis: .vertical).focused($focus, equals: .address)
                        TextField("Correo (opcional)", text: $email)
                            .keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled()
                            .focused($focus, equals: .email)
                        Button("Guardar cliente") { Task { await save(retrying: false) } }
                            .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                            .accessibilityIdentifier("customer-save")
                    } header: { Text("Datos del nuevo cliente") }
                }
                if loading { ProgressView("Consultando IAERP…") }
                if let message {
                    Section {
                        Text(verbatim: message).accessibilityIdentifier("customer-registration-message")
                        if !ready { Button("Volver a consultar") { restore() } }
                    }
                }
            }
            .disabled(loading)
            .scrollDismissesKeyboard(.immediately)
            .navigationTitle("Nuevo cliente")
            .toolbarTitleDisplayMode(.inline)
            .interactiveDismissDisabled(loading)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancelar") { dismiss() }.disabled(loading) }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Listo") { focus = nil }
                }
            }
            .task(id: store.generation) { restore() }
        }
    }

    private func resetLookup() {
        guard pending == nil else { return }
        checked = false
        existing = nil
        name = ""
        address = ""
        email = ""
        message = nil
    }

    private func restore() {
        ready = false
        type = "RUC"
        number = ""
        name = ""
        email = ""
        address = ""
        pending = nil
        message = nil
        existing = nil
        checked = false
        retryAvailable = false
        do {
            pending = try store.customerRegistrationJournal.pending(in: store.customerRegistrationScope(), persist: store.persistsCustomerRegistration)
            ready = true
        } catch { message = friendlyError(error) }
    }

    private func lookup() async {
        guard !loading, let api else { return }
        focus = nil
        loading = true
        message = nil
        existing = nil
        retryAvailable = false
        checked = false
        let epoch = store.generation
        defer { if epoch == store.generation { loading = false } }
        do {
            let scope = try store.customerRegistrationScope()
            let party = try await api.findCustomer(identificationType: pending?.input.identificationType ?? type,
                                                   identificationNumber: pending?.input.identificationNumber ?? number)
            guard epoch == store.generation, !Task.isCancelled else { return }
            if let pending, let party {
                // A concurrent user may have created the same RUC. Present its actual name for selection.
                try store.customerRegistrationJournal.finish(pending, persist: store.persistsCustomerRegistration)
                type = party.identificationType
                number = party.identificationNumber
                self.pending = nil
                existing = party
            } else if let pending {
                retryAvailable = pending.scope.allowsRetry(in: scope)
                message = retryAvailable ? "La empresa aún no registra este cliente. Puedes reenviar la solicitud original." : "Para reintentar, entra con la configuración de la cuenta que inició el alta."
            } else {
                existing = party
                checked = party == nil
            }
        } catch {
            if epoch == store.generation { message = friendlyError(error) }
        }
    }

    private func save(retrying: Bool) async {
        guard !loading, let api, existing == nil, retrying ? retryAvailable : checked else { return }
        let epoch = store.generation
        let persist = store.persistsCustomerRegistration
        let journal = store.customerRegistrationJournal
        focus = nil
        message = nil
        loading = true
        defer { if epoch == store.generation { loading = false } }
        var attempted: CustomerRegistrationAttempt?
        do {
            let scope = try store.customerRegistrationScope()
            let attempt: CustomerRegistrationAttempt
            if retrying {
                guard let original = try journal.pending(in: scope, persist: persist),
                      original.id == pending?.id, original.scope.allowsRetry(in: scope) else {
                    throw InvoiceRecoveryError.wrongIdentity
                }
                retryAvailable = false
                if let party = try await api.findCustomer(identificationType: original.input.identificationType,
                                                          identificationNumber: original.input.identificationNumber) {
                    guard epoch == store.generation, !Task.isCancelled else { return }
                    try journal.finish(original, persist: persist)
                    pending = nil
                    existing = party
                    return
                }
                guard epoch == store.generation, !Task.isCancelled else { return }
                attempt = original
            } else {
                let input = try ERPCustomerRegistrationInput(identificationType: type, identificationNumber: number,
                                                            name: name, address: address, email: email).validated()
                attempt = try journal.begin(input, scope: scope, persist: persist)
            }
            attempted = attempt
            pending = attempt
            let party = try await api.createCustomer(attempt.input, idempotencyKey: attempt.id.uuidString)
            guard epoch == store.generation else { return }
            try journal.finish(attempt, persist: persist)
            pending = nil
            finish(party)
        } catch {
            guard epoch == store.generation else { return }
            do {
                if !retrying, let attempted, let known = error as? ERPClientError {
                    switch known {
                    case .invalidInput, .forbidden, .customerRegistrationConflict:
                        try journal.finish(attempted, persist: persist)
                        pending = nil
                        type = attempted.input.identificationType
                        number = attempted.input.identificationNumber
                        checked = false
                    default: break
                    }
                }
                message = friendlyError(error)
            } catch { message = friendlyError(error) }
        }
    }

    private func finish(_ party: ERPParty) {
        store.rememberCustomer(party, generation: store.generation)
        onSelected(party)
        dismiss()
    }
}

struct CustomerTestProductPicker: View {
    let store: WorkspaceStore
    let customer: ERPParty
    @State private var query = ""
    @State private var selected: ERPProduct?
    @State private var prepareTask: Task<Void, Never>?
    @State private var prepareGeneration: UUID?
    @State private var preparing = false
    @State private var addingProduct = false
    @State private var error: String?

    private func tax(for product: ERPProduct) -> ERPTaxCategory? {
        let date = ERPDisplay.fiscalDate(Date())
        return store.setup?.taxCategories.first { $0.id == product.taxCategoryId && $0.isValid(on: date) }
    }

    var body: some View {
        List {
            Section {
                Text(verbatim: customer.name).font(.headline)
                Text(verbatim: customer.identificationNumber)
                Text("Al continuar, el simulador del Mac usará este cliente y el producto elegido. El total de prueba es USD 0,05 con IVA.")
            } header: { Text("Cliente") }
            Section {
                CatalogSetupRecovery(store: store)
                ERPSearchField(text: $query, prompt: "Buscar productos")
                if store.loadingProducts { ProgressView("Buscando productos…") }
                if let message = store.catalogError {
                    ERPErrorState(message: message) { await store.loadProducts(query: query) }
                } else if store.products.isEmpty && !store.loadingProducts {
                    Text("Sin productos para esta búsqueda.")
                }
                ForEach(store.products) { product in
                    Button {
                        selected = product
                        error = nil
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(verbatim: product.name).font(.headline)
                            Text(verbatim: product.code ?? "")
                            if let rate = tax(for: product)?.rate {
                                Text("\(ERPDisplay.money(product.unitPrice)) · IVA \(ERPDisplay.decimal(rate)) %")
                            } else {
                                Text(store.setup == nil ? "Tarifa pendiente de cargar" : "IVA sin vigencia para hoy")
                            }
                        }
                        .foregroundStyle(.primary)
                        .frame(minHeight: 44, alignment: .leading)
                    }
                    .disabled(tax(for: product) == nil)
                    .accessibilityAddTraits(selected?.id == product.id ? .isSelected : [])
                    .accessibilityIdentifier("test-product-\(product.id.uuidString)")
                }
            } header: { Text("Productos") }
            if let selected, let tax = tax(for: selected) {
                Section {
                    ERPDetailRow(title: "Producto", value: selected.name)
                    ERPDetailRow(title: "Precio de catálogo", value: ERPDisplay.money(selected.unitPrice))
                    ERPDetailRow(title: "Total de prueba con IVA", value: ERPDisplay.money(Decimal(string: "0.05")!))
                    ERPDetailRow(title: "IVA", value: "\(ERPDisplay.decimal(tax.rate)) %")
                    Button("Continuar en pruebas") {
                        guard !preparing else { return }
                        preparing = true
                        let epoch = store.generation
                        prepareGeneration = epoch
                        prepareTask = Task {
                            defer { if epoch == store.generation { preparing = false } }
                            do {
                                try await store.prepareBTOBTestInvoice(customer: customer, product: selected, tax: tax)
                            } catch {
                                if epoch == store.generation { self.error = friendlyError(error) }
                            }
                        }
                    }
                    .accessibilityIdentifier("confirm-test-product")
                } header: { Text("Producto elegido") }
            }
            if preparing { ProgressView("Preparando el comprobante en el simulador…") }
            if let error { Text(verbatim: error) }
        }
        .onDisappear { if prepareGeneration == store.generation { prepareTask?.cancel() } }
        .disabled(preparing)
        .navigationTitle("Factura de prueba")
        .toolbarTitleDisplayMode(.inline)
        .toolbar {
            if store.context?.permits("products:create") == true {
                ToolbarItem(placement: .primaryAction) {
                    Button("Nuevo producto", systemImage: "plus") { addingProduct = true }
                        .accessibilityIdentifier("trial-new-product")
                }
            }
        }
        .sheet(isPresented: $addingProduct) {
            NavigationStack {
                ProductRegistrationView(store: store) { product in
                    store.rememberProduct(product)
                    selected = product
                    error = nil
                    addingProduct = false
                }
            }
        }
        .task(id: query) {
            do { try await Task.sleep(for: .milliseconds(300)) } catch { return }
            await store.loadProducts(query: query)
        }
    }
}
