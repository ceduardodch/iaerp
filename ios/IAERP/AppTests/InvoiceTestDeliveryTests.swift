import Foundation
import IAERPClient
import IAERPIdentity
import Testing
@testable import IAERP

@MainActor private final class TestDeliveryMemoryVault: InvoiceRecoveryVault {
    var contents: Data?
    var failWrite = false
    func read() throws -> Data? { contents }
    func write(_ data: Data) throws {
        if failWrite { throw InvoiceRecoveryError.storageFailure }
        contents = data
    }
}

@MainActor
@Suite("Acciones de factura en pruebas")
struct InvoiceTestDeliveryTests {
    private func scope(_ subject: String, tenant: UUID = DemoCompany.primary.tenantId) throws -> InvoiceRecoveryScope {
        let config = try IdentityConfiguration(apiBaseURL: URL(string: "https://api.example.invalid/api/v1")!,
                                               issuerURL: URL(string: "https://accounts.example.invalid/realms/test")!,
                                               clientID: "iaerp-ios-test", organizationAlias: "empresa-prueba")
        return InvoiceRecoveryScope(profileID: UUID(), configuration: config, subject: subject,
                                    organizationID: "empresa-prueba", tenantID: tenant)
    }

    @Test func reopeningKeepsUnconfirmedEmailAndBlocksAnotherWrite() throws {
        let vault = TestDeliveryMemoryVault()
        let first = InvoiceTestAttemptJournal(vault: vault)
        let invoice = UUID()
        let account = try scope("perfil-a")
        let original = try first.begin(.email, invoiceID: invoice, scope: account)
        #expect(UUID(uuidString: original) != nil)
        let next = InvoiceTestAttemptJournal(vault: vault)
        let sameAccount = try scope("perfil-a")
        #expect(try next.pending(invoiceID: invoice, scope: sameAccount) == .email)
        #expect(throws: InvoiceRecoveryError.pendingOperation) {
            try next.begin(.email, invoiceID: invoice, scope: sameAccount)
        }
        try next.finish(.issue, invoiceID: invoice, scope: sameAccount)
        #expect(try next.pending(invoiceID: invoice, scope: sameAccount) == .email)
        try next.finish(.email, invoiceID: invoice, scope: sameAccount)
        #expect(try next.pending(invoiceID: invoice, scope: sameAccount) == nil)
    }

    @Test func journalSeparatesAccountsCompaniesDocumentsAndDemo() throws {
        let journal = InvoiceTestAttemptJournal(vault: TestDeliveryMemoryVault())
        let invoice = UUID()
        let owner = try scope("perfil-a")
        let other = try scope("perfil-b")
        let secondCompany = try scope("perfil-a", tenant: DemoCompany.secondary.tenantId)
        _ = try journal.begin(.issue, invoiceID: invoice, scope: owner)
        for scope in [other, secondCompany] {
            #expect(try journal.pending(invoiceID: invoice, scope: scope) == nil)
            try journal.finish(.issue, invoiceID: invoice, scope: scope)
        }
        #expect(try journal.pending(invoiceID: UUID(), scope: owner) == nil)
        _ = try journal.begin(.email, invoiceID: invoice, scope: nil)
        journal.clearDemo()
        #expect(try journal.pending(invoiceID: invoice, scope: nil) == nil)
        #expect(try journal.pending(invoiceID: invoice, scope: owner) == .issue)
    }

    @Test func retryReusesTheOriginalKeyAndExactRecipientForTheSameIdentity() throws {
        let vault = TestDeliveryMemoryVault()
        let journal = InvoiceTestAttemptJournal(vault: vault)
        let invoice = UUID()
        let account = try scope("perfil-a")
        let mailbox = "buzon@iaerp.example.org"
        let key = try journal.begin(.email, invoiceID: invoice, scope: account, recipient: mailbox)
        let reopened = InvoiceTestAttemptJournal(vault: vault)
        #expect(try reopened.retryKey(.email, invoiceID: invoice, scope: scope("perfil-a"), recipient: mailbox) == key)
        #expect(throws: InvoiceRecoveryError.reconciliationRequired) {
            try reopened.retryKey(.email, invoiceID: invoice, scope: scope("perfil-b"), recipient: mailbox)
        }
        #expect(throws: InvoiceRecoveryError.reconciliationRequired) {
            try reopened.retryKey(.email, invoiceID: invoice, scope: scope("perfil-a", tenant: DemoCompany.secondary.tenantId), recipient: mailbox)
        }
        #expect(throws: InvoiceRecoveryError.reconciliationRequired) {
            try reopened.retryKey(.email, invoiceID: invoice, scope: account, recipient: "otro@example.invalid")
        }
        #expect(throws: InvoiceRecoveryError.reconciliationRequired) {
            try reopened.retryKey(.issue, invoiceID: invoice, scope: account, recipient: nil)
        }
    }

    @Test func retryRequiresCurrentServerPermissionAndAnUncompletedEffect() {
        let mailbox = "buzon@iaerp.example.org"
        func snapshot(_ issue: Bool, _ email: Bool, environment: String = "TEST", transmission: String = "simulator",
                      received: Bool = false) -> ERPTestInvoiceActions {
            ERPTestInvoiceActions(environment: environment, transmissionMode: transmission,
                                  canIssue: issue, canEmail: email, captureRecipient: mailbox,
                                  emailReceipt: received ? ERPTestEmailReceipt(messageId: "demo", recipient: mailbox,
                                      attachmentNames: ["ejemplo.pdf", "ejemplo.xml"]) : nil)
        }
        #expect(InvoiceTestAction.issue.serverAllowsRetry(status: "DRAFT", actions: snapshot(true, false)))
        #expect(!InvoiceTestAction.issue.serverAllowsRetry(status: "SIGNED", actions: snapshot(true, false)))
        #expect(!InvoiceTestAction.issue.serverAllowsRetry(status: "DRAFT", actions: snapshot(false, false)))
        #expect(!InvoiceTestAction.issue.serverAllowsRetry(status: "DRAFT", actions: snapshot(true, false, environment: "PRODUCTION")))
        #expect(!InvoiceTestAction.issue.serverAllowsRetry(status: "DRAFT", actions: snapshot(true, false, transmission: "soap")))
        #expect(InvoiceTestAction.email.serverAllowsRetry(status: "AUTHORIZED", actions: snapshot(false, true)))
        #expect(!InvoiceTestAction.email.serverAllowsRetry(status: "DRAFT", actions: snapshot(false, true)))
        #expect(!InvoiceTestAction.email.serverAllowsRetry(status: "AUTHORIZED", actions: snapshot(false, false)))
        #expect(!InvoiceTestAction.email.serverAllowsRetry(status: "AUTHORIZED", actions: snapshot(false, true, received: true)))
    }

    @Test func failedSecureWritePreventsObtainingAKey() throws {
        let vault = TestDeliveryMemoryVault()
        vault.failWrite = true
        let journal = InvoiceTestAttemptJournal(vault: vault)
        let account = try scope("perfil-a")
        #expect(throws: InvoiceRecoveryError.storageFailure) {
            try journal.begin(.issue, invoiceID: UUID(), scope: account)
        }
        #expect(vault.contents == nil)
    }
}
