import XCTest

final class SavedAccountsUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    @MainActor private func launch(largestText: Bool = false) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-saved-accounts-fixture"]
        if largestText { app.launchArguments += ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"] }
        app.launch()
        XCTAssertTrue(app.navigationBars["IAERP"].waitForExistence(timeout: 8))
        if !largestText {
            XCTAssertTrue(app.buttons["saved-account-00000000-0000-4000-8000-000000000001"].waitForExistence(timeout: 8))
        }
        return app
    }

    @MainActor func testProfilesAreDistinctAndRemovingOneKeepsOthers() {
        let app = launch()
        let first = app.buttons["saved-account-00000000-0000-4000-8000-000000000001"]
        let second = app.buttons["saved-account-00000000-0000-4000-8000-000000000002"]
        XCTAssertTrue(first.label.contains("alex.ventas"))
        XCTAssertTrue(second.label.contains("alex.consulta"))
        let initial = XCTAttachment(screenshot: app.screenshot())
        initial.name = "Selector-tres-cuentas"
        initial.lifetime = .keepAlways
        add(initial)
        let options = app.buttons["Opciones de Alex Cruz, alex.consulta, empresa demo-a, identity.example.invalid"]
        options.tap()
        app.buttons["Quitar de este iPhone"].tap()
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "alex.consulta · demo-a")).firstMatch.exists)
        app.buttons["Cancelar"].tap()
        XCTAssertTrue(second.exists)
        options.tap()
        app.buttons["Quitar de este iPhone"].tap()
        app.buttons["Quitar cuenta"].tap()
        XCTAssertFalse(second.exists)
        XCTAssertTrue(first.exists)
        XCTAssertTrue(app.buttons["saved-account-00000000-0000-4000-8000-000000000003"].exists)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "Cuentas-guardadas"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

    @MainActor func testReconnectSeedsTheSelectedCompany() {
        let app = launch()
        app.swipeUp()
        app.buttons["Opciones de Alex Cruz, alex.ventas, empresa demo-b, other.example.invalid"].tap()
        app.buttons["Volver a iniciar sesión"].tap()
        XCTAssertTrue(app.textFields["connection-alias"].waitForExistence(timeout: 3))
        XCTAssertEqual(app.textFields["connection-alias"].value as? String, "demo-b")
        XCTAssertEqual(app.textFields["connection-issuer"].value as? String, "https://other.example.invalid/realms/test")
        XCTAssertEqual(app.secureTextFields.count, 0)
        app.buttons["Cancelar"].tap()
        XCTAssertTrue(app.buttons["saved-account-00000000-0000-4000-8000-000000000002"].exists)
    }

    @MainActor func testSavedAccountAccessibilityAtLargestText() throws {
        let app = launch(largestText: true)
        let first = app.buttons["saved-account-00000000-0000-4000-8000-000000000001"]
        for _ in 0..<14 {
            let top = app.navigationBars.firstMatch.frame.maxY
            // Show the section header and complete account, with the intro
            // text fully above the navigation bar rather than clipped by it.
            if first.exists, first.isHittable, first.frame.minY >= top + 140,
               first.frame.minY <= top + 200, first.frame.maxY < app.frame.maxY - 40 { break }
            let start = app.coordinate(withNormalizedOffset: CGVector(dx: 0.03, dy: 0.65))
            let offset: CGFloat
            if first.exists {
                let delta = top + 160 - first.frame.minY
                offset = delta > 0 ? min(80, max(20, delta)) : max(-80, min(-20, delta))
            } else { offset = -80 }
            start.press(forDuration: 0.05, thenDragTo: start.withOffset(CGVector(dx: 0, dy: offset)), withVelocity: .slow, thenHoldForDuration: 0.3)
        }
        XCTAssertTrue(first.isHittable)
        XCTAssertGreaterThanOrEqual(first.frame.minY, app.navigationBars.firstMatch.frame.maxY + 140)
        XCTAssertLessThanOrEqual(first.frame.minY, app.navigationBars.firstMatch.frame.maxY + 200)
        XCTAssertLessThan(first.frame.maxY, app.frame.maxY - 40)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "Cuentas-texto-maximo"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        try app.performAccessibilityAudit()
    }
}
