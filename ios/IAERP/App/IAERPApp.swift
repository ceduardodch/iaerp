import SwiftUI

@main
struct IAERPApp: App {
    var body: some Scene {
        WindowGroup {
            Group {
                #if DEBUG && targetEnvironment(simulator)
                if ProcessInfo.processInfo.arguments.contains("-invoice-recovery-process-fixture") {
                    InvoiceRecoveryProcessFixture()
                } else { standardContent }
                #else
                standardContent
                #endif
            }
                .tint(Color("AccentColor"))
        }
    }

    @ViewBuilder private var standardContent: some View {
        if ProcessInfo.processInfo.arguments.contains("-legacy-demo") { DemoClientsView() }
        else { WorkspaceRootView() }
    }
}
