import XCTest

@MainActor
final class InvoiceTestDeliveryUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    private func reveal(_ element: XCUIElement, in app: XCUIApplication, earlier: Bool = false,
                        file: StaticString = #filePath, line: UInt = #line) {
        for _ in 0..<12 {
            if element.exists, element.isHittable, app.frame.contains(element.frame) { return }
            if earlier { app.swipeDown() } else { app.swipeUp() }
        }
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "Acción de prueba fuera de vista"
        add(image)
        XCTFail("No se puede usar \(element.identifier)", file: file, line: line)
    }

    private func tap(_ id: String, in app: XCUIApplication, earlier: Bool = false) {
        let button = app.buttons[id]
        reveal(button, in: app, earlier: earlier)
        XCTAssertTrue(button.isEnabled)
        button.tap()
    }

    private func text(_ id: String, in app: XCUIApplication) -> String {
        let element = app.descendants(matching: .any)[id].firstMatch
        XCTAssertTrue(element.waitForExistence(timeout: 4))
        return [element.label, element.value as? String ?? ""].joined(separator: " ")
    }

    func testCustomerDraftCanBeIssuedAndBothDocumentsSentToTestInbox() {
        let app = XCUIApplication()
        app.launchArguments = ["-ephemeral-demo"]
        app.launch()
        tap("start-demo", in: app)
        XCTAssertTrue(app.navigationBars["Inicio"].waitForExistence(timeout: 5))
        app.tabBars.buttons["Clientes"].tap()
        tap("workspace-client-00000000-0000-4000-8000-000000000101", in: app)
        tap("new-customer-invoice", in: app)
        tap("add-product", in: app)
        tap("pick-product-00000000-0000-4000-8000-000000000201", in: app)
        XCTAssertTrue(app.navigationBars["Elegir producto"].waitForNonExistence(timeout: 5))
        tap("review-totals", in: app)
        tap("save-draft", in: app)
        XCTAssertTrue(app.navigationBars["Nueva factura"].waitForNonExistence(timeout: 5))
        tap("customer-open-draft", in: app, earlier: true)
        tap("test-issue-invoice", in: app)
        XCTAssertTrue(app.navigationBars["Revisar emisión"].waitForExistence(timeout: 5))
        XCTAssertTrue(text("test-delivery-company", in: app).localizedCaseInsensitiveContains("prueba"))
        XCTAssertTrue(text("test-delivery-total", in: app).contains("115"))
        XCTAssertFalse(text("test-delivery-number", in: app).isEmpty)
        tap("test-cancel-delivery", in: app)
        XCTAssertTrue(app.navigationBars["Revisar emisión"].waitForNonExistence(timeout: 5))
        tap("test-issue-invoice", in: app)
        tap("test-confirm-issue", in: app)
        XCTAssertTrue(app.navigationBars["Revisar emisión"].waitForNonExistence(timeout: 5))
        tap("test-email-invoice", in: app)
        XCTAssertTrue(app.navigationBars["Revisar correo"].waitForExistence(timeout: 5))
        XCTAssertTrue(text("test-delivery-recipient", in: app).contains("buzon@iaerp.example.org"))
        XCTAssertTrue(text("test-delivery-attachment-pdf", in: app).lowercased().contains(".pdf"))
        XCTAssertTrue(text("test-delivery-attachment-xml", in: app).lowercased().contains(".xml"))
        tap("test-cancel-delivery", in: app)
        XCTAssertTrue(app.navigationBars["Revisar correo"].waitForNonExistence(timeout: 5))
        tap("test-email-invoice", in: app)
        tap("test-confirm-email", in: app)
        let receipt = app.descendants(matching: .any)["test-delivery-receipt"].firstMatch
        XCTAssertTrue(receipt.waitForExistence(timeout: 8))
        XCTAssertFalse(app.buttons["test-email-invoice"].exists)
        app.navigationBars["Factura"].buttons.firstMatch.tap()
        tap("customer-open-draft", in: app, earlier: true)
        XCTAssertTrue(receipt.waitForExistence(timeout: 8))
        XCTAssertFalse(app.buttons["test-issue-invoice"].exists)
        XCTAssertFalse(app.buttons["test-email-invoice"].exists)
    }

    func testPrepareFiveCentInvoiceFromSelectedCatalogCustomerAndProduct() {
        let app = XCUIApplication()
        app.launchArguments = ["-ephemeral-demo"]
        app.launch()
        tap("start-btob-test", in: app)
        app.tabBars.buttons["Clientes"].tap()
        tap("workspace-client-00000000-0000-4000-8000-000000002101", in: app)
        tap("customer-prepare-test-invoice", in: app)
        XCTAssertTrue(app.buttons["trial-new-product"].waitForExistence(timeout: 5))
        tap("test-product-00000000-0000-4000-8000-000000002201", in: app)
        tap("confirm-test-product", in: app)
        XCTAssertTrue(app.navigationBars["Factura"].waitForExistence(timeout: 8))
        tap("test-issue-invoice", in: app)
        let amount = text("test-delivery-total", in: app)
        XCTAssertTrue(amount.contains("0,05") || amount.contains("0.05"))
        tap("test-cancel-delivery", in: app)
    }

    func testAuthorizedInvoiceEmailPreviewAtLargestText() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-workspace-demo", "-UIPreferredContentSizeCategoryName",
                               "UICTContentSizeCategoryAccessibilityXXXL"]
        app.launch()
        app.tabBars.buttons["Facturas"].tap()
        tap("workspace-invoice-00000000-0000-4000-8000-000000000601", in: app)
        tap("test-email-invoice", in: app)
        XCTAssertTrue(app.navigationBars["Revisar correo"].waitForExistence(timeout: 5))
        try app.performAccessibilityAudit()
        let confirm = app.buttons["test-confirm-email"]
        reveal(confirm, in: app)
        XCTAssertGreaterThanOrEqual(confirm.frame.height, 44)
        XCTAssertTrue(app.frame.contains(confirm.frame))
        tap("test-cancel-delivery", in: app, earlier: true)
        XCTAssertTrue(app.navigationBars["Revisar correo"].waitForNonExistence(timeout: 5))
        tap("test-email-invoice", in: app)
        XCTAssertTrue(app.navigationBars["Revisar correo"].waitForExistence(timeout: 5))
    }
}
