import Foundation
import CryptoKit

public struct ERPHTTPResponse: Sendable {
    public let statusCode: Int
    public let headers: [String: String]
    public let data: Data
    public init(statusCode: Int, headers: [String: String] = [:], data: Data) {
        self.statusCode = statusCode
        self.headers = Dictionary(headers.map { ($0.key.lowercased(), $0.value) }, uniquingKeysWith: { first, _ in first })
        self.data = data
    }
}
public protocol ERPHTTPTransport: Sendable {
    func send(_ request: URLRequest, maximumBytes: Int) async throws -> ERPHTTPResponse
}

/// Does not follow redirects, including redirects to another origin. Never logs requests.
private final class ERPRedirectBlocker: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

public actor ERPURLSessionTransport: ERPHTTPTransport {
    private let session: URLSession
    public init() {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCredentialStorage = nil
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 60
        session = URLSession(configuration: configuration, delegate: ERPRedirectBlocker(), delegateQueue: nil)
    }
    public func send(_ request: URLRequest, maximumBytes: Int) async throws -> ERPHTTPResponse {
        let (bytes, response) = try await session.bytes(for: request)
        defer { bytes.task.cancel() }
        guard let http = response as? HTTPURLResponse else { throw ERPClientError.invalidResponse }
        guard response.expectedContentLength <= maximumBytes else { throw ERPClientError.documentTooLarge }
        var data = Data()
        data.reserveCapacity(max(0, min(Int(response.expectedContentLength), maximumBytes)))
        for try await byte in bytes {
            guard data.count < maximumBytes else { throw ERPClientError.documentTooLarge }
            data.append(byte)
        }
        try Task.checkCancellation()
        let headers = http.allHeaderFields.reduce(into: [String: String]()) { result, pair in
            if let key = pair.key as? String { result[key.lowercased()] = String(describing: pair.value) }
        }
        return ERPHTTPResponse(statusCode: http.statusCode, headers: headers, data: data)
    }
}

/// API base must include /api/v1. Identity derives tenant exclusively from the bearer token.
public struct LiveERPService: ERPService, ERPInvoiceDraftLookup, ERPSalesOverviewService {
    private let baseURL: URL
    private let tokenProvider: @Sendable (Bool) async throws -> String
    private let transport: any ERPHTTPTransport
    private let documentHosts: Set<String>
    public init(baseURL: URL, tokenProvider: @escaping @Sendable (Bool) async throws -> String, transport: any ERPHTTPTransport = ERPURLSessionTransport(), allowedDocumentHosts: Set<String> = []) throws {
        guard Self.isSecureURL(baseURL), baseURL.query == nil, baseURL.fragment == nil,
              baseURL.path.trimmingCharacters(in: CharacterSet(charactersIn: "/")).hasSuffix("api/v1") else {
            throw ERPClientError.invalidConfiguration
        }
        self.baseURL = baseURL; self.tokenProvider = tokenProvider; self.transport = transport
        self.documentHosts = Set(allowedDocumentHosts.map { $0.lowercased() }).union([baseURL.host!.lowercased()])
    }

    public func context() async throws -> ERPContext { try await get("context") }
    public func memberships() async throws -> [ERPMembership] { try await get("memberships") }
    public func customers(query: String) async throws -> [ERPParty] {
        let term = try validatedQuery(query)
        let values: [ERPParty] = try await get("parties", query: queryItems(term) + [URLQueryItem(name: "role", value: "CUSTOMER")])
        // Keep only customers even if an older server ignores the role filter.
        return values.filter { $0.roles.contains("CUSTOMER") }
    }
    public func products(query: String) async throws -> [ERPProduct] { try await get("products", query: queryItems(query.trimmingCharacters(in: .whitespacesAndNewlines))) }
    public func invoiceSetup() async throws -> ERPInvoiceSetup {
        async let establishments: [ERPEstablishment] = get("establishments")
        async let points: [ERPEmissionPoint] = get("emission-points")
        async let taxes: [ERPTaxCategory] = get("tax-categories")
        return try await ERPInvoiceSetup(establishments: establishments.filter(\.active), emissionPoints: points.filter(\.active), taxCategories: taxes.filter(\.active))
    }
    public func invoices(query: String, status: String?) async throws -> [ERPInvoice] {
        let term = try validatedQuery(query)
        var items = queryItems(term)
        if let status, !status.isEmpty { items.append(URLQueryItem(name: "status", value: status)) }
        return try await get("invoices", query: items)
    }
    public func homeSummary() async throws -> ERPHomeSummary {
        do { return try await get("receivables/overview") }
        catch ERPClientError.idempotencyConflict { throw ERPClientError.unsupportedOverviewCurrency }
    }

    private func monthFilters(query: String, status: String?) throws -> [URLQueryItem] {
        var items = queryItems(try validatedQuery(query))
        if let status, !status.isEmpty { items.append(URLQueryItem(name: "status", value: status)) }
        return items
    }

    public func invoiceMonths(query: String, status: String?) async throws -> [ERPInvoiceMonth] {
        try await get("invoices/months", query: monthFilters(query: query, status: status))
    }

    public func monthPage(_ month: String, currency: String, query: String, status: String?, cursor: String?) async throws -> ERPInvoicePage {
        guard month.wholeMatch(of: /[0-9]{4}-(0[1-9]|1[0-2])/) != nil else {
            throw ERPClientError.invalidInput("Mes no válido.")
        }
        var items = try monthFilters(query: query, status: status)
        items.append(URLQueryItem(name: "currency", value: currency))
        if let cursor { items.append(URLQueryItem(name: "cursor", value: cursor)) }
        return try await get("invoices/months/\(month)", query: items)
    }

    public func invoice(id: UUID) async throws -> ERPInvoice { try await get("invoices/\(id.uuidString)") }
    public func findDraft(idempotencyKey: String) async throws -> UUID? {
        guard idempotencyKey.utf8.count == 36, UUID(uuidString: idempotencyKey) != nil else {
            throw ERPClientError.invalidInput("La operación necesita una clave válida.")
        }
        struct Result: Decodable, Sendable { let invoiceId: UUID }
        do {
            // The server treats the original key as opaque and case-sensitive.
            let result: Result = try await get("invoices/draft-requests/\(idempotencyKey)")
            return result.invoiceId
        } catch ERPClientError.notFound { return nil }
    }
    public func preview(_ input: ERPPreviewInput) async throws -> ERPInvoicePreview {
        try ERPInputValidation.validate(input)
        return try await request("invoices/preview", method: "POST", body: Self.encode(input), mayRefresh: true)
    }
    public func createDraft(_ input: ERPInvoiceInput, idempotencyKey: String) async throws -> ERPInvoice {
        try ERPInputValidation.validate(ERPPreviewInput(issueDate: input.issueDate, lines: input.lines))
        guard idempotencyKey.utf8.count >= 16,
              idempotencyKey.utf8.count <= 128, !idempotencyKey.contains("\n"), !idempotencyKey.contains("\r") else {
            throw ERPClientError.invalidInput("La operación necesita una clave válida.")
        }
        return try await request("invoices", method: "POST", body: Self.encode(input), idempotencyKey: idempotencyKey, mayRefresh: false)
    }
    public func artifacts(invoiceID: UUID) async throws -> [ERPArtifact] { try await get("invoices/\(invoiceID.uuidString)/artifacts") }
    public func document(invoiceID: UUID, artifact: ERPArtifact) async throws -> ERPDocument {
        guard ["ride-pdf", "xml-signed"].contains(artifact.artifactType), artifact.sha256.range(of: #"^[0-9a-fA-F]{64}$"#, options: .regularExpression) != nil else { throw ERPClientError.invalidResponse }
        let info: ERPArtifactDownload = try await get("invoices/\(invoiceID.uuidString)/artifacts/\(artifact.id.uuidString)/download")
        guard let url = URL(string: info.downloadUrl), Self.isSecureURL(url), url.fragment == nil,
              documentHosts.contains(url.host!.lowercased()), info.expiresInSeconds > 0 else { throw ERPClientError.invalidResponse }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)
        request.httpMethod = "GET"
        // Presigned storage URLs are fetched without bearer, cookies or credentials.
        request.setValue(artifact.artifactType == "ride-pdf" ? "application/pdf" : "application/xml", forHTTPHeaderField: "Accept")
        let response = try await transport.send(request, maximumBytes: 20 * 1_024 * 1_024)
        try Self.requireSuccess(response)
        let expectedHash = artifact.sha256.lowercased()
        let hash = SHA256.hash(data: response.data).map { String(format: "%02x", $0) }.joined()
        guard hash == expectedHash else { throw ERPClientError.invalidResponse }
        let mime = artifact.artifactType == "ride-pdf" ? "application/pdf" : "application/xml"
        if artifact.artifactType == "ride-pdf" {
            guard response.data.starts(with: Data("%PDF-".utf8)) else { throw ERPClientError.invalidResponse }
        } else {
            guard let prefix = String(data: response.data.prefix(256), encoding: .utf8), prefix.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("<") else { throw ERPClientError.invalidResponse }
        }
        let leaf = (info.fileName as NSString).lastPathComponent
        let safeName = leaf.filter { !$0.isNewline && !$0.isASCIIControl && $0 != ":" }
        guard !safeName.isEmpty, safeName.utf8.count <= 200, safeName != ".", safeName != ".." else { throw ERPClientError.invalidResponse }
        return ERPDocument(data: response.data, fileName: safeName, mimeType: mime)
    }

    private static func encode<T: Encodable>(_ input: T) throws -> Data {
        let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
        return try encoder.encode(input)
    }
    private func get<T: Decodable & Sendable>(_ route: String, query: [URLQueryItem] = []) async throws -> T {
        try await request(route, method: "GET", query: query, mayRefresh: true)
    }
    private func request<T: Decodable & Sendable>(_ route: String, method: String, query: [URLQueryItem] = [], body: Data? = nil, idempotencyKey: String? = nil, mayRefresh: Bool) async throws -> T {
        var components = URLComponents(url: baseURL.appendingPathComponent(route), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query }
        guard let url = components.url else { throw ERPClientError.invalidConfiguration }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)
        request.httpMethod = method; request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if let idempotencyKey { request.setValue(idempotencyKey, forHTTPHeaderField: "Idempotency-Key") }
        let token = try await tokenProvider(false)
        guard !token.isEmpty, !token.contains("\r"), !token.contains("\n") else { throw ERPClientError.authenticationRequired }
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        var response = try await transport.send(request, maximumBytes: 8 * 1_024 * 1_024)
        if response.statusCode == 401, mayRefresh {
            let fresh = try await tokenProvider(true)
            guard !fresh.isEmpty, !fresh.contains("\r"), !fresh.contains("\n") else { throw ERPClientError.authenticationRequired }
            request.setValue("Bearer \(fresh)", forHTTPHeaderField: "Authorization")
            response = try await transport.send(request, maximumBytes: 8 * 1_024 * 1_024)
        }
        try Task.checkCancellation()
        try Self.requireSuccess(response)
        do { return try JSONDecoder().decode(T.self, from: response.data) }
        catch { throw ERPClientError.invalidResponse }
    }
    private func validatedQuery(_ query: String) throws -> String {
        let term = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard term.isEmpty || term.count >= 2 else { throw ERPClientError.invalidInput("Escribe al menos dos caracteres para buscar.") }
        guard term.count <= 200 else { throw ERPClientError.invalidInput("La búsqueda es demasiado larga.") }
        return term
    }
    private func queryItems(_ term: String) -> [URLQueryItem] { term.isEmpty ? [] : [URLQueryItem(name: "q", value: term)] }
    private static func isSecureURL(_ url: URL) -> Bool {
        url.scheme?.lowercased() == "https" && url.host != nil && url.user == nil && url.password == nil && (url.port == nil || url.port == 443)
    }
    private static func requireSuccess(_ response: ERPHTTPResponse) throws {
        switch response.statusCode {
        case 200..<300: return
        case 401: throw ERPClientError.authenticationRequired
        case 403: throw ERPClientError.forbidden
        case 404: throw ERPClientError.notFound
        case 409: throw ERPClientError.idempotencyConflict
        case 429: throw ERPClientError.rateLimited(retryAfter: response.headers["retry-after"].flatMap(Int.init))
        case 400, 422: throw ERPClientError.invalidInput("Revisa los datos del formulario.")
        default: throw ERPClientError.server(response.statusCode)
        }
    }
}
private extension Character {
    var isASCIIControl: Bool { unicodeScalars.contains { $0.value < 32 || $0.value == 127 } }
}

public enum ERPInputValidation {
    public static func isFiscalDate(_ text: String) -> Bool {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX"); formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone(identifier: "America/Guayaquil"); formatter.dateFormat = "yyyy-MM-dd"; formatter.isLenient = false
        guard let date = formatter.date(from: text) else { return false }
        return formatter.string(from: date) == text
    }
    public static func validate(_ input: ERPPreviewInput) throws {
        guard isFiscalDate(input.issueDate), !input.lines.isEmpty, input.lines.count <= 100 else { throw ERPClientError.invalidInput("Elige una fecha válida y al menos una línea.") }
        for line in input.lines {
            guard !line.description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  line.description.count <= 300, !line.taxCode.isEmpty,
                  validDecimal(line.quantity, positive: true, integerDigits: 6, fractionDigits: 6),
                  validDecimal(line.unitPrice, positive: false, integerDigits: 6, fractionDigits: 6),
                  validDecimal(line.discount, positive: false, integerDigits: 14, fractionDigits: 2) else { throw ERPClientError.invalidInput("Revisa descripción, cantidad, precio, descuento e impuesto de cada línea.") }
        }
    }
    private static func validDecimal(_ value: Decimal, positive: Bool, integerDigits: Int, fractionDigits: Int) -> Bool {
        guard !value.isNaN, positive ? value > 0 : value >= 0 else { return false }
        let text = NSDecimalNumber(decimal: value).stringValue
        let parts = text.split(separator: ".", omittingEmptySubsequences: false)
        return !text.contains("E") && !text.contains("e") && parts[0].count <= integerDigits && (parts.count == 1 || parts[1].count <= fractionDigits)
    }
}
