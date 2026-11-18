import Foundation
import Testing
@testable import IAERPIdentity

private func configuration(alias: String = "empresa-demo", audience: String = "iaerp-api") throws -> IdentityConfiguration {
    try IdentityConfiguration(
        apiBaseURL: URL(string: "https://api.example.invalid/api/v1")!,
        issuerURL: URL(string: "https://identity.example.invalid/realms/iaerp")!,
        clientID: "iaerp-ios", organizationAlias: alias, apiAudience: audience
    )
}

private func grant(
    alias: String = "empresa-demo", organizationID: String = "org-a", subject: String = "subject-a",
    audience: String = "iaerp-api", issuer: String = "https://identity.example.invalid/realms/iaerp",
    authorizedParty: String = "iaerp-ios", lifetime: TimeInterval = 3600,
    organizations: [String: [String: String]]? = nil, algorithm: String = "RS256",
    notBefore: Date? = nil
) throws -> IdentityGrant {
    func segment(_ dictionary: [String: Any]) throws -> String {
        try JSONSerialization.data(withJSONObject: dictionary, options: [.sortedKeys]).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
    let expiry = Date.now.addingTimeInterval(lifetime)
    var claims: [String: Any] = [
        "iss": issuer, "aud": [audience], "azp": authorizedParty, "sub": subject,
        "exp": expiry.timeIntervalSince1970,
        "organization": organizations ?? [alias: ["id": organizationID]],
    ]
    if let notBefore { claims["nbf"] = notBefore.timeIntervalSince1970 }
    let token = try segment(["alg": algorithm, "typ": "JWT"]) + "." + segment(claims) + ".synthetic-signature"
    return IdentityGrant(accessToken: token, expiresAt: expiry, displayName: "Usuario de prueba", serializedState: Data([1, 2, 3]))
}

@Suite("Configuración de identidad")
struct ConfigurationTests {
    @Test(arguments: ["http://identity.example.invalid/realms/iaerp", "https://user:secret@identity.example.invalid/realm", "https://identity.example.invalid/realm?token=bad", "https://identity.example.invalid/realm#bad"])
    func refusesUnsafeURLs(address: String) throws {
        #expect(throws: IdentityError.invalidConfiguration) {
            try IdentityConfiguration(
                apiBaseURL: URL(string: "https://api.example.invalid/api/v1")!,
                issuerURL: URL(string: address)!, clientID: "iaerp-ios", organizationAlias: "empresa-demo"
            )
        }
    }

    @Test func scopesBindOneOrganizationAndOnlyNeededCapabilities() throws {
        let config = try configuration()
        #expect(config.scopes.filter { $0.hasPrefix("organization:") } == ["organization:empresa-demo"])
        #expect(!config.scopes.contains("invoices:issue"))
        #expect(!config.scopes.contains("offline_access"))
        #expect(!config.scopes.contains("parties:write"))
    }

    @Test func refusesWrongCallback() throws {
        #expect(throws: IdentityError.invalidConfiguration) {
            try IdentityConfiguration(
                apiBaseURL: URL(string: "https://api.example.invalid/api/v1")!,
                issuerURL: URL(string: "https://identity.example.invalid/realms/iaerp")!,
                clientID: "iaerp-ios", redirectURL: URL(string: "otherapp:/oauth2redirect")!, organizationAlias: "empresa-demo"
            )
        }
    }

    @Test func decodingCannotBypassValidation() throws {
        let encoded = try JSONEncoder().encode(configuration())
        let invalid = String(decoding: encoded, as: UTF8.self).replacingOccurrences(of: "https:", with: "http:")
        #expect(throws: IdentityError.invalidConfiguration) {
            try JSONDecoder().decode(IdentityConfiguration.self, from: Data(invalid.utf8))
        }
    }

    @Test(arguments: ["https://files.example.invalid", "files.example.invalid:443", "user@files.example.invalid", "files.example.invalid/path", "*.example.invalid", "files..example.invalid", "-files.example.invalid", "files.example.invalid.", "archivos.ejémplo.invalid"])
    func refusesUnsafeDocumentHosts(host: String) throws {
        #expect(throws: IdentityError.invalidConfiguration) {
            try IdentityConfiguration(
                apiBaseURL: URL(string: "https://api.example.invalid/api/v1")!,
                issuerURL: URL(string: "https://identity.example.invalid/realms/iaerp")!,
                clientID: "iaerp-ios", organizationAlias: "empresa-demo", allowedDocumentHosts: [host]
            )
        }
    }

    @Test func documentAllowlistRoundTripsAndNormalizesDNSCase() throws {
        let config = try IdentityConfiguration(
            apiBaseURL: URL(string: "https://api.example.invalid/api/v1")!,
            issuerURL: URL(string: "https://identity.example.invalid/realms/iaerp")!,
            clientID: "iaerp-ios", organizationAlias: "empresa-demo",
            allowedDocumentHosts: ["FILES.Example.invalid"]
        )
        #expect(config.allowedDocumentHosts == ["files.example.invalid"])
        #expect(try JSONDecoder().decode(IdentityConfiguration.self, from: JSONEncoder().encode(config)) == config)
    }

    @Test func oldConfigurationCannotSilentlyGainDocumentPermissions() throws {
        let data = try JSONEncoder().encode(configuration())
        var json = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        json.removeValue(forKey: "allowedDocumentHosts")
        let oldData = try JSONSerialization.data(withJSONObject: json)
        #expect(throws: DecodingError.self) {
            try JSONDecoder().decode(IdentityConfiguration.self, from: oldData)
        }
    }

    @Test func discoveredEndpointsStayOnIssuerOrigin() throws {
        let config = try configuration()
        #expect(config.permitsIdentityEndpoint(URL(string: "https://identity.example.invalid/realms/iaerp/token")!))
        #expect(!config.permitsIdentityEndpoint(URL(string: "https://evil.example.invalid/token")!))
        #expect(!config.permitsIdentityEndpoint(URL(string: "https://identity.example.invalid:8443/token")!))
    }
}

@Suite("Filtro local de metadatos, sin sustituir validación del backend")
struct MetadataTests {
    @Test func acceptsBoundMetadata() throws {
        let session = try AccessTokenMetadata.session(from: grant(), configuration: configuration())
        #expect(session.organizationID == "org-a")
        #expect(session.subject == "subject-a")
    }

    @Test func rejectsOtherAudience() throws {
        #expect(throws: IdentityError.audienceMismatch) {
            try AccessTokenMetadata.session(from: grant(audience: "another-api"), configuration: configuration())
        }
    }

    @Test func rejectsAnotherClient() throws {
        #expect(throws: IdentityError.audienceMismatch) {
            try AccessTokenMetadata.session(from: grant(authorizedParty: "iaerp-web"), configuration: configuration())
        }
    }

    @Test func rejectsOtherIssuer() throws {
        #expect(throws: IdentityError.issuerMismatch) {
            try AccessTokenMetadata.session(from: grant(issuer: "https://evil.example.invalid/realm"), configuration: configuration())
        }
    }

    @Test func rejectsExpiredAccess() throws {
        #expect(throws: IdentityError.expiredToken) {
            try AccessTokenMetadata.session(from: grant(lifetime: -10), configuration: configuration())
        }
    }

    @Test func rejectsSeveralOrganizations() throws {
        #expect(throws: IdentityError.organizationMismatch) {
            try AccessTokenMetadata.session(
                from: grant(organizations: ["empresa-demo": ["id": "org-a"], "otra-empresa": ["id": "org-b"]]),
                configuration: configuration()
            )
        }
    }

    @Test func rejectsWrongSelectedOrganization() throws {
        #expect(throws: IdentityError.organizationMismatch) {
            try AccessTokenMetadata.session(from: grant(alias: "otra-empresa"), configuration: configuration())
        }
    }

    @Test func refusesUnsignedAlgorithm() throws {
        #expect(throws: IdentityError.invalidToken) {
            try AccessTokenMetadata.session(from: grant(algorithm: "none"), configuration: configuration())
        }
    }
}

@MainActor private final class MemoryVault: IdentityVault {
    var value: StoredIdentity?
    var failSave = false
    var failClear = false
    var failLoad = false
    var savedAccessTokens: [String] = []
    var onSave: ((StoredIdentity) -> Void)?
    func save(_ identity: StoredIdentity) throws {
        if failSave { throw IdentityError.storageFailure }
        value = identity
        savedAccessTokens.append(identity.grant.accessToken)
        onSave?(identity)
    }
    func load() throws -> StoredIdentity? {
        if failLoad { throw IdentityError.storageFailure }
        return value
    }
    func clear() throws {
        if failClear { throw IdentityError.storageFailure }
        value = nil
    }
}

@MainActor private final class FakeProvider: IdentityProvider {
    var authorizationGrant: IdentityGrant
    var refreshGrant: IdentityGrant
    var authorizationError: IdentityError?
    var holdAuthorization = false
    var holdRefresh = false
    var pendingAuthorization: CheckedContinuation<IdentityGrant, any Error>?
    var pendingRefresh: CheckedContinuation<IdentityGrant, any Error>?
    var refreshContinuations: [CheckedContinuation<IdentityGrant, any Error>] = []
    var refreshCalls = 0
    var authorizationCalls = 0
    var closeCalls = 0
    var remotelyClosed = false
    var closedGrant: IdentityGrant?
    var closedConfiguration: IdentityConfiguration?

    init() throws { authorizationGrant = try grant(); refreshGrant = try grant(lifetime: 7200) }
    func authorize(configuration: IdentityConfiguration) async throws -> IdentityGrant {
        authorizationCalls += 1
        if let authorizationError { throw authorizationError }
        if holdAuthorization { return try await withCheckedThrowingContinuation { pendingAuthorization = $0 } }
        return authorizationGrant
    }
    func refresh(grant: IdentityGrant, configuration: IdentityConfiguration) async throws -> IdentityGrant {
        refreshCalls += 1
        if holdRefresh {
            return try await withCheckedThrowingContinuation {
                pendingRefresh = $0
                refreshContinuations.append($0)
            }
        }
        return refreshGrant
    }
    func closeRemoteSession(grant: IdentityGrant, configuration: IdentityConfiguration) async -> Bool {
        closeCalls += 1
        closedGrant = grant
        closedConfiguration = configuration
        return remotelyClosed
    }
    func cancel() { /* Intentionally lets test replies arrive late. */ }
}

@Suite("Ciclo de sesión y concurrencia")
@MainActor
struct SessionTests {
    @Test func savedConfigurationReadsPublicProfileWithoutAuthenticating() throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        let config = try configuration()
        vault.value = StoredIdentity(configuration: config, grant: try grant(lifetime: -60))
        let manager = IdentityManager(provider: provider, vault: vault)
        #expect(try manager.savedConfiguration() == config)
        #expect(manager.session == nil)
        #expect(manager.configuration == nil)
        #expect(provider.authorizationCalls == 0)
        #expect(provider.refreshCalls == 0)
        #expect(vault.savedAccessTokens.isEmpty)
    }

    @Test func savedConfigurationReadFailureIsNotHiddenAsMissingSession() throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        vault.failLoad = true
        let manager = IdentityManager(provider: provider, vault: vault)
        #expect(throws: IdentityError.storageFailure) { try manager.savedConfiguration() }
        #expect(manager.session == nil)
        #expect(provider.authorizationCalls == 0)
        #expect(provider.refreshCalls == 0)
    }

    @Test func savedConfigurationReturnsNilAfterExplicitLogout() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        let manager = IdentityManager(provider: provider, vault: vault)
        try await manager.login(configuration: configuration())
        #expect(try manager.savedConfiguration() != nil)
        _ = await manager.logout()
        #expect(try manager.savedConfiguration() == nil)
    }

    @Test func restoreRejectsAnExpandedDocumentAllowlist() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        vault.value = StoredIdentity(configuration: try configuration(), grant: try grant())
        let manager = IdentityManager(provider: provider, vault: vault)
        let changed = try IdentityConfiguration(
            apiBaseURL: URL(string: "https://api.example.invalid/api/v1")!,
            issuerURL: URL(string: "https://identity.example.invalid/realms/iaerp")!,
            clientID: "iaerp-ios", organizationAlias: "empresa-demo",
            allowedDocumentHosts: ["files.example.invalid"]
        )
        let restored = try await manager.restore(configuration: changed)
        #expect(!restored)
        // A caller's changed connection must not delete another saved profile.
        #expect(try vault.value?.configuration == configuration())
        #expect(manager.session == nil)
        #expect(provider.refreshCalls == 0)
    }

    @Test func cancelledLoginStoresNothing() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        provider.authorizationError = .cancelled
        let manager = IdentityManager(provider: provider, vault: vault)
        await #expect(throws: IdentityError.cancelled) { try await manager.login(configuration: configuration()) }
        #expect(manager.session == nil)
        #expect(vault.value == nil)
    }

    @Test func lateBrowserResultAfterCancelCannotRestoreSession() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        provider.holdAuthorization = true
        let manager = IdentityManager(provider: provider, vault: vault)
        let login = Task { try await manager.login(configuration: configuration()) }
        while provider.pendingAuthorization == nil { await Task.yield() }
        manager.cancel()
        provider.pendingAuthorization?.resume(returning: provider.authorizationGrant)
        await #expect(throws: IdentityError.sessionChanged) { try await login.value }
        #expect(manager.session == nil)
        #expect(vault.value == nil)
    }

    @Test func cancelledCallerCannotCommitLateAuthorization() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        provider.holdAuthorization = true
        let manager = IdentityManager(provider: provider, vault: vault)
        let login = Task { try await manager.login(configuration: configuration()) }
        while provider.pendingAuthorization == nil { await Task.yield() }
        login.cancel()
        provider.pendingAuthorization?.resume(returning: provider.authorizationGrant)
        await #expect(throws: IdentityError.cancelled) { try await login.value }
        #expect(manager.session == nil)
        #expect(vault.value == nil)
    }

    @Test func concurrentRefreshUsesOneExchange() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        provider.authorizationGrant = try grant(lifetime: 10)
        provider.holdRefresh = true
        let manager = IdentityManager(provider: provider, vault: vault)
        try await manager.login(configuration: configuration())
        let first = Task { try await manager.accessToken() }
        let second = Task { try await manager.accessToken() }
        while provider.pendingRefresh == nil { await Task.yield() }
        #expect(provider.refreshCalls == 1)
        provider.pendingRefresh?.resume(returning: provider.refreshGrant)
        let firstToken = try await first.value
        let secondToken = try await second.value
        #expect(firstToken == secondToken)
        #expect(firstToken == provider.refreshGrant.accessToken)
    }

    @Test(.timeLimit(.minutes(1)))
    func olderRefreshWaitersCannotOverwriteOrUnregisterNewRefresh() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        let manager = IdentityManager(provider: provider, vault: vault)
        let firstGrant = try grant(lifetime: 7200)
        let secondGrant = try grant(lifetime: 10800)
        provider.holdRefresh = true
        try await manager.login(configuration: configuration())
        let initialToken = try #require(vault.value?.grant.accessToken)
        var nextRefresh: Task<String, any Error>?
        // A consumer requests a fresh token as soon as R1 is committed, while
        // the original callers are still waiting for that shared result.
        vault.onSave = { stored in
            if stored.grant.accessToken == firstGrant.accessToken, nextRefresh == nil {
                nextRefresh = Task(priority: .high) { try await manager.accessToken(forceRefresh: true) }
            }
        }
        var enteredFirstWaiters = 0
        let firstWaiters = (0..<3).map { _ in
            Task(priority: .low) {
                enteredFirstWaiters += 1
                return try await manager.accessToken(forceRefresh: true)
            }
        }
        while enteredFirstWaiters < 3 || provider.refreshContinuations.count < 1 { await Task.yield() }
        provider.refreshContinuations[0].resume(returning: firstGrant)
        while provider.refreshContinuations.count < 2 { await Task.yield() }
        for waiter in firstWaiters { _ = try await waiter.value }
        var followerEntered = false
        let follower = Task {
            followerEntered = true
            return try await manager.accessToken(forceRefresh: true)
        }
        // Entering accessToken runs synchronously on MainActor until its await.
        // Observe that point rather than depending on sleeps or queue timing.
        while !followerEntered { await Task.yield() }
        #expect(provider.refreshCalls == 2)
        #expect(vault.savedAccessTokens == [initialToken, firstGrant.accessToken])
        // Future unintended exchanges complete immediately, so a regression
        // reports assertions rather than leaving continuations suspended.
        provider.refreshGrant = secondGrant
        provider.holdRefresh = false
        for continuation in provider.refreshContinuations.dropFirst() {
            continuation.resume(returning: secondGrant)
        }
        let next = try #require(nextRefresh)
        #expect(try await next.value == secondGrant.accessToken)
        #expect(try await follower.value == secondGrant.accessToken)
        #expect(vault.value?.grant.accessToken == secondGrant.accessToken)
        #expect(provider.refreshCalls == 2)
        #expect(vault.savedAccessTokens == [initialToken, firstGrant.accessToken, secondGrant.accessToken])
    }

    @Test func logoutClearsLocalEvenWhenRemoteFails() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        let manager = IdentityManager(provider: provider, vault: vault)
        try await manager.login(configuration: configuration())
        let result = await manager.logout()
        #expect(result.localCleared)
        #expect(!result.remoteClosed)
        #expect(manager.session == nil)
        #expect(vault.value == nil)
        #expect(provider.closeCalls == 1)
        await #expect(throws: IdentityError.noSession) { try await manager.accessToken() }
    }

    @Test func lateRefreshAfterLogoutCannotResurrectCredentials() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        provider.holdRefresh = true
        let manager = IdentityManager(provider: provider, vault: vault)
        try await manager.login(configuration: configuration())
        let refresh = Task { try await manager.accessToken(forceRefresh: true) }
        while provider.pendingRefresh == nil { await Task.yield() }
        _ = await manager.logout()
        provider.pendingRefresh?.resume(returning: provider.refreshGrant)
        await #expect(throws: IdentityError.sessionChanged) { try await refresh.value }
        #expect(manager.session == nil)
        #expect(vault.value == nil)
    }

    @Test func refreshCannotChangeSubjectOrOrganization() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        provider.refreshGrant = try grant(organizationID: "org-b")
        let manager = IdentityManager(provider: provider, vault: vault)
        try await manager.login(configuration: configuration())
        await #expect(throws: IdentityError.organizationMismatch) { try await manager.accessToken(forceRefresh: true) }
        #expect(manager.session == nil)
        #expect(vault.value == nil)
    }

    @Test func restoreRejectsDifferentProfileWithoutNetwork() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        vault.value = StoredIdentity(configuration: try configuration(), grant: try grant())
        let manager = IdentityManager(provider: provider, vault: vault)
        let restored = try await manager.restore(configuration: configuration(alias: "otra-empresa"))
        #expect(!restored)
        #expect(try vault.value?.configuration == configuration())
        #expect(provider.refreshCalls == 0)
    }

    @Test func cancelImmediatelyInvalidatesMemoryButKeepsRememberedCredentials() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        let manager = IdentityManager(provider: provider, vault: vault)
        try await manager.login(configuration: configuration())
        manager.cancel()
        #expect(manager.session == nil)
        #expect(manager.configuration == nil)
        #expect(vault.value != nil)
        #expect(try manager.savedProfiles().count == 1)
        await #expect(throws: IdentityError.noSession) { try await manager.accessToken() }
    }

    @Test func expiredRestoreCannotSwitchOrganizationDuringRefresh() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        vault.value = StoredIdentity(configuration: try configuration(), grant: try grant(lifetime: -60))
        provider.refreshGrant = try grant(organizationID: "org-b")
        let manager = IdentityManager(provider: provider, vault: vault)
        await #expect(throws: IdentityError.organizationMismatch) {
            try await manager.restore(configuration: configuration())
        }
        #expect(manager.session == nil)
        #expect(vault.value == nil)
    }

    @Test func storageFailureDoesNotExposeSignedInState() async throws {
        let provider = try FakeProvider()
        let vault = MemoryVault()
        vault.failSave = true
        let manager = IdentityManager(provider: provider, vault: vault)
        await #expect(throws: IdentityError.storageFailure) { try await manager.login(configuration: configuration()) }
        #expect(manager.session == nil)
        #expect(vault.value == nil)
    }
}

@MainActor private final class MemoryIdentityStorage: IdentityVaultStorage {
    var items: [String: Data] = [:]
    var failWrite = false
    var failRemove = false
    var writes: [String] = []
    func read(account: String) throws -> Data? { items[account] }
    func write(_ data: Data, account: String) throws {
        if failWrite { throw IdentityError.storageFailure }
        items[account] = data
        writes.append(account)
    }
    func remove(account: String) throws {
        if failRemove { throw IdentityError.storageFailure }
        items.removeValue(forKey: account)
    }
}

@Suite("Usuarios guardados y migración de Llavero")
@MainActor
struct SavedProfilesTests {
    @Test func twoUsersInSameCompanyAndOtherCompanyRemainDistinct() async throws {
        let provider = try FakeProvider()
        let storage = MemoryIdentityStorage()
        let vault = KeychainIdentityVault(storage: storage)
        let manager = IdentityManager(provider: provider, vault: vault)
        try await manager.login(configuration: configuration())
        let firstID = try #require(manager.activeProfileID)
        provider.authorizationGrant = try grant(subject: "subject-b")
        try await manager.login(configuration: configuration())
        let secondID = try #require(manager.activeProfileID)
        provider.authorizationGrant = try grant(alias: "otra-empresa", organizationID: "org-b")
        try await manager.login(configuration: configuration(alias: "otra-empresa"))
        let thirdID = try #require(manager.activeProfileID)
        #expect(Set([firstID, secondID, thirdID]).count == 3)
        #expect(try manager.savedProfiles().count == 3)
        #expect(try manager.savedConfiguration() == nil)
        // Matching only the connection cannot choose between two users.
        #expect(try await manager.restore(configuration: configuration()) == false)
        #expect(manager.session == nil)
        #expect(try manager.savedProfiles().count == 3)
        #expect(try await manager.restore(profileID: firstID))
        #expect(manager.session?.subject == "subject-a")
        #expect(manager.session?.organizationID == "org-a")
        #expect(try await manager.restore(profileID: secondID))
        #expect(manager.session?.subject == "subject-b")
        #expect(try await manager.restore(profileID: thirdID))
        #expect(manager.session?.organizationAlias == "otra-empresa")
        #expect(manager.session?.organizationID == "org-b")
        #expect(provider.refreshCalls == 0)
    }

    @Test func newLoginOfSameBoundUserUpdatesRatherThanDuplicates() async throws {
        let provider = try FakeProvider()
        let vault = KeychainIdentityVault(storage: MemoryIdentityStorage())
        let manager = IdentityManager(provider: provider, vault: vault)
        try await manager.login(configuration: configuration())
        let id = manager.activeProfileID
        provider.authorizationGrant = try grant(lifetime: 7200)
        try await manager.login(configuration: configuration())
        #expect(manager.activeProfileID == id)
        #expect(try manager.savedProfiles().count == 1)
        #expect(try await manager.accessToken() == provider.authorizationGrant.accessToken)
    }

    @Test func cancelledAdditionAndSuspendKeepPreviouslySavedUsersAcrossRelaunch() async throws {
        let provider = try FakeProvider()
        let storage = MemoryIdentityStorage()
        let manager = IdentityManager(provider: provider, vault: KeychainIdentityVault(storage: storage))
        try await manager.login(configuration: configuration())
        let id = try #require(manager.activeProfileID)
        provider.authorizationError = .cancelled
        await #expect(throws: IdentityError.cancelled) { try await manager.login(configuration: configuration()) }
        manager.suspend()
        #expect(manager.session == nil)
        await #expect(throws: IdentityError.noSession) { try await manager.accessToken() }
        let relaunched = IdentityManager(provider: provider, vault: KeychainIdentityVault(storage: storage))
        #expect(try relaunched.savedProfiles().map(\.id) == [id])
        #expect(relaunched.session == nil)
        #expect(try await relaunched.restore(profileID: id))
        #expect(relaunched.session?.subject == "subject-a")
    }

    @Test func forgettingOneProfileAndLogoutPreserveOtherUsers() async throws {
        let provider = try FakeProvider()
        let manager = IdentityManager(provider: provider, vault: KeychainIdentityVault(storage: MemoryIdentityStorage()))
        try await manager.login(configuration: configuration())
        let firstID = try #require(manager.activeProfileID)
        provider.authorizationGrant = try grant(subject: "subject-b")
        try await manager.login(configuration: configuration())
        let secondID = try #require(manager.activeProfileID)
        try manager.forget(profileID: firstID)
        #expect(try manager.savedProfiles().map(\.id) == [secondID])
        #expect(manager.session?.subject == "subject-b")
        #expect(try await manager.restore(profileID: firstID) == false)
        #expect(manager.session == nil)
        #expect(try await manager.restore(profileID: secondID))
        let result = await manager.logout()
        #expect(result.localCleared)
        #expect(try manager.savedProfiles().isEmpty)
        #expect(manager.session == nil)
    }

    @Test func logoutActiveAccountDoesNotRemoveInactiveProfile() async throws {
        let provider = try FakeProvider()
        let manager = IdentityManager(provider: provider, vault: KeychainIdentityVault(storage: MemoryIdentityStorage()))
        try await manager.login(configuration: configuration())
        let firstID = try #require(manager.activeProfileID)
        provider.authorizationGrant = try grant(subject: "subject-b")
        try await manager.login(configuration: configuration())
        _ = await manager.logout()
        #expect(try manager.savedProfiles().map(\.id) == [firstID])
        #expect(try await manager.restore(profileID: firstID))
        #expect(manager.session?.subject == "subject-a")
    }

    @Test func lateRefreshCannotOverwriteOtherSelectedProfile() async throws {
        let provider = try FakeProvider()
        let vault = KeychainIdentityVault(storage: MemoryIdentityStorage())
        let manager = IdentityManager(provider: provider, vault: vault)
        try await manager.login(configuration: configuration())
        let firstID = try #require(manager.activeProfileID)
        provider.authorizationGrant = try grant(subject: "subject-b")
        try await manager.login(configuration: configuration())
        let secondID = try #require(manager.activeProfileID)
        _ = try await manager.restore(profileID: firstID)
        provider.holdRefresh = true
        let refresh = Task { try await manager.accessToken(forceRefresh: true) }
        while provider.pendingRefresh == nil { await Task.yield() }
        _ = try await manager.restore(profileID: secondID)
        provider.pendingRefresh?.resume(returning: provider.refreshGrant)
        await #expect(throws: IdentityError.sessionChanged) { try await refresh.value }
        #expect(manager.activeProfileID == secondID)
        #expect(manager.session?.subject == "subject-b")
        let stored = try vault.loadAll()
        #expect(try stored.first(where: { $0.id == firstID })?.profile().subject == "subject-a")
        #expect(try stored.first(where: { $0.id == secondID })?.profile().subject == "subject-b")
    }

    @Test func renewedTokensPersistOnlyForSelectedProfile() async throws {
        let provider = try FakeProvider()
        let vault = KeychainIdentityVault(storage: MemoryIdentityStorage())
        let manager = IdentityManager(provider: provider, vault: vault)
        try await manager.login(configuration: configuration())
        let firstID = try #require(manager.activeProfileID)
        let originalToken = provider.authorizationGrant.accessToken
        provider.authorizationGrant = try grant(subject: "subject-b")
        provider.refreshGrant = try grant(subject: "subject-b", lifetime: 7200)
        try await manager.login(configuration: configuration())
        let secondID = try #require(manager.activeProfileID)
        _ = try await manager.accessToken(forceRefresh: true)
        let stored = try vault.loadAll()
        #expect(stored.first(where: { $0.id == firstID })?.grant.accessToken == originalToken)
        #expect(stored.first(where: { $0.id == secondID })?.grant.accessToken == provider.refreshGrant.accessToken)
    }

    @Test func legacyMigrationKeepsIdentityAndStableIDAfterRelaunch() throws {
        let storage = MemoryIdentityStorage()
        // Exact former shape: configuration + grant, no profile UUID.
        let legacy = StoredIdentity(configuration: try configuration(), grant: try grant())
        var json = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(legacy)) as? [String: Any])
        json.removeValue(forKey: "id")
        storage.items[KeychainIdentityVault.legacyAccount] = try JSONSerialization.data(withJSONObject: json)
        let migrated = try KeychainIdentityVault(storage: storage).loadAll()
        #expect(migrated.count == 1)
        #expect(try migrated.first?.profile().subject == "subject-a")
        #expect(storage.items[KeychainIdentityVault.legacyAccount] == nil)
        let relaunched = try KeychainIdentityVault(storage: storage).loadAll()
        #expect(relaunched.map(\.id) == migrated.map(\.id))
        #expect(relaunched.first?.grant.accessToken == legacy.grant.accessToken)
    }

    @Test func failedMigrationWriteDoesNotDeleteOriginalSession() throws {
        let storage = MemoryIdentityStorage()
        let original = try JSONEncoder().encode(StoredIdentity(configuration: configuration(), grant: grant()))
        storage.items[KeychainIdentityVault.legacyAccount] = original
        storage.failWrite = true
        let vault = KeychainIdentityVault(storage: storage)
        #expect(throws: IdentityError.storageFailure) { try vault.loadAll() }
        #expect(storage.items[KeychainIdentityVault.legacyAccount] == original)
        #expect(storage.items[KeychainIdentityVault.currentAccount] == nil)
        storage.failWrite = false
        #expect(try vault.loadAll().count == 1)
    }

    @Test func interruptedLegacyDeletionNeverResurrectsRemovedUsers() throws {
        let storage = MemoryIdentityStorage()
        storage.items[KeychainIdentityVault.legacyAccount] = try JSONEncoder().encode(
            StoredIdentity(configuration: configuration(), grant: grant())
        )
        storage.failRemove = true
        let vault = KeychainIdentityVault(storage: storage)
        #expect(throws: IdentityError.storageFailure) { try vault.loadAll() }
        #expect(storage.items[KeychainIdentityVault.currentAccount] != nil)
        // Even if deleting the old item continues failing, an empty v2 is
        // authoritative. Selecting/removing profiles never falls back to v1.
        #expect(throws: IdentityError.storageFailure) { try vault.saveAll([]) }
        #expect(try KeychainIdentityVault(storage: storage).loadAll().isEmpty)
        #expect(storage.items[KeychainIdentityVault.legacyAccount] != nil)
    }

    @Test func corruptCollectionNeverFallsBackToLegacyCredentials() throws {
        let storage = MemoryIdentityStorage()
        storage.items[KeychainIdentityVault.currentAccount] = Data("corrupt".utf8)
        storage.items[KeychainIdentityVault.legacyAccount] = try JSONEncoder().encode(
            StoredIdentity(configuration: configuration(), grant: grant())
        )
        #expect(throws: IdentityError.storageFailure) { try KeychainIdentityVault(storage: storage).loadAll() }
        #expect(storage.writes.isEmpty)
    }
}

@Suite("Fallos de restauración entre cuentas")
@MainActor
struct ProfileRestoreFailureTests {
    @Test func cancellingExpiredRestoreKeepsOtherAndSelectedProfiles() async throws {
        let provider = try FakeProvider()
        let manager = IdentityManager(provider: provider, vault: KeychainIdentityVault(storage: MemoryIdentityStorage()))
        provider.authorizationGrant = try grant(lifetime: 10)
        try await manager.login(configuration: configuration())
        let firstID = try #require(manager.activeProfileID)
        provider.authorizationGrant = try grant(subject: "subject-b")
        try await manager.login(configuration: configuration())
        let secondID = try #require(manager.activeProfileID)
        provider.holdRefresh = true
        let restore = Task { try await manager.restore(profileID: firstID) }
        while provider.pendingRefresh == nil { await Task.yield() }
        restore.cancel()
        provider.pendingRefresh?.resume(returning: provider.refreshGrant)
        await #expect(throws: CancellationError.self) { try await restore.value }
        #expect(manager.session == nil)
        #expect(Set(try manager.savedProfiles().map(\.id)) == Set([firstID, secondID]))
    }

    @Test func wrongSubjectOnRefreshRemovesOnlyThatProfile() async throws {
        let provider = try FakeProvider()
        let manager = IdentityManager(provider: provider, vault: KeychainIdentityVault(storage: MemoryIdentityStorage()))
        provider.authorizationGrant = try grant(lifetime: 10)
        try await manager.login(configuration: configuration())
        let firstID = try #require(manager.activeProfileID)
        provider.authorizationGrant = try grant(subject: "subject-b")
        try await manager.login(configuration: configuration())
        let secondID = try #require(manager.activeProfileID)
        provider.refreshGrant = try grant(subject: "subject-b")
        await #expect(throws: IdentityError.organizationMismatch) { try await manager.restore(profileID: firstID) }
        #expect(manager.session == nil)
        #expect(try manager.savedProfiles().map(\.id) == [secondID])
        #expect(try await manager.restore(profileID: secondID))
        #expect(manager.session?.subject == "subject-b")
    }

    @Test func expandedDocumentPermissionsCreateSeparateBoundProfile() async throws {
        let provider = try FakeProvider()
        let manager = IdentityManager(provider: provider, vault: KeychainIdentityVault(storage: MemoryIdentityStorage()))
        let original = try configuration()
        try await manager.login(configuration: original)
        let firstID = try #require(manager.activeProfileID)
        let expanded = try IdentityConfiguration(apiBaseURL: original.apiBaseURL, issuerURL: original.issuerURL,
            clientID: original.clientID, organizationAlias: original.organizationAlias,
            allowedDocumentHosts: ["files.example.invalid"])
        try await manager.login(configuration: expanded)
        let secondID = try #require(manager.activeProfileID)
        #expect(secondID != firstID)
        #expect(try manager.savedProfiles().count == 2)
        #expect(try await manager.restore(profileID: firstID))
        #expect(manager.configuration?.allowedDocumentHosts.isEmpty == true)
        #expect(try await manager.restore(profileID: secondID))
        #expect(manager.configuration?.allowedDocumentHosts == ["files.example.invalid"])
    }
}

@Suite("Not-before de cuentas guardadas usa el reloj actual")
@MainActor
struct RememberedNotBeforeTests {
    @Test func validNotBeforeAllowsLoginAndSavedPickerMetadata() async throws {
        let provider = try FakeProvider()
        provider.authorizationGrant = try grant(notBefore: .now.addingTimeInterval(-60))
        let manager = IdentityManager(provider: provider, vault: KeychainIdentityVault(storage: MemoryIdentityStorage()))
        try await manager.login(configuration: configuration())
        #expect(manager.session?.subject == "subject-a")
        let profiles = try manager.savedProfiles()
        #expect(profiles.count == 1)
        #expect(profiles.first?.subject == "subject-a")
        #expect(try await manager.accessToken() == provider.authorizationGrant.accessToken)
    }

    @Test func expiredTokenWithPastNotBeforeRemainsSelectableAndRefreshes() async throws {
        let provider = try FakeProvider()
        let storage = MemoryIdentityStorage()
        let vault = KeychainIdentityVault(storage: storage)
        let expired = try grant(lifetime: -10, notBefore: .now.addingTimeInterval(-60))
        let saved = StoredIdentity(configuration: try configuration(), grant: expired)
        try vault.saveAll([saved])
        provider.refreshGrant = try grant(lifetime: 3600, notBefore: .now.addingTimeInterval(-60))
        let manager = IdentityManager(provider: provider, vault: vault)
        #expect(try manager.savedProfiles().map(\.id) == [saved.id])
        #expect(manager.session == nil)
        #expect(try await manager.restore(profileID: saved.id))
        #expect(provider.refreshCalls == 1)
        #expect(try await manager.accessToken() == provider.refreshGrant.accessToken)
        #expect(try vault.loadAll().first?.grant.accessToken == provider.refreshGrant.accessToken)
        #expect(throws: IdentityError.expiredToken) {
            try AccessTokenMetadata.session(from: expired, configuration: configuration())
        }
    }

    @Test func allowingExpiryStillRejectsFutureNotBefore() throws {
        let future = try grant(lifetime: -10, notBefore: .now.addingTimeInterval(300))
        #expect(throws: IdentityError.invalidToken) {
            try AccessTokenMetadata.session(from: future, configuration: configuration(), allowExpired: true)
        }
        #expect(throws: IdentityError.invalidToken) {
            try StoredIdentity(configuration: configuration(), grant: future).profile()
        }
        #expect(throws: IdentityError.invalidToken) {
            try AccessTokenMetadata.session(from: grant(notBefore: .now.addingTimeInterval(300)), configuration: configuration())
        }
    }
}

@Suite("Cierre de sesión captura y borra antes de suspender")
@MainActor
struct BeginLogoutTests {
    @Test func synchronousLogoutRemovesOnlyActiveProfileAndRetainsRemoteSnapshotAfterSuspend() async throws {
        let provider = try FakeProvider()
        provider.remotelyClosed = true
        let vault = KeychainIdentityVault(storage: MemoryIdentityStorage())
        let manager = IdentityManager(provider: provider, vault: vault)
        try await manager.login(configuration: configuration())
        let firstID = try #require(manager.activeProfileID)
        let secondConfiguration = try configuration(alias: "otra-empresa")
        provider.authorizationGrant = try grant(alias: "otra-empresa", organizationID: "org-b", subject: "subject-b")
        try await manager.login(configuration: secondConfiguration)
        let removedID = try #require(manager.activeProfileID)
        let outgoingToken = provider.authorizationGrant.accessToken

        let pendingLogout = manager.beginLogout()
        // No await/yield occurred since beginLogout. Both the in-memory identity
        // and its persisted profile must already be gone while the other stays.
        #expect(manager.session == nil)
        #expect(manager.configuration == nil)
        #expect(manager.activeProfileID == nil)
        #expect(try vault.loadAll().map(\.id) == [firstID])
        #expect(try vault.loadAll().contains(where: { $0.id == removedID }) == false)
        #expect(provider.closeCalls == 0)
        manager.suspend()
        let result = await pendingLogout.value
        #expect(result.localCleared)
        #expect(result.remoteClosed)
        #expect(provider.closeCalls == 1)
        #expect(provider.closedGrant?.accessToken == outgoingToken)
        #expect(provider.closedConfiguration == secondConfiguration)
        #expect(try vault.loadAll().map(\.id) == [firstID])
    }

    @Test func synchronousLogoutReportsStorageFailureEvenAfterMemoryIsSuspendedAgain() async throws {
        let provider = try FakeProvider()
        provider.remotelyClosed = true
        let vault = MemoryVault()
        let manager = IdentityManager(provider: provider, vault: vault)
        try await manager.login(configuration: configuration())
        vault.failClear = true
        let pendingLogout = manager.beginLogout()
        #expect(manager.session == nil)
        #expect(vault.value != nil)
        manager.suspend()
        let result = await pendingLogout.value
        #expect(!result.localCleared)
        #expect(result.remoteClosed)
        #expect(provider.closeCalls == 1)
    }
}
