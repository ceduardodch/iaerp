import Foundation
import XCTest

final class HomeUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    @MainActor private func launch(readOnly: Bool = false, largestText: Bool = false,
                                   dark: Bool = false) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-workspace-demo"]
        if readOnly { app.launchArguments.append("-read-only") }
        if dark { app.launchArguments.append("-dark-mode") }
        if largestText {
            app.launchArguments += ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        }
        app.launch()
        XCTAssertTrue(app.navigationBars["Inicio"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.tabBars.buttons["Inicio"].isSelected)
        return app
    }

    @MainActor private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)[identifier].firstMatch
    }

    @MainActor private func reveal(_ target: XCUIElement, in app: XCUIApplication, earlier: Bool = false) {
        for _ in 0..<20 {
            let navigation = ["Empresa", "Nueva factura", "Factura", "Inicio", "Facturas", "Cuenta"]
                .map { app.navigationBars[$0] }.first { $0.exists && $0.isHittable }
            let top = navigation?.frame.maxY ?? app.frame.minY
            let bottom = app.tabBars.firstMatch.isHittable ? app.tabBars.firstMatch.frame.minY : app.frame.maxY - 32
            if target.exists, target.isHittable, target.frame.minY >= top, target.frame.maxY <= bottom { return }
            let above = target.exists ? target.frame.minY < top : earlier
            let start = app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: 8, dy: (top + bottom) / 2))
            start.press(forDuration: 0.05,
                        thenDragTo: start.withOffset(CGVector(dx: 0, dy: above ? 120 : -120)),
                        withVelocity: .slow, thenHoldForDuration: 0.2)
        }
        XCTFail("El control \(target.identifier) debe quedar completo y operable")
    }

    @MainActor private func assertMetric(_ identifier: String, title: String, amount: String,
                                        in app: XCUIApplication) {
        // Scope the AX query to the visible home content. An untyped query
        // across the replaced tab hierarchy can stall after switching company.
        let metric = identifier == "home-metric-collected" ? app.scrollViews.firstMatch.staticTexts[identifier] : app.scrollViews.firstMatch.buttons[identifier]
        XCTAssertTrue(metric.waitForExistence(timeout: 5))
        let top = app.navigationBars["Inicio"].frame.maxY
        let bottom = app.tabBars.firstMatch.frame.minY
        let frame = metric.frame
        if !metric.isHittable || frame.minY < top || frame.maxY > bottom {
            reveal(metric, in: app)
        }
        let label = metric.label
        XCTAssertTrue(label.contains(title), label)
        XCTAssertTrue(label.contains(amount), label)
    }

    @MainActor private func snapshot(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor func testStartsOnHomeWithExactServerMetricsAndCutoff() {
        let app = launch()
        XCTAssertTrue(app.buttons["home-new-invoice"].isEnabled)
        assertMetric("home-metric-receivable", title: "Por cobrar", amount: "$350,25", in: app)
        assertMetric("home-metric-overdue", title: "Vencido", amount: "$100,50", in: app)
        assertMetric("home-metric-collected", title: "Cobrado este mes", amount: "$230,75", in: app)
        let cutoff = element("home-as-of", in: app)
        XCTAssertTrue(cutoff.isHittable)
        XCTAssertEqual(cutoff.label, "18/11/2026")
        cutoff.tap()
        XCTAssertTrue(app.staticTexts["Resumen del 18 de noviembre de 2026"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.staticTexts["Cobrado este mes incluye efectivo y retenciones."].waitForExistence(timeout: 4))
        app.buttons["Cerrar"].tap()
        snapshot("Inicio-resumen", app: app)
    }

    @MainActor func testReadOnlyProfileDoesNotExposeAmountsOrCreation() {
        let app = launch(readOnly: true)
        let permission = element("home-dashboard-permission", in: app)
        reveal(permission, in: app)
        XCTAssertTrue(permission.label.contains("permiso"))
        XCTAssertFalse(app.buttons["home-new-invoice"].exists)
        for identifier in ["home-metric-receivable", "home-metric-overdue", "home-metric-collected", "home-as-of"] {
            XCTAssertFalse(element(identifier, in: app).exists)
        }
        app.tabBars.buttons["Facturas"].tap()
        XCTAssertTrue(app.navigationBars["Facturas"].waitForExistence(timeout: 4))
        XCTAssertFalse(app.buttons["new-invoice"].exists)
        XCTAssertTrue(app.buttons["invoice-month-2026-11"].waitForExistence(timeout: 5))
    }

    @MainActor func testCompanySwitchResetsHomeMetricsAndMonthlyDocuments() {
        let app = launch()
        assertMetric("home-metric-receivable", title: "Por cobrar", amount: "$350,25", in: app)
        app.tabBars.buttons["Facturas"].tap()
        let firstCompanyInvoice = element("workspace-invoice-00000000-0000-4000-8000-000000000601", in: app)
        reveal(firstCompanyInvoice, in: app)
        XCTAssertTrue(firstCompanyInvoice.exists)
        app.tabBars.buttons["Cuenta"].tap()
        app.buttons["company-profile"].tap()
        let switchCompany = app.buttons["switch-demo-company"]
        reveal(switchCompany, in: app); switchCompany.tap()
        XCTAssertTrue(app.navigationBars["Inicio"].waitForExistence(timeout: 6))
        XCTAssertTrue(app.tabBars.buttons["Inicio"].isSelected)
        assertMetric("home-metric-receivable", title: "Por cobrar", amount: "$80,40", in: app)
        assertMetric("home-metric-overdue", title: "Vencido", amount: "$0,00", in: app)
        assertMetric("home-metric-collected", title: "Cobrado este mes", amount: "$40,20", in: app)
        XCTAssertFalse(app.buttons["home-metric-receivable"].label.contains("$350,25"))
        app.tabBars.buttons["Facturas"].tap()
        let secondCompanyInvoice = element("workspace-invoice-00000000-0000-4000-8000-000000001601", in: app)
        reveal(secondCompanyInvoice, in: app)
        XCTAssertFalse(firstCompanyInvoice.exists)
        XCTAssertTrue(secondCompanyInvoice.label.contains("Cliente de ejemplo Río"))
    }

    @MainActor func testDraftCreatedFromHomeCanBeOpenedAndCancelDoesNotCreateAnother() {
        let app = launch()
        let fiscalMonth = DateFormatter()
        fiscalMonth.locale = Locale(identifier: "en_US_POSIX")
        fiscalMonth.timeZone = TimeZone(identifier: "America/Guayaquil")
        fiscalMonth.dateFormat = "yyyy-MM"
        let createdMonth = fiscalMonth.string(from: Date())
        app.buttons["home-new-invoice"].tap()
        app.buttons["draft-customer"].tap()
        app.buttons["pick-customer-00000000-0000-4000-8000-000000000101"].tap()
        let add = app.buttons["add-product"]
        reveal(add, in: app); add.tap()
        app.buttons["pick-product-00000000-0000-4000-8000-000000000201"].tap()
        let review = app.buttons["review-totals"]
        XCTAssertTrue(review.waitForExistence(timeout: 5))
        XCTAssertTrue(review.isHittable)
        review.tap()
        let total = element("draft-total", in: app)
        reveal(total, in: app)
        XCTAssertEqual(total.label, "$115,00")
        app.buttons["save-draft"].tap()
        XCTAssertTrue(app.navigationBars["Inicio"].waitForExistence(timeout: 5))
        let notice = element("workspace-notice", in: app)
        reveal(notice, in: app)
        XCTAssertEqual(notice.label, "Borrador guardado. No se ha emitido al SRI.")
        let open = app.buttons["home-open-draft"]
        reveal(open, in: app); open.tap()
        XCTAssertTrue(app.navigationBars["Factura"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Borrador guardado. No se ha emitido al SRI."].exists)
        app.navigationBars["Factura"].buttons.firstMatch.tap()
        let navigation = app.navigationBars["Inicio"]
        let create = navigation.buttons["home-new-invoice"]
        XCTAssertTrue(create.waitForExistence(timeout: 5))
        XCTAssertTrue(create.isHittable)
        XCTAssertTrue(navigation.frame.contains(create.frame))
        create.tap()
        XCTAssertTrue(app.navigationBars["Nueva factura"].waitForExistence(timeout: 5))
        app.buttons["Cancelar"].tap()
        app.buttons["Descartar borrador"].tap()
        XCTAssertTrue(app.navigationBars["Inicio"].waitForExistence(timeout: 5))
        let invoicesTab = app.tabBars.buttons["Facturas"]
        let tabIsOperable = XCTNSPredicateExpectation(predicate: NSPredicate(format: "hittable == true"), object: invoicesTab)
        XCTAssertEqual(XCTWaiter.wait(for: [tabIsOperable], timeout: 5), .completed,
                       "Facturas debe volver a ser operable tras cerrar el formulario")
        invoicesTab.tap()
        let month = app.buttons["invoice-month-\(createdMonth)"]
        reveal(month, in: app)
        let expectedCount: String
        let expectedTotal: String
        switch createdMonth {
        case "2026-11": (expectedCount, expectedTotal) = ("4 facturas", "$460,00")
        case "2026-10": (expectedCount, expectedTotal) = ("3 facturas", "$345,00")
        default: (expectedCount, expectedTotal) = ("1 factura", "$115,00")
        }
        XCTAssertTrue(month.label.contains(expectedCount), month.label)
        XCTAssertTrue(month.label.contains(expectedTotal), month.label)
    }

    @MainActor func testMonthGroupsUseServerCountsAndOnlyRevealTheirOwnDocuments() {
        let app = launch()
        app.tabBars.buttons["Facturas"].tap()
        let november = app.buttons["invoice-month-2026-11"]
        XCTAssertTrue(november.waitForExistence(timeout: 5))
        reveal(november, in: app)
        XCTAssertTrue(november.label.contains("Noviembre de 2026"))
        XCTAssertTrue(november.label.contains("3 facturas"))
        XCTAssertTrue(november.label.contains("$345,00"))
        XCTAssertEqual(november.value as? String, "Expandido")
        let first = element("workspace-invoice-00000000-0000-4000-8000-000000000601", in: app)
        reveal(first, in: app)
        XCTAssertTrue(first.label.contains("2026-11"))
        reveal(november, in: app, earlier: true); november.tap()
        XCTAssertEqual(november.value as? String, "Contraído")
        XCTAssertFalse(first.exists)
        let october = app.buttons["invoice-month-2026-10"]
        reveal(october, in: app)
        XCTAssertTrue(october.label.contains("Octubre de 2026"))
        XCTAssertTrue(october.label.contains("2 facturas"))
        XCTAssertTrue(october.label.contains("$230,00"))
        XCTAssertEqual(october.value as? String, "Contraído")
        october.tap()
        XCTAssertEqual(october.value as? String, "Expandido")
        let fourth = element("workspace-invoice-00000000-0000-4000-8000-000000000604", in: app)
        reveal(fourth, in: app)
        XCTAssertTrue(fourth.label.contains("2026-10"))
        let originalPosition = fourth.frame
        fourth.tap()
        XCTAssertTrue(app.navigationBars["Factura"].waitForExistence(timeout: 4))
        app.navigationBars["Factura"].buttons.firstMatch.tap()
        XCTAssertTrue(app.navigationBars["Facturas"].waitForExistence(timeout: 4))
        // Observe the restored viewport before any reveal can repair its position.
        XCTAssertEqual(october.value as? String, "Expandido")
        XCTAssertEqual(november.value as? String, "Contraído")
        XCTAssertTrue(fourth.isHittable)
        XCTAssertEqual(fourth.frame.minY, originalPosition.minY, accuracy: 8,
                       "Volver del detalle debe conservar la posición en octubre")
        snapshot("Facturas-octubre-restaurado", app: app)
        let search = app.textFields["erp-search-field"]
        reveal(search, in: app, earlier: true)
        search.tap(); search.typeText("000000004")
        XCTAssertTrue(november.waitForNonExistence(timeout: 6))
        XCTAssertTrue(october.waitForExistence(timeout: 6))
        XCTAssertTrue(october.label.contains("1 factura"))
        XCTAssertTrue(october.label.contains("$115,00"))
        XCTAssertTrue(fourth.waitForExistence(timeout: 5))
        XCTAssertFalse(first.exists)
        snapshot("Facturas-filtro-mensual", app: app)
    }

    @MainActor func testHomeAccessibilityAtLargestTextAndInDarkMode() throws {
        let app = launch(largestText: true)
        snapshot("Inicio-texto-maximo", app: app)
        try app.performAccessibilityAudit()
        let viewCollections = app.buttons["home-view-collections"]
        XCTAssertTrue(viewCollections.isHittable)
        viewCollections.tap()
        let collected = element("home-metric-collected", in: app)
        XCTAssertTrue(collected.waitForExistence(timeout: 5))
        XCTAssertTrue(collected.isHittable)
        XCTAssertGreaterThanOrEqual(collected.frame.minY, app.navigationBars["Inicio"].frame.maxY)
        XCTAssertLessThanOrEqual(collected.frame.maxY, app.tabBars.firstMatch.frame.minY)
        snapshot("Inicio-cobros-texto-maximo", app: app)
        try app.performAccessibilityAudit()
        app.swipeRight()
        XCTAssertTrue(viewCollections.waitForExistence(timeout: 5))
        XCTAssertTrue(viewCollections.isHittable)
        app.swipeLeft()
        XCTAssertTrue(collected.waitForExistence(timeout: 5))
        XCTAssertTrue(collected.isHittable)
        XCTAssertGreaterThanOrEqual(collected.frame.minY, app.navigationBars["Inicio"].frame.maxY)
        XCTAssertLessThanOrEqual(collected.frame.maxY, app.tabBars.firstMatch.frame.minY)
        app.terminate()
        let dark = launch(dark: true)
        snapshot("Inicio-oscuro", app: dark)
        try dark.performAccessibilityAudit()
    }
}
