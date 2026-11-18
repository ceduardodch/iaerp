import Foundation
import IAERPClient
import Testing
@testable import IAERP

nonisolated struct InvoicePaymentPolicyCase: Sendable {
    let customerDays: Int?
    let companyDays: Int
    let expectedDays: Int
}

nonisolated struct InvoiceDueDateCase: Sendable {
    let instant: String
    let days: Int
    let expectedDate: String
}

@MainActor
private func paymentTestDate(_ value: String) throws -> Date {
    try #require(ISO8601DateFormatter().date(from: value))
}

@MainActor
private func paymentContext(defaultDays: Int) -> ERPContext {
    ERPContext(
        tenantId: DemoCompany.primary.tenantId, ruc: "DEMO-SIN-RUC", name: "Empresa de prueba",
        roles: ["BILLING"], scopes: ["invoices:read", "invoices:write"],
        defaultPaymentTermsDays: defaultDays
    )
}

@Suite("Plazo de pago y fecha fiscal", .timeLimit(.minutes(1)))
@MainActor
struct InvoicePaymentTests {
    @Test(arguments: [
        InvoicePaymentPolicyCase(customerDays: 30, companyDays: 15, expectedDays: 30),
        InvoicePaymentPolicyCase(customerDays: nil, companyDays: 15, expectedDays: 15),
        InvoicePaymentPolicyCase(customerDays: 0, companyDays: 15, expectedDays: 0),
        InvoicePaymentPolicyCase(customerDays: nil, companyDays: 0, expectedDays: 0),
    ])
    func customerTermsOverrideCompanyTermsIncludingExplicitCash(_ example: InvoicePaymentPolicyCase) {
        let customer = ERPParty(
            id: UUID(uuidString: "00000000-0000-4000-8000-000000000101")!,
            name: "Cliente de ejemplo", identificationType: "PASSPORT", identificationNumber: "DEMO-CLIENT",
            paymentTermsDays: example.customerDays
        )
        let composer = InvoiceComposer(customerId: customer.id)
        composer.configurePaymentTerms(customer: customer, context: paymentContext(defaultDays: example.companyDays))
        #expect(composer.paymentTermsDays == example.expectedDays)
    }

    @Test(arguments: [
        InvoiceDueDateCase(instant: "2026-11-18T04:59:59Z", days: 0, expectedDate: "2026-11-17"),
        InvoiceDueDateCase(instant: "2026-11-18T04:59:59Z", days: 1, expectedDate: "2026-11-18"),
        InvoiceDueDateCase(instant: "2026-11-18T05:00:00Z", days: 0, expectedDate: "2026-11-18"),
        InvoiceDueDateCase(instant: "2026-11-18T05:00:00Z", days: 1, expectedDate: "2026-11-19"),
        InvoiceDueDateCase(instant: "2028-01-31T17:00:00Z", days: 30, expectedDate: "2028-03-01"),
        InvoiceDueDateCase(instant: "2027-01-31T17:00:00Z", days: 30, expectedDate: "2027-03-02"),
        InvoiceDueDateCase(instant: "2028-02-28T17:00:00Z", days: 1, expectedDate: "2028-02-29"),
        InvoiceDueDateCase(instant: "2027-02-28T17:00:00Z", days: 1, expectedDate: "2027-03-01"),
    ])
    func dueDateUsesGuayaquilCalendarAcrossMidnightAndLeapYears(_ example: InvoiceDueDateCase) throws {
        let instant = try paymentTestDate(example.instant)
        #expect(ERPDisplay.fiscalDueDate(instant, days: example.days) == example.expectedDate)
    }

    @Test(arguments: [30, 15, 0])
    func savedInstallmentUsesExactPreviewTotalAndConfiguredDueDate(_ days: Int) async throws {
        let service = DemoERPService()
        let setup = try await service.invoiceSetup()
        let sourceCustomer = try #require(try await service.customers(query: "").first)
        let customer = ERPParty(
            id: sourceCustomer.id, name: sourceCustomer.name,
            identificationType: sourceCustomer.identificationType,
            identificationNumber: sourceCustomer.identificationNumber,
            paymentTermsDays: days == 15 ? nil : days
        )
        let product = try #require(try await service.products(query: "").first)
        let composer = InvoiceComposer(customerId: customer.id)
        composer.issueDate = try paymentTestDate("2028-01-31T17:00:00Z")
        composer.configurePaymentTerms(customer: customer, context: paymentContext(defaultDays: 15))
        composer.establishmentId = try #require(setup.establishments.first?.id)
        composer.emissionPointId = try #require(setup.emissionPoints.first?.id)
        composer.add(product, setup: setup)
        await composer.review(using: service, setup: setup)
        let preview = try #require(composer.preview)
        #expect(preview.total == Decimal(string: "115", locale: Locale(identifier: "en_US_POSIX")))
        let expectedDate = days == 30 ? "2028-03-01" : days == 15 ? "2028-02-15" : "2028-01-31"
        #expect(composer.dueDateString == expectedDate)

        let saved = try #require(await composer.save(using: service, setup: setup))
        #expect(saved.installments.count == 1)
        let installment = try #require(saved.installments.first)
        #expect(installment.amount == preview.total)
        #expect(installment.dueDate == expectedDate)
        #expect(saved.total == preview.total)
        let reopened = try await service.invoice(id: saved.id)
        #expect(reopened.installments == saved.installments)
    }
}
