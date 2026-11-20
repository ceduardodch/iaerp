import IAERPClient
import IAERPIdentity
import Combine
import SwiftUI
import UIKit

struct WorkspaceRootView: View {
    @State private var store: WorkspaceStore
    @State private var didPrepare = false
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.colorScheme) private var colorScheme

    init() {
        #if DEBUG && targetEnvironment(simulator)
        if ProcessInfo.processInfo.arguments.contains("-saved-accounts-fixture") {
            _store = State(initialValue: SavedAccountsFixture.makeStore())
            return
        }
        #endif
        _store = State(initialValue: WorkspaceStore())
    }

    var body: some View {
        Group {
            switch store.phase {
            case .signedOut: WelcomeView(store: store)
            case .loading:
                ProgressView("Cargando empresa…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            case .ready:
                TabView {
                    Tab("Inicio", systemImage: "house") {
                        NavigationStack { WorkspaceHomeView(store: store) }
                    }
                    Tab("Clientes", systemImage: "person.2") {
                        NavigationStack { WorkspaceClientsView(store: store) }
                    }
                    Tab("Facturas", systemImage: "doc.text") {
                        NavigationStack { WorkspaceInvoicesView(store: store) }
                    }
                    Tab("Cuenta", systemImage: "person.crop.circle") {
                        NavigationStack { WorkspaceAccountView(store: store) }
                    }
                }
                .tint(colorScheme == .dark ? Color(red: 0.60, green: 0.76, blue: 1) :
                            Color(red: 0.09, green: 0.28, blue: 0.65))
                .id(store.generation)
            }
        }
        .sheet(isPresented: Binding(get: { store.preparedTrialInvoiceID != nil }, set: { if !$0 { store.closePrivateTrial() } })) {
            if let id = store.preparedTrialInvoiceID {
                NavigationStack {
                    WorkspaceInvoiceDetail(store: store.activeTrialStore ?? store, invoiceId: id)
                        .toolbar {
                            ToolbarItem(placement: .cancellationAction) {
                                Button("Cerrar") { store.closePrivateTrial() }
                            }
                        }
                }
            }
        }
        .preferredColorScheme(ProcessInfo.processInfo.arguments.contains("-dark-mode") ? .dark : nil)
        .onChange(of: scenePhase) { _, phase in
            PrivacyShield.update(visible: phase != .active)
            if phase == .background { store.lockForBackground() }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.willResignActiveNotification)) { _ in
            PrivacyShield.update(visible: true)
        }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)) { _ in
            PrivacyShield.update(visible: false)
        }
        .task {
            guard !didPrepare else { return }
            didPrepare = true
            store.findSavedSession()
            do { try await store.documents.reset(generation: store.generation) }
            catch { store.connectionError = "No se pudieron borrar los documentos temporales. Intenta de nuevo." }
            #if DEBUG && targetEnvironment(simulator)
            let arguments = ProcessInfo.processInfo.arguments
            if arguments.contains("-workspace-demo") {
                await store.startDemo(readOnly: arguments.contains("-read-only"),
                                      company: arguments.contains("-btob-sandbox") ? .btobSandbox : nil)
            }
            #endif
        }
    }
}

struct WorkspaceHomeView: View {
    let store: WorkspaceStore
    @State private var composer: ComposerRoute?
    @State private var savedInvoice: ERPInvoice?
    @State private var showingCutoff = false

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var page: SummaryPage = .balances

    private enum SummaryPage: Hashable { case balances, collections }

    var body: some View {
        GeometryReader { viewport in
            Group {
                if dynamicTypeSize >= .accessibility3, store.canReadDashboard,
                   store.dashboardError == nil, let summary = store.dashboard {
                    TabView(selection: $page) {
                        scrollContent {
                            balances
                            Button("Ver cobros") { page = .collections }
                                .frame(minHeight: 44)
                                .accessibilityIdentifier("home-view-collections")
                        }
                        .tag(SummaryPage.balances)
                        scrollContent {
                            companyTitle
                            collections(summary)
                            Button("Ver saldos") { page = .balances }
                                .frame(minHeight: 44)
                        }
                        .tag(SummaryPage.collections)
                    }
                    .tabViewStyle(.page(indexDisplayMode: .never))
                } else {
                    scrollContent {
                        balances
                        if store.canReadDashboard, store.dashboardError == nil, let summary = store.dashboard {
                            collections(summary)
                        }
                    }
                }
            }
            .frame(width: viewport.size.width, height: max(0, viewport.size.height - viewport.safeAreaInsets.bottom),
                   alignment: .top)
            .clipped()
            .padding(.bottom, viewport.safeAreaInsets.bottom)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .toolbarBackground(Color(uiColor: .systemBackground), for: .tabBar)
        .toolbarBackground(.visible, for: .tabBar)
        .navigationTitle("Inicio")
        .toolbar {
            if let summary = store.dashboard {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        showingCutoff = true
                    } label: {
                        Label(shortDate(summary.asOf), systemImage: "calendar")
                            .labelStyle(.titleOnly)
                    }
                    .help("Ver fecha y cálculo del resumen")
                    .accessibilityIdentifier("home-as-of")
                    .popover(isPresented: $showingCutoff) {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Resumen del \(ERPDisplay.longFiscalDate(summary.asOf))").font(.headline)
                            Text("Cobrado este mes incluye efectivo y retenciones.")
                            Button("Cerrar") { showingCutoff = false }
                        }
                        .padding()
                        .presentationCompactAdaptation(.popover)
                    }
                }
            }
            if store.canCreate {
                ToolbarItem(placement: .primaryAction) {
                    Button("Nueva factura", systemImage: "plus") { composer = ComposerRoute() }
                        .disabled(!store.canStartInvoice)
                        .accessibilityIdentifier("home-new-invoice")
                }
            }
        }
        .toolbarTitleDisplayMode(.inline)
        .sheet(item: $composer) { route in
            InvoiceComposerView(store: store, initialCustomerId: route.customerId) { invoice in
                savedInvoice = invoice
                page = .balances
            }
        }
        .task { if store.canReadDashboard { await store.loadDashboard() } }
    }

    private func scrollContent<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16, content: content)
                .padding(16)
                .padding(.bottom, dynamicTypeSize >= .accessibility3 ? 32 : 0)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .refreshable { if store.canReadDashboard { await store.loadDashboard() } }
    }

    private var companyTitle: some View {
        Text(verbatim: store.displayCompany)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(Color.primary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityAddTraits(.isHeader)
    }

    @ViewBuilder private var balances: some View {
        companyTitle
        if let savedInvoice {
            SavedInvoiceLink(store: store, saved: savedInvoice, linkIdentifier: "home-open-draft")
        }
        InvoiceRecoverySection(store: store)
        summaryContent
    }

    private func collections(_ summary: ERPHomeSummary) -> some View {
        metricCard("Cobrado este mes", amount: summary.collectedThisMonth, currency: summary.currency,
                   identifier: "home-metric-collected")
    }

    @ViewBuilder private var summaryContent: some View {
        if !store.canReadDashboard {
            Text("Tu perfil no tiene permiso para consultar la cartera.")
                .accessibilityIdentifier("home-dashboard-permission")
        } else if let error = store.dashboardError {
            ERPErrorState(message: error) { await store.loadDashboard() }
        } else if let summary = store.dashboard {
            NavigationLink {
                CollectionsView(store: store, filter: .all)
            } label: {
                HStack {
                    metric("Por cobrar", value: summary.receivable, currency: summary.currency,
                           featured: true, identifier: "home-amount-receivable")
                    Spacer()
                    Image(systemName: "chevron.right").accessibilityHidden(true)
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .foregroundStyle(.white)
                .background(Color("AccentColor"), in: RoundedRectangle(cornerRadius: 16))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Por cobrar, \(ERPDisplay.money(summary.receivable, currency: summary.currency))")
            .accessibilityHint("Abre las cuentas pendientes por cliente.")
            .accessibilityIdentifier("home-metric-receivable")
            NavigationLink {
                CollectionsView(store: store, filter: .overdue)
            } label: {
                HStack {
                    metric("Vencido", value: summary.overdue, currency: summary.currency, identifier: "home-amount-overdue")
                    Spacer()
                    Image(systemName: "chevron.right").accessibilityHidden(true)
                }
                .padding(16)
                .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Vencido, \(ERPDisplay.money(summary.overdue, currency: summary.currency))")
            .accessibilityHint("Abre las cuentas vencidas.")
            .accessibilityIdentifier("home-metric-overdue")
        } else {
            ProgressView("Consultando cartera…")
        }
    }

    private func metricCard(_ title: String, amount: Decimal, currency: String, identifier: String) -> some View {
        metric(title, value: amount, currency: currency, identifier: identifier)
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
    }

    private func shortDate(_ fiscalDate: String) -> String {
        let parts = fiscalDate.split(separator: "-")
        guard parts.count == 3 else { return fiscalDate }
        return parts.reversed().joined(separator: "/")
    }

    private func metric(_ title: String, value: Decimal, currency: String,
                        featured: Bool = false, identifier: String) -> some View {
        let amount = ERPDisplay.money(value, currency: currency)
        let heading = Text(title).font(featured ? .headline : .subheadline)
        let figure = Text(amount).font(featured ? .largeTitle.bold() : .title2.weight(.semibold))
        return VStack(alignment: .leading, spacing: 4) {
            Text("\(heading)\(featured ? "\n" : "  ")\(figure)")
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier(identifier)
        }
        .padding(.vertical, 4)
    }
}

/// A window-level cover also shields presented forms and document previews.
@MainActor enum PrivacyShield {
    static let tag = 842_017
    static func update(visible: Bool) {
        for scene in UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }) {
            for window in scene.windows where !window.isHidden {
                if visible {
                    guard window.viewWithTag(tag) == nil else { continue }
                    let cover = UIView(frame: window.bounds)
                    cover.tag = tag
                    cover.accessibilityIdentifier = "privacy-shield"
                    cover.backgroundColor = .systemBackground
                    cover.autoresizingMask = [.flexibleWidth, .flexibleHeight]
                    let label = UILabel()
                    label.text = "IAERP"
                    label.font = .preferredFont(forTextStyle: .title1)
                    label.adjustsFontForContentSizeCategory = true
                    label.translatesAutoresizingMaskIntoConstraints = false
                    cover.addSubview(label)
                    NSLayoutConstraint.activate([
                        label.centerXAnchor.constraint(equalTo: cover.centerXAnchor),
                        label.centerYAnchor.constraint(equalTo: cover.centerYAnchor),
                    ])
                    window.addSubview(cover)
                } else { window.viewWithTag(tag)?.removeFromSuperview() }
            }
        }
    }
}

struct WelcomeView: View {
    let store: WorkspaceStore
    @State private var connection: AccountConnectionRoute?
    @State private var profileToForget: SavedIdentityProfile?

    var body: some View {
        NavigationStack {
            List {
                if store.savedProfiles.isEmpty { Section {
                    VStack(alignment: .leading, spacing: 12) {
                        Image(systemName: "doc.text")
                            .font(.largeTitle).foregroundStyle(.tint)
                            .accessibilityHidden(true)
                        Text("Clientes y facturas, desde tu iPhone.").font(.title2.weight(.semibold))
                    }
                    .padding(.vertical, 12)
                } }
                if !store.savedProfiles.isEmpty {
                    SavedAccountsSection(profiles: store.savedProfiles, connecting: store.connecting,
                        select: { profile in Task { await store.restoreSession(profile: profile) } },
                        reconnect: { connection = AccountConnectionRoute(configuration: $0.configuration) },
                        forget: { profileToForget = $0 })
                }
                Section {
                    Button(store.savedProfiles.isEmpty ? "Entrar a mi empresa" : "Añadir cuenta", systemImage: "person.badge.plus") {
                        connection = AccountConnectionRoute(configuration: store.savedProfiles.first?.configuration)
                    }
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("connect-company")
                        .disabled(store.connecting)
                }
                if let message = store.connectionError {
                    Section {
                        Text(message).foregroundStyle(Color.primary).accessibilityIdentifier("connection-error")
                        if let configuration = store.connectionConfigurationForRetry {
                            Button("Volver a iniciar sesión", systemImage: "arrow.clockwise") {
                                connection = AccountConnectionRoute(configuration: configuration)
                            }
                            .frame(minHeight: 44).disabled(store.connecting)
                        }
                    }
                }
                if store.connecting { Section { ProgressView("Actualizando sesión…") } }
                if let message = store.notice {
                    Section { Text(message).foregroundStyle(Color.primary) }
                }
            }
            .scrollEdgeEffectStyle(.hard, for: .all)
        .navigationTitle("IAERP")
            .toolbarBackground(Color(uiColor: .systemBackground), for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .scrollEdgeEffectHidden(true, for: .top)
            .sheet(item: $connection) { route in
                ConnectionView(store: store, configuration: route.configuration)
            }
            .alert("¿Quitar esta cuenta del iPhone?", isPresented: Binding(
                get: { profileToForget != nil }, set: { if !$0 { profileToForget = nil } }
            )) {
                Button("Quitar cuenta", role: .destructive) {
                    if let profile = profileToForget { store.forgetProfile(profile) }
                    profileToForget = nil
                }
                Button("Cancelar", role: .cancel) { profileToForget = nil }
            } message: {
                if let profile = profileToForget {
                    Text("\(profile.displayName) · \(profile.accountLabel) · \(profile.configuration.organizationAlias). Tendrás que iniciar sesión de nuevo para guardarla. Las otras cuentas se conservan.")
                }
            }
        }
    }
}

struct AccountConnectionRoute: Identifiable {
    let id = UUID()
    let configuration: IdentityConfiguration?
}

extension SavedIdentityProfile {
    /// Names are not unique. Prefer the OIDC username; legacy profiles retain
    /// their stable subject as a visible fallback, never as an authority.
    var accountLabel: String {
        if let username, !username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return username }
        return "Cuenta \(subject)"
    }
    var selectionLabel: String {
        "\(displayName), \(accountLabel), empresa \(configuration.organizationAlias), \(configuration.issuerURL.host ?? "")"
    }
}

struct SavedAccountsSection: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let profiles: [SavedIdentityProfile]
    let connecting: Bool
    let select: (SavedIdentityProfile) -> Void
    let reconnect: (SavedIdentityProfile) -> Void
    let forget: (SavedIdentityProfile) -> Void

    var body: some View {
        Section {
            ForEach(profiles) { profile in
                let layout = dynamicTypeSize.isAccessibilitySize
                    ? AnyLayout(VStackLayout(alignment: .leading, spacing: 12))
                    : AnyLayout(HStackLayout(spacing: 12))
                layout {
                    accountButton(profile)
                    options(profile)
                }
                .disabled(connecting)
            }
        } header: {
            Text("Cuentas guardadas").font(.headline)
                .fixedSize(horizontal: false, vertical: true)
                .foregroundStyle(Color.primary)
        }
        footer: {
            Text("Cada cuenta se abre con Face ID o el código del iPhone. Si su sesión vence, vuelve a iniciar sesión.")
                .font(.footnote).fixedSize(horizontal: false, vertical: true)
                .foregroundStyle(Color.primary)
        }
    }

    private func accountButton(_ profile: SavedIdentityProfile) -> some View {
        Button { select(profile) } label: {
            HStack(spacing: 12) {
                if !dynamicTypeSize.isAccessibilitySize {
                    Image(systemName: "person.crop.circle").font(.title2).accessibilityHidden(true)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(profile.displayName).font(.headline)
                    Text(profile.accountLabel).font(.subheadline)
                    Text(profile.configuration.organizationAlias).font(.subheadline)
                    if Set(profiles.map { $0.configuration.issuerURL }).count > 1 {
                        Text(profile.configuration.issuerURL.host ?? "").font(.footnote)
                    }
                }
                .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
                if !dynamicTypeSize.isAccessibilitySize {
                    Image(systemName: "lock").accessibilityHidden(true)
                }
            }
            .foregroundStyle(Color.primary)
            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityHint("Desbloquea con Face ID o el código del iPhone")
        .accessibilityIdentifier("saved-account-\(profile.id.uuidString)")
    }

    private func options(_ profile: SavedIdentityProfile) -> some View {
        Menu {
            Button("Volver a iniciar sesión", systemImage: "arrow.clockwise") { reconnect(profile) }
            Button("Quitar de este iPhone", role: .destructive) { forget(profile) }
        } label: {
            Group {
                if dynamicTypeSize.isAccessibilitySize { Text("Opciones") }
                else { Image(systemName: "ellipsis") }
            }
            .frame(minWidth: 44, minHeight: 44)
        }
        .accessibilityLabel("Opciones de \(profile.selectionLabel)")
    }
}

struct ConnectionView: View {
    let store: WorkspaceStore
    @Environment(\.dismiss) private var dismiss
    @State private var apiURL = ""
    @State private var issuerURL = ""
    @State private var clientID = ""
    @State private var alias = ""
    @State private var documentHosts = ""

    init(store: WorkspaceStore, configuration: IdentityConfiguration? = nil) {
        self.store = store
        // Intentional form seed: editable public connection data, never credentials.
        _apiURL = State(initialValue: configuration?.apiBaseURL.absoluteString ?? IAERPConnection.apiURL.absoluteString)
        _issuerURL = State(initialValue: configuration?.issuerURL.absoluteString ?? IAERPConnection.issuerURL.absoluteString)
        _clientID = State(initialValue: configuration?.clientID ?? IAERPConnection.clientID)
        _alias = State(initialValue: configuration?.organizationAlias ?? "")
        _documentHosts = State(initialValue: configuration?.allowedDocumentHosts.sorted().first ?? IAERPConnection.documentHost)
    }

    var body: some View {
        let configuration = Result {
            try IAERPConnection.formConfiguration(api: apiURL, issuer: issuerURL, client: clientID,
                alias: alias, documentHost: documentHosts)
        }
        NavigationStack {
            Form {
                Section {
                    TextField("Dirección de la API", text: $apiURL, prompt: Text("https://api.ejemplo.com/api/v1"))
                        .accessibilityIdentifier("connection-api")
                    TextField("Dirección de acceso", text: $issuerURL, prompt: Text("https://acceso.ejemplo.com/realms/empresa"))
                        .accessibilityLabel("Dirección de acceso")
                        .accessibilityIdentifier("connection-issuer")
                    TextField("Identificador de la app", text: $clientID, prompt: Text("iaerp-ios"))
                    TextField("Alias de la empresa", text: $alias)
                        .accessibilityIdentifier("connection-alias")
                } header: { Text("Conexión").foregroundStyle(Color.primary) }
                footer: {
                    Text("La conexión a IAERP está preparada. Indica el alias de tu empresa; tu contraseña se escribe sólo en la página segura de acceso.")
                        .foregroundStyle(Color.primary)
                }
                Section {
                    TextField("Servidor de documentos (opcional)", text: $documentHosts, prompt: Text("archivos.ejemplo.com"))
                } footer: {
                    Text("Sólo el nombre HTTPS del servidor de archivos aprobado por tu empresa.")
                        .foregroundStyle(Color.primary)
                }
                Section {
                    if case .failure(let error) = configuration {
                        Text(verbatim: friendlyError(error))
                            .foregroundStyle(Color.primary)
                            .accessibilityIdentifier("connection-error")
                    } else if let message = store.connectionError {
                        Text(message).foregroundStyle(Color.primary).accessibilityIdentifier("connection-error")
                    }
                    Button {
                        if case .success(let config) = configuration {
                            Task {
                                await store.connect(config)
                                if store.phase == .ready { dismiss() }
                            }
                        }
                    } label: {
                        if store.connecting { ProgressView("Abriendo acceso seguro…") }
                        else { Label("Iniciar sesión", systemImage: "lock.open") }
                    }
                    .frame(minHeight: 44)
                    .disabled(store.connecting || (try? configuration.get()) == nil)
                    .accessibilityIdentifier("sign-in")
                }
            }
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .scrollEdgeEffectStyle(.hard, for: .all)
        .navigationTitle("Mi empresa")
            .toolbarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancelar") {
                        store.cancelConnection()
                        dismiss()
                    }
                }
            }
            .interactiveDismissDisabled(store.connecting)
        }
    }


}

struct CompanyProfileRoute: Identifiable {
    let id = UUID()
    let context: ERPContext
}

struct WorkspaceAccountView: View {
    let store: WorkspaceStore
    @Environment(\.colorScheme) private var colorScheme
    @State private var confirmExit = false
    @State private var profile: CompanyProfileRoute?
    @State private var nextDemoCompany: DemoCompany?
    var body: some View {
        GeometryReader { viewport in
            List {
                Section {
                    Text(verbatim: store.displayCompany)
                        .font(.headline)
                        .foregroundStyle(Color.primary)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityAddTraits(.isHeader)
                    if let profile = store.currentProfile {
                        ERPDetailRow(title: "Usuario", value: profile.displayName)
                        ERPDetailRow(title: "Cuenta", value: profile.accountLabel)
                    }
                }
                Section {
                    Button {
                        if let context = store.context { profile = CompanyProfileRoute(context: context) }
                    } label: {
                        Label("Mi empresa", systemImage: "building.2")
                            .foregroundStyle(Color.primary)
                            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("company-profile")
                    Button {
                        Task { await store.showSavedAccounts() }
                    } label: {
                        Text("Cambiar cuenta").foregroundStyle(Color.primary)
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("switch-account")
                    Button(role: .destructive) { confirmExit = true } label: {
                        Text("Cerrar sesión")
                            .foregroundStyle(colorScheme == .dark ? Color(red: 1, green: 0.62, blue: 0.60) :
                                                Color(red: 0.65, green: 0.12, blue: 0.13))
                            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("sign-out")
                }
            }
            .listSectionSpacing(.compact)
            .frame(width: viewport.size.width,
                   height: max(0, viewport.size.height - viewport.safeAreaInsets.bottom), alignment: .top)
            .clipped()
            .padding(.bottom, viewport.safeAreaInsets.bottom)
            .scrollEdgeEffectStyle(.hard, for: .all)
            .scrollEdgeEffectHidden(true, for: .all)
        }
        .navigationTitle("Cuenta")
        .toolbarTitleDisplayMode(.inline)
        .toolbarBackground(Color(uiColor: .systemBackground), for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .toolbarBackground(Color(uiColor: .systemBackground), for: .tabBar)
        .toolbarBackground(.visible, for: .tabBar)
        .sheet(item: $profile, onDismiss: {
            guard let company = nextDemoCompany else { return }
            nextDemoCompany = nil
            guard store.isDemo else { return }
            let readOnly = !store.canCreate
            let persistDelivery = store.persistsDemoDelivery
            Task { await store.startDemo(secondary: company == .secondary, readOnly: readOnly, persistDelivery: persistDelivery) }
        }) { route in
            CompanyProfileView(store: store, context: route.context) { company in
                nextDemoCompany = company
                profile = nil
            }
        }
        .confirmationDialog("¿Cerrar sesión?", isPresented: $confirmExit, titleVisibility: .visible) {
            Button("Cerrar sesión", role: .destructive) { Task { await store.logout() } }
            Button("Cancelar", role: .cancel) { }
        } message: { Text("Cerrar sesión quita este acceso guardado y borra sus datos temporales. Para conservarlo, cancela y usa Cambiar cuenta. Las otras cuentas se conservan.") }
    }
}

struct CompanyProfileView: View {
    let store: WorkspaceStore
    let context: ERPContext
    let selectDemoCompany: (DemoCompany) -> Void
    var body: some View {
        NavigationStack {
            List {
                Section {
                    if store.isDemo { ERPStatusBadge(text: "Demo", systemImage: "testtube.2") }
                    ERPDetailRow(title: "Empresa", value: context.name)
                    ERPDetailRow(title: "RUC", value: context.ruc)
                    ERPDetailRow(title: "Acceso", value: store.canCreate ? "Consulta y borradores" : "Sólo consulta")
                }
                if store.isDemo {
                    Section {
                        Button("Cambiar empresa de prueba") {
                            selectDemoCompany(context.tenantId == DemoCompany.primary.tenantId ? .secondary : .primary)
                        }
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("switch-demo-company")
                    } footer: { Text("Cada empresa usa datos de prueba separados.").foregroundStyle(Color.primary) }
                } else if !store.memberships.isEmpty {
                    Section {
                        ForEach(store.memberships) { membership in Text(membership.tenantName).foregroundStyle(Color.primary) }
                    } header: { Text("Empresas con acceso").foregroundStyle(Color.primary) }
                    footer: {
                        Text("Usa Cambiar cuenta para elegir una cuenta guardada o añadir otra empresa. El acceso se valida de nuevo.")
                            .foregroundStyle(Color.primary)
                    }
                }
            }
            .scrollEdgeEffectStyle(.hard, for: .all)
            .scrollEdgeEffectHidden(true, for: .bottom)
            .navigationTitle("Empresa")
            .toolbarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { ERPCloseButton() } }
        }
    }
}
