import Foundation

public struct ERPHomeSummary: Decodable, Equatable, Sendable {
    public let asOf: String
    public let currency: String
    @ERPDecimal public var receivable: Decimal
    @ERPDecimal public var overdue: Decimal
    @ERPDecimal public var collectedThisMonth: Decimal

    enum CodingKeys: String, CodingKey {
        case asOf, currency, overdue, collectedThisMonth
        case receivable = "outstanding"
    }
}

public struct ERPInvoiceMonth: Decodable, Equatable, Identifiable, Sendable {
    public var id: String { month + "/" + currency }
    public let month: String
    public let count: Int
    @ERPDecimal public var total: Decimal
    public let currency: String
}

public struct ERPMonthInvoice: Decodable, Equatable, Identifiable, Sendable {
    public let id: UUID
    public let number: String
    public let customerName: String
    public let issueDate: String
    public let status: String
    @ERPDecimal public var total: Decimal
    public let currency: String
    public let collectionStatus: String?
}

public struct ERPInvoicePage: Decodable, Sendable {
    public let items: [ERPMonthInvoice]
    public let nextCursor: String?
}

public protocol ERPSalesOverviewService: Sendable {
    func homeSummary() async throws -> ERPHomeSummary
    func invoiceMonths(query: String, status: String?) async throws -> [ERPInvoiceMonth]
    func monthPage(_ month: String, currency: String, query: String, status: String?, cursor: String?) async throws -> ERPInvoicePage
}
