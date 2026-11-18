import Foundation
import Observation

@MainActor
public protocol IdentityProvider: AnyObject {
    func authorize(configuration: IdentityConfiguration) async throws -> IdentityGrant
    func refresh(grant: IdentityGrant, configuration: IdentityConfiguration) async throws -> IdentityGrant
    func closeRemoteSession(grant: IdentityGrant, configuration: IdentityConfiguration) async -> Bool
    func cancel()
}

public struct StoredIdentity: Codable, Sendable {
    public let id: UUID
    public let configuration: IdentityConfiguration
    public let grant: IdentityGrant
    public init(id: UUID = UUID(), configuration: IdentityConfiguration, grant: IdentityGrant) {
        self.id = id
        self.configuration = configuration
        self.grant = grant
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        configuration = try container.decode(IdentityConfiguration.self, forKey: .configuration)
        grant = try container.decode(IdentityGrant.self, forKey: .grant)
    }

    public func profile() throws -> SavedIdentityProfile {
        // Expired tokens may identify a saved profile; they never grant entry.
        let session = try AccessTokenMetadata.session(from: grant, configuration: configuration,
                                                     allowExpired: true)
        return SavedIdentityProfile(id: id, configuration: configuration, displayName: session.displayName,
                                    subject: session.subject, organizationID: session.organizationID, username: grant.username)
    }
}

/// Picker metadata only. Credentials remain private to the vault/manager.
public struct SavedIdentityProfile: Identifiable, Equatable, Sendable {
    public let id: UUID
    public let configuration: IdentityConfiguration
    public let displayName: String
    public let subject: String
    public let organizationID: String
    public let username: String?

    public init(id: UUID, configuration: IdentityConfiguration, displayName: String,
                subject: String, organizationID: String, username: String? = nil) {
        self.id = id; self.configuration = configuration; self.displayName = displayName
        self.subject = subject; self.organizationID = organizationID
        self.username = username
    }
}

@MainActor
public protocol IdentityVault: AnyObject {
    func save(_ identity: StoredIdentity) throws
    func load() throws -> StoredIdentity?
    func clear() throws
    func loadAll() throws -> [StoredIdentity]
    func saveAll(_ identities: [StoredIdentity]) throws
}

public extension IdentityVault {
    // Compatibility for single-session test/adapters. Production implements an
    // atomic collection; an older adapter must never silently discard accounts.
    func loadAll() throws -> [StoredIdentity] { try load().map { [$0] } ?? [] }
    func saveAll(_ identities: [StoredIdentity]) throws {
        guard identities.count <= 1 else { throw IdentityError.storageFailure }
        if let identity = identities.first { try save(identity) } else { try clear() }
    }
}

/// Owns one authenticated organization at a time. UI state and all AppAuth
/// adapter calls stay on MainActor; epochs reject late browser/refresh results.
@MainActor @Observable
public final class IdentityManager {
    public private(set) var session: IdentitySession?
    public private(set) var configuration: IdentityConfiguration?
    public private(set) var isAuthenticating = false
    public private(set) var activeProfileID: UUID?
    @ObservationIgnored private let provider: any IdentityProvider
    @ObservationIgnored private let vault: any IdentityVault
    @ObservationIgnored private var grant: IdentityGrant?
    @ObservationIgnored private var generation: UInt64 = 0
    @ObservationIgnored private var refreshTask: Task<IdentityGrant, Error>?
    @ObservationIgnored private var refreshID: UUID?

    public init(provider: any IdentityProvider, vault: any IdentityVault = KeychainIdentityVault()) {
        self.provider = provider
        self.vault = vault
    }

    /// Reads only the public profile for an explicit "Continue session" action.
    /// Does not authenticate, refresh, expose tokens or change in-memory identity.
    /// Keychain read/corruption failures remain visible to the caller.
    public func savedConfiguration() throws -> IdentityConfiguration? {
        let profiles = try savedProfiles()
        return profiles.count == 1 ? profiles.first?.configuration : nil
    }

    public func savedProfiles() throws -> [SavedIdentityProfile] {
        try vault.loadAll().map { try $0.profile() }
    }

    public func forget(profileID: UUID) throws {
        if activeProfileID == profileID { invalidateMemory() }
        var identities = try vault.loadAll()
        identities.removeAll { $0.id == profileID }
        try vault.saveAll(identities)
    }

    /// Locks the active workspace without revoking/deleting remembered users.
    public func suspend() { invalidateMemory() }

    private func commit(_ identity: StoredIdentity) throws {
        var identities = try vault.loadAll()
        identities.removeAll { $0.id == identity.id }
        identities.append(identity)
        try vault.saveAll(identities)
    }

    public func login(configuration: IdentityConfiguration) async throws {
        // A failed/cancelled addition must preserve every previously saved user.
        suspend()
        try Task.checkCancellation()
        let epoch = generation
        isAuthenticating = true
        defer { if generation == epoch { isAuthenticating = false } }
        do {
            let next = try await provider.authorize(configuration: configuration)
            try Task.checkCancellation()
            guard generation == epoch else { throw IdentityError.sessionChanged }
            let metadata = try AccessTokenMetadata.session(from: next, configuration: configuration)
            let identities = try vault.loadAll()
            let existing = try identities.first {
                guard $0.configuration == configuration else { return false }
                let profile = try $0.profile()
                return profile.subject == metadata.subject && profile.organizationID == metadata.organizationID
            }
            let identity = StoredIdentity(id: existing?.id ?? UUID(), configuration: configuration, grant: next)
            try commit(identity)
            activeProfileID = identity.id
            self.configuration = configuration
            self.grant = next
            self.session = metadata
        } catch {
            guard generation == epoch else { throw IdentityError.sessionChanged }
            suspend()
            if let identityError = error as? IdentityError { throw identityError }
            if error is CancellationError { throw IdentityError.cancelled }
            throw IdentityError.authenticationFailed
        }
    }

    /// Explicit opt-in restore. A profile must match every stored configuration
    /// field; no token is moved to a different API, client, issuer or organization.
    public func restore(configuration: IdentityConfiguration) async throws -> Bool {
        suspend()
        let matches = try vault.loadAll().filter { $0.configuration == configuration }
        guard matches.count == 1, let stored = matches.first else { return false }
        return try await restore(profileID: stored.id)
    }

    /// Callers must first obtain explicit device-owner authentication. No
    /// profile is chosen by mutable display name, tenant alias or array index.
    public func restore(profileID: UUID) async throws -> Bool {
        suspend()
        let epoch = generation
        guard let stored = try vault.loadAll().first(where: { $0.id == profileID }) else { return false }
        try Task.checkCancellation()
        let configuration = stored.configuration
        activeProfileID = stored.id
        self.configuration = configuration
        self.grant = stored.grant
        do {
            if stored.grant.expiresAt.timeIntervalSinceNow > 30 {
                self.session = try AccessTokenMetadata.session(from: stored.grant, configuration: configuration)
            } else {
                // Read only the previous binding, allowing expiry while checking
                // nbf against the actual clock. Never return an expired token.
                let previous = try AccessTokenMetadata.session(
                    from: stored.grant, configuration: configuration,
                    allowExpired: true
                )
                let refreshed = try await provider.refresh(grant: stored.grant, configuration: configuration)
                try Task.checkCancellation()
                guard generation == epoch else { throw IdentityError.sessionChanged }
                let metadata = try AccessTokenMetadata.session(from: refreshed, configuration: configuration)
                guard metadata.subject == previous.subject, metadata.organizationID == previous.organizationID
                else { throw IdentityError.organizationMismatch }
                try commit(StoredIdentity(id: stored.id, configuration: configuration, grant: refreshed))
                self.grant = refreshed
                self.session = metadata
            }
            return true
        } catch {
            if generation == epoch {
                if let identityError = error as? IdentityError,
                   [.organizationMismatch, .invalidToken, .audienceMismatch, .issuerMismatch, .noSession, .expiredToken].contains(identityError) {
                    try? clearLocal()
                } else {
                    // Cancellation or a transient network/storage failure locks
                    // memory, without erasing a previously remembered user.
                    suspend()
                }
            }
            throw error
        }
    }

    public func accessToken(forceRefresh: Bool = false) async throws -> String {
        try Task.checkCancellation()
        guard let original = grant, let configuration, let previous = session else { throw IdentityError.noSession }
        if !forceRefresh && previous.expiresAt.timeIntervalSinceNow > 30 { return original.accessToken }
        let epoch = generation
        let pending: Task<IdentityGrant, Error>
        if let refreshTask {
            pending = refreshTask
        } else {
            let id = UUID()
            refreshID = id
            pending = Task { @MainActor in
                try await self.refreshAndCommit(
                    original: original, configuration: configuration, previous: previous,
                    generation: epoch, id: id
                )
            }
            refreshTask = pending
        }
        do {
            _ = try await pending.value
            try Task.checkCancellation()
            guard generation == epoch, let current = grant else { throw IdentityError.sessionChanged }
            // A later refresh may already have finished before this waiter
            // resumes. Return the current token, never restore the old result.
            return current.accessToken
        } catch is CancellationError {
            throw IdentityError.cancelled
        }
    }

    /// Exactly one task validates, persists and commits each refresh. Waiters
    /// never modify grant/session or clear the in-flight task reference.
    private func refreshAndCommit(
        original: IdentityGrant, configuration: IdentityConfiguration,
        previous: IdentitySession, generation epoch: UInt64, id: UUID
    ) async throws -> IdentityGrant {
        defer {
            // A cancelled old task must never clear a newer refresh reference.
            if refreshID == id {
                refreshTask = nil
                refreshID = nil
            }
        }
        do {
            let next = try await provider.refresh(grant: original, configuration: configuration)
            try Task.checkCancellation()
            guard generation == epoch, refreshID == id else { throw IdentityError.sessionChanged }
            let metadata = try AccessTokenMetadata.session(from: next, configuration: configuration)
            guard metadata.subject == previous.subject, metadata.organizationID == previous.organizationID
            else { throw IdentityError.organizationMismatch }
            guard let profileID = activeProfileID else { throw IdentityError.sessionChanged }
            try commit(StoredIdentity(id: profileID, configuration: configuration, grant: next))
            grant = next
            session = metadata
            return next
        } catch {
            guard generation == epoch, refreshID == id else { throw IdentityError.sessionChanged }
            if let identityError = error as? IdentityError {
                switch identityError {
                case .organizationMismatch, .invalidToken, .audienceMismatch, .issuerMismatch, .noSession, .expiredToken:
                    try? clearLocal()
                default: break
                }
                throw identityError
            }
            if error is CancellationError { throw IdentityError.cancelled }
            throw IdentityError.authenticationFailed
        }
    }

    /// Capture the outgoing identity and remove it before any suspension point.
    /// File cleanup/background locking cannot erase the information required to
    /// remove this profile or change which session remote logout targets.
    public func beginLogout() -> Task<LogoutResult, Never> {
        let previous = grant
        let previousConfiguration = configuration
        var localCleared = true
        do { try clearLocal() } catch { localCleared = false }
        return Task { @MainActor [provider] in
            guard let previous, let previousConfiguration else {
                return LogoutResult(localCleared: localCleared, remoteClosed: true)
            }
            let closed = await provider.closeRemoteSession(grant: previous, configuration: previousConfiguration)
            return LogoutResult(localCleared: localCleared, remoteClosed: closed)
        }
    }

    public func logout() async -> LogoutResult { await beginLogout().value }

    /// Cancels active work, preserving remembered users. Logout/forget are the
    /// explicit actions for deletion; late browser/refresh replies stay invalid.
    public func cancel() {
        suspend()
    }

    private func invalidateMemory() {
        generation &+= 1
        refreshTask?.cancel()
        refreshTask = nil
        refreshID = nil
        isAuthenticating = false
        provider.cancel()
        grant = nil
        configuration = nil
        session = nil
        activeProfileID = nil
    }

    private func clearMemory() throws {
        invalidateMemory()
    }

    private func clearLocal() throws {
        let removedID = activeProfileID
        try clearMemory()
        guard let removedID else { return }
        do { try forget(profileID: removedID) } catch { throw IdentityError.storageFailure }
    }
}
