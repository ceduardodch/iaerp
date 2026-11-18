import Foundation
import CoreFoundation

/// A fail-closed *local safety filter*, not JWT signature verification or authorization.
/// AppAuth validates the OIDC code exchange over TLS; the IAERP API remains the
/// authority for RS256 signature, audience, organization, active membership and scopes.
/// Never derive a trusted backend tenant from the organization fields below.
public enum AccessTokenMetadata {
    public static func session(
        from grant: IdentityGrant,
        configuration: IdentityConfiguration,
        now: Date = .now
    ) throws -> IdentitySession {
        try session(from: grant, configuration: configuration, now: now, allowExpired: false)
    }

    /// Remembered metadata can outlive its access token. Ignore only expiry;
    /// evaluate not-before and every identity binding against the actual clock.
    /// This internal path must never provide an access token to API callers.
    static func session(
        from grant: IdentityGrant,
        configuration: IdentityConfiguration,
        now: Date = .now,
        allowExpired: Bool
    ) throws -> IdentitySession {
        guard allowExpired || grant.expiresAt > now else { throw IdentityError.expiredToken }
        let token = grant.accessToken
        guard token.utf8.count <= 65_536 else { throw IdentityError.invalidToken }
        let parts = token.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 3, !parts[2].isEmpty,
              let header = decode(parts[0]), header["alg"] as? String == "RS256",
              let claims = decode(parts[1]), let issuer = claims["iss"] as? String
        else { throw IdentityError.invalidToken }
        guard issuer == configuration.issuerURL.absoluteString else { throw IdentityError.issuerMismatch }
        let audiences = (claims["aud"] as? [String]) ?? (claims["aud"] as? String).map { [$0] } ?? []
        guard audiences.contains(configuration.apiAudience), claims["azp"] as? String == configuration.clientID
        else { throw IdentityError.audienceMismatch }
        guard let expiry = claims["exp"] as? NSNumber,
              CFGetTypeID(expiry) != CFBooleanGetTypeID(),
              expiry.doubleValue.isFinite,
              allowExpired || expiry.doubleValue > now.timeIntervalSince1970
        else { throw IdentityError.expiredToken }
        if let notBefore = claims["nbf"] as? NSNumber, notBefore.doubleValue > now.timeIntervalSince1970 + 30 {
            throw IdentityError.invalidToken
        }
        guard let subject = claims["sub"] as? String, !subject.isEmpty,
              let organizations = claims["organization"] as? [String: [String: Any]],
              organizations.count == 1,
              let organization = organizations[configuration.organizationAlias],
              let organizationID = organization["id"] as? String, !organizationID.isEmpty
        else { throw IdentityError.organizationMismatch }
        return IdentitySession(
            subject: subject, displayName: grant.displayName.isEmpty ? "Usuario" : grant.displayName,
            organizationAlias: configuration.organizationAlias, organizationID: organizationID,
            expiresAt: min(grant.expiresAt, Date(timeIntervalSince1970: expiry.doubleValue))
        )
    }

    private static func decode(_ input: Substring) -> [String: Any]? {
        var base64 = input.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        base64 += String(repeating: "=", count: (4 - base64.count % 4) % 4)
        guard let data = Data(base64Encoded: base64),
              let decoded = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return decoded
    }
}
