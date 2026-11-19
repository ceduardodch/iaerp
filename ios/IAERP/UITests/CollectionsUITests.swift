import XCTest

final class CollectionsUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    @MainActor private func open(_ filter: String, account: String, largestText: Bool = false) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-workspace-demo"]
        if largestText {
            app.launchArguments += ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        }
        app.launch()
        let card = app.buttons["home-metric-\(filter)"]
        XCTAssertTrue(card.waitForExistence(timeout: 8))
        tap(card, in: app)
        XCTAssertTrue(app.navigationBars["Cobranza"].waitForExistence(timeout: 5))
        if filter == "overdue" {
            XCTAssertTrue(app.segmentedControls.buttons["Vencidas"].isSelected)
            XCTAssertFalse(app.buttons["collection-account-00000000-0000-4000-8000-000000000802"].exists)
        }
        let invoice = app.buttons["collection-account-00000000-0000-4000-8000-000000000\(account)"]
        XCTAssertTrue(invoice.waitForExistence(timeout: 5))
        snapshot("Cartera-\(filter)", app)
        tap(invoice, in: app)
        XCTAssertTrue(app.navigationBars["Cuenta por cobrar"].waitForExistence(timeout: 5))
        return app
    }
    @MainActor private func tap(_ button: XCUIElement, in app: XCUIApplication) {
        for _ in 0..<5 {
            if button.exists && button.isHittable { button.tap(); return }
            app.swipeUp()
        }
        XCTFail("No se encontró el control \(button.identifier)")
    }
    @MainActor private func assertValue(_ id: String, _ expected: String, in app: XCUIApplication,
                                        file: StaticString = #filePath, line: UInt = #line) {
        let row = app.descendants(matching: .any).matching(identifier: id).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 5), file: file, line: line)
        let spoken = [row.label, row.value as? String ?? ""].joined(separator: " ")
        XCTAssertTrue(spoken.contains(expected), spoken, file: file, line: line)
    }
    @MainActor private func snapshot(_ name: String, _ app: XCUIApplication) {
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = name
        image.lifetime = .keepAlways
        add(image)
    }

    @MainActor func testAccountAccessibilityAtLargestText() throws {
        let app = open("receivable", account: "801", largestText: true)
        try app.performAccessibilityAudit { issue in
            print("Auditoría de cobranza", issue.compactDescription, issue.element?.debugDescription ?? "")
            return false
        }
        let recipient = app.descendants(matching: .any)["collection-recipient"].firstMatch
        for _ in 0..<10 {
            if recipient.exists, recipient.isHittable,
               recipient.frame.midY >= app.frame.height * 0.2,
               recipient.frame.maxY <= app.frame.height * 0.9 { break }
            let start = app.coordinate(withNormalizedOffset: CGVector(dx: 0.2, dy: 0.75))
            start.press(forDuration: 0.05, thenDragTo: start.withOffset(CGVector(dx: 0, dy: -140)),
                        withVelocity: .slow, thenHoldForDuration: 0.15)
        }
        XCTAssertTrue(recipient.isHittable)
        XCTAssertLessThan(recipient.frame.maxY, app.frame.height * 0.91)
        assertValue("collection-recipient", "cliente1@example.invalid", in: app)
        snapshot("Ficha-texto-maximo", app)
        try app.performAccessibilityAudit { issue in
            print("Auditoría de cobranza", issue.compactDescription, issue.element?.debugDescription ?? "")
            return false
        }
        tap(app.buttons["collection-promise"], in: app)
        XCTAssertTrue(app.navigationBars["Promesa de pago"].waitForExistence(timeout: 5))
        snapshot("Promesa-texto-maximo", app)
        try app.performAccessibilityAudit { issue in
            print("Auditoría de cobranza", issue.compactDescription, issue.element?.debugDescription ?? "")
            return false
        }
    }

    @MainActor func testSingleEmailNeedsExplicitEnableAndUsesVisibleRecipient() {
        let app = open("overdue", account: "801")
        XCTAssertFalse(app.buttons["collection-send"].exists)
        assertValue("collection-recipient", "cliente1@example.invalid", in: app)
        tap(app.buttons["collection-enable"], in: app)
        XCTAssertTrue(app.buttons["collection-send"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.descendants(matching: .any)["collection-receipt"].exists)
        snapshot("Correo-antes-de-enviar", app)
        tap(app.buttons["collection-send"], in: app)
        assertValue("collection-receipt", "Aceptado en la prueba", in: app)
        XCTAssertFalse(app.buttons["collection-send"].exists)
    }

    @MainActor func testPromisePausesEmailsAndCanBeRemovedWithoutChangingDueDate() {
        let app = open("overdue", account: "801")
        tap(app.buttons["collection-enable"], in: app)
        tap(app.buttons["collection-promise"], in: app)
        tap(app.buttons["En 7 días"], in: app)
        snapshot("Promesa-de-pago", app)
        tap(app.buttons["collection-save"], in: app)
        XCTAssertTrue(app.buttons["Editar promesa"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["collection-send"].exists)
        assertValue("collection-contract-date", "10 de noviembre de 2026", in: app)
        tap(app.buttons["collection-promise"], in: app)
        tap(app.buttons["Retirar promesa"], in: app)
        XCTAssertTrue(app.buttons["collection-send"].waitForExistence(timeout: 5))
    }

    @MainActor func testChooseInstallmentBeforeMovingItsDeadline() {
        let app = open("receivable", account: "802")
        tap(app.buttons["collection-due"], in: app)
        XCTAssertFalse(app.buttons["collection-save"].isEnabled)
        tap(app.buttons["collection-installment-2"], in: app)
        assertValue("collection-prior-installment-date", "5 de enero de 2027", in: app)
        tap(app.buttons["Restar 7 días"], in: app)
        let reason = app.textViews["collection-reason"].firstMatch
        let alternate = app.textFields["collection-reason"]
        let field = reason.exists ? reason : alternate
        tap(field, in: app)
        field.typeText("Acuerdo de pago")
        if app.buttons["Listo"].isHittable { app.buttons["Listo"].tap() }
        snapshot("Cambio-de-cuota", app)
        tap(app.buttons["collection-save"], in: app)
        XCTAssertTrue(app.navigationBars["Cuenta por cobrar"].waitForExistence(timeout: 5))
        tap(app.buttons["collection-due"], in: app)
        XCTAssertTrue(app.buttons["collection-installment-1"].label.contains("5 de diciembre de 2026"))
        XCTAssertTrue(app.buttons["collection-installment-2"].label.contains("29 de diciembre de 2026"))
    }
}
