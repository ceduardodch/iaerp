import Foundation
import IAERPClient
import IAERPIdentity
import Testing
@testable import IAERP

/// Explicit barriers keep these regressions independent of clocks or network timing.
private actor WorkspaceResponse<Value: Sendable> {
    private var requested = false
    private var startWaiters: [CheckedContinuation<Void, Never>] = []
    private var result: CheckedContinuation<Value, any Error>?

    func value() async throws -> Value {
        requested = true
        let waiters = startWaiters
        startWaiters.removeAll()
        waiters.forEach { $0.resume() }
        return try await withCheckedThrowingContinuation { result = $0 }
    }

    func waitUntilRequested() async {
        guard !requested else { return }
        await withCheckedContinuation { startWaiters.append($0) }
    }

    func resolve(_ value: Value) {
        result?.resume(returning: value)
        result = nil
    }
}

nonisolated enum WorkspaceQuery: CaseIterable, Sendable {
    case customers, invoices, products
}

private actor ConcurrentERPService: ERPService, ERPSalesOverviewService {
    nonisolated enum SaveFailure: Sendable { case rejected, forbidden, responseLost }
    let demo = DemoERPService()
    let oldCustomers = WorkspaceResponse<[ERPParty]>()
    let oldInvoices = WorkspaceResponse<[ERPInvoiceMonth]>()
    let oldProducts = WorkspaceResponse<[ERPProduct]>()
    let oldDashboard = WorkspaceResponse<ERPHomeSummary>()
    let oldMonthPage = WorkspaceResponse<ERPInvoicePage>()
    private let holdSalesReads: Bool
    let delayedPreview: WorkspaceResponse<ERPInvoicePreview>?
    private let heldQuery: WorkspaceQuery?
    private var nextSaveFailure: SaveFailure?
    private var writes: [(ERPInvoiceInput, String)] = []

    init(heldQuery: WorkspaceQuery? = nil, delayPreview: Bool = false, holdSalesReads: Bool = false) {
        self.holdSalesReads = holdSalesReads
        self.heldQuery = heldQuery
        self.delayedPreview = delayPreview ? WorkspaceResponse() : nil
    }

    func rejectNextSave(_ failure: SaveFailure) { nextSaveFailure = failure }
    func capturedWrites() -> [(ERPInvoiceInput, String)] { writes }
    func context() async throws -> ERPContext { try await demo.context() }
    func memberships() async throws -> [ERPMembership] { try await demo.memberships() }
    func invoiceSetup() async throws -> ERPInvoiceSetup { try await demo.invoiceSetup() }
    func invoice(id: UUID) async throws -> ERPInvoice { try await demo.invoice(id: id) }
    func artifacts(invoiceID: UUID) async throws -> [ERPArtifact] { try await demo.artifacts(invoiceID: invoiceID) }
    func document(invoiceID: UUID, artifact: ERPArtifact) async throws -> ERPDocument {
        try await demo.document(invoiceID: invoiceID, artifact: artifact)
    }
    func customers(query: String) async throws -> [ERPParty] {
        if heldQuery == .customers, query == "old" { return try await oldCustomers.value() }
        if heldQuery == .customers, query == "new" { return Array(try await demo.customers(query: "").prefix(1)) }
        return try await demo.customers(query: query)
    }
    func invoices(query: String, status: String?) async throws -> [ERPInvoice] {
        return try await demo.invoices(query: query, status: status)
    }
    func homeSummary() async throws -> ERPHomeSummary {
        if holdSalesReads { return try await oldDashboard.value() }
        return try await demo.homeSummary()
    }
    func invoiceMonths(query: String, status: String?) async throws -> [ERPInvoiceMonth] {
        if heldQuery == .invoices, query == "old" { return try await oldInvoices.value() }
        if heldQuery == .invoices, query == "new" { return Array(try await demo.invoiceMonths(query: "", status: status).prefix(1)) }
        return try await demo.invoiceMonths(query: query, status: status)
    }
    func monthPage(_ month: String, currency: String, query: String, status: String?, cursor: String?) async throws -> ERPInvoicePage {
        if holdSalesReads { return try await oldMonthPage.value() }
        return try await demo.monthPage(month, currency: currency, query: query, status: status, cursor: cursor)
    }
    func products(query: String) async throws -> [ERPProduct] {
        if heldQuery == .products, query == "old" { return try await oldProducts.value() }
        if heldQuery == .products, query == "new" { return Array(try await demo.products(query: "").prefix(1)) }
        return try await demo.products(query: query)
    }
    func preview(_ input: ERPPreviewInput) async throws -> ERPInvoicePreview {
        if let delayedPreview { return try await delayedPreview.value() }
        return try await demo.preview(input)
    }
    func createDraft(_ input: ERPInvoiceInput, idempotencyKey: String) async throws -> ERPInvoice {
        writes.append((input, idempotencyKey))
        let failure = nextSaveFailure
        nextSaveFailure = nil
        if failure == .rejected { throw ERPClientError.invalidInput("Revisa el descuento.") }
        if failure == .forbidden { throw ERPClientError.forbidden }
        let invoice = try await demo.createDraft(input, idempotencyKey: idempotencyKey)
        if failure == .responseLost { throw URLError(.networkConnectionLost) }
        return invoice
    }
}

@MainActor
private func workspaceComposer(using service: any ERPService) async throws -> (InvoiceComposer, ERPInvoiceSetup) {
    let setup = try await service.invoiceSetup()
    let customer = try #require(try await service.customers(query: "").first)
    let product = try #require(try await service.products(query: "").first)
    let composer = InvoiceComposer(customerId: customer.id)
    composer.issueDate = try #require(ISO8601DateFormatter().date(from: "2026-11-17T12:00:00Z"))
    composer.establishmentId = try #require(setup.establishments.first?.id)
    composer.emissionPointId = try #require(setup.emissionPoints.first?.id)
    composer.add(product, setup: setup)
    return (composer, setup)
}

@Suite("Respuestas tardías y guardado de borradores", .timeLimit(.minutes(1)))
@MainActor
struct WorkspaceConcurrencyTests {
    @Test func obsoletePreviewNeverPublishesTotalsAndReleasesWorkingState() async throws {
        let service = ConcurrentERPService(delayPreview: true)
        let (composer, setup) = try await workspaceComposer(using: service)
        let gate = try #require(await service.delayedPreview)
        let original = try composer.buildInput(setup: setup)
        let result = try await service.demo.preview(ERPPreviewInput(issueDate: original.issueDate, lines: original.lines))
        let review = Task { await composer.review(using: service, setup: setup) }
        await gate.waitUntilRequested()
        #expect(composer.working)
        composer.lines[0].quantity = "2"
        composer.invalidatePreview()
        await gate.resolve(result)
        await review.value
        #expect(composer.preview == nil)
        #expect(composer.previewInput == nil)
        #expect(!composer.working)
        #expect(composer.canEdit)
    }

    @Test func lostResponseRetriesTheSameSavedOperationWithoutDuplicating() async throws {
        let service = ConcurrentERPService()
        let (composer, setup) = try await workspaceComposer(using: service)
        await composer.review(using: service, setup: setup)
        await service.rejectNextSave(.responseLost)
        #expect(await composer.save(using: service, setup: setup) == nil)
        let pending = try #require(composer.pendingInput)
        let key = try #require(composer.pendingKey)
        #expect(!composer.canEdit)
        let saved = try #require(await composer.save(using: service, setup: setup))
        let writes = await service.capturedWrites()
        #expect(writes.count == 2)
        #expect(writes.allSatisfy { $0.0 == pending && $0.1 == key })
        let serverDrafts = try await service.demo.invoices(query: "", status: "DRAFT")
        #expect(serverDrafts.count == 2) // Existing fixture plus one new operation.
        #expect(serverDrafts.filter { $0.id == saved.id }.count == 1)
        #expect(!composer.working)
    }

    @Test func definitiveRejectionLetsTheUserCorrectAndReviewAgain() async throws {
        let service = ConcurrentERPService()
        let (composer, setup) = try await workspaceComposer(using: service)
        await composer.review(using: service, setup: setup)
        await service.rejectNextSave(.rejected)
        #expect(await composer.save(using: service, setup: setup) == nil)
        #expect(composer.pendingInput == nil && composer.pendingKey == nil)
        #expect(composer.canEdit)
        composer.lines[0].quantity = "2"
        composer.invalidatePreview()
        await composer.review(using: service, setup: setup)
        let saved = try #require(await composer.save(using: service, setup: setup))
        #expect(saved.total == 230)
        let writes = await service.capturedWrites()
        #expect(writes.count == 2)
        #expect(writes[0].1 != writes[1].1)
    }

    @Test func forbiddenRetryCannotDiscardAnAlreadyUncertainOperation() async throws {
        let service = ConcurrentERPService()
        let (composer, setup) = try await workspaceComposer(using: service)
        await composer.review(using: service, setup: setup)
        await service.rejectNextSave(.responseLost)
        #expect(await composer.save(using: service, setup: setup) == nil)
        let originalInput = try #require(composer.pendingInput)
        let originalKey = try #require(composer.pendingKey)

        // The first request was committed. Losing permission on the retry does
        // not prove that original request failed or permit a new operation.
        await service.rejectNextSave(.forbidden)
        #expect(await composer.save(using: service, setup: setup) == nil)
        #expect(composer.pendingInput == originalInput)
        #expect(composer.pendingKey == originalKey)
        #expect(!composer.canEdit)

        let recovered = try #require(await composer.save(using: service, setup: setup))
        let writes = await service.capturedWrites()
        #expect(writes.count == 3)
        #expect(writes.allSatisfy { $0.0 == originalInput && $0.1 == originalKey })
        let drafts = try await service.demo.invoices(query: "", status: "DRAFT")
        #expect(drafts.count == 2) // One seed plus the first, recovered commit.
        #expect(drafts.filter { $0.id == recovered.id }.count == 1)
    }

    @Test func loadingTheNextMonthPageAppendsTheRemainingInvoicesOnce() async throws {
        let service = DemoERPService()
        let (composer, setup) = try await workspaceComposer(using: service)
        let input = try composer.buildInput(setup: setup)
        var createdIDs: [UUID] = []
        for index in 0..<51 {
            let document = try await service.createDraft(input, idempotencyKey: "synthetic-page-draft-\(index)")
            createdIDs.append(document.id)
        }
        let store = WorkspaceStore(service: service)
        await store.loadWorkspace()
        await store.loadInvoices(status: "DRAFT")
        let group = try #require(store.invoiceMonths.first { $0.month == "2026-11" })
        #expect(group.count == createdIDs.count)
        let expected = createdIDs.sorted { $0.uuidString > $1.uuidString }

        await store.loadInvoiceMonth(group)
        let firstPage = try #require(store.monthRows[group.id])
        #expect(firstPage.map(\.id) == Array(expected.prefix(50)))
        #expect(store.moreMonths.contains(group.id))

        await store.loadInvoiceMonth(group, more: true)
        #expect(store.monthRows[group.id]?.map(\.id) == expected)
        #expect(!store.moreMonths.contains(group.id))
        await store.loadInvoiceMonth(group, more: true)
        #expect(store.monthRows[group.id]?.map(\.id) == expected)
        #expect(store.monthErrors[group.id] == nil)
    }

    @Test(arguments: [false, true])
    func oldCompanyCannotPublishDashboardOrMonthPage(afterNewReads: Bool) async throws {
        let primary = ConcurrentERPService(holdSalesReads: true)
        let store = WorkspaceStore(service: primary, resetDocuments: { _ in })
        await store.loadWorkspace()
        await store.loadInvoices()
        let group = try #require(store.invoiceMonths.first)
        let oldSummary = try await primary.demo.homeSummary()
        let oldPage = try await primary.demo.monthPage(
            group.month, currency: group.currency, query: "", status: nil, cursor: nil
        )
        let secondary = DemoERPService(company: .secondary)
        let newSummary = try await secondary.homeSummary()
        let newPage = try await secondary.monthPage(
            group.month, currency: group.currency, query: "", status: nil, cursor: nil
        )
        #expect(oldSummary != newSummary)
        #expect(!oldPage.items.isEmpty && !newPage.items.isEmpty)
        #expect(Set(oldPage.items.map(\.id)).isDisjoint(with: newPage.items.map(\.id)))

        let dashboardRead = Task { await store.loadDashboard() }
        let monthRead = Task { await store.loadInvoiceMonth(group) }
        await primary.oldDashboard.waitUntilRequested()
        await primary.oldMonthPage.waitUntilRequested()
        await store.startDemo(secondary: true)
        if afterNewReads {
            await store.loadDashboard()
            await store.loadInvoices()
            if let matchingGroup = store.invoiceMonths.first(where: { $0.id == group.id }) {
                await store.loadInvoiceMonth(matchingGroup)
            }
        }

        await primary.oldDashboard.resolve(oldSummary)
        await primary.oldMonthPage.resolve(oldPage)
        await dashboardRead.value
        await monthRead.value
        #expect(store.context?.tenantId == DemoCompany.secondary.tenantId)
        if afterNewReads {
            #expect(store.dashboard == newSummary)
            #expect(store.monthRows[group.id] == newPage.items)
        } else {
            #expect(store.dashboard == nil)
            #expect(store.monthRows.isEmpty)
        }
        #expect(!store.loadingDashboard && store.loadingMonths.isEmpty)
        #expect(store.dashboardError == nil && store.monthErrors.isEmpty)
        #expect(store.moreMonths.isEmpty)
    }

    @Test(arguments: WorkspaceQuery.allCases)
    func anOlderQueryCannotOverwriteNewerResults(_ kind: WorkspaceQuery) async throws {
        let service = ConcurrentERPService(heldQuery: kind)
        let store = WorkspaceStore(service: service)
        await store.loadWorkspace()
        let originalCustomers = store.customers
        // Login does not preload the invoice list. The new query owns monthly
        // server headers; use a nonempty baseline to keep the race meaningful.
        let originalInvoices = try await service.demo.invoiceMonths(query: "", status: nil)
        #expect(originalInvoices.count >= 2)
        let originalProducts = store.products
        let earlier = Task {
            switch kind {
            case .customers: await store.loadCustomers(query: "old")
            case .invoices: await store.loadInvoices(query: "old")
            case .products: await store.loadProducts(query: "old")
            }
        }
        switch kind {
        case .customers:
            await service.oldCustomers.waitUntilRequested()
            await store.loadCustomers(query: "new")
            await service.oldCustomers.resolve(Array(originalCustomers.suffix(1)))
        case .invoices:
            await service.oldInvoices.waitUntilRequested()
            await store.loadInvoices(query: "new")
            await service.oldInvoices.resolve(Array(originalInvoices.suffix(1)))
        case .products:
            await service.oldProducts.waitUntilRequested()
            await store.loadProducts(query: "new")
            await service.oldProducts.resolve(Array(originalProducts.suffix(1)))
        }
        await earlier.value
        switch kind {
        case .customers:
            #expect(store.customers == Array(originalCustomers.prefix(1)))
            #expect(!store.loadingCustomers)
        case .invoices:
            #expect(store.invoiceMonths == Array(originalInvoices.prefix(1)))
            #expect(!store.loadingInvoices)
        case .products:
            #expect(store.products == Array(originalProducts.prefix(1)))
            #expect(!store.loadingProducts)
        }
    }
}

@MainActor private final class WorkspaceMemoryVault: IdentityVault {
    private var identity: StoredIdentity?
    func save(_ identity: StoredIdentity) throws { self.identity = identity }
    func load() throws -> StoredIdentity? { identity }
    func clear() throws { identity = nil }
}

@MainActor private final class WorkspaceLogoutProvider: IdentityProvider {
    let response = WorkspaceResponse<Bool>()
    let grant: IdentityGrant
    private(set) var authorizationCalls = 0
    init(configuration: IdentityConfiguration) throws {
        func segment(_ value: [String: Any]) throws -> String {
            try JSONSerialization.data(withJSONObject: value, options: .sortedKeys)
                .base64EncodedString().replacingOccurrences(of: "+", with: "-")
                .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        }
        let expiry = Date.now.addingTimeInterval(3600)
        let claims: [String: Any] = [
            "iss": configuration.issuerURL.absoluteString, "aud": configuration.apiAudience,
            "azp": configuration.clientID, "sub": "workspace-synthetic-user", "exp": expiry.timeIntervalSince1970,
            "organization": [configuration.organizationAlias: ["id": "00000000-0000-4000-8000-000000000001"]],
        ]
        let token = try segment(["alg": "RS256"]) + "." + segment(claims) + ".synthetic-signature"
        grant = IdentityGrant(accessToken: token, expiresAt: expiry, displayName: "Usuario de prueba", serializedState: Data())
    }
    func authorize(configuration: IdentityConfiguration) async throws -> IdentityGrant {
        authorizationCalls += 1
        return grant
    }
    func refresh(grant: IdentityGrant, configuration: IdentityConfiguration) async throws -> IdentityGrant { self.grant }
    func closeRemoteSession(grant: IdentityGrant, configuration: IdentityConfiguration) async -> Bool {
        (try? await response.value()) ?? false
    }
    func cancel() { }
}

@Suite("Salida de sesión y cambio de empresa", .timeLimit(.minutes(1)))
@MainActor
struct WorkspaceLogoutConcurrencyTests {
    @Test func logoutBlocksNewSessionsUntilRemoteCleanupCompletes() async throws {
        let configuration = try IdentityConfiguration(
            apiBaseURL: URL(string: "https://api.example.invalid/api/v1")!,
            issuerURL: URL(string: "https://identity.example.invalid/realms/iaerp")!,
            clientID: "iaerp-ios-test", organizationAlias: "demo-a"
        )
        let provider = try WorkspaceLogoutProvider(configuration: configuration)
        let identity = IdentityManager(provider: provider, vault: WorkspaceMemoryVault())
        try await identity.login(configuration: configuration)
        let store = WorkspaceStore(service: ConcurrentERPService(), authentication: AuthenticationController(manager: identity))
        await store.loadWorkspace()
        let logout = Task { await store.logout() }
        await provider.response.waitUntilRequested()
        #expect(store.connecting)
        #expect(store.phase == .signedOut && store.context == nil)
        #expect(identity.session == nil)
        let epoch = store.generation
        await store.startDemo(secondary: true)
        await store.connect(configuration)
        #expect(store.generation == epoch && store.context == nil)
        #expect(provider.authorizationCalls == 1)
        await provider.response.resolve(false)
        await logout.value
        #expect(!store.connecting && !store.isDemo)
        await store.startDemo(secondary: true)
        #expect(store.isDemo && store.phase == .ready)
        #expect(store.context?.tenantId == DemoCompany.secondary.tenantId)
    }
}
