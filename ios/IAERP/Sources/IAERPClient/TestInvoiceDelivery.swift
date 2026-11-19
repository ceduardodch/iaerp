import Foundation

/// Only implemented by services with a test-delivery API or the local demo mailbox.
public protocol ERPTestInvoiceService: Sendable {
    func testActions(invoiceID: UUID) async throws -> ERPTestInvoiceActions
    func issueTestInvoice(invoiceID: UUID, idempotencyKey: String) async throws -> ERPTestIssueResult
    func testEmailPreview(invoiceID: UUID) async throws -> ERPTestEmailPreview
    func sendTestEmail(invoiceID: UUID, recipient: String, idempotencyKey: String) async throws -> ERPTestEmailReceipt
}

public struct ERPTestInvoiceActions: Decodable, Equatable, Sendable {
    public let environment: String
    public let transmissionMode: String
    public let canIssue: Bool
    public let canEmail: Bool
    public let captureRecipient: String
    public let emailReceipt: ERPTestEmailReceipt?

    public init(environment: String, transmissionMode: String, canIssue: Bool, canEmail: Bool,
                captureRecipient: String, emailReceipt: ERPTestEmailReceipt? = nil) {
        self.environment = environment
        self.transmissionMode = transmissionMode
        self.canIssue = canIssue
        self.canEmail = canEmail
        self.captureRecipient = captureRecipient
        self.emailReceipt = emailReceipt
    }
}

public struct ERPTestIssueResult: Decodable, Equatable, Sendable {
    public let operationId: UUID
    public let status: String

    public init(operationId: UUID, status: String) {
        self.operationId = operationId
        self.status = status
    }
}

public struct ERPTestEmailPreview: Decodable, Equatable, Sendable {
    public let recipient: String
    public let subject: String
    public let message: String
    public let attachmentNames: [String]

    public init(recipient: String, subject: String, message: String, attachmentNames: [String]) {
        self.recipient = recipient
        self.subject = subject
        self.message = message
        self.attachmentNames = attachmentNames
    }
}

public struct ERPTestEmailReceipt: Codable, Equatable, Sendable {
    public let messageId: String
    public let recipient: String
    public let attachmentNames: [String]

    public init(messageId: String, recipient: String, attachmentNames: [String]) {
        self.messageId = messageId
        self.recipient = recipient
        self.attachmentNames = attachmentNames
    }
}

enum TestDeliveryContract {
    static let mailbox = "buzon@iaerp.example.org"

    static func checkEnvelope(recipient: String, names: [String]) throws {
        guard recipient == mailbox, names.count == 2,
              names.allSatisfy({ !$0.isEmpty && !$0.contains("/") && !$0.contains("\\") &&
                  $0.rangeOfCharacter(from: .controlCharacters) == nil }),
              Set(names.map { ($0 as NSString).pathExtension.lowercased() }) == ["pdf", "xml"] else {
            throw ERPClientError.invalidResponse
        }
    }

    static func checkReceipt(_ receipt: ERPTestEmailReceipt) throws {
        guard !receipt.messageId.isEmpty else { throw ERPClientError.invalidResponse }
        try checkEnvelope(recipient: receipt.recipient, names: receipt.attachmentNames)
    }
}
