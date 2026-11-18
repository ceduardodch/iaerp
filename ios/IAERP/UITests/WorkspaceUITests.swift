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
        XCTAssertTrue(app.navigationBars["Inicio"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.tabBars.buttons["Clientes"].waitForExistence(timeout: 8))
        app.tabBars.buttons["Clientes"].tap()
        return app
    }

    @MainActor private func reveal(_ element: XCUIElement, in app: XCUIApplication, searchEarlier: Bool = false) {
        var lastViewport = CGRect.zero
        for _ in 0..<24 {
            // Resolve queries anew on each pass. An index captured while a
            // sheet changes can refer to a collection that no longer exists.
            let form = app.collectionViews["invoice-form"]
            let scroll = form.exists ? form : app.collectionViews.firstMatch
            let bounds = scroll.exists ? scroll.frame : app.frame
            let navigation = currentNavigationBar(in: app)
            let top = max(bounds.minY, navigation.exists ? navigation.frame.maxY : bounds.minY)
            var bottom = bounds.maxY
            if app.tabBars.firstMatch.exists && app.tabBars.firstMatch.isHittable {
                bottom = min(bottom, app.tabBars.firstMatch.frame.minY - 8)
            }
            if form.exists && app.buttons["Cancelar"].isHittable {
                bottom = min(bottom, app.buttons["Cancelar"].frame.minY - 12)
            }
            if element.exists && element.isHittable,
               element.frame.minY >= top, element.frame.maxY <= bottom { return }
            let viewportHeight = bottom - top
            lastViewport = CGRect(x: bounds.minX, y: top, width: bounds.width, height: viewportHeight)
            // Lazy cells outside the viewport have no frame. The caller can
            // identify a known earlier row without changing visibility checks.
            let above = element.exists ? element.frame.minY < top : searchEarlier
            let overflow = element.exists ? (above ? top - element.frame.minY : element.frame.maxY - bottom) : viewportHeight
            let distance = max(24, min(viewportHeight * 0.35, overflow + 16))
            let start = app.coordinate(withNormalizedOffset: .zero).withOffset(
                CGVector(dx: bounds.minX + (form.exists ? bounds.width * 0.28 : 8) - app.frame.minX, dy: (top + bottom) / 2 - app.frame.minY))
            let end = start.withOffset(CGVector(dx: 0, dy: above ? distance : -distance))
            start.press(forDuration: 0.05, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 0.2)
        }
        let targetFrame = element.exists ? element.frame : .null
        snapshot("Control-fuera-de-vista", app: app)
        XCTFail("El control debe estar completo y operable. Target: \(targetFrame), viewport: \(lastViewport)")
    }

    @MainActor private func assertFooterButton(_ button: XCUIElement, in app: XCUIApplication,
                                               file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(button.waitForExistence(timeout: 5), file: file, line: line)
        XCTAssertTrue(button.isHittable, file: file, line: line)
        XCTAssertTrue(button.isEnabled, file: file, line: line)
        XCTAssertGreaterThanOrEqual(button.frame.width, 44, file: file, line: line)
        XCTAssertGreaterThanOrEqual(button.frame.height, 44, file: file, line: line)
        XCTAssertGreaterThanOrEqual(button.frame.minY, app.collectionViews["invoice-form"].frame.maxY, file: file, line: line)
        XCTAssertTrue(app.frame.contains(button.frame), file: file, line: line)
    }

    @MainActor private func currentNavigationBar(in app: XCUIApplication) -> XCUIElement {
        // Prefer the presented screen over the workspace beneath its sheet.
        for title in ["Elegir cliente", "Elegir producto", "Nueva factura", "Empresa", "RIDE",
                      "Factura", "Cliente", "Cuenta", "Facturas", "Clientes", "Inicio"] {
            let bar = app.navigationBars[title]
            if bar.exists && bar.isHittable { return bar }
        }
        return app.navigationBars.firstMatch
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
        let form = app.collectionViews["invoice-form"]
        let navigation = app.navigationBars["Nueva factura"]
        guard element.exists, form.exists, navigation.exists else {
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
        // The field's AX frame includes its leading label. Focus the trailing
        // number, then select it rather than tapping the label at frame center.
        let termsValue = terms.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.5))
        termsValue.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 3))
        termsValue.doubleTap()
        terms.typeText("30")
        XCTAssertEqual(terms.value as? String, "30")
        app.buttons["dismiss-keyboard"].tap()
        let add = app.buttons["add-product"]
        reveal(add, in: app); add.tap()
        app.buttons["pick-product-00000000-0000-4000-8000-000000000201"].tap()
        XCTAssertEqual(app.textFields["payment-terms-days"].value as? String, "30")
        let review = app.buttons["review-totals"]
        assertFooterButton(review, in: app); review.tap()
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
        XCTAssertFalse(app.buttons["review-totals"].isEnabled)
        XCTAssertFalse(app.buttons["save-draft"].exists)
        let add = app.buttons["add-product"]
        reveal(add, in: app); add.tap()
        let picker = app.navigationBars["Elegir producto"]
        XCTAssertTrue(picker.waitForExistence(timeout: 5))
        app.buttons["cancel-product-picker"].tap()
        XCTAssertTrue(picker.waitForNonExistence(timeout: 5))
        XCTAssertFalse(app.textFields["field-Cantidad"].exists)
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
        assertFooterButton(review, in: app); review.tap()
        let total = app.descendants(matching: .any)["draft-total"].firstMatch
        reveal(total, in: app)
        XCTAssertTrue(total.exists)

        // Leave the end of the form to edit an earlier row. Removing the old
        // preview and resizing for the keyboard must not jump back to totals.
        let quantity = app.textFields["field-Cantidad"]
        reveal(quantity, in: app, searchEarlier: true)
        quantity.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.5)).tap()
        let keyboard = app.keyboards.firstMatch
        XCTAssertTrue(keyboard.waitForExistence(timeout: 3))
        let clear = app.buttons["clear-field-Cantidad"]
        XCTAssertTrue(clear.waitForExistence(timeout: 3))
        XCTAssertGreaterThanOrEqual(clear.frame.width, 44)
        XCTAssertGreaterThanOrEqual(clear.frame.height, 44)
        clear.tap()
        XCTAssertFalse(clear.isEnabled)
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
        quantity.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.5)).tap()
        XCTAssertTrue(keyboard.waitForExistence(timeout: 3))
        assertEntireInvoiceControl(quantity, in: app)
        clear.tap()
        XCTAssertFalse(clear.isEnabled)
        quantity.typeText("3")
        XCTAssertEqual(quantity.value as? String, "3")
        clear.tap()
        XCTAssertFalse(clear.isEnabled)
        quantity.typeText("2")
        XCTAssertEqual(quantity.value as? String, "2")
        done.tap()
        XCTAssertTrue(keyboard.waitForNonExistence(timeout: 3))
        assertEntireInvoiceControl(quantity, in: app)
        snapshot("Cantidad-editada-sin-salto", app: app)
        XCTAssertFalse(app.buttons["save-draft"].exists)

        assertFooterButton(review, in: app); review.tap()
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
        XCTAssertTrue(app.navigationBars["Inicio"].waitForExistence(timeout: 6))
        app.tabBars.buttons["Clientes"].tap()
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
        let list = app.collectionViews["invoice-list"]
        XCTAssertTrue(list.waitForExistence(timeout: 5))
        XCTAssertLessThanOrEqual(list.frame.maxY, app.tabBars.firstMatch.frame.minY + 1,
                                 "Las facturas deben desplazarse por encima de la barra de pestañas")
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
        XCTAssertTrue(app.navigationBars["Elegir producto"].waitForExistence(timeout: 5))
        let cancelPicker = app.buttons["cancel-product-picker"]
        XCTAssertTrue(cancelPicker.waitForExistence(timeout: 5))
        XCTAssertTrue(cancelPicker.isHittable)
        XCTAssertGreaterThanOrEqual(cancelPicker.frame.width, 44)
        XCTAssertGreaterThanOrEqual(cancelPicker.frame.height, 44)
        let product = app.buttons["pick-product-00000000-0000-4000-8000-000000000201"]
        XCTAssertTrue(product.waitForExistence(timeout: 5))
        XCTAssertTrue(product.isHittable)
        XCTAssertGreaterThanOrEqual(product.frame.height, 44)
        try app.performAccessibilityAudit()
        product.tap()
        XCTAssertTrue(app.navigationBars["Elegir producto"].waitForNonExistence(timeout: 5))
        let review = app.buttons["review-totals"]
        assertFooterButton(review, in: app); review.tap()
        let total = app.descendants(matching: .any)["draft-total"].firstMatch
        let totalCell = app.cells.containing(.any, identifier: "draft-total").firstMatch
        reveal(totalCell, in: app)
        XCTAssertTrue(totalCell.exists)
        XCTAssertTrue(total.exists)
        assertFooterButton(app.buttons["save-draft"], in: app)
        // Include the final note: a button can have a few hittable pixels
        // above the fixed actions while all of its text is still covered.
        let note = app.staticTexts["Borrador, sin envío al SRI."]
        reveal(note, in: app)
        // Reach the actual end of the form, including its bottom content
        // margin. Stopping when the note first appears leaves part of the
        // preceding IVA amount under the opaque navigation bar.
        let form = app.collectionViews["invoice-form"]
        XCTAssertTrue(form.exists)
        let endStart = app.coordinate(withNormalizedOffset: .zero).withOffset(
            CGVector(dx: form.frame.minX + form.frame.width * 0.28, dy: form.frame.midY))
        endStart.press(forDuration: 0.05,
            thenDragTo: endStart.withOffset(CGVector(dx: 0, dy: -120)),
            withVelocity: .slow, thenHoldForDuration: 0.3)
        XCTAssertFalse(review.exists)
        assertFooterButton(app.buttons["save-draft"], in: app)
        let top = app.navigationBars["Nueva factura"].frame.maxY
        let bottom = form.frame.maxY
        for element in [totalCell, note] {
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
        for element in [totalCell, note] {
            assertEntireInvoiceControl(element, in: app)
        }
        assertFooterButton(app.buttons["save-draft"], in: app)
        snapshot("Importes-despues-auditoria", app: app)
        app.buttons["Cancelar"].tap()
        app.buttons["Descartar borrador"].tap()
        XCTAssertTrue(app.navigationBars["Nueva factura"].waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.navigationBars["Facturas"].waitForExistence(timeout: 5))
        let invoice = app.descendants(matching: .any)["workspace-invoice-00000000-0000-4000-8000-000000000601"].firstMatch
        reveal(invoice, in: app); invoice.tap()
        snapshot("Factura-texto-maximo", app: app)
        try app.performAccessibilityAudit()
    }

    @MainActor func testDarkModeAndPDFPreview() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-workspace-demo", "-dark-mode"]
        app.launch()
        XCTAssertTrue(app.navigationBars["Inicio"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.tabBars.buttons["Clientes"].waitForExistence(timeout: 8))
        app.tabBars.buttons["Clientes"].tap()
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
        let summary = app.buttons["client-search-summary"]
        let oneResult = app.buttons.matching(NSPredicate(format: "identifier == %@ AND label == %@", "client-search-summary", "Resultados: 1")).firstMatch
        XCTAssertTrue(oneResult.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Cliente de ejemplo Costa"].exists)
        XCTAssertFalse(app.staticTexts["Cliente de ejemplo Álamo"].exists)
        summary.tap()
        XCTAssertTrue(app.staticTexts["Hasta 100 por consulta"].waitForExistence(timeout: 4))
        app.buttons["Cerrar"].tap()
        app.buttons["Borrar búsqueda"].tap()
        let allResults = app.buttons.matching(NSPredicate(format: "identifier == %@ AND label == %@", "client-search-summary", "Resultados: 3")).firstMatch
        XCTAssertTrue(allResults.waitForExistence(timeout: 5))
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
