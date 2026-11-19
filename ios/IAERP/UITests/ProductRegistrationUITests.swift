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
        app.launchArguments = ["-workspace-demo", "-ephemeral-demo"]
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
            type("TEST-ALTA-05", field: "catalog-product-code", app: app)
            app.buttons["catalog-product-lookup"].tap()
        }
        lookup()
        type("Servicio sintético", field: "catalog-product-name", app: app)
        type("0.05", field: "catalog-product-price", app: app)
        app.buttons["catalog-product-tax"].tap()
        let zeroTax = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "0 %")).firstMatch
        XCTAssertTrue(zeroTax.waitForExistence(timeout: 5))
        zeroTax.tap()
        let save = app.buttons["catalog-product-save"]
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
}
