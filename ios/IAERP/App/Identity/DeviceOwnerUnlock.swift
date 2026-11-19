import LocalAuthentication

@MainActor
protocol SessionUnlocking: AnyObject {
    func unlock() async throws
    func cancel()
}

enum SessionUnlockError: Error, LocalizedError {
    case unavailable, cancelled

    var errorDescription: String? {
        switch self {
        case .unavailable: "Activa Face ID o el código del iPhone para abrir una cuenta guardada."
        case .cancelled: "No se desbloqueó la cuenta. Puedes intentarlo de nuevo."
        }
    }
}

/// A fresh system challenge for every account selection. No shared success flag
/// or reusable LAContext can unlock a different profile after a suspension.
@MainActor
final class DeviceOwnerUnlock: SessionUnlocking {
    private var context: LAContext?
    private let reason: String

    init(reason: String = "Abre tu cuenta guardada de IAERP.") { self.reason = reason }

    func unlock() async throws {
        cancel()
        let attempt = LAContext()
        context = attempt
        defer {
            if context === attempt { context = nil }
            attempt.invalidate()
        }
        guard attempt.canEvaluatePolicy(.deviceOwnerAuthentication, error: nil) else {
            throw SessionUnlockError.unavailable
        }
        do {
            let allowed = try await attempt.evaluatePolicy(
                .deviceOwnerAuthentication,
                localizedReason: reason
            )
            try Task.checkCancellation()
            guard allowed, context === attempt else { throw SessionUnlockError.cancelled }
        } catch { throw SessionUnlockError.cancelled }
    }

    func cancel() {
        context?.invalidate()
        context = nil
    }
}
