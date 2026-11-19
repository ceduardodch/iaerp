import Foundation
import CryptoKit

public enum DemoCompany: String, CaseIterable, Identifiable, Sendable {
    case primary, secondary, btobSandbox
    public var id: String { rawValue }
    public var name: String {
        switch self {
        case .primary: "Empresa de prueba"
        case .secondary: "Segunda empresa de prueba"
        case .btobSandbox: "BTOB-SAS · Pruebas"
        }
    }
    public var alias: String {
        switch self {
        case .primary: "demo-a"
        case .secondary: "demo-b"
        case .btobSandbox: "btob-sas"
        }
    }
    public var tenantId: UUID { Self.uuid(offset / 1_000 + 1) }
    static func uuid(_ suffix: Int) -> UUID { UUID(uuidString: String(format: "00000000-0000-4000-8000-%012d", suffix))! }
    var offset: Int {
        switch self {
        case .primary: 0
        case .secondary: 1_000
        case .btobSandbox: 2_000
        }
    }
}

/// In-memory fixtures, not a fiscal engine. Each instance belongs to one demo company.
public actor DemoERPService: ERPService, ERPSalesOverviewService, ERPTestInvoiceService, ERPCustomerRegistrationService, ERPCatalogProductRegistrationService {
    public let company: DemoCompany
    public let readOnly: Bool
    private var drafts: [ERPInvoice] = []
    private var savedRequests: [String: (Data, ERPInvoice)] = [:]
    private let btobFixture: Result<BTOBTestFixture, Error>?
    private let testDelivery: DemoTestDeliveryStore
    private let masterCatalog: DemoTestDeliveryStore
    private let rejectTestIssues: Bool

    public init(company: DemoCompany = .primary, readOnly: Bool = false,
                testDeliveryDirectory: URL? = nil, rejectTestIssues: Bool = false) {
        self.company = company
        self.readOnly = readOnly
        self.rejectTestIssues = rejectTestIssues
        let source: Result<BTOBTestFixture, Error>? = company == .btobSandbox
            ? Result { try BTOBTestFixture(demoDirectory: readOnly ? nil : testDeliveryDirectory) } : nil
        self.btobFixture = source
        let variant: String
        switch source {
        case .failure: variant = "-invalid"
        case .success(let fixture): variant = "-" + fixture.ledgerIdentifier
        case nil: variant = ""
        }
        let profile = "\(company.rawValue)-\(readOnly ? "reader" : "billing")"
        let file = testDeliveryDirectory?.appendingPathComponent(profile + variant + ".json")
        self.testDelivery = DemoTestDeliveryStore(file: file)
        // Customers belong to the same company/profile across different test invoices.
        // Separate imported customer records from the public demo and its synthetic fixtures.
        let catalog = variant.hasPrefix("-import-") ? "-private-customers" : "-customers"
        self.masterCatalog = DemoTestDeliveryStore(file: testDeliveryDirectory?.appendingPathComponent(profile + catalog + ".json"))
    }

    public func context() throws -> ERPContext {
        let name = try btobFixture?.get().companyName ?? company.name
        return ERPContext(tenantId: company.tenantId, ruc: "DEMO-SIN-RUC", name: name,
                   roles: [readOnly ? "READER" : "BILLING"], scopes: ["context:read", "memberships:read", "organization:read", "parties:read", "products:read", "invoices:read"] + (readOnly ? [] : ["invoices:write", "receivables:read", "invoices:test-issue", "invoices:test-email", "customers:create", "products:create"]))
    }
    public func memberships() throws -> [ERPMembership] {
        (company == .btobSandbox ? [DemoCompany.btobSandbox] : [.primary, .secondary]).map { ERPMembership(tenantId: $0.tenantId, organizationId: $0.alias, ruc: "DEMO-SIN-RUC", tenantName: $0.name, roles: [readOnly ? "READER" : "BILLING"], active: true) }
    }
    public func customers(query: String) throws -> [ERPParty] {
        let saved = try masterCatalog.read().customerRequests?.values.map(\.party).sorted {
            $0.name.localizedStandardCompare($1.name) == .orderedAscending
        } ?? []
        if let fixture = try btobFixture?.get() {
            return filter([fixture.customer] + saved, query: query) { [$0.name, $0.identificationNumber, $0.address ?? ""] }
        }
        let suffix = company.offset
        let names: [String] = switch company {
        case .primary: ["Cliente de ejemplo Álamo", "Cliente de ejemplo Costa", "Cliente de ejemplo Sierra"]
        case .secondary: ["Cliente de ejemplo Río", "Cliente de ejemplo Bosque", "Cliente de ejemplo Cumbre"]
        case .btobSandbox: []
        }
        let cities = ["Quito", "Guayaquil", "Cuenca"]
        let values = names.enumerated().map { index, name in
            ERPParty(id: DemoCompany.uuid(suffix + 101 + index), name: name, identificationType: "PASSPORT", identificationNumber: "DEMO-\(company.alias)-\(index + 1)", email: "cliente\(index + 1)@example.invalid", address: cities[index])
        }
        return filter(values + saved, query: query) { [$0.name, $0.identificationNumber, $0.address ?? ""] }
    }
    public func findCustomer(identificationType: String, identificationNumber: String) throws -> ERPParty? {
        guard !readOnly else { throw ERPClientError.forbidden }
        let id = try CustomerIdentification(type: identificationType, number: identificationNumber)
        return try customers(query: "").first(where: id.matches)
    }

    public func createCustomer(_ input: ERPCustomerRegistrationInput, idempotencyKey: String) throws -> ERPParty {
        guard !readOnly else { throw ERPClientError.forbidden }
        try ERPInputValidation.validateUUIDKey(idempotencyKey)
        let data = try input.validated()
        let id = try CustomerIdentification(type: data.identificationType, number: data.identificationNumber)
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        let digest = Data(SHA256.hash(data: try encoder.encode(data)))
        let existing = try customers(query: "").first(where: id.matches)
        return try masterCatalog.update { ledger in
            var records = ledger.customerRequests ?? [:]
            if let previous = records[idempotencyKey] {
                guard previous.requestDigest == digest else { throw ERPClientError.customerRegistrationConflict }
                return previous.party
            }
            guard existing == nil, !records.values.contains(where: { id.matches($0.party) }) else {
                throw ERPClientError.customerRegistrationConflict
            }
            let party = ERPParty(id: UUID(), name: data.name, identificationType: data.identificationType,
                                 identificationNumber: data.identificationNumber, email: data.email, address: data.address)
            records[idempotencyKey] = DemoCustomerRegistration(requestDigest: digest, party: party)
            ledger.customerRequests = records
            return party
        }
    }

    public func products(query: String) throws -> [ERPProduct] {
        let registered = try masterCatalog.read().productRequests?.values.map(\.product).sorted {
            $0.name.localizedStandardCompare($1.name) == .orderedAscending
        } ?? []
        if let fixture = try btobFixture?.get() {
            return filter([fixture.product] + registered, query: query) { [$0.name, $0.code ?? ""] }
        }
        let values = [
            ERPProduct(id: DemoCompany.uuid(company.offset + 201), name: "Servicio de ejemplo", code: "DEMO-SERV", unitPrice: 100, taxCategoryId: DemoCompany.uuid(company.offset + 301)),
            ERPProduct(id: DemoCompany.uuid(company.offset + 202), name: "Soporte de ejemplo", code: "DEMO-SOP", unitPrice: 50, taxCategoryId: DemoCompany.uuid(company.offset + 302)),
        ]
        return filter(values + registered, query: query) { [$0.name, $0.code ?? ""] }
    }
    public func findProduct(code: String) throws -> ERPProduct? {
        guard !readOnly else { throw ERPClientError.forbidden }
        let exact = try ERPProductRegistrationInput.validatedCode(code)
        return try products(query: "").first { $0.code == exact }
    }

    public func createProduct(_ input: ERPProductRegistrationInput, idempotencyKey: String) throws -> ERPProduct {
        guard !readOnly else { throw ERPClientError.forbidden }
        try ERPInputValidation.validateUUIDKey(idempotencyKey)
        let input = try input.validated()
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "America/Guayaquil")
        formatter.dateFormat = "yyyy-MM-dd"
        let today = formatter.string(from: Date())
        guard try invoiceSetup().taxCategories.contains(where: { $0.id == input.taxCategoryId && $0.isValid(on: today) }) else {
            throw ERPClientError.invalidInput("Selecciona una tarifa vigente de esta empresa.")
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        let digest = Data(SHA256.hash(data: try encoder.encode(input)))
        let existing = try findProduct(code: input.code)
        return try masterCatalog.update { ledger in
            var records = ledger.productRequests ?? [:]
            if let previous = records[idempotencyKey] {
                guard previous.requestDigest == digest else { throw ERPClientError.productRegistrationConflict }
                return previous.product
            }
            guard existing == nil, !records.values.contains(where: { $0.product.code == input.code }) else {
                throw ERPClientError.productRegistrationConflict
            }
            let item = ERPProduct(id: UUID(), name: input.name, code: input.code, unitPrice: input.unitPrice,
                                  taxCategoryId: input.taxCategoryId)
            records[idempotencyKey] = DemoProductRegistration(requestDigest: digest, product: item)
            ledger.productRequests = records
            return item
        }
    }

    public func invoiceSetup() throws -> ERPInvoiceSetup {
        let establishment = ERPEstablishment(id: DemoCompany.uuid(company.offset + 401), code: "001", name: "Oficina de prueba", address: "Dirección ficticia")
        if let fixture = try btobFixture?.get() {
            return ERPInvoiceSetup(establishments: [establishment],
                emissionPoints: [ERPEmissionPoint(id: DemoCompany.uuid(company.offset + 501), establishmentId: establishment.id, code: "001")],
                taxCategories: fixture.taxCategories)
        }
        return ERPInvoiceSetup(establishments: [establishment], emissionPoints: [ERPEmissionPoint(id: DemoCompany.uuid(company.offset + 501), establishmentId: establishment.id, code: "001")], taxCategories: [
            ERPTaxCategory(id: DemoCompany.uuid(company.offset + 301), sriCode: "4", name: "Impuesto de ejemplo 15 %", rate: 15, validFrom: "2020-01-01", validTo: "2099-12-31"),
            ERPTaxCategory(id: DemoCompany.uuid(company.offset + 302), sriCode: "0", name: "Impuesto de ejemplo 0 %", rate: 0, validFrom: "2020-01-01", validTo: "2099-12-31"),
        ])
    }
    public func invoices(query: String, status: String?) throws -> [ERPInvoice] {
        let ledger = try testDelivery.read()
        var all = try Array(drafts.reversed()) + seedInvoices()
        let ids = Set(all.map(\.id))
        all += ledger.issues.values.map(\.source).filter { !ids.contains($0.id) }
        all = all.map { ledger.issues[$0.id]?.current ?? $0 }
        let matchingStatus = all.filter { status == nil || status!.isEmpty || $0.status == status }
        return filter(matchingStatus, query: query) { [$0.sequential, "001-001-\($0.sequential)", $0.accessKey ?? ""] }
    }
    public func homeSummary() throws -> ERPHomeSummary {
        guard !readOnly else { throw ERPClientError.forbidden }
        if company == .btobSandbox {
            return ERPHomeSummary(asOf: "2026-11-19", currency: "USD", receivable: 0, overdue: 0, collectedThisMonth: 0)
        }
        let primary = company == .primary
        return ERPHomeSummary(asOf: "2026-11-18", currency: "USD",
                              receivable: Self.decimal(primary ? "350.25" : "80.40"),
                              overdue: Self.decimal(primary ? "100.50" : "0"),
                              collectedThisMonth: Self.decimal(primary ? "230.75" : "40.20"))
    }

    public func invoiceMonths(query: String, status: String?) throws -> [ERPInvoiceMonth] {
        let groups = Dictionary(grouping: try invoices(query: query, status: status)) { String($0.issueDate.prefix(7)) }
        return groups.keys.sorted(by: >).map { month in
            let rows = groups[month, default: []]
            return ERPInvoiceMonth(month: month, count: rows.count, total: rows.reduce(0) { $0 + $1.total }, currency: "USD")
        }
    }

    public func monthPage(_ month: String, currency: String, query: String, status: String?, cursor: String?) throws -> ERPInvoicePage {
        let names = Dictionary(uniqueKeysWithValues: try customers(query: "").map { ($0.id, $0.name) })
        let invoices = try invoices(query: query, status: status)
            .filter { $0.issueDate.hasPrefix(month + "-") && $0.currency == currency }
            .sorted { ($0.issueDate, $0.id.uuidString) > ($1.issueDate, $1.id.uuidString) }
        let start: Int
        if let cursor {
            guard let index = invoices.firstIndex(where: { $0.id.uuidString == cursor }) else { throw ERPClientError.invalidInput("Página no válida.") }
            start = index + 1
        } else { start = 0 }
        let slice = invoices.dropFirst(start).prefix(50)
        let rows = slice.map {
            ERPMonthInvoice(id: $0.id, number: "001-001-\($0.sequential)", customerName: names[$0.partyId] ?? "Cliente de prueba",
                            issueDate: $0.issueDate, status: $0.status, total: $0.total, currency: $0.currency, collectionStatus: $0.collectionStatus)
        }
        return ERPInvoicePage(items: rows, nextCursor: start + rows.count < invoices.count ? rows.last?.id.uuidString : nil)
    }

    public func invoice(id: UUID) throws -> ERPInvoice {
        if let issue = try testDelivery.read().issues[id] { return issue.current }
        guard let value = try (drafts + seedInvoices()).first(where: { $0.id == id }) else { throw ERPClientError.notFound }
        return value
    }

    public func preview(_ input: ERPPreviewInput) throws -> ERPInvoicePreview {
        try ERPInputValidation.validate(input)
        if let fixture = try btobFixture?.get() {
            guard input.lines.count == 1, let line = input.lines.first,
                  let selected = try products(query: "").first(where: { $0.id == line.productId }),
                  try invoiceSetup().taxCategories.contains(where: {
                      $0.id == selected.taxCategoryId && $0.sriCode == line.taxCode && $0.isValid(on: input.issueDate)
                  }) else { throw ERPClientError.fixtureUnsupported }
            return try fixture.preview(input)
        }
        // Approved fixture tables. Editing inputs outside these cases is explicit, never silently recalculated.
        let service = ["1": ("100", "15", "115"), "2": ("200", "30", "230"), "3": ("300", "45", "345")]
        let support = ["1": ("50", "0", "50"), "2": ("100", "0", "100"), "3": ("150", "0", "150")]
        let totals: [String: (String, String, String)] = [
            "1-0": ("100", "15", "115"), "2-0": ("200", "30", "230"), "3-0": ("300", "45", "345"),
            "0-1": ("50", "0", "50"), "0-2": ("100", "0", "100"), "0-3": ("150", "0", "150"),
            "1-1": ("150", "15", "165"), "1-2": ("200", "15", "215"), "1-3": ("250", "15", "265"),
            "2-1": ("250", "30", "280"), "2-2": ("300", "30", "330"), "2-3": ("350", "30", "380"),
            "3-1": ("350", "45", "395"), "3-2": ("400", "45", "445"), "3-3": ("450", "45", "495"),
        ]
        guard input.lines.count <= 2 else { throw ERPClientError.fixtureUnsupported }
        var serviceQuantity = "0", supportQuantity = "0"
        var seen: Set<UUID> = []
        let catalog = try products(query: "")
        let lines = try input.lines.map { line -> ERPPreviewLine in
            guard let productId = line.productId, seen.insert(productId).inserted,
                  let product = catalog.first(where: { $0.id == productId }),
                  product.unitPrice == line.unitPrice, line.discount == 0,
                  (product.taxCategoryId == DemoCompany.uuid(company.offset + 301) && product.unitPrice == 100)
                    || (product.taxCategoryId == DemoCompany.uuid(company.offset + 302) && product.unitPrice == 50)
            else { throw ERPClientError.fixtureUnsupported }
            let quantity = NSDecimalNumber(decimal: line.quantity).stringValue
            let isService = product.taxCategoryId == DemoCompany.uuid(company.offset + 301)
            guard line.taxCode == (isService ? "4" : "0"), let entry = (isService ? service : support)[quantity] else { throw ERPClientError.fixtureUnsupported }
            if isService {
                guard serviceQuantity == "0" else { throw ERPClientError.fixtureUnsupported }
                serviceQuantity = quantity
            } else {
                guard supportQuantity == "0" else { throw ERPClientError.fixtureUnsupported }
                supportQuantity = quantity
            }
            return ERPPreviewLine(description: line.description, quantity: line.quantity, unitPrice: line.unitPrice, discount: 0, baseAmount: Self.decimal(entry.0), taxCode: line.taxCode, taxRate: isService ? 15 : 0, taxAmount: Self.decimal(entry.1), total: Self.decimal(entry.2))
        }
        guard let total = totals["\(serviceQuantity)-\(supportQuantity)"] else { throw ERPClientError.fixtureUnsupported }
        return ERPInvoicePreview(lines: lines, subtotal: Self.decimal(total.0), taxTotal: Self.decimal(total.1), total: Self.decimal(total.2))
    }
    public func createDraft(_ input: ERPInvoiceInput, idempotencyKey: String) throws -> ERPInvoice {
        guard !readOnly else { throw ERPClientError.forbidden }
        guard idempotencyKey.utf8.count >= 16, idempotencyKey.utf8.count <= 128, !idempotencyKey.contains("\r"), !idempotencyKey.contains("\n") else { throw ERPClientError.invalidInput("La operación necesita una clave válida.") }
        let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
        let payload = try encoder.encode(input)
        if let saved = savedRequests[idempotencyKey] {
            guard saved.0 == payload else { throw ERPClientError.idempotencyConflict }
            return saved.1
        }
        let ownCustomers = try customers(query: "")
        let setup = try invoiceSetup()
        guard ownCustomers.contains(where: { $0.id == input.customerId }),
              setup.establishments.contains(where: { $0.id == input.establishmentId }),
              setup.emissionPoints.contains(where: { $0.id == input.emissionPointId && $0.establishmentId == input.establishmentId }) else { throw ERPClientError.notFound }
        guard input.installments.count <= 1, !input.collectionEnabled, input.analyticValueIds.isEmpty else { throw ERPClientError.fixtureUnsupported }
        let preview = try self.preview(ERPPreviewInput(issueDate: input.issueDate, lines: input.lines))
        if let installment = input.installments.first {
            guard installment.amount == preview.total, installment.dueDate >= input.issueDate else { throw ERPClientError.invalidInput("Revisa el vencimiento y el total de la cuota.") }
        }
        // A restarted test workspace may already contain drafts issued in an earlier session.
        let highest = try invoices(query: "", status: nil).compactMap { Int($0.sequential) }.max() ?? 0
        let sequential = max(800, highest + 1)
        let id = UUID()
        let lines = preview.lines.enumerated().map { index, line in
            ERPInvoiceLine(id: DemoCompany.uuid(company.offset + 10_000 + drafts.count * 100 + index), lineNumber: index + 1, productId: input.lines[index].productId, description: line.description, quantity: line.quantity, unitPrice: line.unitPrice, discount: line.discount, baseAmount: line.baseAmount, taxCode: line.taxCode, taxRate: line.taxRate, taxAmount: line.taxAmount)
        }
        let invoice = ERPInvoice(id: id, status: "DRAFT", sequential: String(format: "%09d", sequential), issueDate: input.issueDate, subtotal: preview.subtotal, tax: preview.taxTotal, total: preview.total, partyId: input.customerId, establishmentId: input.establishmentId, emissionPointId: input.emissionPointId, lines: lines, installments: input.installments)
        drafts.append(invoice); savedRequests[idempotencyKey] = (payload, invoice)
        return invoice
    }
    public func artifacts(invoiceID: UUID) throws -> [ERPArtifact] {
        let value = try invoice(id: invoiceID)
        guard ["AUTHORIZED", "HISTORICAL_ISSUED"].contains(value.status) else { return [] }
        let documents = try files(for: value)
        return documents.map { document in
            let isPDF = document.mimeType == "application/pdf"
            return ERPArtifact(id: DemoCompany.uuid(company.offset + 20_000 + (Int(value.sequential) ?? 0) * 2 + (isPDF ? 0 : 1)),
                artifactType: isPDF ? "ride-pdf" : "xml-signed",
                sha256: SHA256.hash(data: document.data).map { String(format: "%02x", $0) }.joined(),
                version: 1, createdAt: value.authorizedAt ?? value.issueDate)
        }
    }

    public func document(invoiceID: UUID, artifact: ERPArtifact) throws -> ERPDocument {
        let value = try invoice(id: invoiceID)
        guard try artifacts(invoiceID: invoiceID).contains(artifact),
              let file = try files(for: value).first(where: {
                  $0.mimeType == (artifact.artifactType == "ride-pdf" ? "application/pdf" : "application/xml")
              }) else { throw ERPClientError.notFound }
        return file
    }

    private func files(for invoice: ERPInvoice) throws -> [ERPDocument] {
        if let fixture = try btobFixture?.get(), invoice.id == fixture.authorized.id {
            guard invoice == fixture.authorized else { throw ERPClientError.invalidResponse }
            return fixture.documents
        }
        let ledger = try testDelivery.read()
        if let captured = ledger.captures[invoice.id] { return captured.attachments }
        if let files = ledger.files?[invoice.id] { return files }
        let customer = try customers(query: "").first(where: { $0.id == invoice.partyId })
        guard let customer else { throw ERPClientError.notFound }
        let files = try DemoInvoiceDocuments.render(invoice: invoice, company: company.name, customer: customer.name)
        return try testDelivery.update { ledger in
            if let files = ledger.files?[invoice.id] { return files }
            if ledger.files == nil { ledger.files = [:] }
            ledger.files?[invoice.id] = files
            return files
        }
    }

    public func testActions(invoiceID: UUID) throws -> ERPTestInvoiceActions {
        let invoice = try invoice(id: invoiceID)
        let receipt = try testDelivery.read().captures[invoiceID]?.receipt
        return ERPTestInvoiceActions(environment: "TEST", transmissionMode: "simulator",
            canIssue: !readOnly && invoice.status == "DRAFT",
            canEmail: !readOnly && invoice.status == "AUTHORIZED" && receipt == nil,
            captureRecipient: TestDeliveryContract.mailbox, emailReceipt: receipt)
    }

    public func issueTestInvoice(invoiceID: UUID, idempotencyKey: String) throws -> ERPTestIssueResult {
        guard !readOnly else { throw ERPClientError.forbidden }
        try ERPInputValidation.validateUUIDKey(idempotencyKey)
        let source = try invoice(id: invoiceID)
        let captured = try btobFixture?.get().authorized
        let replay = captured?.id == invoiceID ? captured : nil
        return try testDelivery.update { ledger in
            if let existing = ledger.issues[invoiceID], existing.key == idempotencyKey {
                return existing.operation
            }
            guard ledger.issues[invoiceID] == nil, source.status == "DRAFT",
                  !ledger.issues.values.contains(where: { $0.key == idempotencyKey }) else {
                throw ERPClientError.idempotencyConflict
            }
            let issue = DemoTestIssue(key: idempotencyKey, operationID: UUID(), source: source,
                                      readyAt: Date().addingTimeInterval(0.75), reject: rejectTestIssues, authorizedReplay: replay)
            ledger.issues[invoiceID] = issue
            return issue.operation
        }
    }

    public func testEmailPreview(invoiceID: UUID) throws -> ERPTestEmailPreview {
        guard !readOnly else { throw ERPClientError.forbidden }
        let invoice = try invoice(id: invoiceID)
        guard invoice.status == "AUTHORIZED" else { throw ERPClientError.invalidInput("La factura necesita autorización de pruebas.") }
        if let fixture = try btobFixture?.get(), invoiceID == fixture.authorized.id {
            guard fixture.authorized == invoice else { throw ERPClientError.invalidResponse }
            return fixture.email
        }
        let names = try files(for: invoice).map(\.fileName)
        try TestDeliveryContract.checkEnvelope(recipient: TestDeliveryContract.mailbox, names: names)
        return ERPTestEmailPreview(recipient: TestDeliveryContract.mailbox,
            subject: "Factura de prueba 001-001-\(invoice.sequential)",
            message: "Adjuntamos el RIDE y el XML del comprobante de prueba.", attachmentNames: names)
    }

    public func sendTestEmail(invoiceID: UUID, recipient: String, idempotencyKey: String) throws -> ERPTestEmailReceipt {
        guard !readOnly, recipient == TestDeliveryContract.mailbox else { throw ERPClientError.forbidden }
        try ERPInputValidation.validateUUIDKey(idempotencyKey)
        let preview = try testEmailPreview(invoiceID: invoiceID)
        let documents = try artifacts(invoiceID: invoiceID).map { try document(invoiceID: invoiceID, artifact: $0) }
        return try testDelivery.update { ledger in
            if let captured = ledger.captures[invoiceID], captured.key == idempotencyKey { return captured.receipt }
            guard ledger.captures[invoiceID] == nil,
                  !ledger.captures.values.contains(where: { $0.key == idempotencyKey }) else {
                throw ERPClientError.idempotencyConflict
            }
            let receipt = ERPTestEmailReceipt(messageId: UUID().uuidString, recipient: recipient,
                                               attachmentNames: documents.map(\.fileName))
            ledger.captures[invoiceID] = DemoCapturedEmail(key: idempotencyKey, subject: preview.subject,
                message: preview.message, attachments: documents, receipt: receipt)
            return receipt
        }
    }

    /// Test mailbox inspection verifies the captured MIME parts against the invoice artifacts.
    func capturedTestEmail(invoiceID: UUID) throws -> DemoCapturedEmail? {
        try testDelivery.read().captures[invoiceID]
    }

    private func seedInvoices() throws -> [ERPInvoice] {
        if let fixture = try btobFixture?.get() { return [fixture.draft] }
        let states = ["AUTHORIZED", "PENDING_AUTHORIZATION", "REJECTED", "DRAFT", "HISTORICAL_ISSUED"]
        return states.enumerated().map { index, status in
            ERPInvoice(id: DemoCompany.uuid(company.offset + 601 + index), status: status, sequential: String(format: "%09d", index + 1), issueDate: index < 3 ? "2026-11-17" : "2026-10-15", accessKey: status == "DRAFT" ? nil : "DEMO-\(company.alias)-\(index + 1)", subtotal: 100, tax: 15, total: 115, partyId: DemoCompany.uuid(company.offset + 101), establishmentId: DemoCompany.uuid(company.offset + 401), emissionPointId: DemoCompany.uuid(company.offset + 501), authorizationNumber: status == "AUTHORIZED" ? "DEMO-SIN-VALIDEZ-FISCAL" : nil, authorizedAt: status == "AUTHORIZED" ? "2026-11-17T12:00:00-05:00" : nil, sriTransmission: status == "PENDING_AUTHORIZATION" ? ERPSRITransmission(status: status, message: "Respuesta ficticia pendiente.", lastAttemptAt: "2026-11-17T12:00:00-05:00") : nil, collectionStatus: status == "AUTHORIZED" ? "OPEN" : nil, lines: [ERPInvoiceLine(id: DemoCompany.uuid(company.offset + 30_000 + index), lineNumber: 1, productId: DemoCompany.uuid(company.offset + 201), description: "Servicio de ejemplo", quantity: 1, unitPrice: 100, discount: 0, baseAmount: 100, taxCode: "4", taxRate: 15, taxAmount: 15)])
        }
    }
    private static func decimal(_ text: String) -> Decimal { Decimal(string: text, locale: Locale(identifier: "en_US_POSIX"))! }
    private func filter<T>(_ values: [T], query: String, fields: (T) -> [String]) -> [T] {
        let term = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !term.isEmpty else { return values }
        return values.filter { value in fields(value).contains { $0.range(of: term, options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "es_EC")) != nil } }
    }
}
