import Foundation
import IAERPClient
import IAERPIdentity
import Security
import Testing
@testable import IAERP

@MainActor private final class RecoveryMemoryVault: InvoiceRecoveryVault {
    var data: Data?
    var writeCount = 0
    var failingWrite: Int?
    func read() -> Data? { data }
    func write(_ data: Data) throws {
        writeCount += 1
        if writeCount == failingWrite { throw InvoiceRecoveryError.storageFailure }
        self.data = data
    }
}

private actor RecoveryContextGate {
    private var requested = false
    private var arrival: CheckedContinuation<Void, Never>?
    private var reply: CheckedContinuation<Void, Never>?
    func pause() async {
        requested = true
        await withCheckedContinuation {
            reply = $0
            arrival?.resume(); arrival = nil
        }
    }
    func waitUntilRequested() async {
        if requested { return }
        await withCheckedContinuation { arrival = $0 }
    }
    func release() { reply?.resume(); reply = nil }
}

private actor RecoveryERPService: ERPService, ERPInvoiceDraftLookup {
    let demo = DemoERPService()
    let gate: RecoveryContextGate?
    private var createdIDs: [String: UUID] = [:]
    private var writes: [(String, Data)] = []
    private var loseResponse = false
    private var failGet = false
    private var failure: ERPClientError?
    private var lookupEnabled = true
    private var writable = true
    private var membershipActive = true
    private var expiredServerIdempotency = false
    private var createdInvoiceIDs: Set<UUID> = []
    private var lookups = 0
    init(gate: RecoveryContextGate? = nil) { self.gate = gate }
    func loseNextResponse() { loseResponse = true }
    func failNextConfirmationRead() { failGet = true }
    func rejectNextPost(_ error: ERPClientError) { failure = error }
    func useLookup(_ enabled: Bool) { lookupEnabled = enabled }
    func revoke(write: Bool) { if write { writable = false } else { membershipActive = false } }
    func capturedWrites() -> [(String, Data)] { writes }
    func createdCount() -> Int { createdInvoiceIDs.count }
    func lookupCount() -> Int { lookups }
    func expireIdempotencyEvidence(afterServerElapsed elapsed: TimeInterval) {
        guard elapsed >= 24 * 3600 else { return }
        createdIDs = [:]
        expiredServerIdempotency = true
    }
    func context() async throws -> ERPContext {
        if let gate { await gate.pause() }
        let value = try await demo.context()
        return ERPContext(tenantId: value.tenantId, ruc: value.ruc, name: value.name, roles: value.roles,
            scopes: writable ? value.scopes : value.scopes.filter { $0 != "invoices:write" })
    }
    func memberships() async throws -> [ERPMembership] {
        try await demo.memberships().map {
            ERPMembership(tenantId: $0.tenantId, organizationId: $0.organizationId, ruc: $0.ruc,
                tenantName: $0.tenantName, roles: $0.roles, active: membershipActive)
        }
    }
    func findDraft(idempotencyKey: String) async throws -> UUID? {
        lookups += 1
        return lookupEnabled ? createdIDs[idempotencyKey] : nil
    }
    func customers(query: String) async throws -> [ERPParty] { try await demo.customers(query: query) }
    func products(query: String) async throws -> [ERPProduct] { try await demo.products(query: query) }
    func invoiceSetup() async throws -> ERPInvoiceSetup { try await demo.invoiceSetup() }
    func invoices(query: String, status: String?) async throws -> [ERPInvoice] { try await demo.invoices(query: query, status: status) }
    func preview(_ input: ERPPreviewInput) async throws -> ERPInvoicePreview { try await demo.preview(input) }
    func createDraft(_ input: ERPInvoiceInput, idempotencyKey: String) async throws -> ERPInvoice {
        let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
        writes.append((idempotencyKey, try encoder.encode(input)))
        if let failure { self.failure = nil; throw failure }
        // A server whose idempotency evidence expired would treat a repeated
        // key as a new creation while retaining the existing business document.
        let serverKey = expiredServerIdempotency ? "\(idempotencyKey):expired:\(UUID().uuidString)" : idempotencyKey
        let value = try await demo.createDraft(input, idempotencyKey: serverKey)
        createdIDs[idempotencyKey] = value.id
        createdInvoiceIDs.insert(value.id)
        if loseResponse { loseResponse = false; throw URLError(.networkConnectionLost) }
        return value
    }
    func invoice(id: UUID) async throws -> ERPInvoice {
        if failGet { failGet = false; throw ERPClientError.server(503) }
        return try await demo.invoice(id: id)
    }
    func artifacts(invoiceID: UUID) async throws -> [ERPArtifact] { try await demo.artifacts(invoiceID: invoiceID) }
    func document(invoiceID: UUID, artifact: ERPArtifact) async throws -> ERPDocument {
        try await demo.document(invoiceID: invoiceID, artifact: artifact)
    }
}

@Suite("Recuperación durable de borradores", .timeLimit(.minutes(1)))
@MainActor struct InvoiceRecoveryTests {
    private func scope(subject: String = "recovery-user-a", profileID: UUID = UUID()) throws -> InvoiceRecoveryScope {
        InvoiceRecoveryScope(profileID: profileID,
            configuration: try IdentityConfiguration(apiBaseURL: URL(string: "https://api.example.invalid/api/v1")!,
                issuerURL: URL(string: "https://identity.example.invalid/realms/test")!, clientID: "iaerp-ios-test",
                organizationAlias: DemoCompany.primary.alias),
            subject: subject, organizationID: DemoCompany.primary.alias, tenantID: DemoCompany.primary.tenantId)
    }
    private func composer(_ service: RecoveryERPService) async throws -> (InvoiceComposer, ERPInvoiceSetup) {
        let setup = try await service.invoiceSetup()
        let customer = try #require(try await service.customers(query: "").first)
        let product = try #require(try await service.products(query: "").first)
        let value = InvoiceComposer(customerId: customer.id)
        value.issueDate = try #require(ISO8601DateFormatter().date(from: "2026-11-18T12:00:00Z"))
        value.establishmentId = setup.establishments.first?.id
        value.emissionPointId = setup.emissionPoints.first?.id
        value.add(product, setup: setup)
        await value.review(using: service, setup: setup)
        #expect(value.preview != nil)
        return (value, setup)
    }

    @Test func relaunchBeforePostRecoversOriginalPayloadAndCreatesOnlyOneDraft() async throws {
        let service = RecoveryERPService()
        let (composer, setup) = try await composer(service)
        let scope = try scope()
        let vault = RecoveryMemoryVault()
        let original = try composer.buildInput(setup: setup, total: composer.preview?.total)
        let prepared = try InvoiceRecoveryJournal(vault: vault).prepare(input: original, in: scope)
        #expect(await service.capturedWrites().isEmpty)
        let relaunched = InvoiceRecoveryJournal(vault: vault)
        #expect(try relaunched.pending(in: scope)?.id == prepared.id)
        let saved = try await relaunched.recover(in: scope, using: service) { scope }
        let writes = await service.capturedWrites()
        #expect(writes.count == 1 && writes[0].0 == prepared.idempotencyKey && writes[0].1 == prepared.requestPayload)
        #expect(await service.createdCount() == 1)
        #expect(try relaunched.pending(in: scope) == nil)
        #expect(saved.partyId == original.customerId)
    }

    @Test func relaunchAfterCommitLostResponseRequiresProofAndNeverPostsAgain() async throws {
        let service = RecoveryERPService()
        await service.useLookup(false)
        let (composer, setup) = try await composer(service)
        let scope = try scope(); let vault = RecoveryMemoryVault()
        let journal = InvoiceRecoveryJournal(vault: vault)
        await service.loseNextResponse()
        #expect(await composer.save(using: service, setup: setup, recoveryJournal: journal,
            recoveryScope: scope, authorizeRecoveryScope: { scope }) == nil)
        let pending = try #require(try journal.pending(in: scope))
        #expect(pending.attemptCount == 1)
        let relaunched = InvoiceRecoveryJournal(vault: vault)
        await #expect(throws: InvoiceRecoveryError.reconciliationRequired) {
            try await relaunched.recover(in: scope, using: service) { scope }
        }
        let writes = await service.capturedWrites()
        #expect(writes.count == 1)
        #expect(writes.allSatisfy { $0.0 == pending.idempotencyKey && $0.1 == pending.requestPayload })
        #expect(await service.createdCount() == 1)
        #expect(try relaunched.pending(in: scope) == pending)
        await service.useLookup(true)
        _ = try await relaunched.recover(in: scope, using: service) { scope }
        #expect(await service.capturedWrites().count == 1)
        #expect(try relaunched.pending(in: scope) == nil)
    }

    @Test func responseBeforeTerminationPersistsIDAndLaterUsesReadOnlyConfirmation() async throws {
        let service = RecoveryERPService()
        let (composer, setup) = try await composer(service)
        let scope = try scope(); let vault = RecoveryMemoryVault()
        let then = Date(timeIntervalSince1970: 1_795_000_000)
        let journal = InvoiceRecoveryJournal(vault: vault, now: { then })
        await service.failNextConfirmationRead()
        #expect(await composer.save(using: service, setup: setup, recoveryJournal: journal,
            recoveryScope: scope, authorizeRecoveryScope: { scope }) == nil)
        #expect(try journal.pending(in: scope)?.confirmedInvoiceID != nil)
        let relaunched = InvoiceRecoveryJournal(vault: vault, now: { then.addingTimeInterval(48 * 3600) })
        _ = try await relaunched.recover(in: scope, using: service) { scope }
        #expect(await service.capturedWrites().count == 1)
        #expect(try relaunched.pending(in: scope) == nil)
    }

    @Test func authoritativeLookupRecoversAfterRetentionWindowWithoutAnotherPost() async throws {
        let service = RecoveryERPService()
        let (composer, setup) = try await composer(service)
        let scope = try scope(); let vault = RecoveryMemoryVault()
        let then = Date(timeIntervalSince1970: 1_795_000_000)
        let journal = InvoiceRecoveryJournal(vault: vault, now: { then })
        await service.loseNextResponse()
        #expect(await composer.save(using: service, setup: setup, recoveryJournal: journal,
            recoveryScope: scope, authorizeRecoveryScope: { scope }) == nil)
        #expect(try journal.pending(in: scope)?.confirmedInvoiceID == nil)
        let relaunched = InvoiceRecoveryJournal(vault: vault, now: { then.addingTimeInterval(48 * 3600) })
        _ = try await relaunched.recover(in: scope, using: service) { scope }
        #expect(await service.capturedWrites().count == 1)
        #expect(await service.createdCount() == 1)
    }

    @Test(arguments: [ERPClientError.authenticationRequired, .forbidden, .idempotencyConflict])
    func firstPostAuthorizationOrConflictFailureCannotPermitAnotherPost(_ rejection: ERPClientError) async throws {
        let service = RecoveryERPService()
        await service.useLookup(false)
        let (composer, setup) = try await composer(service)
        let scope = try scope(); let vault = RecoveryMemoryVault()
        let journal = InvoiceRecoveryJournal(vault: vault)
        await service.rejectNextPost(rejection)
        _ = await composer.save(using: service, setup: setup, recoveryJournal: journal,
            recoveryScope: scope, authorizeRecoveryScope: { scope })
        let original = try #require(try journal.pending(in: scope))
        #expect(original.attemptCount == 1)
        await #expect(throws: InvoiceRecoveryError.reconciliationRequired) {
            try await InvoiceRecoveryJournal(vault: vault).recover(in: scope, using: service) { scope }
        }
        let retained = try #require(try journal.pending(in: scope))
        #expect(retained == original)
        #expect(throws: InvoiceRecoveryError.pendingOperation) {
            try journal.prepare(input: original.input(), in: scope)
        }
        #expect(await service.capturedWrites().count == 1)
        #expect(await service.createdCount() == 0)
    }

    @Test func firstValidationRejectionCanBeCorrectedWhileUncertainSaveNeverReposts() async throws {
        let service = RecoveryERPService(); await service.useLookup(false)
        let (composer, setup) = try await composer(service)
        let scope = try scope(); let vault = RecoveryMemoryVault(); let journal = InvoiceRecoveryJournal(vault: vault)
        await service.rejectNextPost(.invalidInput("Revisa el detalle."))
        _ = await composer.save(using: service, setup: setup, recoveryJournal: journal,
            recoveryScope: scope, authorizeRecoveryScope: { scope })
        #expect(try composer.canEdit && composer.pendingKey == nil && journal.pending(in: scope) == nil)
        await service.loseNextResponse()
        _ = await composer.save(using: service, setup: setup, recoveryJournal: journal,
            recoveryScope: scope, authorizeRecoveryScope: { scope })
        let key = try #require(composer.pendingKey)
        await service.rejectNextPost(.invalidInput("Revisa el detalle."))
        _ = await composer.save(using: service, setup: setup, recoveryJournal: journal,
            recoveryScope: scope, authorizeRecoveryScope: { scope })
        #expect(try !composer.canEdit && composer.pendingKey == key && journal.pending(in: scope) != nil)
        #expect(await service.capturedWrites().count == 2) // Initial rejection and one lost response; no third POST.
    }

    @Test func partialClockRollbackAfterServerRetentionExpiresCannotDuplicateTheCommittedDraft() async throws {
        let service = RecoveryERPService()
        let (composer, setup) = try await composer(service)
        let scope = try scope(); let vault = RecoveryMemoryVault()
        let preparedAt = Date(timeIntervalSince1970: 1_795_000_000)
        let journal = InvoiceRecoveryJournal(vault: vault, now: { preparedAt })
        await service.loseNextResponse()
        #expect(await composer.save(using: service, setup: setup, recoveryJournal: journal,
            recoveryScope: scope, authorizeRecoveryScope: { scope }) == nil)
        let original = try #require(try journal.pending(in: scope))
        #expect(original.attemptCount == 1 && original.confirmedInvoiceID == nil)
        #expect(await service.createdCount() == 1)

        // The server independently advanced 26h and purged its key. After a
        // restart the device reports only +2h: still >= createdAt and <23h.
        // Neither local comparison is evidence that replay is safe.
        await service.expireIdempotencyEvidence(afterServerElapsed: 26 * 3600)
        let lookupsBefore = await service.lookupCount()
        let restarted = InvoiceRecoveryJournal(vault: vault, now: { preparedAt.addingTimeInterval(2 * 3600) })
        await #expect(throws: InvoiceRecoveryError.reconciliationRequired) {
            try await restarted.recover(in: scope, using: service) { scope }
        }
        #expect(await service.lookupCount() == lookupsBefore + 1)
        #expect(await service.capturedWrites().count == 1)
        #expect(await service.createdCount() == 1)
        #expect(try restarted.pending(in: scope) == original)
        #expect(throws: InvoiceRecoveryError.pendingOperation) {
            try restarted.prepare(input: original.input(), in: scope)
        }
    }

    @Test func journalFailurePreventsAnyPost() async throws {
        let service = RecoveryERPService()
        let (composer, setup) = try await composer(service)
        let scope = try scope(); let vault = RecoveryMemoryVault(); vault.failingWrite = 1
        _ = await composer.save(using: service, setup: setup, recoveryJournal: InvoiceRecoveryJournal(vault: vault),
            recoveryScope: scope, authorizeRecoveryScope: { scope })
        #expect(await service.capturedWrites().isEmpty)
        #expect(composer.pendingInput == nil)
    }

    @Test func changedIdentityDuringContextCheckCannotSendOrForgetOperation() async throws {
        let gate = RecoveryContextGate(); let service = RecoveryERPService(gate: gate)
        let (composer, setup) = try await composer(service)
        let originalScope = try scope(); var active = originalScope
        let journal = InvoiceRecoveryJournal(vault: RecoveryMemoryVault())
        let record = try journal.prepare(input: composer.buildInput(setup: setup), in: originalScope)
        let recovery = Task { try await journal.recover(in: originalScope, using: service) { active } }
        await gate.waitUntilRequested()
        active = try scope(subject: "another-user")
        await gate.release()
        await #expect(throws: InvoiceRecoveryError.wrongIdentity) { try await recovery.value }
        #expect(await service.capturedWrites().isEmpty)
        #expect(try journal.pending(in: originalScope)?.id == record.id)
        #expect(try journal.pending(in: active) == nil)
    }

    @Test func separateJournalInstancesCannotRaceTheFirstAttemptState() async throws {
        let gate = RecoveryContextGate(); let service = RecoveryERPService(gate: gate)
        let (composer, setup) = try await composer(service)
        let scope = try scope(); let vault = RecoveryMemoryVault()
        let first = InvoiceRecoveryJournal(vault: vault)
        _ = try first.prepare(input: composer.buildInput(setup: setup), in: scope)
        let opening = Task { try await first.recover(in: scope, using: service) { scope } }
        await gate.waitUntilRequested()
        await #expect(throws: InvoiceRecoveryError.busy) {
            try await InvoiceRecoveryJournal(vault: vault).recover(in: scope, using: service) { scope }
        }
        await gate.release()
        _ = try await opening.value
        #expect(await service.capturedWrites().count == 1)
    }

    @Test(arguments: [true, false])
    func freshPermissionOrMembershipRevocationPreventsPost(_ writeRevoked: Bool) async throws {
        let service = RecoveryERPService()
        let (composer, setup) = try await composer(service)
        let scope = try scope(); let journal = InvoiceRecoveryJournal(vault: RecoveryMemoryVault())
        _ = try journal.prepare(input: composer.buildInput(setup: setup), in: scope)
        await service.revoke(write: writeRevoked)
        await #expect(throws: InvoiceRecoveryError.permissionDenied) { try await journal.recover(in: scope, using: service) { scope } }
        #expect(await service.capturedWrites().isEmpty)
        #expect(try journal.pending(in: scope) != nil)
    }

    @Test func expiredUnconfirmedOperationBlocksNewPostWhileFreshSameIdentityLoginCanRecover() async throws {
        let service = RecoveryERPService()
        let (composer, setup) = try await composer(service)
        let scope = try scope(); let vault = RecoveryMemoryVault()
        let then = Date(timeIntervalSince1970: 1_795_000_000)
        let journal = InvoiceRecoveryJournal(vault: vault, now: { then })
        _ = try journal.prepare(input: composer.buildInput(setup: setup), in: scope)
        let stale = InvoiceRecoveryJournal(vault: vault, now: { then.addingTimeInterval(24 * 3600) })
        await #expect(throws: InvoiceRecoveryError.reconciliationRequired) { try await stale.recover(in: scope, using: service) { scope } }
        #expect(await service.capturedWrites().isEmpty)
        let reauthenticated = try self.scope(subject: scope.subject, profileID: UUID())
        let withinWindow = InvoiceRecoveryJournal(vault: vault, now: { then.addingTimeInterval(3600) })
        _ = try await withinWindow.recover(in: reauthenticated, using: service) { reauthenticated }
        #expect(await service.createdCount() == 1)
    }

    @Test func confirmedInvoiceSurvivesJournalCleanupFailureWithoutAnotherPost() async throws {
        let service = RecoveryERPService()
        let (composer, setup) = try await composer(service)
        let scope = try scope(); let vault = RecoveryMemoryVault(); vault.failingWrite = 4
        let journal = InvoiceRecoveryJournal(vault: vault)
        _ = await composer.save(using: service, setup: setup, recoveryJournal: journal,
            recoveryScope: scope, authorizeRecoveryScope: { scope })
        #expect(try journal.pending(in: scope)?.confirmedInvoiceID != nil)
        vault.failingWrite = nil
        _ = try await InvoiceRecoveryJournal(vault: vault).recover(in: scope, using: service) { scope }
        #expect(await service.capturedWrites().count == 1)
        #expect(try journal.pending(in: scope) == nil)
    }

    @Test(arguments: ["documentHost", "clientID", "alias", "apiCanonical"])
    func publicConfigurationChangesCannotHideAnUncertainFinancialWrite(_ change: String) async throws {
        let service = RecoveryERPService(); await service.useLookup(false)
        let (composer, setup) = try await composer(service)
        let originalScope = try scope(); let vault = RecoveryMemoryVault()
        let journal = InvoiceRecoveryJournal(vault: vault)
        await service.loseNextResponse()
        _ = await composer.save(using: service, setup: setup, recoveryJournal: journal,
            recoveryScope: originalScope, authorizeRecoveryScope: { originalScope })
        let original = try #require(try journal.pending(in: originalScope))
        let config = originalScope.configuration
        let changedConfig = try IdentityConfiguration(
            apiBaseURL: change == "apiCanonical" ? URL(string: "https://API.example.invalid:443/api/v1/")! : config.apiBaseURL,
            issuerURL: config.issuerURL, clientID: change == "clientID" ? "iaerp-ios-new" : config.clientID,
            organizationAlias: change == "alias" ? "renamed-company" : config.organizationAlias,
            allowedDocumentHosts: change == "documentHost" ? ["documents.example.invalid"] : config.allowedDocumentHosts
        )
        let current = InvoiceRecoveryScope(profileID: UUID(), configuration: changedConfig,
            subject: originalScope.subject, organizationID: originalScope.organizationID, tenantID: originalScope.tenantID)
        let relaunched = InvoiceRecoveryJournal(vault: vault)
        #expect(try relaunched.pending(in: current)?.id == original.id)
        #expect(throws: InvoiceRecoveryError.pendingOperation) {
            try relaunched.prepare(input: original.input(), in: current)
        }
        await #expect(throws: InvoiceRecoveryError.reconciliationRequired) {
            try await relaunched.recover(in: current, using: service) { current }
        }
        #expect(await service.capturedWrites().count == 1)
        await service.useLookup(true)
        _ = try await relaunched.recover(in: current, using: service) { current }
        #expect(await service.capturedWrites().count == 1)
        #expect(try relaunched.pending(in: current) == nil)
    }

    @Test func downgradedReaderCanConfirmExistingDraftButCannotReplayMissingOperation() async throws {
        let service = RecoveryERPService()
        let (composer, setup) = try await composer(service)
        let scope = try scope(); let vault = RecoveryMemoryVault()
        let journal = InvoiceRecoveryJournal(vault: vault)
        await service.loseNextResponse()
        _ = await composer.save(using: service, setup: setup, recoveryJournal: journal,
            recoveryScope: scope, authorizeRecoveryScope: { scope })
        await service.revoke(write: true)
        _ = try await InvoiceRecoveryJournal(vault: vault).recover(in: scope, using: service) { scope }
        #expect(await service.capturedWrites().count == 1)
        #expect(try journal.pending(in: scope) == nil)
        _ = try journal.prepare(input: composer.buildInput(setup: setup), in: scope)
        await #expect(throws: InvoiceRecoveryError.permissionDenied) {
            try await journal.recover(in: scope, using: service) { scope }
        }
        #expect(await service.capturedWrites().count == 1)
    }

    @Test func nativeKeychainPersistsBetweenVaultInstancesWithoutSync() throws {
        let service = "ec.com.b2b.iaerp.test-recovery.\(UUID().uuidString)"
        defer {
            SecItemDelete([kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service] as CFDictionary)
        }
        let first = KeychainInvoiceRecoveryVault(service: service)
        let payload = Data("synthetic-recovery-state".utf8)
        do { try first.write(payload) }
        catch {
            Issue.record("Keychain operation=\(first.lastOperation ?? "unknown") OSStatus=\(first.lastOperationStatus.map { String($0) } ?? "none")")
            throw error
        }
        let second = KeychainInvoiceRecoveryVault(service: service)
        do {
            let restored = try second.read()
            #expect(restored == payload)
        }
        catch {
            Issue.record("Keychain operation=\(second.lastOperation ?? "unknown") OSStatus=\(second.lastOperationStatus.map { String($0) } ?? "none")")
            throw error
        }
    }
}
