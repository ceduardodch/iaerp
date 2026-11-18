import Foundation
import IAERPClient
import IAERPIdentity
import Observation

@MainActor @Observable
final class WorkspaceStore {
    enum Phase: Equatable { case signedOut, loading, ready }
    var phase: Phase = .signedOut
    private(set) var generation = UUID()
    private(set) var isDemo = false
    private(set) var context: ERPContext?
    private(set) var customers: [ERPParty] = []
    private var customerNames: [UUID: ERPParty] = [:]
    private(set) var invoices: [ERPInvoice] = []
    private(set) var invoiceMonths: [ERPInvoiceMonth] = []
    private(set) var monthRows: [String: [ERPMonthInvoice]] = [:]
    private(set) var monthErrors: [String: String] = [:]
    private(set) var loadingMonths: Set<String> = []
    private var monthCursors: [String: String] = [:]
    var moreMonths: Set<String> { Set(monthCursors.keys) }
    private var invoiceQuery = ""
    private var invoiceStatus: String?
    private(set) var invoiceListRevision = 0
    private(set) var dashboard: ERPHomeSummary?
    private(set) var loadingDashboard = false
    private(set) var dashboardError: String?
    private var dashboardRequest = UUID()
    var canReadDashboard: Bool { context?.permits("receivables:read") == true }
    private(set) var products: [ERPProduct] = []
    private(set) var setup: ERPInvoiceSetup?
    private(set) var memberships: [ERPMembership] = []
    var customerError: String?
    var invoiceError: String?
    var catalogError: String?
    var connectionError: String?
    var notice: String?
    var loadingCustomers = false
    var loadingInvoices = false
    var loadingProducts = false
    var connecting = false
    private var loggingOut = false
    private(set) var pendingInvoiceRecovery: PendingInvoiceWrite?
    private(set) var invoiceRecoveryError: String?
    private(set) var checkingInvoiceRecovery = false
    private var recoveryChecked = false
    private(set) var savedProfiles: [SavedIdentityProfile] = []
    private(set) var service: (any ERPService)?
    private(set) var configuration: IdentityConfiguration?
    private var customerRequest = UUID()
    private var invoiceRequest = UUID()
    private var productRequest = UUID()
    let authentication: AuthenticationController
    let documents: TemporaryDocuments
    let invoiceRecoveryJournal: InvoiceRecoveryJournal
    @ObservationIgnored private let resetDocuments: @Sendable (UUID) async throws -> Void

    init(service: (any ERPService)? = nil, authentication: AuthenticationController? = nil, documents: TemporaryDocuments? = nil,
         resetDocuments: (@Sendable (UUID) async throws -> Void)? = nil,
         invoiceRecoveryJournal: InvoiceRecoveryJournal? = nil) {
        self.service = service
        self.authentication = authentication ?? AuthenticationController()
        self.configuration = self.authentication.configuration
        let temporaryDocuments = documents ?? TemporaryDocuments()
        self.documents = temporaryDocuments
        self.invoiceRecoveryJournal = invoiceRecoveryJournal ?? InvoiceRecoveryJournal()
        self.resetDocuments = resetDocuments ?? { next in try await temporaryDocuments.reset(generation: next) }
    }

    var canCreate: Bool { context?.permits("invoices:write") == true }
    var canStartInvoice: Bool {
        canCreate && (isDemo || (recoveryChecked && pendingInvoiceRecovery == nil && invoiceRecoveryError == nil))
    }
    var currentProfile: SavedIdentityProfile? { savedProfiles.first { $0.id == authentication.activeProfileID } }
    var connectionConfigurationForRetry: IdentityConfiguration? { configuration }

    func currentInvoiceRecoveryScope() throws -> InvoiceRecoveryScope {
        guard !isDemo, phase == .ready, let context, let configuration,
              configuration == authentication.configuration,
              let session = authentication.session, let profileID = authentication.activeProfileID else {
            throw InvoiceRecoveryError.wrongIdentity
        }
        return InvoiceRecoveryScope(profileID: profileID, configuration: configuration,
            subject: session.subject, organizationID: session.organizationID, tenantID: context.tenantId)
    }

    func refreshInvoiceRecovery() {
        pendingInvoiceRecovery = nil
        invoiceRecoveryError = nil
        recoveryChecked = false
        guard !isDemo else { recoveryChecked = true; return }
        do {
            pendingInvoiceRecovery = try invoiceRecoveryJournal.pending(in: currentInvoiceRecoveryScope())
            recoveryChecked = true
        } catch { invoiceRecoveryError = friendlyError(error) }
    }

    func recoverPendingInvoice() async {
        guard !checkingInvoiceRecovery, !isDemo, let service else { return }
        let epoch = generation
        checkingInvoiceRecovery = true
        invoiceRecoveryError = nil
        defer { if epoch == generation { checkingInvoiceRecovery = false } }
        do {
            let scope = try currentInvoiceRecoveryScope()
            let invoice = try await invoiceRecoveryJournal.recover(in: scope, using: service, authorize: { [weak self] in
                guard let self, self.generation == epoch else { throw IdentityError.sessionChanged }
                return try self.currentInvoiceRecoveryScope()
            })
            guard epoch == generation else { return }
            acceptSaved(invoice, generation: epoch)
            refreshInvoiceRecovery()
            notice = "Guardado recuperado y confirmado con IAERP."
        } catch {
            guard epoch == generation else { return }
            refreshInvoiceRecovery()
            invoiceRecoveryError = friendlyError(error)
        }
    }

    func findSavedSession() {
        do { savedProfiles = try authentication.savedProfiles() }
        catch { savedProfiles = []; connectionError = friendlyError(error) }
    }

    func restoreSession(profile: SavedIdentityProfile) async {
        guard !connecting, savedProfiles.contains(where: { $0 == profile }) else { return }
        connecting = true
        clear()
        let config = profile.configuration
        let epoch = generation
        defer { if epoch == generation { connecting = false } }
        isDemo = false
        pendingInvoiceRecovery = nil
        invoiceRecoveryError = nil
        checkingInvoiceRecovery = false
        recoveryChecked = false
        configuration = config
        do {
            try await resetDocuments(epoch)
            guard epoch == generation, !Task.isCancelled else { return }
            guard try await authentication.restore(profileID: profile.id), epoch == generation else { throw IdentityError.noSession }
            service = try LiveERPService(baseURL: config.apiBaseURL, tokenProvider: { [weak self] refresh in
                guard let self else { throw IdentityError.sessionChanged }
                return try await self.token(for: epoch, configuration: config, forceRefresh: refresh)
            }, allowedDocumentHosts: config.allowedDocumentHosts)
            await loadWorkspace()
        } catch {
            guard epoch == generation else { return }
            connectionError = friendlyError(error)
            findSavedSession()
        }
    }

    /// Switching accounts is distinct from signing out: retain encrypted
    /// sessions, but invalidate every request and clear the previous workspace.
    func showSavedAccounts() async {
        guard !connecting else { return }
        connecting = true
        clear()
        isDemo = false
        let epoch = generation
        defer { if epoch == generation { connecting = false } }
        do { try await resetDocuments(epoch) }
        catch { if epoch == generation { connectionError = "No se pudieron borrar los documentos temporales." } }
        guard epoch == generation else { return }
        findSavedSession()
    }

    func forgetProfile(_ profile: SavedIdentityProfile) {
        guard !connecting, phase == .signedOut else { return }
        do {
            try authentication.forget(profileID: profile.id)
            findSavedSession()
            notice = "Cuenta quitada de este iPhone."
        } catch { connectionError = friendlyError(error) }
    }

    func cancelConnection() {
        guard !loggingOut else { return }
        clear()
        connecting = false
        findSavedSession()
    }

    /// Called synchronously at the real background transition, not transient
    /// inactivity caused by Face ID or the system authentication browser.
    func lockForBackground() {
        guard !isDemo, !authentication.isAuthenticating, !loggingOut else { return }
        clear()
        connecting = true
        let epoch = generation
        Task {
            defer { if epoch == generation { connecting = false } }
            do { try await resetDocuments(epoch) }
            catch { if epoch == generation { connectionError = "No se pudieron borrar los documentos temporales." } }
        }
    }

    func clear(cancelAuthentication: Bool = true) {
        if cancelAuthentication { authentication.suspend() }
        generation = UUID()
        service = nil
        context = nil
        customers = []; invoices = []; products = []; memberships = []
        resetMonths()
        invoiceQuery = ""
        invoiceStatus = nil
        dashboard = nil
        dashboardError = nil
        loadingDashboard = false
        customerNames = [:]
        setup = nil
        customerError = nil; invoiceError = nil; catalogError = nil
        connectionError = nil; notice = nil
        loadingCustomers = false; loadingInvoices = false; loadingProducts = false
        phase = .signedOut
        configuration = nil
        isDemo = false
        pendingInvoiceRecovery = nil
        invoiceRecoveryError = nil
        checkingInvoiceRecovery = false
        recoveryChecked = false
    }

    func startDemo(secondary: Bool = false, readOnly: Bool = false) async {
        guard !connecting else { return }
        connecting = true
        clear()
        let epoch = generation
        defer { if epoch == generation { connecting = false } }
        do { try await resetDocuments(epoch) }
        catch {
            if epoch == generation { connectionError = "No se pudieron borrar los documentos temporales." }
            return
        }
        guard epoch == generation, !Task.isCancelled else { return }
        isDemo = true
        service = DemoERPService(company: secondary ? .secondary : .primary, readOnly: readOnly)
        await loadWorkspace()
    }

    func connect(_ config: IdentityConfiguration) async {
        guard !connecting else { return }
        connecting = true
        clear()
        let epoch = generation
        defer { if epoch == generation { connecting = false } }
        do { try await resetDocuments(epoch) }
        catch {
            if epoch == generation { connectionError = "No se pudieron borrar los documentos temporales." }
            return
        }
        guard epoch == generation, !Task.isCancelled else { return }
        isDemo = false
        configuration = config
        do {
            try await authentication.login(configuration: config)
            guard epoch == generation else { return }
            service = try LiveERPService(baseURL: config.apiBaseURL, tokenProvider: { [weak self] refresh in
                guard let self else { throw IdentityError.sessionChanged }
                return try await self.token(for: epoch, configuration: config, forceRefresh: refresh)
            }, allowedDocumentHosts: config.allowedDocumentHosts)
            await loadWorkspace()
            findSavedSession()
        } catch {
            guard epoch == generation else { return }
            connectionError = friendlyError(error)
            phase = .signedOut
        }
    }

    private func token(for epoch: UUID, configuration expected: IdentityConfiguration, forceRefresh: Bool) async throws -> String {
        guard epoch == generation, configuration == expected else { throw IdentityError.sessionChanged }
        let token = try await authentication.accessToken(forceRefresh: forceRefresh)
        guard epoch == generation, configuration == expected else { throw IdentityError.sessionChanged }
        return token
    }

    func loadWorkspace() async {
        guard let service else { return }
        let epoch = generation
        phase = .loading
        do {
            let result = try await service.context()
            guard epoch == generation, !Task.isCancelled else { return }
            context = result
            phase = .ready
            refreshInvoiceRecovery()
            async let clients: Void = loadCustomers()
            async let catalog: Void = loadCatalog()
            async let companies: Void = loadMemberships()
            _ = await (clients, catalog, companies)
        } catch {
            guard epoch == generation else { return }
            connectionError = friendlyError(error)
            phase = .signedOut
            self.service = nil
        }
    }

    func loadCustomers(query: String = "") async {
        guard let service else { return }
        let epoch = generation
        let request = UUID(); customerRequest = request
        loadingCustomers = true
        customerError = nil
        do {
            let result = try await service.customers(query: query.count >= 2 ? query : "")
            guard epoch == generation, request == customerRequest, !Task.isCancelled else { return }
            customers = result.filter { $0.roles.contains("CUSTOMER") }
            for customer in customers { customerNames[customer.id] = customer }
        } catch {
            guard epoch == generation, request == customerRequest, !Task.isCancelled else { return }
            customerError = friendlyError(error)
        }
        if epoch == generation && request == customerRequest { loadingCustomers = false }
    }

    func loadDashboard() async {
        guard canReadDashboard, let api = service as? any ERPSalesOverviewService else { return }
        let epoch = generation
        let request = UUID()
        dashboardRequest = request
        loadingDashboard = true
        dashboardError = nil
        defer {
            if epoch == generation && request == dashboardRequest { loadingDashboard = false }
        }
        do {
            let result = try await api.homeSummary()
            guard epoch == generation, request == dashboardRequest, !Task.isCancelled else { return }
            dashboard = result
        } catch {
            guard epoch == generation, request == dashboardRequest, !Task.isCancelled else { return }
            dashboard = nil
            dashboardError = friendlyError(error)
        }
    }

    private func resetMonths() {
        invoiceMonths = []
        monthRows = [:]
        monthCursors = [:]
        monthErrors = [:]
        loadingMonths = []
    }

    func loadInvoices(query: String = "", status: String? = nil) async {
        guard let api = service as? any ERPSalesOverviewService else { return }
        let epoch = generation
        let request = UUID()
        invoiceRequest = request
        invoiceQuery = query
        invoiceStatus = status
        resetMonths()
        loadingInvoices = true
        invoiceError = nil
        defer {
            if epoch == generation && request == invoiceRequest { loadingInvoices = false }
        }
        do {
            let result = try await api.invoiceMonths(query: query, status: status)
            guard epoch == generation, request == invoiceRequest, !Task.isCancelled else { return }
            invoiceMonths = result
        } catch {
            guard epoch == generation, request == invoiceRequest, !Task.isCancelled else { return }
            invoiceError = friendlyError(error)
        }
    }

    func loadInvoiceMonth(_ group: ERPInvoiceMonth, more: Bool = false) async {
        let month = group.id
        guard let api = service as? any ERPSalesOverviewService,
              invoiceMonths.contains(group),
              !loadingMonths.contains(month) else { return }
        let cursor = monthCursors[month]
        guard more ? cursor != nil : monthRows[month] == nil else { return }
        let epoch = generation
        let request = invoiceRequest
        loadingMonths.insert(month)
        monthErrors[month] = nil
        defer {
            if epoch == generation && request == invoiceRequest { loadingMonths.remove(month) }
        }
        do {
            let page = try await api.monthPage(group.month, currency: group.currency, query: invoiceQuery, status: invoiceStatus, cursor: more ? cursor : nil)
            guard epoch == generation, request == invoiceRequest, !Task.isCancelled else { return }
            monthRows[month, default: []].append(contentsOf: page.items)
            monthCursors[month] = page.nextCursor
        } catch {
            guard epoch == generation, request == invoiceRequest, !Task.isCancelled else { return }
            monthErrors[month] = friendlyError(error)
        }
    }

    func loadProducts(query: String = "") async {
        guard let service else { return }
        let epoch = generation
        let request = UUID(); productRequest = request
        loadingProducts = true
        do {
            let result = try await service.products(query: query.count >= 2 ? query : "")
            guard epoch == generation, request == productRequest, !Task.isCancelled else { return }
            products = result; catalogError = nil
        } catch {
            guard epoch == generation, request == productRequest, !Task.isCancelled else { return }
            catalogError = friendlyError(error)
        }
        if epoch == generation && request == productRequest { loadingProducts = false }
    }

    func loadCatalog() async {
        guard let service else { return }
        let epoch = generation
        let productLoad = UUID(); productRequest = productLoad
        catalogError = nil
        do {
            let setupResult = try await service.invoiceSetup()
            guard epoch == generation, !Task.isCancelled else { return }
            setup = setupResult
            if canCreate {
                let itemsResult = try await service.products(query: "")
                guard epoch == generation, !Task.isCancelled else { return }
                if productRequest == productLoad { products = itemsResult }
            }
        } catch {
            guard epoch == generation else { return }
            catalogError = friendlyError(error)
        }
    }

    private func loadMemberships() async {
        guard let service else { return }
        let epoch = generation
        do {
            let result = try await service.memberships()
            guard epoch == generation, !Task.isCancelled else { return }
            memberships = result.filter(\.active)
        } catch {
            // Memberships are supplementary; failure does not hide a valid context.
            // An alternate organization still requires a fresh OIDC login.
        }
    }

    func logout() async {
        guard !connecting else { return }
        let wasDemo = isDemo
        clear(cancelAuthentication: false)
        connecting = true
        loggingOut = true
        defer { loggingOut = false }
        let epoch = generation
        let pendingLogout = authentication.beginLogout()
        var filesCleared = true
        do { try await resetDocuments(epoch) } catch { filesCleared = false }
        let result = await pendingLogout.value
        if epoch == generation {
            notice = filesCleared ? (wasDemo ? "Demo cerrada." : result.message) :
                "Sesión cerrada. No se pudieron borrar todos los documentos temporales; vuelve a abrir la app para reintentar."
            connecting = false
            isDemo = false
            findSavedSession()
        }
    }

    func customerName(_ id: UUID) -> String {
        customerNames[id]?.name ?? "Cliente no cargado (\(id.uuidString.prefix(8)))"
    }
    func customer(_ id: UUID) -> ERPParty? { customerNames[id] }
    func invoiceNumber(_ invoice: ERPInvoice) -> String {
        guard let establishment = setup?.establishments.first(where: { $0.id == invoice.establishmentId }),
              let point = setup?.emissionPoints.first(where: { $0.id == invoice.emissionPointId }) else {
            return "Secuencial \(invoice.sequential)"
        }
        return "\(establishment.code)-\(point.code)-\(invoice.sequential)"
    }

    func acceptSaved(_ invoice: ERPInvoice, generation expected: UUID) {
        guard expected == generation else { return }
        invoices.removeAll { $0.id == invoice.id }
        invoices.insert(invoice, at: 0)
        invoiceListRevision += 1
        notice = invoice.status == "DRAFT" ? "Borrador guardado. No se ha emitido al SRI." :
            "Guardado confirmado. Estado: \(ERPDisplay.status(invoice.status))."
    }
}

func friendlyError(_ error: any Error) -> String {
    if error is CancellationError { return "Se canceló la consulta." }
    if let known = error as? ERPClientError { return known.localizedDescription }
    if let known = error as? IdentityError { return known.localizedDescription }
    if let known = error as? SessionUnlockError { return known.localizedDescription }
    if let known = error as? InvoiceRecoveryError { return known.localizedDescription }
    return "No se pudo completar la conexión. Revisa tu red e intenta de nuevo."
}
