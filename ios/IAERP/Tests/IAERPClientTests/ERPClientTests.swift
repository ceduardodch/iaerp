import Foundation
import CryptoKit
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
        #expect(document.data.starts(with: Data("%PDF-1.4".utf8)))
        #expect(document.mimeType == "application/pdf")
        #expect(String(decoding: document.data, as: UTF8.self).contains("sin validez fiscal"))
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
