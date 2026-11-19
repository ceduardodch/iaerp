import IAERPClient
import SwiftUI

struct ProductRegistrationView: View {
    let store: WorkspaceStore
    let useProduct: (ERPProduct) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var code = ""
    @State private var name = ""
    @State private var price = ""
    @FocusState private var focused: Field?
    private enum Field { case code, name, price }
    @State private var taxID: UUID?
    @State private var checkedCode: String?
    @State private var existing: ERPProduct?
    @State private var message: String?
    @State private var busy = false
    @State private var lastInput: ERPProductRegistrationInput?
    @State private var key = UUID().uuidString
    private var normalizedCode: String { code.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var taxes: [ERPTaxCategory] {
        store.setup?.taxCategories.filter { $0.isValid(on: ERPDisplay.fiscalDate(Date())) } ?? []
    }
    private var lookupGuidance: String? {
        if normalizedCode.isEmpty { return "Escribe el código del producto para buscar." }
        if normalizedCode.count > 80 { return "Acorta el código a 80 caracteres como máximo." }
        return nil
    }
    private func registrationInput() throws -> ERPProductRegistrationInput {
        guard !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw ERPClientError.invalidInput("Escribe el nombre del producto para guardarlo.")
        }
        guard let amount = DecimalEntry.parse(price) else {
            throw ERPClientError.invalidInput(price.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? "Escribe el precio unitario sin IVA. Puedes ingresar cero."
                : "Escribe un precio sin signo ni separador de miles, con hasta 12 enteros y 6 decimales.")
        }
        guard store.setup != nil else {
            throw ERPClientError.invalidInput("Pulsa Reintentar para cargar las tarifas de IVA.")
        }
        guard !taxes.isEmpty else {
            throw ERPClientError.invalidInput("Pide a un administrador que habilite una tarifa de IVA vigente para hoy.")
        }
        guard let taxID, taxes.contains(where: { $0.id == taxID }) else {
            throw ERPClientError.invalidInput("Elige una tarifa de IVA vigente para guardar el producto.")
        }
        return try ERPProductRegistrationInput(code: normalizedCode, name: name, unitPrice: amount, taxCategoryId: taxID).validated()
    }
    private var saveGuidance: String? {
        do { _ = try registrationInput(); return nil }
        catch { return friendlyError(error) }
    }

    var body: some View {
        Form {
            Section {
                Text(verbatim: store.displayCompany).font(.headline)
                Text(store.isDemo ? "El producto se guardará en el catálogo de pruebas." : "El producto se guardará en el catálogo de esta empresa.")
            }
            Section {
                TextField("Código", text: $code)
                    .focused($focused, equals: .code)
                    .autocorrectionDisabled().textInputAutocapitalization(.never)
                    .accessibilityIdentifier("catalog-product-code")
                    .onChange(of: code) { checkedCode = nil; existing = nil; message = nil }
                Button("Buscar código") { Task { await lookup() } }
                    .disabled(lookupGuidance != nil)
                    .accessibilityIdentifier("catalog-product-lookup")
            } header: { Text("Código del producto") } footer: {
                if let lookupGuidance {
                    Text(verbatim: lookupGuidance).accessibilityIdentifier("catalog-product-lookup-guidance")
                }
            }
            if let existing {
                Section("Este código ya existe") {
                    Text(verbatim: existing.name)
                    ERPDetailRow(title: "Precio", value: ERPDisplay.money(existing.unitPrice))
                    Button("Usar este producto") { useProduct(existing) }
                        .accessibilityIdentifier("catalog-product-use-existing")
                }
            } else if checkedCode == normalizedCode {
                Section("Datos del producto") {
                    TextField("Nombre", text: $name).focused($focused, equals: .name).accessibilityIdentifier("catalog-product-name")
                    TextField("Precio unitario sin IVA", text: $price).focused($focused, equals: .price).keyboardType(.decimalPad)
                        .accessibilityIdentifier("catalog-product-price")
                    Picker("IVA", selection: $taxID) {
                        Text("Elegir tarifa").tag(nil as UUID?)
                        ForEach(taxes) { category in
                            Text(verbatim: "\(category.name) · \(ERPDisplay.decimal(category.rate)) %").tag(Optional(category.id))
                        }
                    }.accessibilityIdentifier("catalog-product-tax")
                    if store.setup == nil { CatalogSetupRecovery(store: store) }
                    else if taxes.isEmpty { Text("No hay tarifas de IVA vigentes para hoy.") }
                }
                Section {
                    Button("Guardar") { Task { await save() } }
                        .disabled(saveGuidance != nil)
                        .accessibilityIdentifier("catalog-product-save")
                } footer: {
                    if let saveGuidance {
                        Text(verbatim: saveGuidance).accessibilityIdentifier("catalog-product-save-guidance")
                    }
                }
            }
            if busy { ProgressView("Consultando catálogo…") }
            if let message { Text(verbatim: message).accessibilityIdentifier("catalog-product-feedback") }
        }
        .disabled(busy)
        .interactiveDismissDisabled(busy)
        .navigationTitle("Nuevo producto").navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("Listo") { focused = nil }
            }
            ToolbarItem(placement: .cancellationAction) { Button("Cancelar") { dismiss() }.disabled(busy) }
        }
    }

    private func lookup() async {
        guard !busy, let api = store.service as? any ERPCatalogProductRegistrationService else { return }
        let epoch = store.generation
        let code = normalizedCode
        busy = true
        defer { busy = false }
        do {
            let value = try await api.findProduct(code: code)
            guard epoch == store.generation, !Task.isCancelled, normalizedCode == code else { return }
            checkedCode = code
            existing = value
            message = nil
        } catch {
            if epoch == store.generation { message = friendlyError(error) }
        }
    }

    private func save() async {
        guard !busy, checkedCode == normalizedCode, let input = try? registrationInput(),
              let api = store.service as? any ERPCatalogProductRegistrationService else { return }
        let epoch = store.generation
        if lastInput != input { key = UUID().uuidString; lastInput = input }
        busy = true
        defer { busy = false }
        do {
            let product = try await api.createProduct(input, idempotencyKey: key)
            guard epoch == store.generation, !Task.isCancelled else { return }
            useProduct(product)
        } catch {
            guard epoch == store.generation else { return }
            checkedCode = nil
            message = friendlyError(error) + " Busca el código para comprobar si quedó guardado."
        }
    }
}

struct CatalogSetupRecovery: View {
    let store: WorkspaceStore
    @State private var loading = false
    var body: some View {
        if store.setup == nil {
            if loading { ProgressView("Consultando tarifas de IVA…") }
            else {
                ERPErrorState(message: "No se pudieron cargar las tarifas de IVA de la empresa.") {
                    loading = true
                    await store.loadCatalog()
                    loading = false
                }
            }
        }
    }
}
