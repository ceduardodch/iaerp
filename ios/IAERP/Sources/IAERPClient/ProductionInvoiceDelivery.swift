import Foundation

/// Fiscal operations available to an authorized production session.
public protocol ERPProductionInvoiceService: Sendable {
    func deliveryStatus(invoiceID: UUID) async throws -> ERPInvoiceDeliveryStatus
    func issueInvoice(invoiceID: UUID, idempotencyKey: String) async throws -> ERPInvoiceIssueResult
    func invoiceEmailPreview(invoiceID: UUID) async throws -> ERPInvoiceEmailPreview
    func sendInvoiceEmail(invoiceID: UUID, recipient: String, preview: ERPInvoiceEmailPreview,
                          idempotencyKey: String) async throws -> ERPInvoiceEmailReceipt
}

public struct ERPInvoiceDeliveryStatus: Decodable, Equatable, Sendable {
    public let fiscalEnvironment: String
    public let emailStatus: String
    public let receipt: ERPInvoiceEmailReceipt?

    public init(fiscalEnvironment: String, emailStatus: String, receipt: ERPInvoiceEmailReceipt? = nil) {
        self.fiscalEnvironment = fiscalEnvironment
        self.emailStatus = emailStatus
        self.receipt = receipt
    }
}

public struct ERPInvoiceIssueResult: Decodable, Equatable, Sendable {
    public let operationId: UUID
    public let status: String

    public init(operationId: UUID, status: String) {
        self.operationId = operationId
        self.status = status
    }
}

public struct ERPInvoiceEmailPreview: Decodable, Equatable, Sendable {
    public let recipient: String?
    public let senderAddress: String?
    public let senderName: String?
    public let subject: String
    public let message: String
    public let attachmentNames: [String]
    public let previewDigest: String
    public internal(set) var invoiceID: UUID?

    // The binding comes from the route used to fetch the preview.
    enum CodingKeys: String, CodingKey {
        case recipient, senderAddress, senderName, subject, message, attachmentNames, previewDigest
    }

    public init(recipient: String?, senderAddress: String? = nil, senderName: String? = nil,
                subject: String, message: String, attachmentNames: [String], previewDigest: String,
                invoiceID: UUID? = nil) {
        self.recipient = recipient
        self.senderAddress = senderAddress
        self.senderName = senderName
        self.subject = subject
        self.message = message
        self.attachmentNames = attachmentNames
        self.previewDigest = previewDigest
        self.invoiceID = invoiceID
    }

    func validate() throws {
        guard previewDigest.utf8.count == 64,
              previewDigest.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
              !subject.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              subject.rangeOfCharacter(from: .controlCharacters) == nil else { throw ERPClientError.invalidResponse }
        if let recipient { try FiscalEmailEnvelope.validateAddress(recipient) }
        if let senderAddress { try FiscalEmailEnvelope.validateAddress(senderAddress) }
        try FiscalEmailEnvelope.validateAttachments(attachmentNames)
    }
}

public struct ERPInvoiceEmailReceipt: Codable, Equatable, Sendable {
    public let messageId: String
    public let recipient: String
    public let senderAddress: String?
    public let senderName: String?
    public let attachmentNames: [String]

    public init(messageId: String, recipient: String, senderAddress: String? = nil,
                senderName: String? = nil, attachmentNames: [String]) {
        self.messageId = messageId
        self.recipient = recipient
        self.senderAddress = senderAddress
        self.senderName = senderName
        self.attachmentNames = attachmentNames
    }

    func validate() throws {
        guard !messageId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              messageId.rangeOfCharacter(from: .controlCharacters) == nil else { throw ERPClientError.invalidResponse }
        try FiscalEmailEnvelope.validateAddress(recipient)
        if let senderAddress { try FiscalEmailEnvelope.validateAddress(senderAddress) }
        try FiscalEmailEnvelope.validateAttachments(attachmentNames)
    }
}

private enum FiscalEmailEnvelope {
    static func validateAddress(_ address: String) throws {
        let parts = address.split(separator: "@", omittingEmptySubsequences: false)
        let forbidden = CharacterSet.whitespacesAndNewlines.union(.controlCharacters)
            .union(CharacterSet(charactersIn: ",;<>"))
        guard parts.count == 2, parts.allSatisfy({ !$0.isEmpty }),
              address.rangeOfCharacter(from: forbidden) == nil else { throw ERPClientError.invalidResponse }
    }

    static func validateAttachments(_ names: [String]) throws {
        guard (2...3).contains(names.count), Set(names).count == names.count,
              names.allSatisfy({ !$0.isEmpty && !$0.contains("/") && !$0.contains("\\") &&
                  $0.rangeOfCharacter(from: .controlCharacters) == nil }) else { throw ERPClientError.invalidResponse }
        let extensions = names.map { ($0 as NSString).pathExtension.lowercased() }
        guard extensions.filter({ $0 == "xml" }).count == 1,
              extensions.filter({ $0 == "pdf" }).count == names.count - 1 else { throw ERPClientError.invalidResponse }
    }
}

extension ERPClientError {
    /// Only recognized server reasons can become user-visible guidance.
    static func fiscalDeliveryError(_ response: ERPHTTPResponse) -> Self? {
        guard [409, 422, 503].contains(response.statusCode) else { return nil }
        struct Reason: Decodable { let detail: String }
        let reason = response.data.count <= 4096 ? try? JSONDecoder().decode(Reason.self, from: response.data).detail : nil
        switch (response.statusCode, reason) {
        case (409, "invoice_email_preview_changed"): return .invoiceEmailPreviewChanged
        case (409, "invoice_email_pending"): return .invoiceEmailDeliveryPending
        case (422, "invoice_email_rejected"): return .invoiceEmailRejected
        case (409, "invoice_environment_not_production"):
            return .invalidInput("Consulta la configuración de la empresa. La emisión real requiere el ambiente de producción del SRI.")
        case (409, "Signing certificate is not configured"):
            return .invalidInput("La empresa necesita configurar su certificado de firma antes de emitir la factura.")
        case (422, "Approve the required monthly report before emailing the invoice"):
            return .invoiceEmailPreparationFailed("Falta aprobar el informe mensual de este contrato. Pide su aprobación y vuelve a preparar el correo.")
        case (422, "Approved report file is missing"), (422, "Approved report checksum is missing"):
            return .invoiceEmailPreparationFailed("Pide que revisen el archivo del informe mensual aprobado. Hace falta para preparar el correo.")
        case (409, "invoice_email_attachment_changed"):
            return .invoiceEmailPreparationFailed("Pide que revisen los archivos de esta factura. El contenido guardado cambió.")
        case (422, "Authorized invoice requires both signed XML and RIDE before email"):
            return .invoiceEmailPreparationFailed("Falta el XML firmado o el RIDE. Consulta los documentos de esta factura antes de preparar el correo.")
        case (422, "Only authorized invoices can be emailed"):
            return .invoiceEmailPreparationFailed("Consulta el estado del SRI. El correo requiere una factura autorizada.")
        case (422, "Google Workspace is not connected"), (422, "Google Workspace must be reconnected"):
            return .invoiceEmailPreparationFailed("Pide que conecten tu cuenta de Google Workspace en IAERP y vuelve a preparar el correo.")
        case (422, "Google Workspace sender is missing"), (503, "Google OAuth is not configured"):
            return .invoiceEmailPreparationFailed("Pide a quien administra la empresa que configure el remitente de Google Workspace en IAERP.")
        case (422, "Invoice numbering data is incomplete"):
            return .invoiceEmailPreparationFailed("Pide que revisen el establecimiento y el punto de emisión de esta factura.")
        case (422, "Invoice customer or company is incomplete"):
            return .invoiceEmailPreparationFailed("Pide que completen los datos de la empresa y del cliente de esta factura.")
        case (409, _): return .invoiceDeliveryConflict
        default: return nil
        }
    }
}
