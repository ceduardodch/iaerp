import XCTest

final class LaunchUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testProductionWelcomeOpensCompanySignIn() {
        let app = XCUIApplication()
        app.launch()
        let connect = app.buttons["connect-company"]
        XCTAssertTrue(connect.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["start-demo"].exists)
        XCTAssertFalse(app.buttons["start-btob-test"].exists)
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS[cd] %@ OR label CONTAINS[cd] %@", "demo", "prueba")).firstMatch.exists)
        connect.tap()
        XCTAssertTrue(app.textFields["connection-alias"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testLaunchNavigateAndReturn() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-legacy-demo"]
        app.launch()
        XCTAssertTrue(app.navigationBars["Clientes"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["demo-mode"].firstMatch.exists)
        let client = app.descendants(matching: .any)[
            "demo-client-00000000-0000-4000-8000-000000000101"
        ].firstMatch
        XCTAssertTrue(client.exists)
        client.tap()
        XCTAssertTrue(app.navigationBars["Cliente"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts[
            "Ficha ficticia para probar IAERP. No contiene datos fiscales reales."
        ].exists)
        app.navigationBars.buttons.firstMatch.tap()
        XCTAssertTrue(app.navigationBars["Clientes"].waitForExistence(timeout: 3))
    }

    @MainActor
    func testSearchDoesNotShowUnrelatedClient() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-legacy-demo"]
        app.launch()
        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap()
        search.typeText("guayaquil")
        XCTAssertTrue(app.staticTexts["Cliente de ejemplo Costa"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.staticTexts["Cliente de ejemplo Sierra"].exists)
    }

    @MainActor
    func testAccessibilityAtLargestTextSize() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-legacy-demo"]
        app.launchArguments += [
            "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL",
        ]
        app.launch()
        XCTAssertTrue(app.navigationBars["Clientes"].waitForExistence(timeout: 5))
        try app.performAccessibilityAudit { issue in
            print("Accessibility audit issue: \(issue.auditType.rawValue): \(issue.compactDescription): \(issue.detailedDescription)")
            return false
        }
        let client = app.descendants(matching: .any)[
            "demo-client-00000000-0000-4000-8000-000000000101"
        ].firstMatch
        XCTAssertTrue(client.exists)
        client.tap()
        XCTAssertTrue(app.navigationBars["Cliente"].waitForExistence(timeout: 3))
        try app.performAccessibilityAudit { issue in
            print("Accessibility audit issue: \(issue.auditType.rawValue): \(issue.compactDescription): \(issue.detailedDescription)")
            return false
        }
    }
}
