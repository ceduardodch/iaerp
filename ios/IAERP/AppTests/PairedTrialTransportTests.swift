import Foundation
import IAERPClient
import Testing
@testable import IAERP

@Suite("Transporte del simulador por cable")
struct PairedTrialTransportTests {
    @Test func transportRestrictsWritesToSelectedInvoiceAndTestActions() {
        let target = UUID()
        let transport = PairedTrialTransport(directory: URL.temporaryDirectory, selectionSHA256: "test", invoiceID: target)
        let path = "/api/v1/invoices/\(target)"
        #expect(transport.allows("POST", path: path + "/test-delivery/issue"))
        #expect(transport.allows("POST", path: path + "/test-delivery/email"))
        #expect(transport.allows("GET", path: path + "/artifacts/\(UUID())/download"))
        #expect(!transport.allows("POST", path: path + "/issue"))
        #expect(!transport.allows("POST", path: path + "/email"))
        #expect(!transport.allows("POST", path: "/api/v1/invoices/\(UUID())/test-delivery/issue"))
        #expect(!transport.allows("GET", path: "/api/v1/parties"))
        #expect(!transport.allows("GET", path: "/trial-files/../../private"))
    }

    @Test func exchangesOriginalKeyAndReadsResponseWithoutExportingCredentials() async throws {
        let directory = URL.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: directory) }
        let invoiceID = UUID()
        let api = PairedTrialTransport(directory: directory, selectionSHA256: "sample", invoiceID: invoiceID)
        let outgoing = Task {
            var request = URLRequest(url: URL(string: "https://paired.iaerp.invalid/api/v1/invoices/\(invoiceID)/test-delivery/issue")!)
            request.httpMethod = "POST"
            request.setValue("synthetic-credential-never-exported", forHTTPHeaderField: "Authorization")
            request.setValue("synthetic-stable-request", forHTTPHeaderField: "Idempotency-Key")
            return try await api.send(request, maximumBytes: 1024)
        }
        defer { outgoing.cancel() }
        let requests = directory.appending(path: "requests")
        var file: URL?
        for _ in 0..<100 {
            file = try? FileManager.default.contentsOfDirectory(at: requests, includingPropertiesForKeys: nil).first
            if file != nil { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        let url = try #require(file)
        let bytes = try Data(contentsOf: url)
        let value = try #require(try JSONSerialization.jsonObject(with: bytes) as? [String: Any])
        #expect(value["idempotencyKey"] as? String == "synthetic-stable-request")
        #expect(!String(decoding: bytes, as: UTF8.self).contains("synthetic-credential-never-exported"))
        let body = Data("{}".utf8)
        let reply: [String: Any] = ["statusCode": 202, "headers": ["content-type": "application/json"],
                                    "body": body.base64EncodedString(), "selectionSHA256": "sample"]
        let response = directory.appending(path: "responses").appending(path: url.lastPathComponent)
        try JSONSerialization.data(withJSONObject: reply).write(to: response, options: .atomic)
        let received = try await outgoing.value
        #expect(received.statusCode == 202)
        #expect(received.data == body)
        #expect(!FileManager.default.fileExists(atPath: url.path))
    }
}
