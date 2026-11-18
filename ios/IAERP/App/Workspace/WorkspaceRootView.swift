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
            if ProcessInfo.processInfo.arguments.contains("-workspace-demo") {
                await store.startDemo(readOnly: ProcessInfo.processInfo.arguments.contains("-read-only"))
            }
        }
    }
}

struct WorkspaceHomeView: View {
    let store: WorkspaceStore
    @State private var composer: ComposerRoute?
    @State private var savedInvoice: ERPInvoice?
    @State private var showingCutoff = false

    var body: some View {
        GeometryReader { viewport in
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let savedInvoice {
                        Text(savedInvoice.status == "DRAFT" ? "Borrador guardado. No se ha emitido al SRI." : "Guardado confirmado.")
                            .accessibilityIdentifier("workspace-notice")
                        NavigationLink {
                            WorkspaceInvoiceDetail(store: store, invoiceId: savedInvoice.id)
                        } label: {
                            Label(savedInvoice.status == "DRAFT" ? "Ver borrador" : "Ver factura", systemImage: "doc.text")
                        }
                        .accessibilityIdentifier("home-open-draft")
                    }
                    InvoiceRecoverySection(store: store)
                    summaryContent
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(width: viewport.size.width, height: viewport.size.height, alignment: .top)
            .clipped()
            .refreshable { if store.canReadDashboard { await store.loadDashboard() } }
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .toolbarBackground(Color(uiColor: .systemBackground), for: .tabBar)
        .toolbarBackground(.visible, for: .tabBar)
        .navigationTitle("Inicio")
        .navigationSubtitle(Text(verbatim: store.displayCompany))
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
            InvoiceComposerView(store: store, initialCustomerId: route.customerId) { savedInvoice = $0 }
        }
        .task { if store.canReadDashboard { await store.loadDashboard() } }
    }

    @ViewBuilder private var summaryContent: some View {
        if !store.canReadDashboard {
            Text("Tu perfil no tiene permiso para consultar la cartera.")
                .accessibilityIdentifier("home-dashboard-permission")
        } else if let error = store.dashboardError {
            ERPErrorState(message: error) { await store.loadDashboard() }
        } else if let summary = store.dashboard {
            metric("Por cobrar", value: summary.receivable, currency: summary.currency,
                   featured: true, identifier: "home-metric-receivable")
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .foregroundStyle(.white)
                .background(Color("AccentColor"), in: RoundedRectangle(cornerRadius: 16))
            VStack(alignment: .leading, spacing: 12) {
                metric("Vencido", value: summary.overdue, currency: summary.currency, identifier: "home-metric-overdue")
                Divider()
                metric("Cobrado este mes", value: summary.collectedThisMonth, currency: summary.currency,
                       identifier: "home-metric-collected")
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
        } else {
            ProgressView("Consultando cartera…")
        }
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
                        Text("Entra a tu empresa o recorre la app con datos de prueba.")
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
                    Button("Probar demo", systemImage: "testtube.2") { Task { await store.startDemo() } }
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("start-demo")
                        .disabled(store.connecting)
                } footer: {
                    Text("La demo usa datos ficticios. Los borradores de prueba se borran al salir.")
                        .foregroundStyle(Color.primary)
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
    @State private var errorMessage: String?

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
                if let message = errorMessage ?? store.connectionError {
                    Section { Text(message).foregroundStyle(Color.primary).accessibilityIdentifier("connection-error") }
                }
                Section {
                    Button {
                        Task { await connect() }
                    } label: {
                        if store.connecting { ProgressView("Abriendo acceso seguro…") }
                        else { Label("Iniciar sesión", systemImage: "lock.open") }
                    }
                    .frame(minHeight: 44)
                    .disabled(store.connecting)
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

    private func connect() async {
        errorMessage = nil
        do {
            guard let api = URL(string: apiURL.trimmingCharacters(in: .whitespacesAndNewlines)),
                  let issuer = URL(string: issuerURL.trimmingCharacters(in: .whitespacesAndNewlines)) else {
                throw IdentityError.invalidConfiguration
            }
            let host = documentHosts.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            guard host.isEmpty || host.range(of: #"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$"#, options: .regularExpression) != nil else {
                throw IdentityError.invalidConfiguration
            }
            let config = try IdentityConfiguration(apiBaseURL: api, issuerURL: issuer,
                                                   clientID: clientID.trimmingCharacters(in: .whitespacesAndNewlines),
                                                   organizationAlias: alias, allowedDocumentHosts: host.isEmpty ? [] : [host])
            await store.connect(config)
            if store.phase == .ready { dismiss() }
        } catch { errorMessage = friendlyError(error) }
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
    var body: some View {
        List {
            WorkspaceContextSection(store: store)
            if let profile = store.currentProfile {
                Section {
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
        .scrollEdgeEffectStyle(.hard, for: .all)
        .scrollEdgeEffectHidden(true, for: .all)
        .navigationTitle("Cuenta")
        .toolbarTitleDisplayMode(.inline)
        .toolbarBackground(Color(uiColor: .systemBackground), for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .toolbarBackground(Color(uiColor: .systemBackground), for: .tabBar)
        .toolbarBackground(.visible, for: .tabBar)
        .sheet(item: $profile) { CompanyProfileView(store: store, context: $0.context) }
        .confirmationDialog("¿Cerrar sesión?", isPresented: $confirmExit, titleVisibility: .visible) {
            Button("Cerrar sesión", role: .destructive) { Task { await store.logout() } }
            Button("Cancelar", role: .cancel) { }
        } message: { Text("Cerrar sesión quita este acceso guardado y borra sus datos temporales. Para conservarlo, cancela y usa Cambiar cuenta. Las otras cuentas se conservan.") }
    }
}

struct CompanyProfileView: View {
    let store: WorkspaceStore
    let context: ERPContext
    @Environment(\.dismiss) private var dismiss
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
                            let secondary = context.tenantId == DemoCompany.primary.tenantId
                            let readOnly = !store.canCreate
                            dismiss()
                            Task { await store.startDemo(secondary: secondary, readOnly: readOnly) }
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
