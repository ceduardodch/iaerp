import IAERPIdentity
import Observation
import UIKit

/// UI adapter keeps UIKit presentation outside the testable identity manager.
@MainActor @Observable
final class AuthenticationController {
    private let manager: IdentityManager
    private let unlocking: any SessionUnlocking
    private var generation = UUID()

    var session: IdentitySession? { manager.session }
    var isAuthenticating: Bool { manager.isAuthenticating }
    var configuration: IdentityConfiguration? { manager.configuration }
    var activeProfileID: UUID? { manager.activeProfileID }

    init(manager: IdentityManager, unlocking: (any SessionUnlocking)? = nil) {
        self.manager = manager
        self.unlocking = unlocking ?? DeviceOwnerUnlock()
    }

    init() {
        let provider = AppAuthIdentityProvider {
            guard let scene = UIApplication.shared.connectedScenes
                .compactMap({ $0 as? UIWindowScene })
                .first(where: { $0.activationState == .foregroundActive }),
                  let window = scene.windows.first(where: \.isKeyWindow),
                  var controller = window.rootViewController
            else { throw IdentityError.browserUnavailable }
            while let presented = controller.presentedViewController { controller = presented }
            return controller
        }
        manager = IdentityManager(provider: provider)
        unlocking = DeviceOwnerUnlock()
    }

    func savedConfiguration() throws -> IdentityConfiguration? {
        try manager.savedConfiguration()
    }

    func savedProfiles() throws -> [SavedIdentityProfile] { try manager.savedProfiles() }

    func login(configuration: IdentityConfiguration) async throws {
        suspend()
        try await manager.login(configuration: configuration)
    }

    func restore(configuration: IdentityConfiguration) async throws -> Bool {
        suspend()
        let epoch = generation
        try await unlocking.unlock()
        guard epoch == generation else { throw IdentityError.sessionChanged }
        return try await manager.restore(configuration: configuration)
    }

    func restore(profileID: UUID) async throws -> Bool {
        suspend()
        let epoch = generation
        try await unlocking.unlock()
        guard epoch == generation else { throw IdentityError.sessionChanged }
        return try await manager.restore(profileID: profileID)
    }

    func forget(profileID: UUID) throws { try manager.forget(profileID: profileID) }

    func suspend() {
        generation = UUID()
        unlocking.cancel()
        manager.suspend()
    }

    func accessToken(forceRefresh: Bool = false) async throws -> String {
        try await manager.accessToken(forceRefresh: forceRefresh)
    }

    func beginLogout() -> Task<LogoutResult, Never> {
        generation = UUID()
        unlocking.cancel()
        return manager.beginLogout()
    }
    func logout() async -> LogoutResult { await beginLogout().value }
    func cancel() { suspend() }
}
