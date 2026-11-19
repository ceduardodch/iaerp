import XCTest

@MainActor
final class ProductRegistrationUITests: XCTestCase {
    private func type(_ value: String, field id: String, app: XCUIApplication) {
        let field = app.textFields[id]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText(value)
        let done = app.buttons["Listo"].firstMatch
        if done.exists && done.isHittable { done.tap() }
    }

    func testCreateProductAndReuseSameCodeFromOpenInvoice() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-workspace-demo"]
        app.launch()
        XCTAssertTrue(app.navigationBars["Inicio"].waitForExistence(timeout: 6))
        app.tabBars.buttons["Clientes"].tap()
        let client = app.buttons["workspace-client-00000000-0000-4000-8000-000000000101"]
        XCTAssertTrue(client.waitForExistence(timeout: 5))
        client.tap()
        let newInvoice = app.buttons["new-customer-invoice"]
        XCTAssertTrue(newInvoice.waitForExistence(timeout: 5))
        newInvoice.tap()
        XCTAssertTrue(app.navigationBars["Nueva factura"].waitForExistence(timeout: 5))

        func lookup() {
            let add = app.buttons["add-product"]
            for _ in 0..<8 where !add.isHittable { app.swipeUp() }
            add.tap()
            app.buttons["new-catalog-product"].tap()
            let codeHelp = app.staticTexts["catalog-product-lookup-guidance"]
            XCTAssertTrue(codeHelp.waitForExistence(timeout: 5))
            XCTAssertTrue(codeHelp.label.contains("código del producto"))
            XCTAssertFalse(app.buttons["catalog-product-lookup"].isEnabled)
            type("TEST-ALTA-05", field: "catalog-product-code", app: app)
            XCTAssertFalse(codeHelp.exists)
            app.buttons["catalog-product-lookup"].tap()
        }
        let save = app.buttons["catalog-product-save"]
        let saveHelp = app.staticTexts["catalog-product-save-guidance"]
        func checkSaveHelp(_ expected: String) {
            for _ in 0..<4 where !saveHelp.exists { app.swipeUp() }
            XCTAssertTrue(saveHelp.waitForExistence(timeout: 3))
            XCTAssertTrue(saveHelp.label.contains(expected), saveHelp.label)
            XCTAssertFalse(save.isEnabled)
        }
        lookup()
        checkSaveHelp("nombre del producto")
        type("Servicio sintético", field: "catalog-product-name", app: app)
        checkSaveHelp("precio unitario sin IVA")
        type("0.05", field: "catalog-product-price", app: app)
        checkSaveHelp("Elige una tarifa de IVA")
        app.buttons["catalog-product-tax"].tap()
        let zeroTax = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "0 %")).firstMatch
        XCTAssertTrue(zeroTax.waitForExistence(timeout: 5))
        zeroTax.tap()
        XCTAssertFalse(saveHelp.exists)
        XCTAssertTrue(save.isEnabled)
        if !save.isHittable { app.swipeUp() }
        save.tap()
        XCTAssertTrue(app.navigationBars["Elegir producto"].waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.textFields.containing(NSPredicate(format: "value == %@", "Servicio sintético")).firstMatch.waitForExistence(timeout: 5))
        lookup()
        XCTAssertTrue(app.buttons["catalog-product-use-existing"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["catalog-product-save"].exists)
        app.buttons["catalog-product-use-existing"].tap()
        XCTAssertTrue(app.navigationBars["Elegir producto"].waitForNonExistence(timeout: 5))
    }

    func testTrialShowsHowToEnableContinue() {
        let app = XCUIApplication()
        app.launchArguments = ["-workspace-demo", "-btob-sandbox"]
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["Clientes"].waitForExistence(timeout: 6))
        app.tabBars.buttons["Clientes"].tap()
        app.buttons["workspace-client-00000000-0000-4000-8000-000000002101"].tap()
        let prepare = app.buttons["customer-prepare-test-invoice"]
        for _ in 0..<5 where !prepare.isHittable { app.swipeUp() }
        prepare.tap()
        XCTAssertTrue(app.navigationBars["Factura de prueba"].waitForExistence(timeout: 5))
        let guidance = app.staticTexts["test-product-selection-guidance"]
        for _ in 0..<4 where !guidance.exists { app.swipeUp() }
        XCTAssertTrue(guidance.waitForExistence(timeout: 5))
        XCTAssertTrue(guidance.label.contains("IVA vigente"))
        let next = app.buttons["confirm-test-product"]
        XCTAssertFalse(next.isEnabled)
        let product = app.buttons["test-product-00000000-0000-4000-8000-000000002201"]
        XCTAssertTrue(product.waitForExistence(timeout: 5))
        product.tap()
        XCTAssertTrue(next.waitForExistence(timeout: 5))
        XCTAssertTrue(next.isHittable)
        XCTAssertTrue(next.isEnabled)
        XCTAssertFalse(guidance.exists)
    }
}
