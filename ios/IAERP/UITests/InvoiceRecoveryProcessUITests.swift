#if targetEnvironment(simulator)
import XCTest

final class InvoiceRecoveryProcessUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    @MainActor func testActualTerminationRecoversOneDraftAtEachCommitBoundary() {
        for stage in ["before-post", "commit-lost", "after-response"] {
            let run = UUID().uuidString
            let app = XCUIApplication()
            func arguments(phase: String) -> [String] {
                ["-invoice-recovery-process-fixture", "-recovery-run", run,
                 "-recovery-stage", stage, "-recovery-phase", phase]
            }
            app.launchArguments = arguments(phase: "start")
            app.launch()
            XCTAssertTrue(app.staticTexts["recovery-process-ready"].waitForExistence(timeout: 20), "Checkpoint \(stage)")
            let oldPID = app.staticTexts["recovery-process-pid"].label
            let originalKey = app.staticTexts["recovery-process-original-key"].label
            app.terminate()
            XCTAssertEqual(app.state, .notRunning)

            app.launchArguments = arguments(phase: "recover")
            app.launch()
            let recover = app.buttons["recovery-process-recover"]
            XCTAssertTrue(recover.waitForExistence(timeout: 15), "Persisted operation \(stage)")
            XCTAssertNotEqual(app.staticTexts["recovery-process-pid"].label, oldPID, "Must be a different process")
            XCTAssertEqual(app.staticTexts["recovery-process-original-key"].label, originalKey, "Must retain the pre-termination key")
            recover.tap()
            XCTAssertTrue(app.staticTexts["recovery-process-complete"].waitForExistence(timeout: 15), "Recovery \(stage)")
            XCTAssertEqual(app.staticTexts["recovery-process-server-count"].label, "1")
            XCTAssertEqual(app.staticTexts["recovery-process-key-match"].label, "true")
            XCTAssertEqual(app.staticTexts["recovery-process-pending"].label, "none")
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.name = "Recuperacion-proceso-\(stage)"
            screenshot.lifetime = .keepAlways
            add(screenshot)
            app.buttons["recovery-process-cleanup"].tap()
            XCTAssertTrue(app.staticTexts["recovery-process-cleaned"].waitForExistence(timeout: 5))
            app.terminate()
        }
    }
}
#endif
