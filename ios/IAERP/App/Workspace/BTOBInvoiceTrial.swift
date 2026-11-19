import CryptoKit
import Foundation
import IAERPClient

/// Only the selected catalog entries travel to the paired development Mac.
struct BTOBTrialSelection: Codable {
    let customer: ERPParty
    let product: ERPProduct
    let tax: ERPTaxCategory

    static func productGuidance(for product: ERPProduct) -> String? {
        guard let code = product.code, !code.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return "Elige un servicio AWS que tenga código de catálogo."
        }
        let catalogEntry = code + " " + product.name
        let pattern = #"(?<![A-Za-z])AWS(?![A-Za-z])|Amazon Web Services"#
        if catalogEntry.range(of: pattern, options: [.regularExpression, .caseInsensitive]) == nil {
            return "Elige un servicio con AWS o Amazon Web Services en el nombre o código."
        }
        return nil
    }

    func matches(customer copy: ERPParty, product item: ERPProduct, invoice: ERPInvoice) -> Bool {
        guard let line = invoice.lines.first, invoice.lines.count == 1 else { return false }
        return customer.identificationType == copy.identificationType &&
            customer.identificationNumber == copy.identificationNumber && customer.name == copy.name &&
            customer.address == copy.address && customer.email == copy.email &&
            product.code == item.code && product.name == item.name && product.unitPrice == item.unitPrice &&
            line.productId == item.id && line.taxCode == tax.sriCode && line.taxRate == tax.rate &&
            invoice.partyId == copy.id && invoice.total == Decimal(string: "0.05") && invoice.currency == "USD"
    }
}

private struct TrialSelectionRejection: Decodable {
    let selectionSHA256: String
    let reason: String
}

struct PreparedBTOBTrial: Decodable {
    static func read(_ data: Data, matching digest: String, selectionFile: URL) throws -> PreparedBTOBTrial? {
        let decoder = JSONDecoder()
        if let rejection = try? decoder.decode(TrialSelectionRejection.self, from: data),
           rejection.selectionSHA256 == digest {
            if ["customerOutsideTrial", "productOutsideTrial"].contains(rejection.reason),
               let current = try? Data(contentsOf: selectionFile),
               SHA256.hash(data: current).map({ String(format: "%02x", $0) }).joined() == digest {
                try FileManager.default.removeItem(at: selectionFile)
            }
            switch rejection.reason {
            case "customerOutsideTrial":
                throw ERPClientError.invalidInput("Este cliente o sus datos no coinciden con el caso preparado en el Mac. Vuelve a la ficha y verifica la identificación, el nombre, la dirección y el correo del cliente de prueba.")
            case "productOutsideTrial":
                throw ERPClientError.invalidInput("Elige un servicio AWS del catálogo para este ensayo.")
            default: break
            }
        }
        guard let ready = try? decoder.decode(Self.self, from: data), ready.selectionSHA256 == digest else { return nil }
        return ready
    }

    let selectionSHA256: String
    let invoiceID: UUID
    let context: ERPContext
    let customer: ERPParty
    let product: ERPProduct
    let tax: ERPTaxCategory
    let draft: ERPInvoice
}

extension WorkspaceStore {
    var canPrepareBTOBTestInvoice: Bool {
        guard phase == .ready, canStartInvoice, context?.permits("products:read") == true else { return false }
        if isDemo { return context?.tenantId == DemoCompany.btobSandbox.tenantId }
        return configuration?.organizationAlias == "btob-sas"
    }

    func prepareBTOBTestInvoice(customer: ERPParty, product: ERPProduct, tax: ERPTaxCategory) async throws {
        guard canPrepareBTOBTestInvoice, product.taxCategoryId == tax.id,
              tax.isValid(on: ERPDisplay.fiscalDate(Date())), customer.roles.contains("CUSTOMER"),
              products.contains(product), setup?.taxCategories.contains(tax) == true else { throw ERPClientError.forbidden }
        if let guidance = BTOBTrialSelection.productGuidance(for: product) {
            throw ERPClientError.invalidInput(guidance)
        }
        let epoch = generation
        let selection = BTOBTrialSelection(customer: customer, product: product, tax: tax)
        if isDemo, let demo = service as? DemoERPService {
            let id = try await matchingInvoice(for: selection, using: demo)
            guard generation == epoch else { throw CancellationError() }
            preparedTrialInvoiceID = id
            return
        }
        let scope = try currentInvoiceRecoveryScope()
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        let digest = SHA256.hash(data: try encoder.encode(scope)).map { String(format: "%02x", $0) }.joined()
        var directory = URL.applicationSupportDirectory.appending(path: "IAERPInvoiceTrials/\(digest)", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                               attributes: [.protectionKey: FileProtectionType.complete])
        var properties = URLResourceValues()
        properties.isExcludedFromBackup = true
        try directory.setResourceValues(properties)
        let selectionFile = directory.appending(path: "selection.json")
        let selectionData = try encoder.encode(selection)
        try selectionData.write(to: selectionFile, options: [.atomic, .completeFileProtection])
        let readyFile = directory.appending(path: "prepared.json")
        let expected = SHA256.hash(data: selectionData).map { String(format: "%02x", $0) }.joined()
        for _ in 0..<60 {
            try Task.checkCancellation()
            guard generation == epoch else { throw CancellationError() }
            if let attrs = try? readyFile.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]),
               attrs.isRegularFile == true, attrs.isSymbolicLink != true, (attrs.fileSize ?? Int.max) < 512_000,
               let content = try? Data(contentsOf: readyFile),
               let prepared = try PreparedBTOBTrial.read(content, matching: expected, selectionFile: selectionFile) {
                guard scope == (try currentInvoiceRecoveryScope()), prepared.invoiceID == prepared.draft.id,
                      prepared.draft.status == "DRAFT", prepared.context.tenantId != scope.tenantID,
                      prepared.context.permits("invoices:test-issue"), prepared.context.permits("invoices:test-email"),
                      prepared.tax.id == prepared.product.taxCategoryId, prepared.tax.sriCode == tax.sriCode,
                      prepared.tax.rate == tax.rate, prepared.tax.isValid(on: prepared.draft.issueDate),
                      selection.matches(customer: prepared.customer, product: prepared.product, invoice: prepared.draft)
                else { throw ERPClientError.invalidResponse }
                let transport = PairedTrialTransport(directory: directory, selectionSHA256: expected, invoiceID: prepared.invoiceID)
                let api = try LiveERPService(baseURL: URL(string: "https://paired.iaerp.invalid/api/v1")!,
                                             tokenProvider: { _ in "paired-local" }, transport: transport)
                try await openPrivateTrial(api, prepared: prepared, expectedGeneration: epoch)
                return
            }
            try await Task.sleep(for: .seconds(1))
        }
        throw ERPClientError.invalidInput("El simulador del Mac aún no ha respondido. Comprueba el cable y verifica que los datos del cliente coincidan con los del ensayo en el Mac. Después, toca Continuar en pruebas.")
    }

    private func matchingInvoice(for selection: BTOBTrialSelection, using demo: DemoERPService) async throws -> UUID {
        let customers = try await demo.customers(query: selection.customer.identificationNumber)
        let products = try await demo.products(query: selection.product.code ?? selection.product.name)
        let docs = try await demo.invoices(query: "", status: nil)
        for invoice in docs {
            if let customer = customers.first(where: { $0.id == invoice.partyId }),
               let product = products.first(where: { $0.id == invoice.lines.first?.productId }),
               selection.matches(customer: customer, product: product, invoice: invoice) { return invoice.id }
        }
        throw ERPClientError.invalidInput("El comprobante de pruebas disponible corresponde a otra selección. Prepara el cliente y producto elegidos en el simulador del Mac.")
    }
}
