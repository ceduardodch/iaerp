import Foundation
import IAERPIdentity

/// Public connection details only. Organization membership and permissions are
/// resolved after interactive OIDC authentication; no credentials are bundled.
enum IAERPConnection {
    static let apiURL = URL(string: "https://iaerp.b2b.com.ec/api/v1")!
    static let issuerURL = URL(string: "https://iaerp-auth.b2b.com.ec/realms/iaerp")!
    static let clientID = "iaerp-ios"
    static let documentHost = "iaerp-files.b2b.com.ec"

    static func configuration(organizationAlias: String) throws -> IdentityConfiguration {
        try IdentityConfiguration(apiBaseURL: apiURL, issuerURL: issuerURL, clientID: clientID,
            organizationAlias: organizationAlias, allowedDocumentHosts: [documentHost])
    }
}
