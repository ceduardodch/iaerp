import XCTest
import UIKit

final class WorkspaceUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    @MainActor private func app(readOnly: Bool = false, largestText: Bool = false, traceInvoiceLayout: Bool = false) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-workspace-demo"]
        if readOnly { app.launchArguments.append("-read-only") }
        if traceInvoiceLayout { app.launchArguments.append("-trace-invoice-layout") }
        if largestText {
            app.launchArguments += ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        }
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["Clientes"].waitForExistence(timeout: 8))
        return app
    }

    @MainActor private func reveal(_ element: XCUIElement, in app: XCUIApplication) {
        var lastViewport = CGRect.zero
        for _ in 0..<24 {
            let scroll = app.collectionViews.allElementsBoundByIndex.last
            let bounds = scroll?.frame ?? app.frame
            let navigation = app.navigationBars.allElementsBoundByIndex.last
            let top = max(bounds.minY, navigation?.frame.maxY ?? bounds.minY)
            var bottom = bounds.maxY
            if app.tabBars.firstMatch.exists && app.tabBars.firstMatch.isHittable {
                bottom = min(bottom, app.tabBars.firstMatch.frame.minY - 8)
            }
            if app.buttons["save-draft"].exists && app.buttons["Cancelar"].isHittable {
                bottom = min(bottom, app.buttons["Cancelar"].frame.minY - 12)
            }
            if element.exists && element.isHittable,
               element.frame.minY >= top, element.frame.maxY <= bottom { return }
            let viewportHeight = bottom - top
            lastViewport = CGRect(x: bounds.minX, y: top, width: bounds.width, height: viewportHeight)
            let above = element.exists && element.frame.minY < top
            let overflow = element.exists ? (above ? top - element.frame.minY : element.frame.maxY - bottom) : viewportHeight
            let distance = max(24, min(viewportHeight * 0.35, overflow + 16))
            let start = app.coordinate(withNormalizedOffset: .zero).withOffset(
                CGVector(dx: bounds.minX + 8 - app.frame.minX, dy: (top + bottom) / 2 - app.frame.minY))
            let end = start.withOffset(CGVector(dx: 0, dy: above ? distance : -distance))
            start.press(forDuration: 0.05, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 0.2)
        }
        let targetFrame = element.exists ? element.frame : .null
        XCTFail("El control debe estar completo y operable. Target: \(targetFrame), viewport: \(lastViewport)")
    }

    @MainActor private func snapshot(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    /// Observe the current viewport without scrolling to repair a regression.
    @MainActor private func assertEntireInvoiceControl(_ element: XCUIElement, in app: XCUIApplication,
                                                       file: StaticString = #filePath, line: UInt = #line) {
        guard element.exists,
              let form = app.collectionViews.allElementsBoundByIndex.last,
              let navigation = app.navigationBars.allElementsBoundByIndex.last else {
            XCTFail("El formulario y su control deben seguir presentes", file: file, line: line)
            return
        }
        let top = max(form.frame.minY, navigation.frame.maxY)
        var bottom = min(form.frame.maxY, app.frame.maxY)
        let keyboard = app.keyboards.firstMatch
        if keyboard.exists { bottom = min(bottom, keyboard.frame.minY) }
        let cancel = app.buttons["Cancelar"]
        if cancel.exists && cancel.isHittable { bottom = min(bottom, cancel.frame.minY) }
        let frame = element.frame
        XCTAssertTrue(element.isHittable, file: file, line: line)
        XCTAssertGreaterThan(frame.width, 0, file: file, line: line)
        XCTAssertGreaterThan(frame.height, 0, file: file, line: line)
        XCTAssertGreaterThanOrEqual(frame.minY, top, file: file, line: line)
        XCTAssertLessThanOrEqual(frame.maxY, bottom, file: file, line: line)
    }

    @MainActor func testCreateReviewSaveAndReopenDraft() throws {
        let app = app()
        snapshot("Clientes", app: app)
        app.tabBars.buttons["Facturas"].tap()
        app.buttons["new-invoice"].tap()
        app.buttons["draft-customer"].tap()
        app.buttons["pick-customer-00000000-0000-4000-8000-000000000101"].tap()
        let terms = app.textFields["payment-terms-days"]
        reveal(terms, in: app)
        // Select the existing number: a single tap can place the caret before
        // its first digit, where Backspace would leave that digit untouched.
        terms.doubleTap()
        terms.typeText("30")
        app.buttons["dismiss-keyboard"].tap()
        let add = app.buttons["add-product"]
        reveal(add, in: app); add.tap()
        app.buttons["pick-product-00000000-0000-4000-8000-000000000201"].tap()
        XCTAssertEqual(app.textFields["payment-terms-days"].value as? String, "30")
        let review = app.buttons["review-totals"]
        reveal(review, in: app); review.tap()
        let total = app.descendants(matching: .any)["draft-total"].firstMatch
        reveal(total, in: app)
        XCTAssertTrue(total.exists)
        snapshot("Borrador-importes", app: app)
        app.buttons["save-draft"].tap()
        XCTAssertTrue(app.navigationBars["Facturas"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Borrador guardado. No se ha emitido al SRI."].exists)
        snapshot("Facturas-borrador-guardado", app: app)
        let rows = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "workspace-invoice-"))
        XCTAssertTrue(rows.firstMatch.exists)
        rows.firstMatch.tap()
        XCTAssertTrue(app.navigationBars["Factura"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts["Borrador guardado. No se ha emitido al SRI."].exists)
    }

    @MainActor func testCancelDoesNotSaveDraft() throws {
        let app = app()
        app.tabBars.buttons["Facturas"].tap()
        app.buttons["new-invoice"].tap()
        XCTAssertFalse(app.buttons["save-draft"].isEnabled)
        app.buttons["Cancelar"].tap()
        app.buttons["Descartar borrador"].tap()
        XCTAssertTrue(app.navigationBars["Facturas"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.staticTexts["Borrador guardado. No se ha emitido al SRI."].exists)
    }

    @MainActor func testEditingQuantityKeepsTheFieldVisibleAcrossKeyboardChanges() throws {
        let app = app()
        app.tabBars.buttons["Facturas"].tap()
        app.buttons["new-invoice"].tap()
        app.buttons["draft-customer"].tap()
        app.buttons["pick-customer-00000000-0000-4000-8000-000000000101"].tap()
        let add = app.buttons["add-product"]
        reveal(add, in: app); add.tap()
        app.buttons["pick-product-00000000-0000-4000-8000-000000000201"].tap()
        let review = app.buttons["review-totals"]
        reveal(review, in: app); review.tap()
        let total = app.descendants(matching: .any)["draft-total"].firstMatch
        reveal(total, in: app)
        XCTAssertTrue(total.exists)

        // Leave the end of the form to edit an earlier row. Removing the old
        // preview and resizing for the keyboard must not jump back to totals.
        let quantity = app.textFields["field-Cantidad"]
        reveal(quantity, in: app)
        quantity.doubleTap()
        let keyboard = app.keyboards.firstMatch
        XCTAssertTrue(keyboard.waitForExistence(timeout: 3))
        quantity.typeText("2")
        XCTAssertEqual(quantity.value as? String, "2")
        assertEntireInvoiceControl(quantity, in: app)
        let done = app.buttons["dismiss-keyboard"]
        XCTAssertTrue(done.waitForExistence(timeout: 3))
        done.tap()
        XCTAssertTrue(keyboard.waitForNonExistence(timeout: 3))
        XCTAssertEqual(quantity.value as? String, "2")
        assertEntireInvoiceControl(quantity, in: app)

        // A second real edit proves the retained field is still operable,
        // rather than merely displaying a stale value after losing focus.
        quantity.tap()
        XCTAssertTrue(keyboard.waitForExistence(timeout: 3))
        assertEntireInvoiceControl(quantity, in: app)
        quantity.typeText("0")
        XCTAssertNotEqual(quantity.value as? String, "2")
        quantity.typeText(XCUIKeyboardKey.delete.rawValue)
        XCTAssertEqual(quantity.value as? String, "2")
        done.tap()
        XCTAssertTrue(keyboard.waitForNonExistence(timeout: 3))
        assertEntireInvoiceControl(quantity, in: app)
        snapshot("Cantidad-editada-sin-salto", app: app)

        reveal(review, in: app); review.tap()
        reveal(total, in: app)
        XCTAssertEqual(total.label, "$230,00")
    }

    @MainActor func testReadOnlyUserDoesNotGetCreateAction() throws {
        let app = app(readOnly: true)
        app.tabBars.buttons["Facturas"].tap()
        XCTAssertFalse(app.buttons["new-invoice"].exists)
        app.tabBars.buttons["Cuenta"].tap()
        app.buttons["company-profile"].tap()
        XCTAssertTrue(app.staticTexts["Sólo consulta"].exists)
    }

    @MainActor func testSwitchCompanyAndLogoutClearVisibleData() throws {
        let app = app()
        XCTAssertTrue(app.staticTexts["Cliente de ejemplo Álamo"].waitForExistence(timeout: 4))
        app.tabBars.buttons["Cuenta"].tap()
        app.buttons["company-profile"].tap()
        let button = app.buttons["switch-demo-company"]
        reveal(button, in: app); button.tap()
        XCTAssertTrue(app.staticTexts["Cliente de ejemplo Río"].waitForExistence(timeout: 6))
        XCTAssertFalse(app.staticTexts["Cliente de ejemplo Álamo"].exists)
        app.tabBars.buttons["Cuenta"].tap()
        let signOut = app.buttons["sign-out"]
        reveal(signOut, in: app); signOut.tap()
        app.buttons.matching(NSPredicate(format: "label == %@ AND identifier != %@", "Cerrar sesión", "sign-out")).firstMatch.tap()
        XCTAssertTrue(app.buttons["start-demo"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.tabBars.buttons["Clientes"].exists)
        XCTAssertFalse(app.staticTexts["Cliente de ejemplo Río"].exists)
    }

    @MainActor func testConnectionRejectsEmptyConfiguration() throws {
        let app = XCUIApplication()
        app.launchArguments = []
        app.launch()
        app.buttons["connect-company"].tap()
        let signIn = app.buttons["sign-in"]
        reveal(signIn, in: app); signIn.tap()
        XCTAssertTrue(app.staticTexts["connection-error"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.tabBars.buttons["Clientes"].exists)
    }

    @MainActor func testWorkspaceAccessibilityAtLargestTextSize() throws {
        let app = app(largestText: true)
        snapshot("Clientes-texto-maximo", app: app)
        try app.performAccessibilityAudit()
        let client = app.buttons["workspace-client-00000000-0000-4000-8000-000000000101"]
        reveal(client, in: app); client.tap()
        XCTAssertTrue(app.navigationBars["Cliente"].waitForExistence(timeout: 4))
        snapshot("Cliente-texto-maximo", app: app)
        try app.performAccessibilityAudit()
        app.navigationBars["Cliente"].buttons.firstMatch.tap()
        app.tabBars.buttons["Facturas"].tap()
        snapshot("Facturas-texto-maximo", app: app)
        try app.performAccessibilityAudit()
        app.tabBars.buttons["Cuenta"].tap()
        // The account picker adds a third action. Prepare the viewport with
        // all actions above the floating tab bar before auditing this state.
        reveal(app.buttons["sign-out"], in: app)
        let top = app.navigationBars.firstMatch.frame.maxY
        let bottom = app.tabBars.firstMatch.frame.minY - 8
        for identifier in ["company-profile", "switch-account", "sign-out"] {
            let action = app.buttons[identifier]
            XCTAssertTrue(action.isHittable)
            XCTAssertGreaterThanOrEqual(action.frame.minY, top)
            XCTAssertLessThanOrEqual(action.frame.maxY, bottom)
        }
        snapshot("Cuenta-texto-maximo", app: app)
        try app.performAccessibilityAudit()
        reveal(app.buttons["company-profile"], in: app)
        app.buttons["company-profile"].tap()
        XCTAssertTrue(app.navigationBars["Empresa"].waitForExistence(timeout: 4))
        snapshot("Empresa-texto-maximo", app: app)
        try app.performAccessibilityAudit()
    }

    @MainActor func testOpenSyntheticXMLWithoutExecutingContent() throws {
        let app = app()
        app.tabBars.buttons["Facturas"].tap()
        let invoice = app.descendants(matching: .any)["workspace-invoice-00000000-0000-4000-8000-000000000601"].firstMatch
        XCTAssertTrue(invoice.waitForExistence(timeout: 5))
        invoice.tap()
        let open = app.buttons["open-xml-signed"]
        reveal(open, in: app); open.tap()
        XCTAssertTrue(app.descendants(matching: .any)["xml-document"].firstMatch.waitForExistence(timeout: 4))
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Datos ficticios, sin validez fiscal")).firstMatch.exists)
        snapshot("Documento-XML", app: app)
        app.buttons["Cerrar"].tap()
        XCTAssertTrue(app.navigationBars["Factura"].exists)
    }

    @MainActor func testInvoiceFormAndDetailAccessibilityAtLargestTextSize() throws {
        let app = app(largestText: true, traceInvoiceLayout: true)
        app.tabBars.buttons["Facturas"].tap()
        app.buttons["new-invoice"].tap()
        snapshot("Nueva-factura-texto-maximo", app: app)
        try app.performAccessibilityAudit()
        app.buttons["draft-customer"].tap()
        try app.performAccessibilityAudit()
        app.buttons["pick-customer-00000000-0000-4000-8000-000000000101"].tap()
        let add = app.buttons["add-product"]
        reveal(add, in: app); add.tap()
        try app.performAccessibilityAudit()
        app.buttons["pick-product-00000000-0000-4000-8000-000000000201"].tap()
        let review = app.buttons["review-totals"]
        reveal(review, in: app); review.tap()
        let total = app.descendants(matching: .any)["draft-total"].firstMatch
        let totalCell = app.cells.containing(.any, identifier: "draft-total").firstMatch
        reveal(totalCell, in: app)
        XCTAssertTrue(totalCell.exists)
        XCTAssertTrue(total.exists)
        XCTAssertTrue(app.buttons["save-draft"].isHittable)
        // Include the final note: a button can have a few hittable pixels
        // above the fixed actions while all of its text is still covered.
        let note = app.staticTexts["Borrador, sin envío al SRI."]
        reveal(note, in: app)
        // Reach the actual end of the form, including its bottom content
        // margin. Stopping when the note first appears leaves part of the
        // preceding IVA amount under the opaque navigation bar.
        let form = app.collectionViews.allElementsBoundByIndex.last!
        let endStart = app.coordinate(withNormalizedOffset: .zero).withOffset(
            CGVector(dx: form.frame.minX + 8, dy: form.frame.midY))
        endStart.press(forDuration: 0.05,
            thenDragTo: endStart.withOffset(CGVector(dx: 0, dy: -120)),
            withVelocity: .slow, thenHoldForDuration: 0.3)
        XCTAssertTrue(app.buttons["review-totals"].isHittable)
        let top = app.navigationBars.allElementsBoundByIndex.last!.frame.maxY
        let bottom = app.collectionViews.allElementsBoundByIndex.last!.frame.maxY
        for element in [totalCell, app.buttons["review-totals"], note] {
            XCTAssertGreaterThanOrEqual(element.frame.minY, top)
            XCTAssertLessThanOrEqual(element.frame.maxY, bottom)
        }
        XCTAssertLessThanOrEqual(note.frame.maxY, bottom - 24)
        snapshot("Importes-texto-maximo", app: app)
        let totalsHierarchy = XCTAttachment(string: app.debugDescription)
        totalsHierarchy.name = "Totales-hierarchy"
        totalsHierarchy.lifetime = .keepAlways
        self.add(totalsHierarchy)
        try app.performAccessibilityAudit()
        // The audit changes Dynamic Type. Its return must leave the complete
        // totals viewport usable, without a reveal that could hide a bad offset.
        for element in [totalCell, review, note] {
            assertEntireInvoiceControl(element, in: app)
        }
        XCTAssertTrue(app.buttons["save-draft"].isHittable)
        snapshot("Importes-despues-auditoria", app: app)
        app.buttons["Cancelar"].tap()
        app.buttons["Descartar borrador"].tap()
        let invoice = app.descendants(matching: .any)["workspace-invoice-00000000-0000-4000-8000-000000000601"].firstMatch
        reveal(invoice, in: app); invoice.tap()
        snapshot("Factura-texto-maximo", app: app)
        try app.performAccessibilityAudit()
    }

    @MainActor func testDarkModeAndPDFPreview() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-workspace-demo", "-dark-mode"]
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["Clientes"].waitForExistence(timeout: 8))
        snapshot("Clientes-oscuro", app: app)
        try app.performAccessibilityAudit()
        app.tabBars.buttons["Facturas"].tap()
        snapshot("Facturas-oscuro", app: app)
        let invoice = app.descendants(matching: .any)["workspace-invoice-00000000-0000-4000-8000-000000000601"].firstMatch
        XCTAssertTrue(invoice.waitForExistence(timeout: 5))
        invoice.tap()
        let open = app.buttons["open-ride-pdf"]
        reveal(open, in: app); open.tap()
        XCTAssertTrue(app.navigationBars["RIDE"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.descendants(matching: .any)["ride-document"].firstMatch.exists)
        snapshot("Documento-RIDE", app: app)
    }

    @MainActor func testSearchClientsAndClearQuery() throws {
        let app = app()
        let search = app.textFields["erp-search-field"]
        XCTAssertTrue(search.waitForExistence(timeout: 4))
        search.tap(); search.typeText("Costa")
        XCTAssertTrue(app.staticTexts["Resultados: 1"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Cliente de ejemplo Costa"].exists)
        XCTAssertFalse(app.staticTexts["Cliente de ejemplo Álamo"].exists)
        app.buttons["Borrar búsqueda"].tap()
        XCTAssertTrue(app.staticTexts["Resultados: 3"].waitForExistence(timeout: 5))
    }

    @MainActor func testPDFSnapshotIsCoveredWhenEnteringBackground() throws {
        let app = app()
        app.tabBars.buttons["Facturas"].tap()
        app.descendants(matching: .any)["workspace-invoice-00000000-0000-4000-8000-000000000601"].firstMatch.tap()
        let open = app.buttons["open-ride-pdf"]
        reveal(open, in: app); open.tap()
        XCTAssertTrue(app.navigationBars["RIDE"].waitForExistence(timeout: 4))
        let start = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 1))
        let end = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        start.press(forDuration: 0.1, thenDragTo: end, withVelocity: .fast, thenHoldForDuration: 1)
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        XCTAssertTrue(springboard.otherElements["AppSwitcherContentView"].waitForExistence(timeout: 4))
        let card = springboard.otherElements.matching(NSPredicate(format: "identifier BEGINSWITH %@", "card:ec.com.b2b.iaerp.demo:")).firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 4))
        let hierarchy = XCTAttachment(string: springboard.debugDescription)
        hierarchy.name = "Selector-apps-hierarchy"
        hierarchy.lifetime = .keepAlways
        add(hierarchy)
        snapshot("Selector-apps-RIDE", app: springboard)
        try assertPrivateCard(card.screenshot())
        app.activate()
        XCTAssertTrue(app.navigationBars["RIDE"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.otherElements["privacy-shield"].exists)
    }

    @MainActor private func assertPrivateCard(_ screenshot: XCUIScreenshot) throws {
        let image = try XCTUnwrap(screenshot.image.cgImage)
        let width = image.width, height = image.height
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        try pixels.withUnsafeMutableBytes { bytes in
            let context = try XCTUnwrap(CGContext(data: bytes.baseAddress, width: width, height: height,
                bitsPerComponent: 8, bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
            context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        }
        let reference = (height / 3 * width + width / 2) * 4
        var differences = 0
        // Ignore rounded edges and the small central IAERP label, then require
        // an opaque uniform card. PDF text or toolbar content fails this check.
        for y in stride(from: height * 8 / 100, to: height * 92 / 100, by: 2) {
            if (height * 44 / 100...height * 56 / 100).contains(y) { continue }
            for x in stride(from: width / 5, to: width * 4 / 5, by: 2) {
                let index = (y * width + x) * 4
                if (0..<3).contains(where: { abs(Int(pixels[index + $0]) - Int(pixels[reference + $0])) > 16 }) {
                    differences += 1
                }
            }
        }
        XCTAssertEqual(differences, 0, "El selector debe mostrar el escudo opaco, sin contenido del documento")
    }
}
