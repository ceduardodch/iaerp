import Foundation
import Security

/// Keychain encrypts all remembered sessions on this device only. The complete
/// collection is replaced atomically; an empty v2 record prevents a stale v1
/// item from ever becoming active again after an interrupted migration.
@MainActor
public final class KeychainIdentityVault: IdentityVault {
    static let currentAccount = "oidc.saved-sessions.v2"
    static let legacyAccount = "oidc.current-session.v1"
    private let storage: any IdentityVaultStorage

    public init(service: String = "ec.com.b2b.iaerp.identity") {
        storage = SecurityIdentityVaultStorage(service: service)
    }

    init(storage: any IdentityVaultStorage) { self.storage = storage }

    public func save(_ identity: StoredIdentity) throws { try saveAll([identity]) }
    public func load() throws -> StoredIdentity? {
        let identities = try loadAll()
        guard identities.count <= 1 else { throw IdentityError.storageFailure }
        return identities.first
    }

    public func saveAll(_ identities: [StoredIdentity]) throws {
        try Self.validate(identities)
        let data: Data
        do { data = try JSONEncoder().encode(identities) }
        catch { throw IdentityError.storageFailure }
        try storage.write(data, account: Self.currentAccount)
        // The v2 record is durable before removal of the v1 item. Failure here
        // is reported; v2 remains authoritative on subsequent launches.
        try storage.remove(account: Self.legacyAccount)
    }

    public func loadAll() throws -> [StoredIdentity] {
        if let data = try storage.read(account: Self.currentAccount) {
            do {
                let identities = try JSONDecoder().decode([StoredIdentity].self, from: data)
                try Self.validate(identities)
                return identities
            } catch { throw IdentityError.storageFailure }
        }
        guard let data = try storage.read(account: Self.legacyAccount) else { return [] }
        let legacy: StoredIdentity
        do {
            legacy = try JSONDecoder().decode(StoredIdentity.self, from: data)
            try Self.validate([legacy])
        } catch { throw IdentityError.storageFailure }
        try saveAll([legacy])
        return [legacy]
    }

    public func clear() throws {
        // Keep an empty authoritative v2 collection even if v1 removal fails.
        try saveAll([])
    }

    private static func validate(_ identities: [StoredIdentity]) throws {
        guard Set(identities.map(\.id)).count == identities.count else { throw IdentityError.storageFailure }
        for identity in identities { _ = try identity.profile() }
    }
}

/// Small storage boundary makes migration failure ordering reproducible without
/// reading or mutating the developer's real keychain in unit tests.
@MainActor
protocol IdentityVaultStorage: AnyObject {
    func read(account: String) throws -> Data?
    func write(_ data: Data, account: String) throws
    func remove(account: String) throws
}

@MainActor
private final class SecurityIdentityVaultStorage: IdentityVaultStorage {
    let service: String
    init(service: String) { self.service = service }

    func write(_ data: Data, account: String) throws {
        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        let query = query(account: account)
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var insertion = query
            attributes.forEach { insertion[$0.key] = $0.value }
            guard SecItemAdd(insertion as CFDictionary, nil) == errSecSuccess else { throw IdentityError.storageFailure }
        } else if status != errSecSuccess { throw IdentityError.storageFailure }
    }

    func read(account: String) throws -> Data? {
        var request = query(account: account)
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(request as CFDictionary, &item)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = item as? Data else { throw IdentityError.storageFailure }
        return data
    }

    func remove(account: String) throws {
        let status = SecItemDelete(query(account: account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw IdentityError.storageFailure }
    }

    private func query(account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account,
         kSecAttrSynchronizable as String: false]
    }
}
