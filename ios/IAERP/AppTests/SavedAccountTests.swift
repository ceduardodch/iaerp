import Foundation
import IAERPClient
import IAERPIdentity
import Testing
@testable import IAERP

@MainActor
private final class AccountVault: IdentityVault {
    var records: [StoredIdentity] = []
    var reads = 0
    func load() -> StoredIdentity? { records.first }
    func save(_ identity: StoredIdentity) { records = [identity] }
    func clear() { records = [] }
    func loadAll() -> [StoredIdentity] { reads += 1; return records }
    func saveAll(_ identities: [StoredIdentity]) { records = identities }
}

@MainActor
private final class AccountProvider: IdentityProvider {
    var subject = "user-a"
    var refreshes = 0
    func authorize(configuration: IdentityConfiguration) async throws -> IdentityGrant {
        func segment(_ object: [String: Any]) throws -> String {
            try JSONSerialization.data(withJSONObject: object, options: .sortedKeys).base64EncodedString()
                .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
                .replacingOccurrences(of: "=", with: "")
        }
        let expiry = Date.now.addingTimeInterval(3600)
        let claims: [String: Any] = [
            "iss": configuration.issuerURL.absoluteString, "aud": configuration.apiAudience,
            "azp": configuration.clientID, "sub": subject, "exp": expiry.timeIntervalSince1970,
            "organization": [configuration.organizationAlias: ["id": "tenant-a"]],
        ]
        return try IdentityGrant(accessToken: segment(["alg": "RS256"]) + "." + segment(claims) + ".synthetic",
            expiresAt: expiry, displayName: subject, serializedState: Data())
    }
    func refresh(grant: IdentityGrant, configuration: IdentityConfiguration) async throws -> IdentityGrant {
        refreshes += 1
        return grant
    }
    func closeRemoteSession(grant: IdentityGrant, configuration: IdentityConfiguration) async -> Bool { true }
    func cancel() { }
}

/// Explicit continuations deliberately allow a cancelled system prompt to reply
/// late, proving that the controller's epoch is an independent safety boundary.
@MainActor
private final class AccountUnlock: SessionUnlocking {
    var failure: SessionUnlockError?
    var held = false
    var calls = 0
    private var pending: [Int: CheckedContinuation<Void, any Error>] = [:]
    private var arrivals: [Int: CheckedContinuation<Void, Never>] = [:]
    func unlock() async throws {
        calls += 1
        let id = calls
        if held {
            try await withCheckedThrowingContinuation { continuation in
                pending[id] = continuation
                arrivals.removeValue(forKey: id)?.resume()
            }
        } else if let failure { throw failure }
    }
    func waitForCall(_ id: Int) async {
        if pending[id] != nil { return }
        await withCheckedContinuation { arrivals[id] = $0 }
    }
    func succeed(_ id: Int) { pending.removeValue(forKey: id)?.resume() }
    func cancel() { } // Exercise late replies rather than relying on cancellation.
}

@Suite("Cuentas guardadas y desbloqueo local", .timeLimit(.minutes(1)))
@MainActor
struct SavedAccountTests {
    private func fixture() async throws -> (IdentityManager, AuthenticationController, AccountUnlock, AccountVault, [SavedIdentityProfile]) {
        let config = try IdentityConfiguration(apiBaseURL: URL(string: "https://api.example.invalid/api/v1")!,
            issuerURL: URL(string: "https://identity.example.invalid/realms/test")!,
            clientID: "iaerp-ios-test", organizationAlias: "demo-a")
        let provider = AccountProvider()
        let vault = AccountVault()
        let manager = IdentityManager(provider: provider, vault: vault)
        try await manager.login(configuration: config)
        provider.subject = "user-b"
        try await manager.login(configuration: config)
        let profiles = try manager.savedProfiles().sorted { $0.subject < $1.subject }
        #expect(profiles.count == 2)
        let unlock = AccountUnlock()
        let controller = AuthenticationController(manager: manager, unlocking: unlock)
        controller.suspend()
        return (manager, controller, unlock, vault, profiles)
    }

    @Test(arguments: [SessionUnlockError.cancelled, .unavailable])
    func failedUnlockDoesNotReadOrRestoreCredentials(_ failure: SessionUnlockError) async throws {
        let (manager, controller, unlock, vault, profiles) = try await fixture()
        unlock.failure = failure
        let reads = vault.reads
        await #expect(throws: SessionUnlockError.self) { try await controller.restore(profileID: profiles[0].id) }
        #expect(manager.session == nil)
        #expect(vault.reads == reads)
        #expect(try manager.savedProfiles().count == 2)
    }

    @Test func selectingEachAccountRequiresFreshDeviceUnlock() async throws {
        let (manager, controller, unlock, _, profiles) = try await fixture()
        for index in [0, 1, 0] {
            #expect(try await controller.restore(profileID: profiles[index].id))
            #expect(manager.session?.subject == profiles[index].subject)
        }
        #expect(unlock.calls == 3)
        #expect(try manager.savedProfiles().count == 2)
    }

    @Test func lateUnlockOfAIsRejectedAfterSelectingB() async throws {
        let (manager, controller, unlock, _, profiles) = try await fixture()
        unlock.held = true
        let first = Task { try await controller.restore(profileID: profiles[0].id) }
        await unlock.waitForCall(1)
        let second = Task { try await controller.restore(profileID: profiles[1].id) }
        await unlock.waitForCall(2)
        unlock.succeed(2)
        #expect(try await second.value)
        unlock.succeed(1)
        await #expect(throws: IdentityError.sessionChanged) { try await first.value }
        #expect(manager.session?.subject == profiles[1].subject)
    }

    @Test func backgroundDuringUnlockCannotOpenSelectedAccount() async throws {
        let (manager, controller, unlock, _, profiles) = try await fixture()
        let store = WorkspaceStore(authentication: controller)
        store.findSavedSession()
        unlock.held = true
        let opening = Task { await store.restoreSession(profile: profiles[0]) }
        await unlock.waitForCall(1)
        let epoch = store.generation
        store.lockForBackground()
        #expect(store.generation != epoch && store.phase == .signedOut)
        unlock.succeed(1)
        await opening.value
        #expect(manager.session == nil && store.service == nil && store.context == nil)
        #expect(try manager.savedProfiles().count == 2)
    }

    @Test func accountSelectorClearsWorkspaceAndDocumentsButKeepsProfiles() async throws {
        let (manager, controller, _, _, _) = try await fixture()
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let documents = TemporaryDocuments(root: root)
        let store = WorkspaceStore(authentication: controller, documents: documents)
        await store.startDemo()
        #expect(store.phase == .ready && !store.customers.isEmpty)
        let file = try await documents.store(data: Data("%PDF-synthetic".utf8), fileName: "synthetic.pdf", generation: store.generation)
        let epoch = store.generation
        await store.showSavedAccounts()
        #expect(store.generation != epoch && store.phase == .signedOut && !store.isDemo)
        #expect(store.context == nil && store.customers.isEmpty && store.invoices.isEmpty && store.service == nil)
        #expect(!FileManager.default.fileExists(atPath: file.path))
        #expect(store.savedProfiles.count == 2 && manager.session == nil)
        store.forgetProfile(store.savedProfiles[0])
        #expect(store.savedProfiles.count == 1)
    }

    @Test func backgroundLocksReadyWorkspaceAndPreservesAccounts() async throws {
        let (manager, controller, _, _, profiles) = try await fixture()
        #expect(try await controller.restore(profileID: profiles[0].id))
        let store = WorkspaceStore(service: DemoERPService(), authentication: controller)
        store.findSavedSession()
        await store.loadWorkspace()
        #expect(store.phase == .ready && !store.isDemo && manager.session != nil)
        let epoch = store.generation
        store.lockForBackground()
        #expect(store.generation != epoch && store.phase == .signedOut)
        #expect(store.context == nil && store.customers.isEmpty && store.service == nil)
        #expect(manager.session == nil && store.savedProfiles.count == 2)
        await #expect(throws: IdentityError.noSession) { try await controller.accessToken() }
    }

    @Test func backgroundDuringLogoutCleanupCannotPreserveTheSignedOutProfile() async throws {
        let (manager, controller, _, vault, profiles) = try await fixture()
        #expect(try await controller.restore(profileID: profiles[0].id))
        let gate = AccountCleanupGate()
        let store = WorkspaceStore(service: DemoERPService(), authentication: controller,
                                   resetDocuments: { _ in await gate.pauseFirstReset() })
        await store.loadWorkspace()
        let closing = Task { await store.logout() }
        await gate.waitUntilPaused()
        let epoch = store.generation
        #expect(manager.session == nil && vault.records.count == 1)
        #expect(try vault.records[0].profile().subject == profiles[1].subject)
        store.lockForBackground()
        #expect(store.generation == epoch && store.connecting)
        #expect(store.phase == .signedOut && store.context == nil)
        await gate.resume()
        await closing.value
        #expect(!store.connecting && store.savedProfiles.count == 1)
    }

    @Test func restartingWorkspaceWithPendingWriteBlocksAnotherInvoice() async throws {
        let (_, controller, _, _, profiles) = try await fixture()
        #expect(try await controller.restore(profileID: profiles[0].id))
        let vault = AccountRecoveryVault()
        let api = DemoERPService()
        let first = WorkspaceStore(service: api, authentication: controller,
                                   invoiceRecoveryJournal: InvoiceRecoveryJournal(vault: vault))
        await first.loadWorkspace()
        #expect(first.canStartInvoice)
        let scope = try first.currentInvoiceRecoveryScope()
        let customer = try #require(try await api.customers(query: "").first)
        let product = try #require(try await api.products(query: "").first)
        let setup = try await api.invoiceSetup()
        let input = ERPInvoiceInput(customerId: customer.id, establishmentId: setup.establishments[0].id,
            emissionPointId: setup.emissionPoints[0].id, issueDate: "2026-11-18",
            lines: [ERPInvoiceLineInput(productId: product.id, description: product.name,
                quantity: 1, unitPrice: product.unitPrice, taxCode: "4")])
        let pending = try first.invoiceRecoveryJournal.prepare(input: input, in: scope)
        let restarted = WorkspaceStore(service: api, authentication: controller,
            invoiceRecoveryJournal: InvoiceRecoveryJournal(vault: vault))
        await restarted.loadWorkspace()
        #expect(restarted.pendingInvoiceRecovery?.id == pending.id)
        #expect(restarted.canCreate && !restarted.canStartInvoice)
        await restarted.startDemo()
        #expect(restarted.isDemo && restarted.canStartInvoice && restarted.pendingInvoiceRecovery == nil)
        #expect(try InvoiceRecoveryJournal(vault: vault).pending(in: scope)?.id == pending.id)
    }

    @Test(arguments: [false, true], [false, true])
    func interruptionDuringCleanupDoesNotStartAnObsoleteLogin(cancel: Bool, newLogin: Bool) async throws {
        let (manager, controller, unlock, _, profiles) = try await fixture()
        let gate = AccountCleanupGate()
        let store = WorkspaceStore(authentication: controller, resetDocuments: { _ in await gate.pauseFirstReset() })
        store.findSavedSession()
        let opening = Task {
            if newLogin { await store.connect(profiles[0].configuration) }
            else { await store.restoreSession(profile: profiles[0]) }
        }
        await gate.waitUntilPaused()
        if cancel { store.cancelConnection() }
        else { store.lockForBackground() }
        await gate.resume()
        await opening.value
        #expect(unlock.calls == 0 && manager.session == nil && store.context == nil)
        #expect(store.savedProfiles.count == 2)
    }
}

@MainActor private final class AccountRecoveryVault: InvoiceRecoveryVault {
    private var data: Data?
    func read() -> Data? { data }
    func write(_ data: Data) { self.data = data }
}

private actor AccountCleanupGate {
    private var started = false
    private var pause: CheckedContinuation<Void, Never>?
    private var waiter: CheckedContinuation<Void, Never>?
    func pauseFirstReset() async {
        guard !started else { return }
        started = true
        await withCheckedContinuation {
            pause = $0
            waiter?.resume()
            waiter = nil
        }
    }
    func waitUntilPaused() async {
        if pause != nil { return }
        await withCheckedContinuation { waiter = $0 }
    }
    func resume() { pause?.resume(); pause = nil }
}
