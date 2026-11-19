import Foundation
import IAERPIdentity
import IAERPClient

/// Public connection details only. Organization membership and permissions are
/// resolved after interactive OIDC authentication; no credentials are bundled.
enum IAERPConnection {
    static let apiURL = URL(string: "https://iaerp.b2b.com.ec/api/v1")!
    static let issuerURL = URL(string: "https://iaerp-auth.b2b.com.ec/realms/iaerp")!
    static let clientID = "iaerp-ios"
    static let documentHost = "iaerp-files.b2b.com.ec"

    static func formConfiguration(api: String, issuer: String, client: String, alias: String,
                                  documentHost: String) throws -> IdentityConfiguration {
        let trimmedAlias = alias.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedAlias.isEmpty else {
            throw ERPClientError.invalidInput("Escribe el alias de tu empresa para iniciar sesión.")
        }
        guard let apiURL = URL(string: api.trimmingCharacters(in: .whitespacesAndNewlines)),
              IdentityConfiguration.isHTTPSResource(apiURL) else {
            throw ERPClientError.invalidInput("En Dirección de la API, escribe la dirección HTTPS de IAERP.")
        }
        guard let issuerURL = URL(string: issuer.trimmingCharacters(in: .whitespacesAndNewlines)),
              IdentityConfiguration.isHTTPSResource(issuerURL) else {
            throw ERPClientError.invalidInput("En Dirección de acceso, escribe la dirección HTTPS del servicio de acceso.")
        }
        let clientID = client.trimmingCharacters(in: .whitespacesAndNewlines)
        guard IdentityConfiguration.isValidClientID(clientID) else {
            throw ERPClientError.invalidInput("Revisa el identificador de la app. Debe tener entre 1 y 200 caracteres, sin espacios.")
        }
        let host = documentHost.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard host.isEmpty || IdentityConfiguration.isDocumentHost(host) else {
            throw ERPClientError.invalidInput("En Servidor de documentos, usa sólo el nombre del servidor o deja el campo vacío.")
        }
        do {
            return try IdentityConfiguration(apiBaseURL: apiURL, issuerURL: issuerURL, clientID: clientID,
                organizationAlias: trimmedAlias, allowedDocumentHosts: host.isEmpty ? [] : [host])
        } catch IdentityError.invalidOrganization {
            throw ERPClientError.invalidInput("En Alias de la empresa, usa de 2 a 63 letras, números o guiones. Empieza con una letra o número.")
        }
    }

    static func configuration(organizationAlias: String) throws -> IdentityConfiguration {
        try IdentityConfiguration(apiBaseURL: apiURL, issuerURL: issuerURL, clientID: clientID,
            organizationAlias: organizationAlias, allowedDocumentHosts: [documentHost])
    }
}
