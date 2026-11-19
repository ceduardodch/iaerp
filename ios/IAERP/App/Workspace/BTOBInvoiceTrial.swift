import CryptoKit
import Foundation
import IAERPClient

/// Only the selected catalog entries travel to the paired development Mac.
struct BTOBTrialSelection: Codable {
    let customer: ERPParty
    let product: ERPProduct
    let tax: ERPTaxCategory

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

struct PreparedBTOBTrial: Decodable {
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
        try encoder.encode(selection).write(to: directory.appending(path: "selection.json"),
                                            options: [.atomic, .completeFileProtection])
        let readyFile = directory.appending(path: "prepared.json")
        let expected = SHA256.hash(data: try encoder.encode(selection)).map { String(format: "%02x", $0) }.joined()
        for _ in 0..<60 {
            try Task.checkCancellation()
            guard generation == epoch else { throw CancellationError() }
            if let attrs = try? readyFile.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]),
               attrs.isRegularFile == true, attrs.isSymbolicLink != true, (attrs.fileSize ?? Int.max) < 512_000,
               let content = try? Data(contentsOf: readyFile),
               let prepared = try? JSONDecoder().decode(PreparedBTOBTrial.self, from: content),
               prepared.selectionSHA256 == expected {
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
        throw ERPClientError.invalidInput("El simulador del Mac aún no ha respondido. Comprueba el cable y vuelve a tocar Continuar en pruebas.")
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
