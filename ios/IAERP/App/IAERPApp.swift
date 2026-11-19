import SwiftUI

@main
struct IAERPApp: App {
    var body: some Scene {
        WindowGroup {
            Group {
                #if DEBUG && targetEnvironment(simulator)
                if ProcessInfo.processInfo.arguments.contains("-production-delivery-fixture") {
                    ProductionDeliveryFixtureView()
                } else if ProcessInfo.processInfo.arguments.contains("-invoice-recovery-process-fixture") {
                    InvoiceRecoveryProcessFixture()
                } else if ProcessInfo.processInfo.arguments.contains("-legacy-demo") {
                    DemoClientsView()
                } else {
                    WorkspaceRootView()
                }
                #else
                WorkspaceRootView()
                #endif
            }
                .tint(Color("AccentColor"))
        }
    }
}
