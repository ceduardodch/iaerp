import Foundation
import IAERPClient

/// Developer trial transport through the paired Mac. Ignores request credentials.
nonisolated struct PairedTrialTransport: ERPHTTPTransport {
    static let host = "paired.iaerp.invalid"
    let directory: URL
    let selectionSHA256: String
    let invoiceID: UUID

    struct Request: Encodable {
        let selectionSHA256: String
        let method: String
        let path: String
        let query: String
        let body: Data?
        let idempotencyKey: String?
    }
    struct Response: Decodable {
        let selectionSHA256: String
        let statusCode: Int
        let headers: [String: String]
        let body: Data
    }

    func send(_ request: URLRequest, maximumBytes: Int) async throws -> ERPHTTPResponse {
        guard let url = request.url, url.scheme == "https", url.host == Self.host, url.port == nil,
              url.user == nil, url.password == nil, url.fragment == nil,
              let method = request.httpMethod, ["GET", "POST"].contains(method),
              allows(method, path: url.path) else { throw ERPClientError.forbidden }
        let requests = directory.appending(path: "requests", directoryHint: .isDirectory)
        let responses = directory.appending(path: "responses", directoryHint: .isDirectory)
        for folder in [requests, responses] {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true,
                                                   attributes: [.protectionKey: FileProtectionType.complete])
        }
        let name = UUID().uuidString.lowercased() + ".json"
        let outgoing = requests.appending(path: name)
        let incoming = responses.appending(path: name)
        let data = Request(selectionSHA256: selectionSHA256, method: method, path: url.path,
                           query: URLComponents(url: url, resolvingAgainstBaseURL: false)?.percentEncodedQuery ?? "",
                           body: request.httpBody, idempotencyKey: request.value(forHTTPHeaderField: "Idempotency-Key"))
        try Task.checkCancellation()
        try JSONEncoder().encode(data).write(to: outgoing, options: [.atomic, .completeFileProtection])
        defer {
            try? FileManager.default.removeItem(at: outgoing)
            try? FileManager.default.removeItem(at: incoming)
        }
        for _ in 0..<120 {
            try Task.checkCancellation()
            if FileManager.default.fileExists(atPath: incoming.path) {
                // The device may see the name before the USB transfer completes.
                let attrs = try incoming.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey])
                guard attrs.isRegularFile == true, attrs.isSymbolicLink != true,
                      let count = attrs.fileSize, count <= maximumBytes * 2 + 16384 else { throw ERPClientError.documentTooLarge }
                if let decoded = try? JSONDecoder().decode(Response.self, from: Data(contentsOf: incoming)) {
                    guard decoded.selectionSHA256 == selectionSHA256, (100...599).contains(decoded.statusCode),
                          decoded.body.count <= maximumBytes else { throw ERPClientError.invalidResponse }
                    return ERPHTTPResponse(statusCode: decoded.statusCode, headers: decoded.headers, data: decoded.body)
                }
            }
            try await Task.sleep(for: .milliseconds(250))
        }
        throw URLError(.timedOut)
    }

    func allows(_ method: String, path: String) -> Bool {
        let parts = path.split(separator: "/").map(String.init)
        if parts.count == 2, parts[0] == "trial-files" {
            return method == "GET" && UUID(uuidString: parts[1]) != nil
        }
        guard parts.count >= 4, Array(parts.prefix(3)) == ["api", "v1", "invoices"],
              UUID(uuidString: parts[3]) == invoiceID else { return false }
        let suffix = Array(parts.dropFirst(4))
        if method == "GET" {
            return [[], ["artifacts"], ["test-delivery"], ["test-delivery", "email-preview"]].contains(suffix) ||
                (suffix.count == 3 && suffix[0] == "artifacts" && UUID(uuidString: suffix[1]) != nil && suffix[2] == "download")
        }
        return method == "POST" && [["test-delivery", "issue"], ["test-delivery", "email"]].contains(suffix)
    }
}
