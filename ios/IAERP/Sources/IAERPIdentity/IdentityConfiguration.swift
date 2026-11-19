import Foundation

public enum IdentityError: Error, LocalizedError, Equatable, Sendable {
    case invalidConfiguration
    case invalidOrganization
    case invalidToken
    case expiredToken
    case audienceMismatch
    case issuerMismatch
    case organizationMismatch
    case noSession
    case cancelled
    case sessionChanged
    case authenticationFailed
    case storageFailure
    case browserUnavailable

    public var errorDescription: String? {
        switch self {
        case .invalidConfiguration: "Revisa las direcciones HTTPS y el cliente de acceso de la empresa."
        case .invalidOrganization: "El alias de empresa no es válido."
        case .invalidToken, .audienceMismatch, .issuerMismatch:
            "El servicio de acceso devolvió una sesión no válida para esta app."
        case .expiredToken: "La sesión venció. Vuelve a entrar."
        case .organizationMismatch: "La sesión no corresponde a la empresa elegida."
        case .noSession: "Inicia sesión para continuar."
        case .cancelled: "Se canceló el inicio de sesión."
        case .sessionChanged: "La sesión cambió. Vuelve a intentar la operación."
        case .authenticationFailed: "No se pudo completar el acceso. Intenta de nuevo."
        case .storageFailure: "No se pudo proteger la sesión en este dispositivo."
        case .browserUnavailable: "No se pudo abrir el acceso seguro. Intenta de nuevo."
        }
    }
}

public struct IdentityConfiguration: Codable, Equatable, Sendable {
    public let apiBaseURL: URL
    public let issuerURL: URL
    public let clientID: String
    public let redirectURL: URL
    public let organizationAlias: String
    public let apiAudience: String
    public let allowedDocumentHosts: Set<String>

    public init(
        apiBaseURL: URL,
        issuerURL: URL,
        clientID: String,
        redirectURL: URL = URL(string: "ec.com.b2b.iaerp:/oauth2redirect")!,
        organizationAlias: String,
        apiAudience: String = "iaerp-api",
        allowedDocumentHosts: Set<String> = []
    ) throws {
        let alias = organizationAlias.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard alias.range(of: "^[a-z0-9][a-z0-9-]{1,62}$", options: .regularExpression) != nil else {
            throw IdentityError.invalidOrganization
        }
        guard Self.isHTTPSResource(apiBaseURL), Self.isHTTPSResource(issuerURL),
              Self.isValidClientID(clientID),
              !apiAudience.isEmpty, apiAudience.count <= 200,
              redirectURL.absoluteString == "ec.com.b2b.iaerp:/oauth2redirect"
        else { throw IdentityError.invalidConfiguration }
        let documentHosts = Set(allowedDocumentHosts.map { $0.lowercased() })
        guard documentHosts.allSatisfy(Self.isDocumentHost) else { throw IdentityError.invalidConfiguration }
        self.apiBaseURL = apiBaseURL
        self.issuerURL = issuerURL
        self.clientID = clientID
        self.redirectURL = redirectURL
        self.organizationAlias = alias
        self.apiAudience = apiAudience
        self.allowedDocumentHosts = documentHosts
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            apiBaseURL: container.decode(URL.self, forKey: .apiBaseURL),
            issuerURL: container.decode(URL.self, forKey: .issuerURL),
            clientID: container.decode(String.self, forKey: .clientID),
            redirectURL: container.decode(URL.self, forKey: .redirectURL),
            organizationAlias: container.decode(String.self, forKey: .organizationAlias),
            apiAudience: container.decode(String.self, forKey: .apiAudience),
            allowedDocumentHosts: container.decode(Set<String>.self, forKey: .allowedDocumentHosts)
        )
    }

    // Keycloak accepts one organization selector. The API read permission
    // organization:read is already a default scope of the native client.
    public var scopes: [String] {
        ["openid", "profile", "organization:\(organizationAlias)",
         "context:read", "memberships:read", "parties:read", "products:read",
         "invoices:read", "invoices:write"]
    }

    public static func isHTTPSResource(_ url: URL) -> Bool {
        url.scheme?.lowercased() == "https" && !(url.host ?? "").isEmpty
            && url.user == nil && url.password == nil && url.query == nil && url.fragment == nil
    }

    public static func isValidClientID(_ value: String) -> Bool {
        !value.isEmpty && value.count <= 200 && value.rangeOfCharacter(from: .whitespacesAndNewlines) == nil
    }

    public static func isDocumentHost(_ host: String) -> Bool {
        guard !host.isEmpty, host.utf8.count <= 253 else { return false }
        return host.split(separator: ".", omittingEmptySubsequences: false).allSatisfy { label in
            !label.isEmpty && label.utf8.count <= 63
                && label.range(of: "^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", options: .regularExpression) != nil
        }
    }

    public func permitsIdentityEndpoint(_ url: URL) -> Bool {
        Self.isHTTPSResource(url)
            && url.host?.lowercased() == issuerURL.host?.lowercased()
            && (url.port ?? 443) == (issuerURL.port ?? 443)
    }
}

public struct IdentitySession: Equatable, Sendable {
    public let subject: String
    public let displayName: String
    public let organizationAlias: String
    public let organizationID: String
    public let expiresAt: Date
}

/// Tokens are obtained only by the OIDC provider adapter, never entered by the user.
/// `serializedState` is an AppAuth secure archive, stored only in Keychain.
public struct IdentityGrant: Codable, Sendable {
    public let accessToken: String
    public let expiresAt: Date
    public let displayName: String
    public let serializedState: Data
    public let username: String?

    public init(accessToken: String, expiresAt: Date, displayName: String, serializedState: Data, username: String? = nil) {
        self.accessToken = accessToken
        self.expiresAt = expiresAt
        self.displayName = displayName
        self.serializedState = serializedState
        self.username = username
    }
}

public struct LogoutResult: Equatable, Sendable {
    public let localCleared: Bool
    public let remoteClosed: Bool
    public var message: String {
        if !localCleared { return "La sesión se cerró en memoria, pero no se pudo borrar del Llavero. Intenta salir de nuevo." }
        return remoteClosed ? "Sesión cerrada." : "Sesión local cerrada. No se pudo confirmar el cierre remoto; el navegador puede conservar su sesión."
    }
}
