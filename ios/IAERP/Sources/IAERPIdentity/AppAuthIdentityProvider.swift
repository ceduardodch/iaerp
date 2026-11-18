#if os(iOS)
import Foundation
import UIKit
import AppAuth

/// AppAuth 3.0.0 owns PKCE/state/nonce and OIDC response validation. Its token
/// callbacks are documented on the main thread; MainActor.assumeIsolated below
/// makes that existing Objective-C contract explicit without making tokens or
/// OIDAuthState @unchecked Sendable. Replace with annotated SDK APIs when available.
@MainActor
public final class AppAuthIdentityProvider: IdentityProvider {
    private let presenter: @MainActor () throws -> UIViewController
    private let network: URLSession
    private let redirectPolicy: IdentityRedirectPolicy
    private var externalFlow: (any OIDExternalUserAgentSession)?
    private var flowGeneration: UInt64 = 0

    public init(presenter: @escaping @MainActor () throws -> UIViewController) {
        self.presenter = presenter
        let policy = IdentityRedirectPolicy()
        self.redirectPolicy = policy
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = 20
        configuration.timeoutIntervalForResource = 30
        self.network = URLSession(configuration: configuration, delegate: policy, delegateQueue: nil)
        // This app has one identity provider. Install before any AppAuth request;
        // subsequent providers use the same no-cache, no-cookie redirect policy.
        OIDURLSessionProvider.setSession(network)
    }

    public func authorize(configuration: IdentityConfiguration) async throws -> IdentityGrant {
        cancel()
        let epoch = flowGeneration
        let service = try await discover(configuration)
        guard flowGeneration == epoch else { throw IdentityError.cancelled }
        let request = OIDAuthorizationRequest(
            configuration: service, clientId: configuration.clientID,
            clientSecret: nil, scopes: configuration.scopes,
            redirectURL: configuration.redirectURL, responseType: OIDResponseTypeCode,
            // Adding a remembered user requires an interactive identity choice,
            // even when an identity-provider browser session still exists.
            additionalParameters: ["prompt": "login", "ui_locales": "es"]
        )
        guard request.codeChallengeMethod == OIDOAuthorizationRequestCodeChallengeMethodS256,
              !(request.state ?? "").isEmpty, !(request.nonce ?? "").isEmpty,
              let userAgent = OIDExternalUserAgentIOS(presenting: try presenter(), prefersEphemeralSession: true)
        else { throw IdentityError.browserUnavailable }
        let grant: IdentityGrant = try await withCheckedThrowingContinuation { continuation in
            externalFlow = OIDAuthState.authState(byPresenting: request, externalUserAgent: userAgent) { [weak self] state, error in
                // AppAuth's completion is dispatched to the main queue.
                MainActor.assumeIsolated {
                    guard let self, self.flowGeneration == epoch else {
                        continuation.resume(throwing: IdentityError.cancelled)
                        return
                    }
                    self.externalFlow = nil
                    if let state {
                        do {
                            guard state.lastTokenResponse?.idToken != nil else { throw IdentityError.invalidToken }
                            continuation.resume(returning: try self.makeGrant(
                                state, configuration: configuration, fallbackName: "Usuario", fallbackUsername: nil
                            ))
                        } catch { continuation.resume(throwing: error) }
                    } else {
                        continuation.resume(throwing: Self.safeError(error))
                    }
                }
            }
        }
        guard flowGeneration == epoch else { throw IdentityError.cancelled }
        return grant
    }

    public func refresh(grant: IdentityGrant, configuration: IdentityConfiguration) async throws -> IdentityGrant {
        let epoch = flowGeneration
        let state = try unarchive(grant, configuration: configuration)
        guard !(state.refreshToken ?? "").isEmpty else { throw IdentityError.noSession }
        state.setNeedsTokenRefresh()
        let updated: IdentityGrant = try await withCheckedThrowingContinuation { continuation in
            state.performAction { [weak self] accessToken, _, error in
                // performActionWithFreshTokens is documented to call on main.
                MainActor.assumeIsolated {
                    guard let self, self.flowGeneration == epoch else {
                        continuation.resume(throwing: IdentityError.sessionChanged)
                        return
                    }
                    if accessToken != nil, error == nil {
                        do {
                            continuation.resume(returning: try self.makeGrant(
                                state, configuration: configuration, fallbackName: grant.displayName,
                                fallbackUsername: grant.username
                            ))
                        } catch { continuation.resume(throwing: error) }
                    } else {
                        continuation.resume(throwing: Self.safeError(error))
                    }
                }
            }
        }
        return updated
    }

    public func closeRemoteSession(grant: IdentityGrant, configuration: IdentityConfiguration) async -> Bool {
        let epoch = flowGeneration
        guard let state = try? unarchive(grant, configuration: configuration) else { return false }
        let service = state.lastAuthorizationResponse.request.configuration
        var revoked = false
        if let refreshToken = state.refreshToken,
           let address = service.discoveryDocument?.discoveryDictionary["revocation_endpoint"] as? String,
           let endpoint = URL(string: address), configuration.permitsIdentityEndpoint(endpoint) {
            var request = URLRequest(url: endpoint)
            request.httpMethod = "POST"
            request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
            var form = URLComponents()
            form.queryItems = [
                URLQueryItem(name: "client_id", value: configuration.clientID),
                URLQueryItem(name: "token", value: refreshToken),
                URLQueryItem(name: "token_type_hint", value: "refresh_token"),
            ]
            // Escape literal '+' which form decoders otherwise interpret as space.
            request.httpBody = form.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B").data(using: .utf8)
            if let (_, response) = try? await network.data(for: request), let http = response as? HTTPURLResponse {
                revoked = (200...299).contains(http.statusCode)
            }
        }
        guard flowGeneration == epoch else { return false }
        guard let endSession = service.endSessionEndpoint,
              configuration.permitsIdentityEndpoint(endSession),
              let idToken = state.lastTokenResponse?.idToken,
              let viewController = try? presenter(),
              let agent = OIDExternalUserAgentIOS(presenting: viewController, prefersEphemeralSession: true)
        else { return false }
        let request = OIDEndSessionRequest(
            configuration: service, idTokenHint: idToken,
            postLogoutRedirectURL: configuration.redirectURL,
            additionalParameters: ["client_id": configuration.clientID]
        )
        let ended: Bool = await withCheckedContinuation { continuation in
            externalFlow = OIDAuthorizationService.present(request, externalUserAgent: agent) { [weak self] response, error in
                MainActor.assumeIsolated {
                    guard let self, self.flowGeneration == epoch else {
                        continuation.resume(returning: false)
                        return
                    }
                    self.externalFlow = nil
                    continuation.resume(returning: response != nil && error == nil)
                }
            }
        }
        return revoked && ended
    }

    public func cancel() {
        flowGeneration &+= 1
        let previous = externalFlow
        externalFlow = nil
        previous?.cancel()
    }

    private func discover(_ configuration: IdentityConfiguration) async throws -> OIDServiceConfiguration {
        let discoveryURL = configuration.issuerURL.appendingPathComponent(".well-known/openid-configuration")
        let (data, response) = try await network.data(from: discoveryURL)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200,
              data.count <= 512 * 1024,
              let discovery = try? OIDServiceDiscovery(jsonData: data),
              discovery.issuer == configuration.issuerURL,
              configuration.permitsIdentityEndpoint(discovery.authorizationEndpoint),
              configuration.permitsIdentityEndpoint(discovery.tokenEndpoint),
              configuration.permitsIdentityEndpoint(discovery.jwksURL)
        else { throw IdentityError.invalidConfiguration }
        return OIDServiceConfiguration(discoveryDocument: discovery)
    }

    private func unarchive(_ grant: IdentityGrant, configuration: IdentityConfiguration) throws -> OIDAuthState {
        guard grant.serializedState.count <= 1024 * 1024,
              let state = try? NSKeyedUnarchiver.unarchivedObject(ofClass: OIDAuthState.self, from: grant.serializedState)
        else { throw IdentityError.invalidToken }
        let request = state.lastAuthorizationResponse.request
        guard request.clientID == configuration.clientID, request.redirectURL == configuration.redirectURL,
              request.configuration.issuer == configuration.issuerURL,
              configuration.permitsIdentityEndpoint(request.configuration.tokenEndpoint),
              configuration.permitsIdentityEndpoint(request.configuration.authorizationEndpoint)
        else { throw IdentityError.invalidConfiguration }
        return state
    }

    private func makeGrant(_ state: OIDAuthState, configuration: IdentityConfiguration, fallbackName: String,
                           fallbackUsername: String?) throws -> IdentityGrant {
        guard state.isAuthorized, let token = state.lastTokenResponse?.accessToken,
              let expiresAt = state.lastTokenResponse?.accessTokenExpirationDate,
              expiresAt > .now else { throw IdentityError.noSession }
        let claims = state.lastTokenResponse?.idToken.flatMap { OIDIDToken(idTokenString: $0)?.claims }
        let name = claims?["name"] as? String ?? fallbackName
        let username = claims?["preferred_username"] as? String ?? fallbackUsername
        guard let data = try? NSKeyedArchiver.archivedData(withRootObject: state, requiringSecureCoding: true)
        else { throw IdentityError.storageFailure }
        return IdentityGrant(accessToken: token, expiresAt: expiresAt, displayName: name, serializedState: data,
                             username: username)
    }

    private static func safeError(_ error: (any Error)?) -> IdentityError {
        let nsError = error as NSError?
        if nsError?.domain == OIDOAuthTokenErrorDomain { return .noSession }
        if nsError?.domain == OIDGeneralErrorDomain,
           nsError?.code == OIDErrorCode.userCanceledAuthorizationFlow.rawValue { return .cancelled }
        // Never surface provider NSError descriptions: they can embed OAuth URLs.
        return .authenticationFailed
    }
}

/// OAuth token/discovery endpoints must not redirect sensitive request bodies.
/// This delegate is immutable; Foundation's Sendable delegate conformance is safe.
private final class IdentityRedirectPolicy: NSObject, URLSessionTaskDelegate {
    func urlSession(
        _ session: URLSession, task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping @Sendable (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}
#endif
