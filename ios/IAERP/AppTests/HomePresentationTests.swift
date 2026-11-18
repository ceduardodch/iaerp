import Foundation
import Testing
@testable import IAERP

@Suite("Presentación fiscal de Inicio y meses") @MainActor
struct HomePresentationTests {
    @Test(arguments: [
        ("2026-01", "Enero de 2026"),
        ("2026-11", "Noviembre de 2026"),
        ("2026-12", "Diciembre de 2026"),
        ("2027-01", "Enero de 2027"),
        ("2026-11-18", "18 de noviembre de 2026"),
    ])
    func fiscalMonthAndCutoffAreReadable(_ input: String, _ expected: String) {
        #expect(ERPDisplay.longFiscalDate(input) == expected)
    }

    @Test(arguments: [
        ("2027-01-01T04:59:59Z", "2026-12-31"),
        ("2027-01-01T05:00:00Z", "2027-01-01"),
        ("2026-12-01T04:59:59Z", "2026-11-30"),
        ("2026-12-01T05:00:00Z", "2026-12-01"),
    ])
    func fiscalDateUsesGuayaquilAtMonthAndYearBoundaries(_ instant: String, _ expected: String) throws {
        let date = try #require(ISO8601DateFormatter().date(from: instant))
        #expect(ERPDisplay.fiscalDate(date) == expected)
    }

    @Test(arguments: [
        ("350.25", "$350,25"),
        ("100.50", "$100,50"),
        ("230.75", "$230,75"),
        ("80.40", "$80,40"),
        ("0", "$0,00"),
        ("40.20", "$40,20"),
    ])
    func metricAmountsKeepServerCents(_ decimal: String, _ expected: String) throws {
        let value = try #require(Decimal(string: decimal, locale: Locale(identifier: "en_US_POSIX")))
        #expect(ERPDisplay.money(value) == expected)
    }
}
