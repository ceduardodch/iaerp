import CryptoKit
import Foundation
import PDFKit

/// A five-cent invoice exported from the test billing service. No network or external references are followed.
struct BTOBTestFixture {
    static let invoiceID = DemoCompany.uuid(2_601)
    static let customerName = "Cliente Facturable"
    static let amount = Decimal(string: "0.05")!
    let companyName: String
    let customer: ERPParty
    let product: ERPProduct
    let taxCategories: [ERPTaxCategory]
    let authorized: ERPInvoice
    let email: ERPTestEmailPreview
    let documents: [ERPDocument]
    let ledgerIdentifier: String

    init(demoDirectory: URL?) throws {
        let fm = FileManager.default
        let imported = demoDirectory?.appendingPathComponent("BTOBInvoice", isDirectory: true)
        let folder: URL
        let isPrivate: Bool
        if let imported, fm.fileExists(atPath: imported.path) {
            let attrs = try imported.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
            guard attrs.isDirectory == true, attrs.isSymbolicLink != true else { throw ERPClientError.invalidResponse }
            folder = imported
            isPrivate = true
        } else {
            guard let url = Bundle.module.url(forResource: "BTOBTestInvoice", withExtension: nil) else {
                throw ERPClientError.invalidResponse
            }
            folder = url
            isPrivate = false
        }

        func read(_ name: String, limit: Int = 262_144) throws -> Data {
            let url = folder.appendingPathComponent(name)
            let attrs = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
            guard attrs.isRegularFile == true, attrs.isSymbolicLink != true, let size = attrs.fileSize,
                  size > 0, size <= limit else { throw ERPClientError.invalidResponse }
            return try Data(contentsOf: url)
        }

        let json = try read("invoice.json")
        let previewJSON = try read("email-preview.json")
        let xml = try read("invoice.xml", limit: 2_097_152)
        let pdf = try read("ride.pdf", limit: 5_242_880)
        let server = try JSONDecoder().decode(ERPInvoice.self, from: json)
        guard server.type == "INVOICE", server.status == "AUTHORIZED",
              server.total == Self.amount, server.subtotal + server.tax == server.total, server.currency == "USD",
              server.lines.count == 1, let line = server.lines.first, line.quantity > 0, line.unitPrice >= 0,
              line.taxRate >= 0, line.discount >= 0, line.baseAmount == server.subtotal, line.taxAmount == server.tax,
              let accessKey = server.accessKey, accessKey.utf8.count == 49, accessKey.utf8.allSatisfy({ (48...57).contains($0) }),
              accessKey.dropFirst(23).first == "1", server.authorizationNumber == accessKey else { throw ERPClientError.invalidResponse }
        let header = try FiscalXMLHeader.parse(xml)
        guard ERPInputValidation.isFiscalDate(server.issueDate) else { throw ERPClientError.invalidResponse }
        let xmlDate = server.issueDate.split(separator: "-").reversed().joined(separator: "/")
        func matches(_ field: String, _ amount: Decimal) -> Bool {
            header[field].flatMap { Decimal(string: $0, locale: Locale(identifier: "en_US_POSIX")) } == amount
        }
        guard let issuer = header["razonSocial"], !issuer.isEmpty,
              let buyer = header["razonSocialComprador"], !buyer.isEmpty,
              let identification = header["identificacionComprador"], !identification.isEmpty,
              header["ambiente"] == "1", header["claveAcceso"] == accessKey, header["fechaEmision"] == xmlDate,
              accessKey.hasPrefix(xmlDate.replacingOccurrences(of: "/", with: "")),
              header["secuencial"] == server.sequential, header["moneda"] == server.currency,
              matches("importeTotal", server.total), matches("totalSinImpuestos", server.subtotal),
              matches("detalle/cantidad", line.quantity), matches("detalle/precioUnitario", line.unitPrice),
              matches("detalle/descuento", line.discount), matches("detalle/precioTotalSinImpuesto", line.baseAmount),
              matches("detalle/tarifa", line.taxRate), matches("detalle/valor", line.taxAmount),
              header["detalle/codigoPorcentaje"] == line.taxCode,
              header["descripcion"] == line.description else { throw ERPClientError.invalidResponse }
        // The same signed access key and buyer must be present in the RIDE that accompanies this XML.
        guard let pdfText = PDFDocument(data: pdf)?.string, pdfText.contains(accessKey),
              pdfText.contains(identification), pdfText.contains(server.sequential),
              pdfText.range(of: #"(?i)VALOR\s+TOTAL\s+(?:USD|\$)?\s*0[.,]05(?:\s|$)"#, options: .regularExpression) != nil
        else { throw ERPClientError.invalidResponse }
        let testName = issuer.localizedCaseInsensitiveContains("prueba") ? issuer : issuer + " · Pruebas"
        companyName = isPrivate ? testName : DemoCompany.btobSandbox.name
        email = try JSONDecoder().decode(ERPTestEmailPreview.self, from: previewJSON)
        try TestDeliveryContract.checkEnvelope(recipient: email.recipient, names: email.attachmentNames)
        guard email.attachmentNames.allSatisfy({ $0.contains(server.sequential) }) else { throw ERPClientError.invalidResponse }
        documents = email.attachmentNames.map { name in
            let isPDF = name.lowercased().hasSuffix(".pdf")
            return ERPDocument(data: isPDF ? pdf : xml, fileName: name, mimeType: isPDF ? "application/pdf" : "application/xml")
        }

        var fingerprint = SHA256()
        for part in [json, previewJSON, xml, pdf] { fingerprint.update(data: part) }
        let productID: UUID
        var productCode: String? = "PRUEBA"
        var catalogPrice = line.unitPrice
        var catalogName = line.description
        var catalogTaxID = DemoCompany.uuid(line.taxRate == 0 ? 2_302 : 2_301)
        var exportedTaxCategories: [ERPTaxCategory]?
        if isPrivate {
            let customerJSON = try read("customer.json")
            customer = try JSONDecoder().decode(ERPParty.self, from: customerJSON)
            guard customer.id == server.partyId, customer.identificationNumber == identification,
                  customer.name == buyer, customer.roles.contains("CUSTOMER") else { throw ERPClientError.invalidResponse }
            let productJSON = try read("product.json")
            let source = try JSONDecoder().decode(ERPProduct.self, from: productJSON)
            guard source.id == line.productId, source.unitPrice >= 0, !source.name.isEmpty
            else { throw ERPClientError.invalidResponse }
            productID = source.id
            productCode = source.code
            catalogPrice = source.unitPrice
            catalogName = source.name
            catalogTaxID = source.taxCategoryId
            let taxesJSON = try read("tax-categories.json")
            let taxes = try JSONDecoder().decode([ERPTaxCategory].self, from: taxesJSON)
            guard Set(taxes.map(\.id)).count == taxes.count,
                  let applied = taxes.first(where: { $0.id == catalogTaxID }),
                  ERPInputValidation.isFiscalDate(applied.validFrom),
                  applied.validTo.map(ERPInputValidation.isFiscalDate) ?? true,
                  applied.isValid(on: server.issueDate),
                  applied.sriCode == line.taxCode, applied.rate == line.taxRate
            else { throw ERPClientError.invalidResponse }
            exportedTaxCategories = taxes.filter(\.active)
            for part in [customerJSON, productJSON, taxesJSON] { fingerprint.update(data: part) }
            var protectedFolder = folder
            var options = URLResourceValues()
            options.isExcludedFromBackup = true
            try protectedFolder.setResourceValues(options)
            #if os(iOS)
            let filenames = ["invoice.json", "email-preview.json", "ride.pdf", "invoice.xml", "customer.json", "product.json", "tax-categories.json"]
            for file in filenames {
                let path = folder.appendingPathComponent(file).path
                if fm.fileExists(atPath: path) { try fm.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: path) }
            }
            #endif
        } else {
            customer = ERPParty(id: DemoCompany.uuid(2_101), name: buyer, identificationType: "RUC",
                                identificationNumber: identification, email: "cliente@example.invalid")
            productID = DemoCompany.uuid(2_201)
        }
        ledgerIdentifier = (isPrivate ? "import-" : "bundle-") + fingerprint.finalize().map { String(format: "%02x", $0) }.joined()
        product = ERPProduct(id: productID, name: catalogName, code: productCode, unitPrice: catalogPrice, taxCategoryId: catalogTaxID)
        taxCategories = exportedTaxCategories ?? [ERPTaxCategory(id: catalogTaxID, sriCode: line.taxCode,
            name: "IVA de prueba", rate: line.taxRate, validFrom: "2020-01-01", validTo: "2099-12-31")]
        authorized = ERPInvoice(id: isPrivate ? server.id : Self.invoiceID, status: server.status,
            sequential: server.sequential, issueDate: server.issueDate, accessKey: accessKey, subtotal: server.subtotal,
            tax: server.tax, total: server.total, currency: server.currency, partyId: customer.id,
            establishmentId: DemoCompany.uuid(2_401), emissionPointId: DemoCompany.uuid(2_501),
            fiscalPolicyVersion: server.fiscalPolicyVersion, authorizationNumber: server.authorizationNumber,
            authorizedAt: server.authorizedAt, sriTransmission: server.sriTransmission, collectionStatus: server.collectionStatus,
            collectionEnabled: server.collectionEnabled,
            lines: [ERPInvoiceLine(id: line.id, lineNumber: line.lineNumber, productId: productID,
                                   description: line.description, quantity: line.quantity, unitPrice: line.unitPrice,
                                   discount: line.discount, baseAmount: line.baseAmount, taxCode: line.taxCode,
                                   taxRate: line.taxRate, taxAmount: line.taxAmount)], installments: server.installments)
    }

    var draft: ERPInvoice {
        var invoice = authorized
        invoice.status = "DRAFT"
        invoice.accessKey = nil
        invoice.authorizationNumber = nil
        invoice.authorizedAt = nil
        invoice.sriTransmission = nil
        return invoice
    }

    func preview(_ input: ERPPreviewInput) throws -> ERPInvoicePreview {
        guard input.lines.count == 1, let line = input.lines.first else {
            throw ERPClientError.fixtureUnsupported
        }
        if let reference = authorized.lines.first, line.quantity == reference.quantity,
           line.unitPrice == reference.unitPrice, line.discount == reference.discount, line.taxCode == reference.taxCode {
            return ERPInvoicePreview(lines: [ERPPreviewLine(description: line.description, quantity: line.quantity,
                unitPrice: reference.unitPrice, discount: reference.discount, baseAmount: reference.baseAmount,
                taxCode: reference.taxCode, taxRate: reference.taxRate, taxAmount: reference.taxAmount, total: authorized.total)],
                subtotal: authorized.subtotal, taxTotal: authorized.tax, total: authorized.total)
        }
        guard ledgerIdentifier.hasPrefix("bundle-"), line.unitPrice == product.unitPrice, line.taxCode == "0",
              line.discount == 0, [Decimal(1), 2, 3].contains(line.quantity) else { throw ERPClientError.fixtureUnsupported }
        let total = line.unitPrice * line.quantity
        return ERPInvoicePreview(lines: [ERPPreviewLine(description: line.description, quantity: line.quantity,
            unitPrice: line.unitPrice, discount: 0, baseAmount: total, taxCode: "0", taxRate: 0, taxAmount: 0,
            total: total)], subtotal: total, taxTotal: 0, total: total)
    }
}

private final class FiscalXMLHeader: NSObject, XMLParserDelegate {
    private var values: [String: String] = [:]
    private var text = ""
    private var path: [String] = []
    private let detailFields: Set<String> = ["cantidad", "precioUnitario", "descuento", "precioTotalSinImpuesto", "tarifa", "valor", "codigoPorcentaje"]
    private let fields: Set<String> = ["razonSocial", "razonSocialComprador", "identificacionComprador", "claveAcceso",
                                       "ambiente", "secuencial", "fechaEmision", "moneda", "importeTotal", "totalSinImpuestos", "descripcion"]

    static func parse(_ data: Data) throws -> [String: String] {
        // Billing exports UTF-8 XML. Disallow DTDs and external entities in imported dossiers.
        guard let string = String(data: data, encoding: .utf8), !string.contains("<!DOCTYPE") else {
            throw ERPClientError.invalidResponse
        }
        let header = FiscalXMLHeader()
        let parser = XMLParser(data: data)
        parser.shouldResolveExternalEntities = false
        parser.delegate = header
        guard parser.parse() else { throw ERPClientError.invalidResponse }
        return header.values
    }

    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?,
                qualifiedName qName: String?, attributes attributeDict: [String: String] = [:]) { text = ""; path.append(elementName) }
    func parser(_ parser: XMLParser, foundCharacters string: String) { text += string }
    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName qName: String?) {
        let isDetail = path.contains("detalle") && detailFields.contains(elementName)
        if fields.contains(elementName) || isDetail {
            let key = isDetail ? "detalle/" + elementName : elementName
            guard values[key] == nil else { parser.abortParsing(); return }
            values[key] = text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        _ = path.popLast()
        text = ""
    }
}
