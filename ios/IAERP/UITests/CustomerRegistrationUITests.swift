import XCTest

@MainActor
final class CustomerRegistrationUITests: XCTestCase {
    private func launch(reader: Bool = false) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-workspace-demo"] + (reader ? ["-read-only"] : [])
        app.launch()
        XCTAssertTrue(app.navigationBars["Inicio"].waitForExistence(timeout: 8))
        return app
    }

    private func tap(_ element: XCUIElement, in app: XCUIApplication,
                     file: StaticString = #filePath, line: UInt = #line) {
        for _ in 0..<6 {
            if element.exists && element.isHittable { break }
            app.swipeUp()
        }
        XCTAssertTrue(element.isHittable, file: file, line: line)
        element.tap()
    }

    private func enter(_ value: String, field: String, in app: XCUIApplication) {
        let input = app.textFields[field]
        let focusedInput = app.textFields.matching(NSPredicate(
            format: "identifier == %@ AND hasKeyboardFocus == true", field
        )).firstMatch
        tap(input, in: app)
        if !focusedInput.waitForExistence(timeout: 3) { tap(input, in: app) }
        XCTAssertTrue(focusedInput.waitForExistence(timeout: 8), "El teclado debe tener el foco en " + field)
        focusedInput.typeText(value)
        XCTAssertEqual(input.value as? String, value)
        if app.keyboards.firstMatch.exists {
            let done = app.buttons["Listo"].firstMatch
            if done.exists && done.isHittable { done.tap() }
        }
    }

    private func lookUp(_ number: String, in app: XCUIApplication) {
        XCTAssertTrue(app.navigationBars["Nuevo cliente"].waitForExistence(timeout: 5))
        enter(number, field: "customer-id-number", in: app)
        tap(app.buttons["customer-lookup"], in: app)
    }

    func testNewClientFromListThenUseExactMatchInDraft() {
        let app = launch()
        let name = "Taller Sintético Norte"
        let number = "1790000723001"
        app.tabBars.buttons["Clientes"].tap()
        tap(app.buttons["clients-new-customer"], in: app)
        let lookupHelp = app.staticTexts["customer-lookup-guidance"]
        XCTAssertTrue(lookupHelp.waitForExistence(timeout: 5))
        XCTAssertTrue(lookupHelp.label.contains("13 dígitos del RUC"))
        XCTAssertFalse(app.buttons["customer-lookup"].isEnabled)
        enter(number, field: "customer-id-number", in: app)
        XCTAssertFalse(lookupHelp.exists)
        tap(app.buttons["customer-lookup"], in: app)
        let nameHelp = app.staticTexts["customer-save-guidance"]
        for _ in 0..<4 where !nameHelp.exists { app.swipeUp() }
        XCTAssertTrue(nameHelp.label.contains("nombre o la razón social"))
        XCTAssertFalse(app.buttons["customer-save"].isEnabled)
        enter(name, field: "customer-name", in: app)
        XCTAssertFalse(nameHelp.exists)
        tap(app.buttons["customer-save"], in: app)
        XCTAssertTrue(app.navigationBars["Cliente"].waitForExistence(timeout: 6))
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", name)).firstMatch.exists)
        app.navigationBars["Cliente"].buttons.firstMatch.tap()
        XCTAssertTrue(app.navigationBars["Clientes"].waitForExistence(timeout: 4))
        let savedRows = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'workspace-client-' AND label CONTAINS %@", name))
        XCTAssertTrue(savedRows.firstMatch.waitForExistence(timeout: 4))
        XCTAssertEqual(savedRows.count, 1)
        app.tabBars.buttons["Facturas"].tap()
        tap(app.buttons["new-invoice"], in: app)
        tap(app.buttons["draft-customer"], in: app)
        tap(app.buttons["picker-new-customer"], in: app)
        lookUp(number, in: app)
        XCTAssertTrue(app.buttons["customer-use-existing"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["customer-save"].exists)
        tap(app.buttons["customer-use-existing"], in: app)
        XCTAssertTrue(app.navigationBars["Elegir cliente"].waitForNonExistence(timeout: 6))
        XCTAssertTrue(app.buttons["draft-customer"].label.contains(name))
    }

    func testRegisterFromComposerKeepsProductAndEnablesReview() {
        let app = launch()
        let name = "Taller Sintético Sur"
        app.tabBars.buttons["Facturas"].tap()
        tap(app.buttons["new-invoice"], in: app)
        tap(app.buttons["add-product"], in: app)
        tap(app.buttons["pick-product-00000000-0000-4000-8000-000000000201"], in: app)
        XCTAssertTrue(app.navigationBars["Elegir producto"].waitForNonExistence(timeout: 5))
        let picker = app.buttons["draft-customer"]
        for _ in 0..<5 where !picker.isHittable { app.swipeDown() }
        tap(picker, in: app)
        tap(app.buttons["picker-new-customer"], in: app)
        lookUp("1790000724001", in: app)
        enter(name, field: "customer-name", in: app)
        tap(app.buttons["customer-save"], in: app)
        XCTAssertTrue(app.navigationBars["Elegir cliente"].waitForNonExistence(timeout: 6))
        XCTAssertTrue(picker.label.contains(name))
        tap(app.buttons["review-totals"], in: app)
        XCTAssertTrue(app.buttons["save-draft"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["save-draft"].isEnabled)
    }

    func testReadOnlyCatalogOmitsRegistration() {
        let app = launch(reader: true)
        app.tabBars.buttons["Clientes"].tap()
        XCTAssertTrue(app.navigationBars["Clientes"].waitForExistence(timeout: 4))
        XCTAssertFalse(app.buttons["clients-new-customer"].exists)
    }
}
