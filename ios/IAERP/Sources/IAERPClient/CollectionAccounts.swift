import Foundation

public struct CollectionInstallment: Decodable, Equatable, Identifiable, Sendable {
    public let id: UUID
    public let sequence: Int
    public var dueDate: String
    @ERPDecimal public var openAmount: Decimal
}

public struct CollectionAccount: Decodable, Equatable, Identifiable, Sendable {
    public let id: UUID
    public let partyId: UUID
    public let customerName: String
    public let invoiceNumber: String
    public let currency: String
    @ERPDecimal public var openAmount: Decimal
    @ERPDecimal public var originalAmount: Decimal
    @ERPDecimal public var cashAmount: Decimal
    @ERPDecimal public var retentionAmount: Decimal
    public var dueDate: String
    public var overdue: Bool
    public let installmentCount: Int
    public var installments: [CollectionInstallment]
    public var promisedDate: String?
    public let email: String?
    public var collectionEnabled: Bool
    public var canEnableReminders: Bool
    public var reminderBlockedReason: String?
    public var lastReminderAt: String?
    public var lastReminderStatus: String?
}

public enum CollectionAction: Equatable, Sendable, Encodable {
    case promise(date: String?, previous: String?)
    case dueDate(installment: UUID, date: String, previous: String, reason: String)
    case enableReminders
    case reminder(recipient: String, amount: Decimal, dueDate: String)

    var path: String {
        switch self {
        case .promise: "promise"
        case .dueDate: "due-date"
        case .enableReminders: "enable-reminders"
        case .reminder: "reminder"
        }
    }
    var method: String {
        if case .reminder = self { return "POST" }
        return "PUT"
    }
    enum CodingKeys: String, CodingKey {
        case promisedDate, previousPromisedDate, installmentId, dueDate, previousDueDate, reason
        case expectedRecipient, expectedOpenAmount, expectedDueDate
    }
    public func encode(to encoder: any Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case let .promise(date, previous):
            try values.encode(date, forKey: .promisedDate)
            try values.encode(previous, forKey: .previousPromisedDate)
        case let .dueDate(installment, date, previous, reason):
            try values.encode(installment, forKey: .installmentId)
            try values.encode(date, forKey: .dueDate)
            try values.encode(previous, forKey: .previousDueDate)
            try values.encode(reason, forKey: .reason)
        case .enableReminders: break
        case let .reminder(recipient, amount, dueDate):
            try values.encode(recipient, forKey: .expectedRecipient)
            try values.encode(ERPDecimal(wrappedValue: amount), forKey: .expectedOpenAmount)
            try values.encode(dueDate, forKey: .expectedDueDate)
        }
    }
}

public protocol ERPCollectionsService: Sendable {
    func collectionAccounts() async throws -> [CollectionAccount]
    func collectionAccount(_ id: UUID) async throws -> CollectionAccount
    func changeCollectionAccount(_ id: UUID, action: CollectionAction, key: UUID) async throws -> CollectionAccount
}
