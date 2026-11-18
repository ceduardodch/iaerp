import Foundation
import CryptoKit

public enum DemoCompany: String, CaseIterable, Identifiable, Sendable {
    case primary, secondary
    public var id: String { rawValue }
    public var name: String { self == .primary ? "Empresa de prueba" : "Segunda empresa de prueba" }
    public var alias: String { self == .primary ? "demo-a" : "demo-b" }
    public var tenantId: UUID { Self.uuid(self == .primary ? 1 : 2) }
    static func uuid(_ suffix: Int) -> UUID { UUID(uuidString: String(format: "00000000-0000-4000-8000-%012d", suffix))! }
    var offset: Int { self == .primary ? 0 : 1_000 }
}

/// In-memory fixtures, not a fiscal engine. Each instance belongs to one demo company.
public actor DemoERPService: ERPService {
    public let company: DemoCompany
    public let readOnly: Bool
    private var drafts: [ERPInvoice] = []
    private var savedRequests: [String: (Data, ERPInvoice)] = [:]
    public init(company: DemoCompany = .primary, readOnly: Bool = false) { self.company = company; self.readOnly = readOnly }

    public func context() throws -> ERPContext {
        ERPContext(tenantId: company.tenantId, ruc: "DEMO-SIN-RUC", name: company.name,
                   roles: [readOnly ? "READER" : "BILLING"], scopes: ["context:read", "memberships:read", "organization:read", "parties:read", "products:read", "invoices:read"] + (readOnly ? [] : ["invoices:write"]))
    }
    public func memberships() throws -> [ERPMembership] {
        DemoCompany.allCases.map { ERPMembership(tenantId: $0.tenantId, organizationId: $0.alias, ruc: "DEMO-SIN-RUC", tenantName: $0.name, roles: [readOnly ? "READER" : "BILLING"], active: true) }
    }
    public func customers(query: String) throws -> [ERPParty] {
        let suffix = company.offset
        let names = company == .primary ? ["Cliente de ejemplo Álamo", "Cliente de ejemplo Costa", "Cliente de ejemplo Sierra"] : ["Cliente de ejemplo Río", "Cliente de ejemplo Bosque", "Cliente de ejemplo Cumbre"]
        let cities = ["Quito", "Guayaquil", "Cuenca"]
        let values = names.enumerated().map { index, name in
            ERPParty(id: DemoCompany.uuid(suffix + 101 + index), name: name, identificationType: "PASSPORT", identificationNumber: "DEMO-\(company.alias)-\(index + 1)", email: "cliente\(index + 1)@example.invalid", address: cities[index])
        }
        return filter(values, query: query) { [$0.name, $0.identificationNumber, $0.address ?? ""] }
    }
    public func products(query: String) throws -> [ERPProduct] {
        let values = [
            ERPProduct(id: DemoCompany.uuid(company.offset + 201), name: "Servicio de ejemplo", code: "DEMO-SERV", unitPrice: 100, taxCategoryId: DemoCompany.uuid(company.offset + 301)),
            ERPProduct(id: DemoCompany.uuid(company.offset + 202), name: "Soporte de ejemplo", code: "DEMO-SOP", unitPrice: 50, taxCategoryId: DemoCompany.uuid(company.offset + 302)),
        ]
        return filter(values, query: query) { [$0.name, $0.code ?? ""] }
    }
    public func invoiceSetup() throws -> ERPInvoiceSetup {
        let establishment = ERPEstablishment(id: DemoCompany.uuid(company.offset + 401), code: "001", name: "Oficina de prueba", address: "Dirección ficticia")
        return ERPInvoiceSetup(establishments: [establishment], emissionPoints: [ERPEmissionPoint(id: DemoCompany.uuid(company.offset + 501), establishmentId: establishment.id, code: "001")], taxCategories: [
            ERPTaxCategory(id: DemoCompany.uuid(company.offset + 301), sriCode: "4", name: "Impuesto de ejemplo 15 %", rate: 15, validFrom: "2020-01-01", validTo: "2099-12-31"),
            ERPTaxCategory(id: DemoCompany.uuid(company.offset + 302), sriCode: "0", name: "Impuesto de ejemplo 0 %", rate: 0, validFrom: "2020-01-01", validTo: "2099-12-31"),
        ])
    }
    public func invoices(query: String, status: String?) throws -> [ERPInvoice] {
        let all = Array(drafts.reversed()) + seedInvoices()
        let matchingStatus = all.filter { status == nil || status!.isEmpty || $0.status == status }
        return filter(matchingStatus, query: query) { [$0.sequential, $0.accessKey ?? ""] }
    }
    public func invoice(id: UUID) throws -> ERPInvoice {
        guard let value = (drafts + seedInvoices()).first(where: { $0.id == id }) else { throw ERPClientError.notFound }
        return value
    }

    public func preview(_ input: ERPPreviewInput) throws -> ERPInvoicePreview {
        try ERPInputValidation.validate(input)
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
                  product.unitPrice == line.unitPrice, line.discount == 0 else { throw ERPClientError.fixtureUnsupported }
            let quantity = NSDecimalNumber(decimal: line.quantity).stringValue
            let isService = product.id == DemoCompany.uuid(company.offset + 201)
            guard line.taxCode == (isService ? "4" : "0"), let entry = (isService ? service : support)[quantity] else { throw ERPClientError.fixtureUnsupported }
            if isService { serviceQuantity = quantity } else { supportQuantity = quantity }
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
        let id = DemoCompany.uuid(company.offset + 800 + drafts.count)
        let lines = preview.lines.enumerated().map { index, line in
            ERPInvoiceLine(id: DemoCompany.uuid(company.offset + 10_000 + drafts.count * 100 + index), lineNumber: index + 1, productId: input.lines[index].productId, description: line.description, quantity: line.quantity, unitPrice: line.unitPrice, discount: line.discount, baseAmount: line.baseAmount, taxCode: line.taxCode, taxRate: line.taxRate, taxAmount: line.taxAmount)
        }
        let invoice = ERPInvoice(id: id, status: "DRAFT", sequential: String(format: "%09d", 800 + drafts.count), issueDate: input.issueDate, subtotal: preview.subtotal, tax: preview.taxTotal, total: preview.total, partyId: input.customerId, establishmentId: input.establishmentId, emissionPointId: input.emissionPointId, lines: lines, installments: input.installments)
        drafts.append(invoice); savedRequests[idempotencyKey] = (payload, invoice)
        return invoice
    }
    public func artifacts(invoiceID: UUID) throws -> [ERPArtifact] {
        let value = try invoice(id: invoiceID)
        guard ["AUTHORIZED", "HISTORICAL_ISSUED"].contains(value.status) else { return [] }
        var types = ["ride-pdf"]
        if value.status == "AUTHORIZED" { types.append("xml-signed") }
        return types.enumerated().map { index, type in
            let document = makeDocument(value, type: type)
            return ERPArtifact(id: DemoCompany.uuid(company.offset + 20_000 + (value.id == DemoCompany.uuid(company.offset + 605) ? 100 : 0) + index), artifactType: type, sha256: SHA256.hash(data: document.data).map { String(format: "%02x", $0) }.joined(), version: 1, createdAt: "2026-11-17T12:00:00-05:00")
        }
    }
    public func document(invoiceID: UUID, artifact: ERPArtifact) throws -> ERPDocument {
        let value = try invoice(id: invoiceID)
        let values = try artifacts(invoiceID: invoiceID)
        guard values.contains(artifact) else { throw ERPClientError.notFound }
        return makeDocument(value, type: artifact.artifactType)
    }

    private func seedInvoices() -> [ERPInvoice] {
        let states = ["AUTHORIZED", "PENDING_AUTHORIZATION", "REJECTED", "DRAFT", "HISTORICAL_ISSUED"]
        return states.enumerated().map { index, status in
            ERPInvoice(id: DemoCompany.uuid(company.offset + 601 + index), status: status, sequential: String(format: "%09d", index + 1), issueDate: "2026-11-17", accessKey: status == "DRAFT" ? nil : "DEMO-\(company.alias)-\(index + 1)", subtotal: 100, tax: 15, total: 115, partyId: DemoCompany.uuid(company.offset + 101), establishmentId: DemoCompany.uuid(company.offset + 401), emissionPointId: DemoCompany.uuid(company.offset + 501), authorizationNumber: status == "AUTHORIZED" ? "DEMO-SIN-VALIDEZ-FISCAL" : nil, authorizedAt: status == "AUTHORIZED" ? "2026-11-17T12:00:00-05:00" : nil, sriTransmission: status == "PENDING_AUTHORIZATION" ? ERPSRITransmission(status: status, message: "Respuesta ficticia pendiente.", lastAttemptAt: "2026-11-17T12:00:00-05:00") : nil, collectionStatus: status == "AUTHORIZED" ? "OPEN" : nil, lines: [ERPInvoiceLine(id: DemoCompany.uuid(company.offset + 30_000 + index), lineNumber: 1, productId: DemoCompany.uuid(company.offset + 201), description: "Servicio de ejemplo", quantity: 1, unitPrice: 100, discount: 0, baseAmount: 100, taxCode: "4", taxRate: 15, taxAmount: 15)])
        }
    }
    private func makeDocument(_ invoice: ERPInvoice, type: String) -> ERPDocument {
        if type == "ride-pdf" {
            return ERPDocument(data: Self.pdf(sequential: invoice.sequential, secondary: company == .secondary), fileName: "DEMO-\(invoice.sequential).pdf", mimeType: "application/pdf")
        }
        return ERPDocument(data: Data("<?xml version=\"1.0\" encoding=\"UTF-8\"?><documentoDemostracion><aviso>Datos ficticios, sin validez fiscal ni firma real.</aviso><numero>\(invoice.sequential)</numero></documentoDemostracion>".utf8), fileName: "DEMO-\(invoice.sequential).xml", mimeType: "application/xml")
    }
    private static func pdf(sequential: String, secondary: Bool) -> Data {
        let stream = "BT /F1 20 Tf 50 770 Td (IAERP - DEMOSTRACION) Tj /F1 12 Tf 0 -40 Td (Documento ficticio sin validez fiscal.) Tj 0 -25 Td (Empresa de prueba \(secondary ? "B" : "A")) Tj 0 -25 Td (Numero: \(sequential)) Tj 0 -25 Td (Total de ejemplo: USD 115.00) Tj ET"
        let objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", "<< /Length \(stream.utf8.count) >>\nstream\n\(stream)\nendstream"]
        var data = Data("%PDF-1.4\n".utf8), offsets: [Int] = [0]
        for (index, object) in objects.enumerated() {
            offsets.append(data.count); data.append(Data("\(index + 1) 0 obj\n\(object)\nendobj\n".utf8))
        }
        let xref = data.count
        data.append(Data("xref\n0 6\n0000000000 65535 f \n".utf8))
        for offset in offsets.dropFirst() { data.append(Data(String(format: "%010d 00000 n \n", offset).utf8)) }
        data.append(Data("trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n\(xref)\n%%EOF\n".utf8))
        return data
    }
    private static func decimal(_ text: String) -> Decimal { Decimal(string: text, locale: Locale(identifier: "en_US_POSIX"))! }
    private func filter<T>(_ values: [T], query: String, fields: (T) -> [String]) -> [T] {
        let term = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !term.isEmpty else { return values }
        return values.filter { value in fields(value).contains { $0.range(of: term, options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "es_EC")) != nil } }
    }
}
