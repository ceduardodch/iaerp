import Foundation
import CryptoKit
import PDFKit
import Testing
@testable import IAERPClient

private actor MockHTTP: ERPHTTPTransport {
    enum Event: Sendable { case response(ERPHTTPResponse), lostConnection }
    var events: [Event]
    var requests: [URLRequest] = []
    init(_ responses: [ERPHTTPResponse]) { events = responses.map(Event.response) }
    init(events: [Event]) { self.events = events }
    func send(_ request: URLRequest, maximumBytes: Int) async throws -> ERPHTTPResponse {
        requests.append(request)
        guard !events.isEmpty else { throw ERPClientError.invalidResponse }
        switch events.removeFirst() {
        case .response(let response):
            guard response.data.count <= maximumBytes else { throw ERPClientError.documentTooLarge }
            return response
        case .lostConnection: throw URLError(.networkConnectionLost)
        }
    }
    func captured() -> [URLRequest] { requests }
}
private actor TokenCalls {
    var calls: [Bool] = []
    func token(_ refresh: Bool) -> String { calls.append(refresh); return refresh ? "fresh-demo-token" : "initial-demo-token" }
    func captured() -> [Bool] { calls }
}
private let baseURL = URL(string: "https://api.example.invalid/api/v1")!
private let contextJSON = Data(#"{"tenantId":"00000000-0000-4000-8000-000000000001","ruc":"DEMO","name":"Empresa de prueba","roles":["READER"],"scopes":["context:read"],"automationWritesEnabled":false,"defaultPaymentTermsDays":0}"#.utf8)
private func ok(_ data: Data) -> ERPHTTPResponse { ERPHTTPResponse(statusCode: 200, data: data) }
private func service(_ http: MockHTTP) throws -> LiveERPService {
    try LiveERPService(baseURL: baseURL, tokenProvider: { _ in "demo-token" }, transport: http)
}
private func demoInput(_ api: DemoERPService, quantity: Decimal = 1) async throws -> ERPInvoiceInput {
    let customer = try #require(await api.customers(query: "").first)
    let product = try #require(await api.products(query: "Servicio").first)
    let setup = try await api.invoiceSetup()
    return ERPInvoiceInput(customerId: customer.id, establishmentId: setup.establishments[0].id, emissionPointId: setup.emissionPoints[0].id, issueDate: "2026-11-17", lines: [ERPInvoiceLineInput(productId: product.id, description: product.name, quantity: quantity, unitPrice: product.unitPrice, taxCode: "4")])
}

struct ERPClientTests {
    @Test func mixedCurrencyDashboardDoesNotReportADraftConflict() async throws {
        let api = try service(MockHTTP([ERPHTTPResponse(statusCode: 409, data: Data())]))
        await #expect(throws: ERPClientError.unsupportedOverviewCurrency) { try await api.homeSummary() }
    }

    @Test func overviewAndMonthlyRoutesPreserveMoneyFiltersAndCursor() async throws {
        let http = MockHTTP([
            ok(Data(#"{"asOf":"2026-11-18","currency":"USD","outstanding":"1000000000.01","overdue":"12.34","collectedThisMonth":"0.02"}"#.utf8)),
            ok(Data(#"[{"month":"2026-11","currency":"USD","count":151,"total":"200.01"}]"#.utf8)),
            ok(Data(#"{"items":[{"id":"00000000-0000-4000-8000-000000000601","number":"001-001-000000001","customerName":"Ejemplo","issueDate":"2026-11-17","status":"AUTHORIZED","total":"7.50","currency":"USD","collectionStatus":"OPEN"}],"nextCursor":"next"}"#.utf8))
        ])
        let api = try service(http)
        let home = try await api.homeSummary()
        #expect(home.receivable == Decimal(string: "1000000000.01"))
        #expect(home.collectedThisMonth == Decimal(string: "0.02"))
        let months = try await api.invoiceMonths(query: "001-001-000000001", status: "AUTHORIZED")
        #expect(months.first?.count == 151)
        let page = try await api.monthPage("2026-11", currency: "USD", query: "001-001-000000001", status: "AUTHORIZED", cursor: "opaque:1")
        #expect(page.items.first?.collectionStatus == "OPEN")
        #expect(page.items.first?.total == Decimal(string: "7.50"))
        #expect(page.nextCursor == "next")
        let requests = await http.captured()
        #expect(requests.compactMap { $0.url?.path } == ["/api/v1/receivables/overview", "/api/v1/invoices/months", "/api/v1/invoices/months/2026-11"])
        let url = try #require(requests.last?.url)
        let params = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        #expect(Dictionary(uniqueKeysWithValues: params.map { ($0.name, $0.value) }) ==
                    ["q": "001-001-000000001", "status": "AUTHORIZED", "currency": "USD", "cursor": "opaque:1"])
    }

    @Test func draftLookupKeepsTheOriginalCaseSensitiveKey() async throws {
        let key = "ABCDEFAB-1234-4ABC-8123-ABCDEFABCDEF"
        let invoiceID = UUID(uuidString: "00000000-0000-4000-8000-000000000601")!
        let http = MockHTTP([ok(Data("{\"invoiceId\":\"\(invoiceID.uuidString)\"}".utf8))])
        let result = try await service(http).findDraft(idempotencyKey: key)
        #expect(result == invoiceID)
        let request = try #require(await http.captured().first)
        #expect(request.url?.path == "/api/v1/invoices/draft-requests/\(key)")
        #expect(request.httpMethod == "GET" && request.httpBody == nil)
    }

    @Test func draftLookupDistinguishesMissingFromDenied() async throws {
        let key = UUID().uuidString
        let http = MockHTTP([ERPHTTPResponse(statusCode: 404, data: Data()), ERPHTTPResponse(statusCode: 403, data: Data())])
        let api = try service(http)
        #expect(try await api.findDraft(idempotencyKey: key) == nil)
        await #expect(throws: ERPClientError.forbidden) { try await api.findDraft(idempotencyKey: key) }
    }

    @Test func unsafeDraftLookupKeyFailsBeforeSending() async throws {
        let http = MockHTTP([])
        await #expect(throws: ERPClientError.self) { try await service(http).findDraft(idempotencyKey: "../other-tenant") }
        #expect(await http.captured().isEmpty)
    }

    @Test func decimalOverflowIsRejectedInsteadOfRounded() throws {
        let raw = Data(("{\"id\":\"00000000-0000-4000-8000-000000000201\",\"name\":\"Ejemplo\",\"unitPrice\":\"" + String(repeating: "9", count: 39) + "\",\"taxCategoryId\":\"00000000-0000-4000-8000-000000000301\"}").utf8)
        #expect(throws: (any Error).self) { try JSONDecoder().decode(ERPProduct.self, from: raw) }
    }

    @Test func decimalStringsRoundTripWithoutBinaryFloatingPoint() throws {
        let raw = Data(#"{"id":"00000000-0000-4000-8000-000000000201","name":"Ejemplo","code":null,"unitPrice":"999999999999.123456","taxCategoryId":"00000000-0000-4000-8000-000000000301"}"#.utf8)
        let product = try JSONDecoder().decode(ERPProduct.self, from: raw)
        #expect(product.unitPrice == Decimal(string: "999999999999.123456"))
        let object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(product)) as? [String: Any])
        #expect(object["unitPrice"] as? String == "999999999999.123456")
        let numeric = Data(String(decoding: raw, as: UTF8.self).replacingOccurrences(of: #""999999999999.123456""#, with: "999999999999.123456").utf8)
        #expect(throws: (any Error).self) { try JSONDecoder().decode(ERPProduct.self, from: numeric) }
    }
    @Test func repeatedProductsKeepDistinctLocalLineIdentityOutsidePayload() throws {
        let productID = UUID()
        let first = ERPInvoiceLineInput(productId: productID, description: "Uno", quantity: 1, unitPrice: 100, taxCode: "4")
        let second = ERPInvoiceLineInput(productId: productID, description: "Dos", quantity: 1, unitPrice: 100, taxCode: "4")
        #expect(first.id != second.id)
        #expect(first.id == first.id)
        let object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(first)) as? [String: Any])
        #expect(object["id"] == nil && object["localID"] == nil)
        #expect(object["quantity"] as? String == "1")
        #expect(object["productId"] as? String == productID.uuidString)
    }
    @Test func customerContractUsesRoleFilterAndNeverSendsTenant() async throws {
        let customer = ERPParty(id: UUID(), name: "Cliente de prueba", identificationType: "PASSPORT", identificationNumber: "DEMO")
        let supplier = ERPParty(id: UUID(), name: "Proveedor de prueba", identificationType: "PASSPORT", identificationNumber: "DEMO2", roles: ["SUPPLIER"])
        let http = MockHTTP([ok(try JSONEncoder().encode([customer, supplier]))])
        let values = try await service(http).customers(query: "Cliente & prueba")
        #expect(values == [customer])
        let request = try #require(await http.captured().first)
        let items = try #require(URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems)
        #expect(items.contains(URLQueryItem(name: "role", value: "CUSTOMER")))
        #expect(items.contains(URLQueryItem(name: "q", value: "Cliente & prueba")))
        #expect(!items.contains { $0.name.lowercased().contains("tenant") })
        #expect(request.httpBody == nil)
        #expect(request.value(forHTTPHeaderField: "Authorization") == "Bearer demo-token")
    }
    @Test func shortSearchFailsBeforeNetwork() async throws {
        let http = MockHTTP([])
        await #expect(throws: ERPClientError.invalidInput("Escribe al menos dos caracteres para buscar.")) {
            try await service(http).customers(query: "a")
        }
        #expect(await http.captured().isEmpty)
    }
    @Test func unauthorizedReadRefreshesOnce() async throws {
        let http = MockHTTP([ERPHTTPResponse(statusCode: 401, data: Data()), ok(contextJSON)])
        let calls = TokenCalls()
        let api = try LiveERPService(baseURL: baseURL, tokenProvider: { await calls.token($0) }, transport: http)
        let context = try await api.context()
        #expect(context.name == "Empresa de prueba")
        #expect(await calls.captured() == [false, true])
        let requests = await http.captured()
        #expect(requests.count == 2)
        #expect(requests.last?.value(forHTTPHeaderField: "Authorization") == "Bearer fresh-demo-token")
    }
    @Test func repeatedUnauthorizedReadStopsAfterOneRefresh() async throws {
        let http = MockHTTP([ERPHTTPResponse(statusCode: 401, data: Data()), ERPHTTPResponse(statusCode: 401, data: Data())])
        await #expect(throws: ERPClientError.authenticationRequired) { try await service(http).context() }
        #expect(await http.captured().count == 2)
    }
    @Test(arguments: [403, 429, 503]) func errorsRemainDistinct(_ code: Int) async throws {
        let http = MockHTTP([ERPHTTPResponse(statusCode: code, headers: ["Retry-After": "17"], data: Data())])
        let expected: ERPClientError = code == 403 ? .forbidden : code == 429 ? .rateLimited(retryAfter: 17) : .server(503)
        await #expect(throws: expected) { try await service(http).context() }
    }
    @Test func draftUnauthorizedIsNotAutomaticallyReplayed() async throws {
        let http = MockHTTP([ERPHTTPResponse(statusCode: 401, data: Data())])
        let input = try await demoInput(DemoERPService())
        await #expect(throws: ERPClientError.authenticationRequired) { try await service(http).createDraft(input, idempotencyKey: "demo-idempotency-0001") }
        let requests = await http.captured()
        #expect(requests.count == 1)
        #expect(requests[0].httpMethod == "POST")
        #expect(requests[0].value(forHTTPHeaderField: "Idempotency-Key") == "demo-idempotency-0001")
        let object = try #require(JSONSerialization.jsonObject(with: requests[0].httpBody!) as? [String: Any])
        #expect(object["tenantId"] == nil)
        #expect(object["collectionEnabled"] as? Bool == false)
    }
    @Test func manualRetryAfterLostResponsePreservesKeyAndPayload() async throws {
        let demo = DemoERPService()
        let input = try await demoInput(demo)
        let saved = try await demo.createDraft(input, idempotencyKey: "demo-idempotency-0001")
        let http = MockHTTP(events: [.lostConnection, .response(ok(try JSONEncoder().encode(saved)))])
        let api = try service(http)
        await #expect(throws: (any Error).self) { try await api.createDraft(input, idempotencyKey: "demo-idempotency-0001") }
        #expect(try await api.createDraft(input, idempotencyKey: "demo-idempotency-0001").id == saved.id)
        let requests = await http.captured()
        #expect(requests.count == 2)
        #expect(requests[0].httpBody == requests[1].httpBody)
        #expect(requests[0].value(forHTTPHeaderField: "Idempotency-Key") == requests[1].value(forHTTPHeaderField: "Idempotency-Key"))
    }
    @Test(arguments: ["short", String(repeating: "x", count: 129), "invalid-idempotency\nkey"])
    func invalidIdempotencyKeyFailsBeforeNetwork(_ key: String) async throws {
        let http = MockHTTP([])
        let input = try await demoInput(DemoERPService())
        await #expect(throws: (any Error).self) { try await service(http).createDraft(input, idempotencyKey: key) }
        #expect(await http.captured().isEmpty)
    }
    @Test(arguments: ["http://api.example.invalid/api/v1", "https://user:secret@api.example.invalid/api/v1", "https://api.example.invalid:444/api/v1", "https://api.example.invalid/api/v1?tenant=bad"])
    func insecureConfigurationRejected(_ raw: String) throws {
        #expect(throws: ERPClientError.invalidConfiguration) { try LiveERPService(baseURL: URL(string: raw)!, tokenProvider: { _ in "demo" }) }
    }
    @Test func twoCompaniesCannotReadOrSaveEachOthersRecords() async throws {
        let first = DemoERPService(company: .primary)
        let second = DemoERPService(company: .secondary)
        let primary = try await first.context(), secondary = try await second.context()
        #expect(primary.tenantId != secondary.tenantId)
        let firstCustomer = try #require(await first.customers(query: "").first)
        #expect(try await second.customers(query: "").allSatisfy { $0.id != firstCustomer.id })
        let firstInvoice = try #require(await first.invoices(query: "", status: nil).first)
        await #expect(throws: ERPClientError.notFound) { try await second.invoice(id: firstInvoice.id) }
        var input = try await demoInput(first)
        let secondSetup = try await second.invoiceSetup()
        input.establishmentId = secondSetup.establishments[0].id; input.emissionPointId = secondSetup.emissionPoints[0].id
        await #expect(throws: ERPClientError.notFound) { try await second.createDraft(input, idempotencyKey: "tenant-isolation-0001") }
    }
    @Test func demoIdempotencyConcurrentRequestsCreateOneDraft() async throws {
        let api = DemoERPService()
        let input = try await demoInput(api)
        let ids = try await withThrowingTaskGroup(of: UUID.self) { group in
            for _ in 0..<12 { group.addTask { try await api.createDraft(input, idempotencyKey: "concurrent-draft-0001").id } }
            var values: [UUID] = []
            for try await value in group { values.append(value) }
            return values
        }
        #expect(Set(ids).count == 1)
        #expect(try await api.invoices(query: "", status: "DRAFT").count == 2) // One seed + one saved.
        var changed = input; changed.lines[0].quantity = 2
        await #expect(throws: ERPClientError.idempotencyConflict) { try await api.createDraft(changed, idempotencyKey: "concurrent-draft-0001") }
    }
    @Test func readOnlyRoleCannotCreateDraft() async throws {
        let reader = DemoERPService(readOnly: true)
        let context = try await reader.context()
        #expect(!context.permits("invoices:write"))
        #expect(try await reader.customers(query: "").count == 3)
        let input = try await demoInput(reader)
        await #expect(throws: ERPClientError.forbidden) { try await reader.createDraft(input, idempotencyKey: "read-only-draft-0001") }
    }
    @Test func fixedPreviewSupportsTwoProductsAndRejectsModifiedPrice() async throws {
        let api = DemoERPService()
        var input = try await demoInput(api, quantity: 2)
        let support = try #require(await api.products(query: "Soporte").first)
        input.lines.append(ERPInvoiceLineInput(productId: support.id, description: support.name, quantity: 3, unitPrice: 50, taxCode: "0"))
        let preview = try await api.preview(ERPPreviewInput(issueDate: input.issueDate, lines: input.lines))
        #expect(preview.subtotal == 350 && preview.taxTotal == 30 && preview.total == 380)
        input.lines[0].unitPrice = 101
        await #expect(throws: ERPClientError.fixtureUnsupported) { try await api.preview(ERPPreviewInput(issueDate: input.issueDate, lines: input.lines)) }
    }
    @Test func invalidDateAndQuantityAreRejected() throws {
        #expect(ERPInputValidation.isFiscalDate("2026-11-17"))
        #expect(!ERPInputValidation.isFiscalDate("2026-02-30"))
        #expect(!ERPInputValidation.isFiscalDate("2026-2-1"))
        let line = ERPInvoiceLineInput(description: "Servicio", quantity: 0, unitPrice: 100, taxCode: "4")
        #expect(throws: (any Error).self) { try ERPInputValidation.validate(ERPPreviewInput(issueDate: "2026-11-17", lines: [line])) }
    }
    @Test func syntheticDocumentsHavePDFAndXMLAndStayTenantScoped() async throws {
        let api = DemoERPService()
        let value = try #require(await api.invoices(query: "", status: "AUTHORIZED").first)
        let artifacts = try await api.artifacts(invoiceID: value.id)
        #expect(artifacts.count == 2)
        let pdf = try #require(artifacts.first { $0.artifactType == "ride-pdf" })
        let document = try await api.document(invoiceID: value.id, artifact: pdf)
        #expect(document.data.starts(with: Data("%PDF-".utf8)))
        #expect(document.mimeType == "application/pdf")
        let pdfText = try #require(PDFDocument(data: document.data)?.string)
        #expect(pdfText.contains("sin validez fiscal") && pdfText.contains("Total: USD 115.00"))
        let secondary = DemoERPService(company: .secondary)
        await #expect(throws: ERPClientError.notFound) { try await secondary.document(invoiceID: value.id, artifact: pdf) }
        let historical = try #require(await api.invoices(query: "", status: "HISTORICAL_ISSUED").first)
        #expect(try await api.artifacts(invoiceID: historical.id).map(\.artifactType) == ["ride-pdf"])
    }
    @Test func documentUsesAllowlistedHostWithoutBearerAndVerifiesDigest() async throws {
        let pdf = Data("%PDF-1.4 synthetic".utf8)
        let hash = SHA256.hash(data: pdf).map { String(format: "%02x", $0) }.joined()
        let artifact = ERPArtifact(id: UUID(), artifactType: "ride-pdf", sha256: hash, version: 1, createdAt: "2026-11-17T12:00:00Z")
        let metadata = ERPArtifactDownload(downloadUrl: "https://storage.example.invalid/fixture.pdf?signature=synthetic", expiresInSeconds: 300, fileName: "../fixture.pdf")
        let http = MockHTTP([ok(try JSONEncoder().encode(metadata)), ok(pdf)])
        let api = try LiveERPService(baseURL: baseURL, tokenProvider: { _ in "demo-token" }, transport: http, allowedDocumentHosts: ["storage.example.invalid"])
        let result = try await api.document(invoiceID: UUID(), artifact: artifact)
        #expect(result.fileName == "fixture.pdf")
        #expect(result.data == pdf)
        let requests = await http.captured()
        #expect(requests.count == 2)
        #expect(requests[0].value(forHTTPHeaderField: "Authorization") == "Bearer demo-token")
        #expect(requests[1].value(forHTTPHeaderField: "Authorization") == nil)
        #expect(requests[1].value(forHTTPHeaderField: "Cookie") == nil)
    }
    @Test func unapprovedDocumentOriginFailsBeforeDownload() async throws {
        let artifact = ERPArtifact(id: UUID(), artifactType: "ride-pdf", sha256: String(repeating: "0", count: 64), version: 1, createdAt: "2026-11-17T12:00:00Z")
        let metadata = ERPArtifactDownload(downloadUrl: "https://unapproved.example.invalid/fixture.pdf", expiresInSeconds: 300, fileName: "fixture.pdf")
        let http = MockHTTP([ok(try JSONEncoder().encode(metadata))])
        await #expect(throws: ERPClientError.invalidResponse) { try await service(http).document(invoiceID: UUID(), artifact: artifact) }
        #expect(await http.captured().count == 1)
    }
    @Test func wrongDocumentDigestFailsClosed() async throws {
        let artifact = ERPArtifact(id: UUID(), artifactType: "ride-pdf", sha256: String(repeating: "0", count: 64), version: 1, createdAt: "2026-11-17T12:00:00Z")
        let metadata = ERPArtifactDownload(downloadUrl: "https://api.example.invalid/fixture.pdf", expiresInSeconds: 300, fileName: "fixture.pdf")
        let http = MockHTTP([ok(try JSONEncoder().encode(metadata)), ok(Data("%PDF-wrong".utf8))])
        await #expect(throws: ERPClientError.invalidResponse) { try await service(http).document(invoiceID: UUID(), artifact: artifact) }
    }
}

@Suite("Emisión simulada y buzón de pruebas")
struct TestInvoiceDeliveryTests {
    let mailbox = "buzon@iaerp.example.org"

    @Test func liveUsesOnlyTheTestRoutesAndConfirmsThePreviewEnvelope() async throws {
        let id = UUID()
        let key = UUID().uuidString
        let emailKey = UUID().uuidString
        let receiptJSON = #"{"messageId":"capture-1","recipient":"buzon@iaerp.example.org","attachmentNames":["FACTURA-1.xml","FACTURA-1.pdf"]}"#
        let http = MockHTTP([
            ok(Data(#"{"environment":"TEST","transmissionMode":"simulator","canIssue":true,"canEmail":false,"captureRecipient":"buzon@iaerp.example.org","emailReceipt":null}"#.utf8)),
            ERPHTTPResponse(statusCode: 202, data: Data("{\"operationId\":\"\(UUID().uuidString)\",\"status\":\"PROCESSING\"}".utf8)),
            ok(Data(#"{"recipient":"buzon@iaerp.example.org","subject":"Prueba","message":"RIDE y XML","attachmentNames":["FACTURA-1.xml","FACTURA-1.pdf"]}"#.utf8)),
            ok(Data(receiptJSON.utf8)),
            ok(Data(("{\"environment\":\"TEST\",\"transmissionMode\":\"simulator\",\"canIssue\":false,\"canEmail\":false,\"captureRecipient\":\"buzon@iaerp.example.org\",\"emailReceipt\":" + receiptJSON + "}").utf8))
        ])
        let api = try service(http)
        #expect(try await api.testActions(invoiceID: id).canIssue)
        #expect(try await api.issueTestInvoice(invoiceID: id, idempotencyKey: key).status == "PROCESSING")
        let preview = try await api.testEmailPreview(invoiceID: id)
        let receipt = try await api.sendTestEmail(invoiceID: id, recipient: preview.recipient, idempotencyKey: emailKey)
        #expect(receipt.attachmentNames == preview.attachmentNames)
        let reopened = try await api.testActions(invoiceID: id)
        #expect(reopened.emailReceipt == receipt && !reopened.canEmail)
        let requests = await http.captured()
        let base = "/api/v1/invoices/\(id.uuidString)/test-delivery"
        #expect(requests.map { $0.url?.path } == [base, base + "/issue", base + "/email-preview", base + "/email", base])
        #expect(requests.map(\.httpMethod) == ["GET", "POST", "GET", "POST", "GET"])
        #expect(requests.map { $0.value(forHTTPHeaderField: "Idempotency-Key") } == [nil, key, nil, emailKey, nil])
        #expect(requests.allSatisfy { $0.value(forHTTPHeaderField: "Authorization") == "Bearer demo-token" })
        #expect(requests[1].httpBody == nil)
        let body = try #require(requests[3].httpBody)
        #expect(try JSONDecoder().decode([String: String].self, from: body) == ["recipient": mailbox])
    }

    @Test(arguments: ["PRODUCTION|simulator", "TEST|soap", "TEST|unknown"])
    func refusesUnsupportedEnvironment(_ settings: String) async throws {
        let fields = settings.split(separator: "|")
        let json = "{\"environment\":\"\(fields[0])\",\"transmissionMode\":\"\(fields[1])\",\"canIssue\":true,\"canEmail\":true,\"captureRecipient\":\"buzon@iaerp.example.org\"}"
        let api = try service(MockHTTP([ok(Data(json.utf8))]))
        await #expect(throws: ERPClientError.invalidResponse) { try await api.testActions(invoiceID: UUID()) }
    }

    @Test func incompletePreviewOrUnexpectedRecipientCannotSend() async throws {
        let data = Data(#"{"recipient":"buzon@iaerp.example.org","subject":"Prueba","message":"Adjunto","attachmentNames":["factura.pdf"]}"#.utf8)
        let http = MockHTTP([ok(data)])
        let api = try service(http)
        await #expect(throws: ERPClientError.invalidResponse) { try await api.testEmailPreview(invoiceID: UUID()) }
        await #expect(throws: ERPClientError.forbidden) {
            try await api.sendTestEmail(invoiceID: UUID(), recipient: "cliente@example.invalid", idempotencyKey: UUID().uuidString)
        }
        await #expect(throws: ERPClientError.self) { try await api.issueTestInvoice(invoiceID: UUID(), idempotencyKey: "short") }
        #expect(await http.captured().count == 1)
    }

    @Test func unsuccessfulWritesNeverResendAutomatically() async throws {
        let tokens = TokenCalls()
        let http = MockHTTP(events: [.response(ERPHTTPResponse(statusCode: 401, data: Data())), .lostConnection])
        let api = try LiveERPService(baseURL: baseURL, tokenProvider: { await tokens.token($0) }, transport: http)
        await #expect(throws: ERPClientError.authenticationRequired) { try await api.issueTestInvoice(invoiceID: UUID(), idempotencyKey: UUID().uuidString) }
        await #expect(throws: URLError.self) { try await api.sendTestEmail(invoiceID: UUID(), recipient: mailbox, idempotencyKey: UUID().uuidString) }
        #expect(await tokens.captured() == [false, false])
        #expect(await http.captured().count == 2)
    }

    @Test func authorizedTestInvoiceAndCaptureSurviveRelaunchWithTheExactTwoFiles() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let demo = DemoERPService(testDeliveryDirectory: directory)
        var input = try await demoInput(demo, quantity: 2)
        input.lines[0].description = "Servicio & soporte <prueba> (Álamo)"
        let draft = try await demo.createDraft(input, idempotencyKey: UUID().uuidString)
        let issueKey = UUID().uuidString
        async let issue1 = demo.issueTestInvoice(invoiceID: draft.id, idempotencyKey: issueKey)
        async let issue2 = demo.issueTestInvoice(invoiceID: draft.id, idempotencyKey: issueKey)
        let (first, second) = try await (issue1, issue2)
        #expect(first == second && first.status == "PROCESSING")
        let reopened = DemoERPService(testDeliveryDirectory: directory)
        let pending = try await reopened.invoice(id: draft.id)
        #expect(["PENDING_AUTHORIZATION","AUTHORIZED"].contains(pending.status))
        try await Task.sleep(for: .milliseconds(800))
        let authorized = try await reopened.invoice(id: draft.id)
        #expect(authorized.status == "AUTHORIZED" && authorized.total == draft.total)
        #expect(try await reopened.invoices(query: "", status: "AUTHORIZED").contains { $0.id == draft.id })
        #expect(try await reopened.artifacts(invoiceID: draft.id).count == 2)
        let emailKey = UUID().uuidString
        let preview = try await reopened.testEmailPreview(invoiceID: draft.id)
        #expect(preview.recipient == mailbox)
        async let send1 = demo.sendTestEmail(invoiceID: draft.id, recipient: preview.recipient, idempotencyKey: emailKey)
        async let send2 = reopened.sendTestEmail(invoiceID: draft.id, recipient: preview.recipient, idempotencyKey: emailKey)
        let (receipt1, receipt2) = try await (send1, send2)
        #expect(receipt1 == receipt2)
        let relaunched = DemoERPService(testDeliveryDirectory: directory)
        let recovered = try await relaunched.testActions(invoiceID: draft.id)
        #expect(!recovered.canEmail && recovered.emailReceipt == receipt1)
        let mail = try #require(try await relaunched.capturedTestEmail(invoiceID: draft.id))
        #expect(mail.subject == preview.subject && mail.message == preview.message)
        #expect(mail.attachments.count == 2)
        #expect(mail.attachments.map(\.fileName) == receipt1.attachmentNames)
        let capturedPDF = try #require(mail.attachments.first { $0.mimeType == "application/pdf" })
        let pdfText = try #require(PDFDocument(data: capturedPDF.data)?.string)
        #expect(pdfText.contains("Empresa de prueba") && pdfText.contains("Cliente de ejemplo Álamo"))
        #expect(pdfText.contains("Factura: 001-001-" + draft.sequential))
        #expect(pdfText.contains("Subtotal: USD 200.00") && pdfText.contains("IVA: USD 30.00"))
        #expect(pdfText.contains("Total: USD 230.00") && pdfText.contains(input.lines[0].description))
        let capturedXML = try #require(mail.attachments.first { $0.mimeType == "application/xml" })
        let tags = try CapturedXML.parse(capturedXML.data)
        #expect(tags["total"] == ["230.00"] && tags["subtotal"] == ["200.00"])
        #expect(tags["iva"]?.last == "30.00" && tags["descripcion"] == [input.lines[0].description])
        #expect(tags["moneda"] == ["USD"] && tags["numeroCompleto"] == ["001-001-" + draft.sequential])
        let files = try await relaunched.artifacts(invoiceID: draft.id)
        for artifact in files {
            let expected = try await relaunched.document(invoiceID: draft.id, artifact: artifact)
            #expect(mail.attachments.contains(expected))
        }
        #expect(mail.attachments.contains { $0.mimeType == "application/pdf" && $0.data.starts(with: "%PDF-".utf8) })
        #expect(mail.attachments.contains { $0.mimeType == "application/xml" && String(decoding: $0.data, as: UTF8.self).contains("<numero>\(draft.sequential)</numero>") })
        await #expect(throws: ERPClientError.idempotencyConflict) {
            try await relaunched.sendTestEmail(invoiceID: draft.id, recipient: mailbox, idempotencyKey: UUID().uuidString)
        }
        let next = try await relaunched.createDraft(input, idempotencyKey: UUID().uuidString)
        #expect(next.id != draft.id && next.sequential != draft.sequential)
        let other = DemoERPService(company: .secondary, testDeliveryDirectory: directory)
        await #expect(throws: ERPClientError.notFound) { try await other.testActions(invoiceID: draft.id) }
        #expect(try await other.capturedTestEmail(invoiceID: draft.id) == nil)
    }

    @Test func rejectedFixtureKeepsTheReasonAndCannotBeEmailed() async throws {
        let demo = DemoERPService(rejectTestIssues: true)
        let input = try await demoInput(demo)
        let draft = try await demo.createDraft(input, idempotencyKey: UUID().uuidString)
        _ = try await demo.issueTestInvoice(invoiceID: draft.id, idempotencyKey: UUID().uuidString)
        try await Task.sleep(for: .milliseconds(800))
        let invoice = try await demo.invoice(id: draft.id)
        #expect(invoice.status == "REJECTED")
        #expect(invoice.sriTransmission?.message?.contains("rechazó") == true)
        #expect(try await demo.artifacts(invoiceID: draft.id).isEmpty)
        #expect(try await !demo.testActions(invoiceID: draft.id).canIssue)
        await #expect(throws: ERPClientError.self) { try await demo.testEmailPreview(invoiceID: draft.id) }
        #expect(try await demo.capturedTestEmail(invoiceID: draft.id) == nil)
    }

    @Test func readOnlyCannotIssueOrCapture() async throws {
        let reader = DemoERPService(readOnly: true)
        let draft = try #require(try await reader.invoices(query: "", status: "DRAFT").first)
        let authorized = try #require(try await reader.invoices(query: "", status: "AUTHORIZED").first)
        #expect(try await !reader.testActions(invoiceID: draft.id).canIssue)
        #expect(try await !reader.testActions(invoiceID: authorized.id).canEmail)
        await #expect(throws: ERPClientError.forbidden) { try await reader.issueTestInvoice(invoiceID: draft.id, idempotencyKey: UUID().uuidString) }
        await #expect(throws: ERPClientError.forbidden) { try await reader.sendTestEmail(invoiceID: authorized.id, recipient: mailbox, idempotencyKey: UUID().uuidString) }
    }
}

private final class CapturedXML: NSObject, XMLParserDelegate {
    private var elements: [String: [String]] = [:]
    private var text = ""

    static func parse(_ data: Data) throws -> [String: [String]] {
        let result = CapturedXML()
        let parser = XMLParser(data: data)
        parser.shouldResolveExternalEntities = false
        parser.delegate = result
        guard parser.parse() else { throw parser.parserError ?? ERPClientError.invalidResponse }
        return result.elements
    }

    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?,
                qualifiedName qName: String?, attributes attributeDict: [String: String] = [:]) { text = "" }
    func parser(_ parser: XMLParser, foundCharacters string: String) { text += string }
    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?,
                qualifiedName qName: String?) {
        elements[elementName, default: []].append(text.trimmingCharacters(in: .whitespacesAndNewlines))
        text = ""
    }
}

extension TestInvoiceDeliveryTests {
    @Test func btobSandboxDeliversBothWebArtifactsForExactlyFiveCents() async throws {
        let api = DemoERPService(company: .btobSandbox)
        let draft = try #require(try await api.invoices(query: "", status: "DRAFT").first)
        #expect(draft.id == DemoCompany.uuid(2_601) && draft.total == Decimal(string: "0.05")!)
        #expect(try await api.products(query: "").first?.unitPrice == draft.total)
        #expect(try await api.memberships().map(\.organizationId) == ["btob-sas"])
        #expect(try await DemoERPService().memberships().allSatisfy { $0.organizationId != "btob-sas" })
        #expect(try await api.artifacts(invoiceID: draft.id).isEmpty)
        _ = try await api.issueTestInvoice(invoiceID: draft.id, idempotencyKey: UUID().uuidString)
        try await Task.sleep(for: .milliseconds(800))
        let invoice = try await api.invoice(id: draft.id)
        let preview = try await api.testEmailPreview(invoiceID: draft.id)
        #expect(preview.subject.contains("001-001-" + invoice.sequential))
        #expect(preview.message.contains("0.05") && preview.message.contains(invoice.issueDate))
        let receipt = try await api.sendTestEmail(invoiceID: draft.id, recipient: preview.recipient, idempotencyKey: UUID().uuidString)
        #expect(receipt.attachmentNames == preview.attachmentNames)
        let mail = try #require(try await api.capturedTestEmail(invoiceID: draft.id))
        #expect(mail.subject == preview.subject && mail.message == preview.message)
        let pdf = try #require(mail.attachments.first { $0.mimeType == "application/pdf" })
        let pdfText = try #require(PDFDocument(data: pdf.data)?.string)
        let number = "001-001-" + draft.sequential
        #expect(pdfText.contains(number) && pdfText.contains("VALOR TOTAL 0.05"))
        #expect(pdfText.contains("SUBTOTAL SIN IMPUESTOS 0.05") && pdfText.contains("IVA 0.00"))
        #expect(pdfText.contains("AMBIENTE: PRUEBAS") && pdfText.contains(BTOBTestFixture.customerName))
        #expect(pdfText.contains("Servicio de prueba"))
        let authorization = try #require(invoice.authorizationNumber)
        #expect(pdfText.contains(authorization))
        let xml = try #require(mail.attachments.first { $0.mimeType == "application/xml" })
        let tags = try CapturedXML.parse(xml.data)
        #expect(tags["importeTotal"] == ["0.05"] && tags["moneda"] == ["USD"])
        #expect(tags["totalSinImpuestos"] == ["0.05"] && tags["secuencial"] == [draft.sequential])
        #expect(tags["claveAcceso"] == [authorization] && tags["ambiente"] == ["1"])
        #expect(tags["razonSocialComprador"] == [BTOBTestFixture.customerName])
        #expect(tags["descripcion"] == ["Servicio de prueba"] && tags["precioTotalSinImpuesto"] == ["0.05"])
        let artifacts = try await api.artifacts(invoiceID: draft.id)
        for artifact in artifacts {
            let document = try await api.document(invoiceID: draft.id, artifact: artifact)
            #expect(mail.attachments.contains(document))
        }
    }
}

extension TestInvoiceDeliveryTests {
    @Test func importedWebDossierIsBoundToTheDemoCompanyAndExactCustomer() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let source = try #require(Bundle.module.url(forResource: "BTOBTestInvoice", withExtension: nil))
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let folder = directory.appendingPathComponent("BTOBInvoice")
        try FileManager.default.copyItem(at: source, to: folder)
        let invoice = try JSONDecoder().decode(ERPInvoice.self, from: Data(contentsOf: folder.appendingPathComponent("invoice.json")))
        let header = try CapturedXML.parse(Data(contentsOf: folder.appendingPathComponent("invoice.xml")))
        let name = try #require(header["razonSocialComprador"]?.first)
        let identification = try #require(header["identificacionComprador"]?.first)
        let email = "cliente-sintetico@example.invalid"
        func writeContact(_ id: UUID, address: String) throws {
            let customer = ERPParty(id: id, name: name, identificationType: "RUC", identificationNumber: identification,
                                    email: email, phone: "0000000000", address: address)
            try JSONEncoder().encode(customer).write(to: folder.appendingPathComponent("customer.json"), options: .atomic)
        }
        try writeContact(invoice.partyId, address: "Dirección sintética A")
        let line = try #require(invoice.lines.first)
        let catalogProduct = ERPProduct(id: try #require(line.productId), name: "Servicio del catálogo",
            code: try #require(header["codigoPrincipal"]?.first), unitPrice: 25, taxCategoryId: UUID())
        let productFile = folder.appendingPathComponent("product.json")
        let categoryFile = folder.appendingPathComponent("tax-categories.json")
        let validTax = ERPTaxCategory(id: catalogProduct.taxCategoryId, sriCode: line.taxCode, name: "Tarifa de prueba",
                                      rate: line.taxRate, validFrom: invoice.issueDate, validTo: invoice.issueDate)
        let encoder = JSONEncoder()
        // A private export must contain the product and its actual tax category, never a reconstructed default.
        #expect(throws: (any Error).self) { try BTOBTestFixture(demoDirectory: directory) }
        try encoder.encode(catalogProduct).write(to: productFile, options: .atomic)
        #expect(throws: (any Error).self) { try BTOBTestFixture(demoDirectory: directory) }
        let invalidCategories = [
            ERPTaxCategory(id: UUID(), sriCode: line.taxCode, name: "Ajena", rate: line.taxRate, validFrom: "2020-01-01"),
            ERPTaxCategory(id: validTax.id, sriCode: "ajeno", name: "Otra", rate: line.taxRate, validFrom: "2020-01-01"),
            ERPTaxCategory(id: validTax.id, sriCode: line.taxCode, name: "Otra tarifa", rate: line.taxRate + 1, validFrom: "2020-01-01"),
            ERPTaxCategory(id: validTax.id, sriCode: line.taxCode, name: "Sin vigencia", rate: line.taxRate, validFrom: "2020-01-01", validTo: "2020-01-02"),
            ERPTaxCategory(id: validTax.id, sriCode: line.taxCode, name: "Futura", rate: line.taxRate, validFrom: "2099-01-01"),
            ERPTaxCategory(id: validTax.id, sriCode: line.taxCode, name: "Inactiva", rate: line.taxRate, validFrom: "2020-01-01", active: false)
        ]
        for invalid in invalidCategories {
            try encoder.encode([invalid]).write(to: categoryFile, options: .atomic)
            #expect(throws: ERPClientError.invalidResponse) { try BTOBTestFixture(demoDirectory: directory) }
        }
        try encoder.encode([validTax]).write(to: categoryFile, options: .atomic)
        try FileManager.default.removeItem(at: productFile)
        #expect(throws: (any Error).self) { try BTOBTestFixture(demoDirectory: directory) }
        try encoder.encode(catalogProduct).write(to: productFile, options: .atomic)
        let xmlFile = folder.appendingPathComponent("invoice.xml")
        let originalXML = try String(contentsOf: xmlFile, encoding: .utf8)
        let inconsistentXML = originalXML.replacingOccurrences(of: "<fechaEmision>19/11/2026</fechaEmision>", with: "<fechaEmision>20/11/2026</fechaEmision>")
        #expect(inconsistentXML != originalXML)
        try inconsistentXML.write(to: xmlFile, atomically: true, encoding: .utf8)
        #expect(throws: ERPClientError.invalidResponse) { try BTOBTestFixture(demoDirectory: directory) }
        try originalXML.write(to: xmlFile, atomically: true, encoding: .utf8)
        let api = DemoERPService(company: .btobSandbox, testDeliveryDirectory: directory)
        #expect(try await api.products(query: "").first == catalogProduct)
        #expect(try await api.invoiceSetup().taxCategories == [validTax])
        let contact = try #require(try await api.customers(query: identification).first)
        #expect(contact.id == invoice.partyId && contact.email == email && contact.address == "Dirección sintética A")
        let draft = try #require(try await api.invoices(query: "", status: "DRAFT").first)
        #expect(draft.id == invoice.id && draft.partyId == contact.id)
        _ = try await api.issueTestInvoice(invoiceID: draft.id, idempotencyKey: UUID().uuidString)
        try await Task.sleep(for: .milliseconds(800))
        let receipt = try await api.sendTestEmail(invoiceID: draft.id, recipient: mailbox, idempotencyKey: UUID().uuidString)
        #expect(receipt.recipient == mailbox && receipt.recipient != contact.email)
        let reopened = DemoERPService(company: .btobSandbox, testDeliveryDirectory: directory)
        #expect(try await reopened.testActions(invoiceID: draft.id).emailReceipt == receipt)
        let onlyReader = DemoERPService(company: .btobSandbox, readOnly: true, testDeliveryDirectory: directory)
        #expect(try await onlyReader.customers(query: "").allSatisfy { $0.id != contact.id })
        let other = DemoERPService(company: .secondary, testDeliveryDirectory: directory)
        await #expect(throws: ERPClientError.notFound) { try await other.invoice(id: draft.id) }
        try writeContact(invoice.partyId, address: "Dirección sintética B")
        let replacement = DemoERPService(company: .btobSandbox, testDeliveryDirectory: directory)
        #expect(try await replacement.testActions(invoiceID: draft.id).emailReceipt == nil)
        #expect(try await replacement.customers(query: "").first?.address == "Dirección sintética B")
        try writeContact(UUID(), address: "Contacto distinto")
        let mismatched = DemoERPService(company: .btobSandbox, testDeliveryDirectory: directory)
        await #expect(throws: ERPClientError.invalidResponse) { try await mismatched.context() }
        await #expect(throws: ERPClientError.invalidResponse) { try await mismatched.invoices(query: "", status: nil) }
    }
}

@Suite("Registro de clientes por identificación")
struct CustomerRegistrationTests {
    private let input = ERPCustomerRegistrationInput(identificationType: "RUC", identificationNumber: "1790000000001",
        name: "Cliente de prueba", address: "Dirección ficticia", email: "cliente@example.invalid")

    @Test func scopedRegistrationAndLookupKeepIdentificationOutOfURLs() async throws {
        let party = ERPParty(id: UUID(), name: input.name, identificationType: input.identificationType,
                             identificationNumber: input.identificationNumber, email: input.email, address: input.address)
        let body = try JSONEncoder().encode(party)
        let http = MockHTTP([ERPHTTPResponse(statusCode: 404, data: Data()), ERPHTTPResponse(statusCode: 201, data: body), ok(body)])
        let live = try service(http)
        #expect(try await live.findCustomer(identificationType: input.identificationType, identificationNumber: input.identificationNumber) == nil)
        let key = UUID().uuidString
        #expect(try await live.createCustomer(input, idempotencyKey: key) == party)
        #expect(try await live.findCustomer(identificationType: input.identificationType, identificationNumber: input.identificationNumber) == party)
        let requests = await http.captured()
        #expect(requests.map { $0.url?.path } == ["/api/v1/customers/lookup", "/api/v1/customers", "/api/v1/customers/lookup"])
        #expect(requests.map(\.httpMethod) == ["POST", "POST", "POST"])
        #expect(requests.map { $0.value(forHTTPHeaderField: "Idempotency-Key") } == [nil, key, nil])
        #expect(requests.allSatisfy { $0.url?.query == nil && $0.url?.absoluteString.contains(input.identificationNumber) == false })
        let keyBody = try #require(requests[0].httpBody)
        #expect(try JSONDecoder().decode([String: String].self, from: keyBody) == ["identificationType": "RUC", "identificationNumber": input.identificationNumber])
        let createBody = try #require(requests[1].httpBody)
        let fields = try JSONDecoder().decode([String: String].self, from: createBody)
        #expect(Set(fields.keys) == ["identificationType", "identificationNumber", "name", "address", "email"])
    }

    @Test func conflictsAndAmbiguousCreatesNeedAnExplicitLookup() async throws {
        let http = MockHTTP(events: [.response(ERPHTTPResponse(statusCode: 409, data: Data())),
            .response(ERPHTTPResponse(statusCode: 409, data: Data())), .lostConnection,
            .response(ERPHTTPResponse(statusCode: 403, data: Data()))])
        let live = try service(http)
        await #expect(throws: ERPClientError.customerIdentificationUnavailable) {
            try await live.findCustomer(identificationType: "RUC", identificationNumber: input.identificationNumber)
        }
        await #expect(throws: ERPClientError.customerRegistrationConflict) { try await live.createCustomer(input, idempotencyKey: UUID().uuidString) }
        await #expect(throws: URLError.self) { try await live.createCustomer(input, idempotencyKey: UUID().uuidString) }
        await #expect(throws: ERPClientError.forbidden) { try await live.findCustomer(identificationType: "RUC", identificationNumber: input.identificationNumber) }
        #expect(await http.captured().count == 4)
    }

    @Test func registeredCustomerSurvivesRelaunchAndCanInvoiceWithoutDuplicate() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let first = DemoERPService(company: .btobSandbox, testDeliveryDirectory: directory)
        let second = DemoERPService(company: .btobSandbox, testDeliveryDirectory: directory)
        let key = UUID().uuidString
        async let firstTry = first.createCustomer(input, idempotencyKey: key)
        async let retry = second.createCustomer(input, idempotencyKey: key)
        let (created, repeated) = try await (firstTry, retry)
        #expect(created == repeated)
        let reopened = DemoERPService(company: .btobSandbox, testDeliveryDirectory: directory)
        #expect(try await reopened.customers(query: input.identificationNumber).map(\.id) == [created.id])
        #expect(try await reopened.findCustomer(identificationType: "RUC", identificationNumber: input.identificationNumber) == created)
        var changed = input
        changed.name = "Solicitud distinta"
        await #expect(throws: ERPClientError.customerRegistrationConflict) { try await reopened.createCustomer(changed, idempotencyKey: key) }
        await #expect(throws: ERPClientError.customerRegistrationConflict) { try await reopened.createCustomer(changed, idempotencyKey: UUID().uuidString) }
        let catalog = try #require(try await reopened.products(query: "").first)
        let setup = try await reopened.invoiceSetup()
        let draft = ERPInvoiceInput(customerId: created.id, establishmentId: setup.establishments[0].id,
            emissionPointId: setup.emissionPoints[0].id, issueDate: "2026-11-19",
            lines: [ERPInvoiceLineInput(productId: catalog.id, description: catalog.name, quantity: 1,
                                         unitPrice: catalog.unitPrice, taxCode: "0")])
        #expect(try await reopened.createDraft(draft, idempotencyKey: UUID().uuidString).partyId == created.id)
        let other = DemoERPService(company: .secondary, testDeliveryDirectory: directory)
        #expect(try await other.findCustomer(identificationType: "RUC", identificationNumber: input.identificationNumber) == nil)
        let reader = DemoERPService(company: .btobSandbox, readOnly: true, testDeliveryDirectory: directory)
        await #expect(throws: ERPClientError.forbidden) { try await reader.createCustomer(input, idempotencyKey: UUID().uuidString) }
    }

    @Test func rejectsInvalidFieldsWithoutSendingAndAcceptsUserCorrections() async throws {
        let http = MockHTTP([])
        let live = try service(http)
        var edited = input
        edited.identificationNumber = "１２３４５６７８９０１２３"
        await #expect(throws: ERPClientError.self) { try await live.createCustomer(edited, idempotencyKey: UUID().uuidString) }
        edited.identificationType = "cedula"
        edited.identificationNumber = "0100000000"
        edited.email = "correo incorrecto"
        await #expect(throws: ERPClientError.self) { try await live.createCustomer(edited, idempotencyKey: UUID().uuidString) }
        edited.name = "    "
        edited.email = nil
        #expect(throws: ERPClientError.self) { try edited.validated() }
        edited.name = " Nombre corregido "
        #expect(try edited.validated().name == "Nombre corregido")
        #expect(try edited.validated().identificationType == "CEDULA")
        #expect(await http.captured().isEmpty)
    }
}

@Suite("Alta de productos de catálogo")
struct CatalogProductRegistrationTests {
    @Test func scopedReadsAndWritesMatchTheCatalogContract() async throws {
        let input = ERPProductRegistrationInput(code: " AWS-DEMO ", name: "Servicio de prueba",
            unitPrice: Decimal(string: "0.043478")!, taxCategoryId: UUID())
        let product = ERPProduct(id: UUID(), name: input.name, code: "AWS-DEMO", unitPrice: input.unitPrice,
                                 taxCategoryId: input.taxCategoryId)
        let response = try JSONEncoder().encode(product)
        let http = MockHTTP([ERPHTTPResponse(statusCode: 404, data: Data()), ERPHTTPResponse(statusCode: 201, data: response),
                             ok(response), ERPHTTPResponse(statusCode: 409, data: Data()), ERPHTTPResponse(statusCode: 409, data: Data())])
        let live = try service(http)
        let key = UUID().uuidString
        #expect(try await live.findProduct(code: input.code) == nil)
        #expect(try await live.createProduct(input, idempotencyKey: key) == product)
        #expect(try await live.findProduct(code: input.code) == product)
        await #expect(throws: ERPClientError.productCodeUnavailable) { try await live.findProduct(code: input.code) }
        await #expect(throws: ERPClientError.productRegistrationConflict) { try await live.createProduct(input, idempotencyKey: UUID().uuidString) }
        let calls = await http.captured()
        #expect(calls.map { $0.url?.path } == ["/api/v1/catalog-products/lookup", "/api/v1/catalog-products",
                                             "/api/v1/catalog-products/lookup", "/api/v1/catalog-products/lookup", "/api/v1/catalog-products"])
        #expect(calls.allSatisfy { $0.httpMethod == "POST" && $0.url?.query == nil })
        #expect(calls[0].value(forHTTPHeaderField: "Idempotency-Key") == nil)
        #expect(calls[1].value(forHTTPHeaderField: "Idempotency-Key") == key)
        let lookup = try #require(calls[0].httpBody)
        let write = try #require(calls[1].httpBody)
        #expect(try JSONDecoder().decode([String: String].self, from: lookup) == ["code": "AWS-DEMO"])
        #expect(try JSONDecoder().decode([String: String].self, from: write) ==
            ["code": "AWS-DEMO", "name": input.name, "unitPrice": "0.043478", "taxCategoryId": input.taxCategoryId.uuidString])
    }

    @Test func demoCreatesAndReopensProductAtFiveCentsWithoutDuplicatingIt() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let first = DemoERPService(company: .btobSandbox, testDeliveryDirectory: directory)
        let tax = try #require(try await first.invoiceSetup().taxCategories.first)
        let originalProductIDs = try await first.products(query: "AWS").map(\.id)
        let input = ERPProductRegistrationInput(code: "AWS-FICTICIO", name: "Servicio AWS de ejemplo",
                                                unitPrice: Decimal(string: "0.05")!, taxCategoryId: tax.id)
        let second = DemoERPService(company: .btobSandbox, testDeliveryDirectory: directory)
        let key = UUID().uuidString
        async let new = first.createProduct(input, idempotencyKey: key)
        async let replay = second.createProduct(input, idempotencyKey: key)
        let (created, again) = try await (new, replay)
        #expect(created == again)
        let reopened = DemoERPService(company: .btobSandbox, testDeliveryDirectory: directory)
        #expect(try await reopened.findProduct(code: input.code) == created)
        #expect(try await reopened.findProduct(code: input.code.lowercased()) == nil)
        let matchingIDs = try await reopened.products(query: "AWS").map(\.id)
        #expect(matchingIDs.count == originalProductIDs.count + 1)
        #expect(Set(matchingIDs) == Set(originalProductIDs + [created.id]))
        var changed = input
        changed.unitPrice = 3
        await #expect(throws: ERPClientError.productRegistrationConflict) { try await reopened.createProduct(changed, idempotencyKey: key) }
        await #expect(throws: ERPClientError.productRegistrationConflict) { try await reopened.createProduct(input, idempotencyKey: UUID().uuidString) }
        let line = ERPInvoiceLineInput(productId: created.id, description: created.name, quantity: 1,
                                       unitPrice: created.unitPrice, taxCode: tax.sriCode)
        let preview = try await reopened.preview(ERPPreviewInput(issueDate: "2026-11-19", lines: [line]))
        #expect(preview.total == input.unitPrice)
        #expect(preview.lines.first?.description == input.name)
        #expect(preview.lines.first?.taxRate == tax.rate)
        let other = DemoERPService(company: .primary, testDeliveryDirectory: directory)
        #expect(try await other.findProduct(code: input.code) == nil)
        await #expect(throws: ERPClientError.self) { try await other.createProduct(input, idempotencyKey: UUID().uuidString) }
        let reader = DemoERPService(company: .btobSandbox, readOnly: true, testDeliveryDirectory: directory)
        await #expect(throws: ERPClientError.forbidden) { try await reader.createProduct(input, idempotencyKey: key) }
    }

    @Test func invalidPricesAndUncertainCreateNeverSendAnotherPost() async throws {
        var input = ERPProductRegistrationInput(code: "TEST", name: "Producto", unitPrice: 0, taxCategoryId: UUID())
        let http = MockHTTP(events: [.lostConnection, .response(ERPHTTPResponse(statusCode: 401, data: Data()))])
        let api = try service(http)
        for price in ["-1", "1.0000001", "1000000000000"] {
            input.unitPrice = try #require(Decimal(string: price))
            await #expect(throws: ERPClientError.self) { try await api.createProduct(input, idempotencyKey: UUID().uuidString) }
        }
        #expect(await http.captured().isEmpty)
        input.unitPrice = 0
        await #expect(throws: URLError.self) { try await api.createProduct(input, idempotencyKey: UUID().uuidString) }
        await #expect(throws: ERPClientError.authenticationRequired) { try await api.createProduct(input, idempotencyKey: UUID().uuidString) }
        #expect(await http.captured().count == 2)
    }
}

extension ERPClientTests {
    @Test func validationResponseNamesTheLineWithoutEchoingSubmittedValues() async throws {
        let body = Data(#"{"detail":[{"loc":["body","lines",1,"quantity"],"input":"private value","msg":"internal reason"}]}"#.utf8)
        let api = try service(MockHTTP([ERPHTTPResponse(statusCode: 422, data: body)]))
        await #expect(throws: ERPClientError.invalidInput("Línea 2. Escribe una cantidad mayor que cero.")) {
            try await api.context()
        }
    }

    @Test func unknownValidationFieldsShowSafeGuidance() async throws {
        let body = Data(#"{"detail":[{"loc":["body","unknown"],"msg":"private detail"}]}"#.utf8)
        let api = try service(MockHTTP([ERPHTTPResponse(statusCode: 400, data: body)]))
        await #expect(throws: ERPClientError.invalidInput("IAERP rechazó los datos. Revisa los campos del formulario antes de volver a enviarlo.")) {
            try await api.context()
        }
    }
}

@Suite("Emisión y correo de producción")
struct ProductionInvoiceDeliveryTests {
    private let invoiceID = UUID()
    private let key = UUID().uuidString
    private let recipient = "ventas@example.invalid"
    private let digest = String(repeating: "a", count: 64)
    private let attachments = ["FACTURA-001.xml", "FACTURA-001.pdf"]

    private func preview(_ names: [String], recipient: String?, digest: String? = nil) throws -> ERPHTTPResponse {
        var data: [String: Any] = [
            "subject": "Factura 001", "message": "Adjuntamos los documentos.",
            "attachmentNames": names, "previewDigest": digest ?? self.digest,
            "dueDate": "2026-11-19", "paymentTermsDays": 0
        ]
        if let recipient { data["recipient"] = recipient }
        return ok(try JSONSerialization.data(withJSONObject: data))
    }

    private func receipt(_ names: [String], recipient: String, messageId: String = "synthetic-id") -> ERPInvoiceEmailReceipt {
        ERPInvoiceEmailReceipt(messageId: messageId, recipient: recipient, attachmentNames: names)
    }

    private func deliveryStatus(_ status: String, environment: String = "PRODUCTION",
                                receipt: ERPInvoiceEmailReceipt? = nil) throws -> ERPHTTPResponse {
        var data: [String: Any] = ["emailStatus": status, "fiscalEnvironment": environment]
        if let receipt { data["receipt"] = try JSONSerialization.jsonObject(with: JSONEncoder().encode(receipt)) }
        return ok(try JSONSerialization.data(withJSONObject: data))
    }

    @Test(arguments: [false, true]) func confirmsExactlyTheCatalogRecipientAndDisclosedDocuments(report: Bool) async throws {
        let names = attachments + (report ? ["INFORME-MENSUAL.pdf"] : [])
        let sent = receipt(names, recipient: recipient)
        let operationID = UUID()
        let http = try MockHTTP([
            deliveryStatus("NOT_SENT"),
            ERPHTTPResponse(statusCode: 202, data: JSONSerialization.data(withJSONObject: [
                "status": "PROCESSING", "operationId": operationID.uuidString,
                "result": ["sales_document_id": invoiceID.uuidString]
            ])),
            preview(names, recipient: recipient),
            ok(JSONEncoder().encode(sent)),
            deliveryStatus("SENT", receipt: sent)
        ])
        let api = try service(http)
        #expect(try await api.deliveryStatus(invoiceID: invoiceID).emailStatus == "NOT_SENT")
        let issue = try await api.issueInvoice(invoiceID: invoiceID, idempotencyKey: key)
        #expect(issue == ERPInvoiceIssueResult(operationId: operationID, status: "PROCESSING"))
        let reviewed = try await api.invoiceEmailPreview(invoiceID: invoiceID)
        #expect(reviewed.invoiceID == invoiceID)
        #expect(reviewed.attachmentNames == names)
        #expect(try await api.sendInvoiceEmail(invoiceID: invoiceID, recipient: recipient, preview: reviewed,
                                               idempotencyKey: key) == sent)
        #expect(try await api.deliveryStatus(invoiceID: invoiceID).receipt == sent)
        let calls = await http.captured()
        let route = "/api/v1/invoices/\(invoiceID.uuidString)"
        #expect(calls.compactMap { $0.url?.path } == ["delivery-status", "issue", "email-preview", "email", "delivery-status"].map { route + "/" + $0 })
        #expect(calls.map(\.httpMethod) == ["GET", "POST", "GET", "POST", "GET"])
        #expect(calls.map { $0.value(forHTTPHeaderField: "Idempotency-Key") } == [nil, key, nil, key, nil])
        #expect(calls.allSatisfy { $0.url?.query == nil })
        #expect(calls[1].httpBody == nil)
        let body = try #require(calls[3].httpBody)
        #expect(try JSONDecoder().decode([String: String].self, from: body) == ["recipient": recipient, "previewDigest": digest])
    }

    @Test func preventsUnreviewedRecipientInvalidKeyAndCrossInvoiceBeforeSending() async throws {
        let http = try MockHTTP([preview(attachments, recipient: recipient), preview(attachments, recipient: nil)])
        let api = try service(http)
        let reviewed = try await api.invoiceEmailPreview(invoiceID: invoiceID)
        let missing = try await api.invoiceEmailPreview(invoiceID: invoiceID)
        #expect(missing.recipient == nil)
        await #expect(throws: ERPClientError.invoiceEmailPreviewChanged) {
            try await api.sendInvoiceEmail(invoiceID: UUID(), recipient: recipient, preview: reviewed, idempotencyKey: key)
        }
        await #expect(throws: ERPClientError.invoiceEmailPreviewChanged) {
            try await api.sendInvoiceEmail(invoiceID: invoiceID, recipient: "otro@example.invalid", preview: reviewed, idempotencyKey: key)
        }
        await #expect(throws: ERPClientError.invoiceEmailPreviewChanged) {
            try await api.sendInvoiceEmail(invoiceID: invoiceID, recipient: recipient, preview: missing, idempotencyKey: key)
        }
        await #expect(throws: ERPClientError.self) {
            try await api.sendInvoiceEmail(invoiceID: invoiceID, recipient: recipient, preview: reviewed, idempotencyKey: "invalid")
        }
        await #expect(throws: ERPClientError.self) { try await api.issueInvoice(invoiceID: invoiceID, idempotencyKey: "invalid") }
        #expect(await http.captured().map(\.httpMethod) == ["GET", "GET"])
    }

    @Test func rejectsIncompleteOrChangedServerEvidence() async throws {
        let names = attachments + ["INFORME.pdf"]
        let invalidPreviews = try [
            preview(attachments, recipient: recipient, digest: "a"),
            preview(["RIDE.pdf"], recipient: recipient),
            preview(attachments + ["../private.pdf"], recipient: recipient),
            preview(attachments + ["other.html"], recipient: recipient),
            preview(attachments, recipient: "a@example.invalid, b@example.invalid")
        ]
        let mismatches = [
            receipt(attachments, recipient: recipient), receipt(names, recipient: "otro@example.invalid"),
            receipt(names, recipient: recipient, messageId: "")
        ]
        let http = try MockHTTP(invalidPreviews + [preview(names, recipient: recipient)] +
            mismatches.map { ok(try JSONEncoder().encode($0)) })
        let api = try service(http)
        for _ in invalidPreviews {
            await #expect(throws: ERPClientError.invalidResponse) { try await api.invoiceEmailPreview(invoiceID: invoiceID) }
        }
        let reviewed = try await api.invoiceEmailPreview(invoiceID: invoiceID)
        for _ in mismatches {
            await #expect(throws: ERPClientError.invalidResponse) {
                try await api.sendInvoiceEmail(invoiceID: invoiceID, recipient: recipient, preview: reviewed, idempotencyKey: key)
            }
        }
    }

    @Test func statusRequiresKnownEnvironmentAndConsistentReceipt() async throws {
        let sent = receipt(attachments, recipient: recipient)
        let invalidStatuses = try [
            deliveryStatus("SENT"), deliveryStatus("PENDING", receipt: sent), deliveryStatus("NOT_SENT", receipt: sent),
            deliveryStatus("UNKNOWN"), deliveryStatus("PENDING", environment: "UNKNOWN")
        ]
        let http = try MockHTTP(invalidStatuses + [
            deliveryStatus("PENDING"), deliveryStatus("NOT_SENT", environment: "TEST"),
            deliveryStatus("NOT_SENT", environment: "UNCONFIGURED")
        ])
        let api = try service(http)
        for _ in invalidStatuses {
            await #expect(throws: ERPClientError.invalidResponse) { try await api.deliveryStatus(invoiceID: invoiceID) }
        }
        for environment in ["PRODUCTION", "TEST", "UNCONFIGURED"] {
            #expect(try await api.deliveryStatus(invoiceID: invoiceID).fiscalEnvironment == environment)
        }
    }

    @Test func neverReplaysWritesAfterSessionExpiryTimeoutOrConflict() async throws {
        let conflicts: [(String, ERPClientError)] = [
            ("invoice_email_preview_changed", .invoiceEmailPreviewChanged),
            ("invoice_email_pending", .invoiceEmailDeliveryPending),
            ("invoice_email_key_conflict", .invoiceDeliveryConflict),
            ("private server detail", .invoiceDeliveryConflict)
        ]
        let expired = ERPHTTPResponse(statusCode: 401, data: Data())
        let events: [MockHTTP.Event] = try conflicts.map { detail, _ in
            .response(ERPHTTPResponse(statusCode: 409, data: try JSONEncoder().encode(["detail": detail])))
        }
        let http = try MockHTTP(events: [
            .response(expired), .response(preview(attachments, recipient: recipient)),
            .response(expired), .lostConnection, .response(expired), .lostConnection
        ] + events)
        let tokens = TokenCalls()
        let api = try LiveERPService(baseURL: baseURL, tokenProvider: { await tokens.token($0) }, transport: http)
        let reviewed = try await api.invoiceEmailPreview(invoiceID: invoiceID)
        await #expect(throws: ERPClientError.authenticationRequired) {
            try await api.issueInvoice(invoiceID: invoiceID, idempotencyKey: key)
        }
        await #expect(throws: URLError.self) { try await api.issueInvoice(invoiceID: invoiceID, idempotencyKey: key) }
        await #expect(throws: ERPClientError.authenticationRequired) {
            try await api.sendInvoiceEmail(invoiceID: invoiceID, recipient: recipient, preview: reviewed, idempotencyKey: key)
        }
        await #expect(throws: URLError.self) {
            try await api.sendInvoiceEmail(invoiceID: invoiceID, recipient: recipient, preview: reviewed, idempotencyKey: key)
        }
        for (_, error) in conflicts {
            await #expect(throws: error) {
                try await api.sendInvoiceEmail(invoiceID: invoiceID, recipient: recipient, preview: reviewed, idempotencyKey: key)
            }
        }
        #expect(await http.captured().count == 6 + conflicts.count)
        #expect(await tokens.captured().filter { $0 }.count == 1)
    }
}

extension ProductionInvoiceDeliveryTests {
    @Test func fiscalPreconditionsIdentifyTheFieldOrMissingDocument() async throws {
        let reasons: [(Int, String, String)] = [
            (409, "Signing certificate is not configured", "certificado"),
            (422, "Approve the required monthly report before emailing the invoice", "informe mensual"),
            (422, "Authorized invoice requires both signed XML and RIDE before email", "XML firmado o el RIDE"),
            (422, "Google Workspace must be reconnected", "Google Workspace")
        ]
        for (status, reason, expected) in reasons {
            let body = try JSONEncoder().encode(["detail": reason])
            let response = ERPHTTPResponse(statusCode: status, data: body)
            let error = try #require(ERPClientError.fiscalDeliveryError(response))
            #expect(error.localizedDescription.contains(expected))
        }
        let body = try JSONEncoder().encode(["detail": "invoice_email_rejected"])
        #expect(ERPClientError.fiscalDeliveryError(.init(statusCode: 422, data: body)) == .invoiceEmailRejected)
        #expect(ERPClientError.fiscalDeliveryError(.init(statusCode: 500, data: body)) == nil)
    }
}
