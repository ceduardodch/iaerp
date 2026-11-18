#if DEBUG && targetEnvironment(simulator)
import Foundation
import IAERPIdentity

/// Simulator-only, synthetic UI data. This does not replace the device-owner
/// unlocker, mint real credentials or run in an iPhone/distribution build.
@MainActor enum SavedAccountsFixture {
    static func makeStore() -> WorkspaceStore {
        do {
            let records = try [
                record(index: 1, username: "alex.ventas", alias: "demo-a"),
                record(index: 2, username: "alex.consulta", alias: "demo-a"),
                record(index: 3, username: "alex.ventas", alias: "demo-b", alternateIssuer: true),
            ]
            let manager = IdentityManager(provider: UnavailableProvider(), vault: FixtureVault(records: records))
            return WorkspaceStore(authentication: AuthenticationController(manager: manager))
        } catch { preconditionFailure("Invalid synthetic account fixture") }
    }

    private static func record(index: Int, username: String, alias: String, alternateIssuer: Bool = false) throws -> StoredIdentity {
        let config = try IdentityConfiguration(apiBaseURL: URL(string: "https://api.example.invalid/api/v1")!,
            issuerURL: URL(string: "https://\(alternateIssuer ? "other" : "identity").example.invalid/realms/test")!,
            clientID: "iaerp-ios-ui-fixture", organizationAlias: alias)
        let expiry = Date.now.addingTimeInterval(3600)
        func segment(_ object: [String: Any]) throws -> String {
            try JSONSerialization.data(withJSONObject: object, options: .sortedKeys).base64EncodedString()
                .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
                .replacingOccurrences(of: "=", with: "")
        }
        let claims: [String: Any] = [
            "iss": config.issuerURL.absoluteString, "aud": config.apiAudience, "azp": config.clientID,
            "sub": "synthetic-user-\(index)", "exp": expiry.timeIntervalSince1970,
            "organization": [alias: ["id": "synthetic-tenant-\(alias)"]],
        ]
        let grant = try IdentityGrant(accessToken: segment(["alg": "RS256"]) + "." + segment(claims) + ".synthetic",
            expiresAt: expiry, displayName: "Alex Cruz", serializedState: Data(), username: username)
        return StoredIdentity(id: UUID(uuidString: "00000000-0000-4000-8000-00000000000\(index)")!,
            configuration: config, grant: grant)
    }

    private final class FixtureVault: IdentityVault {
        var records: [StoredIdentity]
        init(records: [StoredIdentity]) { self.records = records }
        func load() -> StoredIdentity? { records.first }
        func save(_ identity: StoredIdentity) { records = [identity] }
        func clear() { records = [] }
        func loadAll() -> [StoredIdentity] { records }
        func saveAll(_ identities: [StoredIdentity]) { records = identities }
    }

    private final class UnavailableProvider: IdentityProvider {
        func authorize(configuration: IdentityConfiguration) async throws -> IdentityGrant { throw IdentityError.authenticationFailed }
        func refresh(grant: IdentityGrant, configuration: IdentityConfiguration) async throws -> IdentityGrant { throw IdentityError.noSession }
        func closeRemoteSession(grant: IdentityGrant, configuration: IdentityConfiguration) async -> Bool { false }
        func cancel() { }
    }
}
#endif
