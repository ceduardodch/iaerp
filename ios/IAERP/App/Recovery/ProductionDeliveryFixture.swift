#if DEBUG && targetEnvironment(simulator)
import Foundation
import IAERPClient
import SwiftUI

struct ProductionDeliveryFixtureView: View {
    @State private var store: WorkspaceStore?
    @State private var error: String?
    var body: some View {
        NavigationStack {
            if let store {
                WorkspaceInvoiceDetail(store: store, invoiceId: ProductionDeliveryFixtureTransport.invoiceID,
                                       listedNumber: "001-001-000000042", listedCustomerName: "Cliente de control")
            } else if let error {
                Text(error)
            } else {
                ProgressView().task {
                    do { store = try WorkspaceStore.productionDeliveryFixture() }
                    catch { self.error = error.localizedDescription }
                }
            }
        }
    }
}

/// Requests follow the real client's encoding and decoding, entirely in memory.
actor ProductionDeliveryFixtureTransport: ERPHTTPTransport {
    nonisolated static let invoiceID = UUID(uuidString: "00000000-0000-4000-8000-000000005601")!
    private let partyID = UUID()
    private let establishmentID = UUID()
    private let pointID = UUID()
    private var files = ["factura-42.pdf", "factura-42.xml"]
    private let recipient = "cliente@example.invalid"
    private var digest = String(repeating: "a", count: 64)
    private var issued = ProcessInfo.processInfo.arguments.contains("-production-invoice-authorized")
    private var sent = false

    func send(_ request: URLRequest, maximumBytes: Int) async throws -> ERPHTTPResponse {
        let path = "/api/v1/invoices/" + Self.invoiceID.uuidString.lowercased()
        guard let url = request.url, url.host == "invoice.example.invalid",
              url.path.lowercased().starts(with: path) else { throw ERPClientError.notFound }
        let suffix = String(url.path.lowercased().dropFirst(path.count))
        let method = request.httpMethod ?? ""
        if method == "POST" && request.value(forHTTPHeaderField: "Idempotency-Key") == nil {
            throw ERPClientError.invalidResponse
        }
        let receipt: [String: Any] = ["messageId": "synthetic-mail-42", "recipient": recipient,
            "senderAddress": "ventas@example.invalid", "senderName": "Ventas", "attachmentNames": files]
        switch (method, suffix) {
        case ("GET", ""):
            let invoice = ERPInvoice(id: Self.invoiceID, status: issued ? "AUTHORIZED" : "DRAFT",
                sequential: "000000042", issueDate: "2026-11-19", subtotal: 5, tax: 0, total: 5,
                partyId: partyID, establishmentId: establishmentID, emissionPointId: pointID,
                authorizationNumber: issued ? String(repeating: "2", count: 49) : nil)
            return ERPHTTPResponse(statusCode: 200, data: try JSONEncoder().encode(invoice))
        case ("GET", "/artifacts"):
            let artifacts = issued ? ["ride-pdf", "xml-signed"].map {
                ERPArtifact(id: UUID(), artifactType: $0, sha256: digest, version: 1, createdAt: "2026-11-19T13:00:00Z")
            } : []
            return ERPHTTPResponse(statusCode: 200, data: try JSONEncoder().encode(artifacts))
        case ("GET", "/delivery-status"):
            var value: [String: Any] = ["fiscalEnvironment": "PRODUCTION", "emailStatus": sent ? "SENT" : "NOT_SENT"]
            if sent { value["receipt"] = receipt }
            return try json(value)
        case ("POST", "/issue") where !issued:
            issued = true
            return try json(["operationId": UUID().uuidString, "status": "PROCESSING"], status: 202)
        case ("GET", "/email-preview") where issued:
            return try json(["recipient": recipient, "senderAddress": "ventas@example.invalid", "senderName": "Ventas",
                "subject": "Factura 001-001-000000042", "message": "Adjuntamos los documentos de su factura.",
                "attachmentNames": files, "previewDigest": digest])
        case ("POST", "/email") where issued && !sent:
            guard let body = request.httpBody, let payload = try JSONSerialization.jsonObject(with: body) as? [String: String],
                  payload == ["recipient": recipient, "previewDigest": digest] else { throw ERPClientError.invalidResponse }
            if ProcessInfo.processInfo.arguments.contains("-production-report-changed"), files.count == 2 {
                files.append("informe-aprobado.pdf")
                digest = String(repeating: "b", count: 64)
                return try json(["detail": "Approve the required monthly report before emailing the invoice"], status: 422)
            }
            sent = true
            if ProcessInfo.processInfo.arguments.contains("-production-email-response-lost") { throw URLError(.timedOut) }
            return try json(receipt)
        default:
            return try json(["detail": "Solicitud de control desconocida"], status: 409)
        }
    }

    private func json(_ value: [String: Any], status: Int = 200) throws -> ERPHTTPResponse {
        ERPHTTPResponse(statusCode: status, headers: ["Content-Type": "application/json"],
                        data: try JSONSerialization.data(withJSONObject: value))
    }
}
#endif
