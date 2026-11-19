import IAERPClient
import SwiftUI

enum PortfolioFilter: String, CaseIterable {
    case all = "Pendientes"
    case overdue = "Vencidas"
}

struct CollectionsView: View {
    let store: WorkspaceStore
    @State var filter: PortfolioFilter
    @State private var rows: [CollectionAccount]?
    @State private var error: String?
    @State private var search = ""
    @State private var request = UUID()

    private var groups: [(id: UUID, accounts: [CollectionAccount])] {
        let term = search.trimmingCharacters(in: .whitespacesAndNewlines)
        let matches = (rows ?? []).filter { row in
            (filter == .all || row.overdue) && (term.isEmpty ||
                row.customerName.localizedStandardContains(term) || row.invoiceNumber.localizedStandardContains(term))
        }
        return Dictionary(grouping: matches, by: \.partyId)
            .map { (id: $0.key, accounts: $0.value.sorted { ($0.dueDate, $0.invoiceNumber) < ($1.dueDate, $1.invoiceNumber) }) }
            .sorted { $0.accounts[0].customerName.localizedStandardCompare($1.accounts[0].customerName) == .orderedAscending }
    }

    var body: some View {
        List {
            Section {
                Picker("Estado de cobro", selection: $filter) {
                    ForEach(PortfolioFilter.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }.pickerStyle(.segmented)
            }
            if let error {
                ERPErrorState(message: error) { await load() }
            } else if rows == nil {
                ProgressView("Consultando cuentas…")
            } else if groups.isEmpty {
                ContentUnavailableView(search.isEmpty ?
                    (filter == .overdue ? "Sin cuentas vencidas" : "Sin saldos pendientes") : "Sin coincidencias",
                    systemImage: search.isEmpty ? "checkmark.circle" : "magnifyingglass")
            } else {
                ForEach(groups, id: \.id) { group in
                    Section(group.accounts[0].customerName) {
                        ForEach(group.accounts) { account in
                            NavigationLink {
                                CollectionAccountView(store: store, accountID: account.id, expectedGeneration: store.generation) { latest in
                                    guard let index = rows?.firstIndex(where: { $0.id == latest.id }) else { return }
                                    rows?[index] = latest
                                }
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(ERPDisplay.money(account.openAmount, currency: account.currency)).font(.headline)
                                    Text("Factura \(account.invoiceNumber)")
                                    Text("\(account.overdue ? "Vencida" : "Vence") el \(ERPDisplay.longFiscalDate(account.dueDate))")
                                        .font(.footnote)
                                    if let promise = account.promisedDate {
                                        Text("Promesa para el \(ERPDisplay.longFiscalDate(promise))").font(.footnote)
                                    }
                                }.padding(.vertical, 3)
                            }.accessibilityIdentifier("collection-account-\(account.id.uuidString)")
                        }
                    }
                }
            }
        }
        .navigationTitle("Cobranza")
        .searchable(text: $search, prompt: "Cliente o número de factura")
        .refreshable { await load() }
        .task(id: store.generation) { await load() }
    }

    private func load() async {
        let current = UUID(), generation = store.generation
        request = current
        guard let service = store.service as? any ERPCollectionsService, store.canReadDashboard else {
            rows = nil; error = friendlyError(ERPClientError.forbidden); return
        }
        do {
            let result = try await service.collectionAccounts()
            guard request == current, store.generation == generation, !Task.isCancelled else { return }
            rows = result; error = nil
        } catch {
            guard request == current, store.generation == generation, !Task.isCancelled else { return }
            rows = nil; self.error = friendlyError(error)
        }
    }
}

struct CollectionValue: View {
    let title: String
    let value: String
    @Environment(\.dynamicTypeSize) private var typeSize

    init(_ title: String, value: String) {
        self.title = title
        self.value = value
    }

    var body: some View {
        let layout = typeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 2))
            : AnyLayout(HStackLayout(alignment: .firstTextBaseline, spacing: 12))
        layout {
            Text(title)
            if !typeSize.isAccessibilitySize { Spacer(minLength: 0) }
            Text(verbatim: value)
                .multilineTextAlignment(typeSize.isAccessibilitySize ? .leading : .trailing)
        }
        .foregroundStyle(Color.primary)
        .fixedSize(horizontal: false, vertical: true)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

enum CollectionSheet: String, Identifiable {
    case promise, dueDate
    var id: Self { self }
}

private struct CollectionTermsReview: Identifiable {
    let id = UUID()
    let kind: CollectionSheet
    let account: CollectionAccount
}

private struct CollectionPanel<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    init(_ title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(.headline).accessibilityAddTraits(.isHeader)
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
    }
}

struct CollectionAccountView: View {
    let store: WorkspaceStore
    let accountID: UUID
    let expectedGeneration: UUID
    let received: (CollectionAccount) -> Void
    @State private var account: CollectionAccount?
    @State private var readError: String?
    @State private var feedback: String?
    @State private var sheet: CollectionTermsReview?
    @State private var sending = false
    @State private var request = UUID()
    @State private var lastAction: CollectionAction?
    @State private var lastActionKey = UUID()
    @Environment(\.scenePhase) private var phase

    @ViewBuilder private var sections: some View {
        if let readError {
            ERPErrorState(message: readError) { await load() }
        } else if let account {
            CollectionPanel(account.customerName) {
                CollectionValue("Factura", value: account.invoiceNumber)
                CollectionValue("Saldo pendiente", value: money(account.openAmount, account))
                    .font(.headline)
                CollectionValue(account.overdue ? "Vencida desde" : "Vencimiento",
                               value: ERPDisplay.longFiscalDate(account.dueDate))
                    .accessibilityIdentifier("collection-contract-date")
                DisclosureGroup("Detalle del saldo") {
                    CollectionValue("Importe original", value: money(account.originalAmount, account))
                    CollectionValue("Pagos", value: money(account.cashAmount, account))
                    CollectionValue("Retenciones", value: money(account.retentionAmount, account))
                }
            }
            CollectionPanel("Correo de cobro") {
                if let email = account.email, !email.isEmpty {
                    CollectionValue("Destinatario", value: email)
                        .accessibilityIdentifier("collection-recipient")
                } else {
                    Text("Falta el correo del cliente. Actualízalo en su ficha y vuelve a consultar.")
                }
                if let state = account.lastReminderStatus {
                    CollectionValue("Último aviso", value: reminderLabel(state))
                        .accessibilityIdentifier("collection-receipt")
                    if let stamp = account.lastReminderAt {
                        Text(CollectionDates.contactTime(stamp)).font(.footnote)
                    }
                    if ["PENDING", "PROCESSING", "UNCERTAIN"].contains(state) {
                        Button("Consultar estado") { Task { await load() } }
                    }
                }
                if !canNotify {
                    Text("Tu perfil puede consultar esta cuenta. Pide permiso de cobranza al administrador para enviar correos.")
                } else if let reason = account.reminderBlockedReason {
                    Text(reason)
                }
                if canNotify, account.canEnableReminders && !account.collectionEnabled {
                    Button("Habilitar avisos para esta factura") { Task { _ = await save(.enableReminders) } }
                        .accessibilityIdentifier("collection-enable")
                } else if canNotify, account.collectionEnabled && account.reminderBlockedReason == nil,
                          let email = account.email, !email.isEmpty {
                    Button("Enviar recordatorio", systemImage: "envelope") {
                        Task { _ = await save(.reminder(recipient: email, amount: account.openAmount, dueDate: account.dueDate)) }
                    }
                    .accessibilityHint("Envía un correo de cobro al destinatario indicado con el saldo pendiente.")
                    .accessibilityIdentifier("collection-send")
                }
            }
            CollectionPanel("Fechas de cobranza") {
                CollectionValue("Promesa de pago", value: account.promisedDate.map(ERPDisplay.longFiscalDate) ?? "Sin registrar")
                if let date = account.promisedDate {
                    Text("Pausa de avisos hasta el \(ERPDisplay.longFiscalDate(date)), inclusive.").font(.footnote)
                }
                if canEditTerms {
                    Button(account.promisedDate == nil ? "Registrar promesa" : "Editar promesa") { sheet = CollectionTermsReview(kind: .promise, account: account) }
                        .accessibilityIdentifier("collection-promise")
                    if account.installments.contains(where: { $0.openAmount > 0 }) {
                        Button("Cambiar vencimiento") { sheet = CollectionTermsReview(kind: .dueDate, account: account) }.accessibilityIdentifier("collection-due")
                    } else {
                        Text("La factura ya no tiene cuotas pendientes para ajustar.")
                    }
                } else {
                    Text("Pide permiso de gestión de plazos al administrador para cambiar estas fechas.")
                }
            }
        } else {
            ProgressView("Consultando factura…")
        }
        if let feedback {
            Text(feedback).accessibilityIdentifier("collection-feedback")
        }
    }

    var body: some View {
        GeometryReader { viewport in
            ScrollView {
                VStack(alignment: .leading, spacing: 16) { sections }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(Color(uiColor: .systemGroupedBackground))
            .frame(width: viewport.size.width, height: viewport.size.height)
            .clipped()
        }
        .disabled(sending)
        .overlay { if sending { ProgressView("Guardando…").padding().background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12)) } }
        .toolbarVisibility(.hidden, for: .tabBar)
        .scrollEdgeEffectHidden(true, for: .vertical)
        .toolbarBackground(.visible, for: .navigationBar)
        .toolbarBackground(Color(uiColor: .systemBackground), for: .navigationBar)
        .navigationTitle("Cuenta por cobrar")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { if !sending { await load() } }
        .task(id: accountID) { await load() }
        .task(id: shouldPoll) {
            guard shouldPoll else { return }
            for _ in 0..<12 {
                do { try await Task.sleep(for: .seconds(4)) } catch { return }
                guard shouldPoll else { return }
                await load()
            }
        }
        .sheet(item: $sheet) { review in
            CollectionTermsForm(account: review.account, kind: review.kind) { change in
                await save(change)
            }
        }
    }

    private var canNotify: Bool { store.context?.permits("collections:notify") == true }
    private var canEditTerms: Bool { store.context?.permits("collections:terms") == true }
    private var shouldPoll: Bool {
        guard phase == .active, !sending, sheet == nil, let state = account?.lastReminderStatus else { return false }
        return ["PENDING", "PROCESSING", "UNCERTAIN"].contains(state)
    }
    private func reminderLabel(_ state: String) -> String {
        switch state {
        case "PENDING", "PROCESSING": "En proceso de envío"
        case "SENT": store.isDemo ? "Aceptado en la prueba" : "Aceptado para envío"
        case "FAILED": "Falló el envío. Revisa la dirección y la conexión de correo de tu empresa."
        case "UNCERTAIN": "El proveedor aún no confirma el envío."
        case "CANCELLED": "Cancelado"
        default: "Pendiente de verificar"
        }
    }
    private func money(_ value: Decimal, _ account: CollectionAccount) -> String {
        ERPDisplay.money(value, currency: account.currency)
    }
    private func update(_ row: CollectionAccount) {
        account = row
        readError = nil
        received(row)
    }
    private func load() async {
        let generation = store.generation, current = UUID()
        request = current
        guard let service = store.service as? any ERPCollectionsService else { readError = friendlyError(ERPClientError.forbidden); return }
        do {
            let row = try await service.collectionAccount(accountID)
            guard request == current, generation == store.generation, !Task.isCancelled else { return }
            update(row)
        } catch {
            guard request == current, generation == store.generation, !Task.isCancelled else { return }
            readError = friendlyError(error); account = nil
        }
    }

    private func save(_ change: CollectionAction) async -> String? {
        guard !sending, expectedGeneration == store.generation, store.phase == .ready,
              let service = store.service as? any ERPCollectionsService else { return "Vuelve a abrir la cuenta." }
        switch change {
        case .promise, .dueDate:
            guard canEditTerms else { return friendlyError(ERPClientError.forbidden) }
        case .enableReminders, .reminder:
            guard canNotify else { return friendlyError(ERPClientError.forbidden) }
        }
        sending = true
        defer { sending = false }
        request = UUID()
        let generation = store.generation
        if lastAction != change { lastAction = change; lastActionKey = UUID() }
        do {
            let row = try await service.changeCollectionAccount(accountID, action: change, key: lastActionKey)
            guard generation == store.generation else { return "Cambió la sesión." }
            update(row)
            lastAction = nil
            switch change {
            case .reminder:
                // The status row is the receipt, including while the provider is processing.
                feedback = nil
            case .enableReminders: feedback = "Avisos habilitados para esta factura."
            case .promise(let date, _): feedback = date == nil ? "Promesa retirada." : "Promesa de pago guardada."
            case .dueDate: feedback = "Vencimiento comercial actualizado."
            }
            await store.loadDashboard()
            return nil
        } catch {
            guard generation == store.generation else { return "Cambió la sesión." }
            let message = friendlyError(error)
            feedback = message
            await load()
            return message
        }
    }
}
