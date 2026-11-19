import Foundation
import IAERPClient
import IAERPIdentity
import Testing
@testable import IAERP

@MainActor private final class CustomerJournalTestVault: InvoiceRecoveryVault {
    var data: Data?
    func read() throws -> Data? { data }
    func write(_ data: Data) throws { self.data = data }
}

@MainActor
@Suite("Recuperación de altas de cliente")
struct CustomerRegistrationJournalTests {
    private func scope(subject: String, company: UUID, client: String = "iaerp-ios") throws -> CustomerCatalogScope {
        let config = try IdentityConfiguration(apiBaseURL: URL(string: "https://erp.example.invalid/api/v1")!,
                                               issuerURL: URL(string: "https://login.example.invalid/realms/test")!,
                                               clientID: client, organizationAlias: "empresa-prueba")
        return .live(InvoiceRecoveryScope(profileID: UUID(), configuration: config, subject: subject,
                                         organizationID: "empresa-prueba", tenantID: company))
    }

    private let input = ERPCustomerRegistrationInput(identificationType: "RUC", identificationNumber: "1790000723001", name: "Taller Sintético")

    @Test func ambiguousAttemptSurvivesReopeningAndIsScopedToFinancialIdentity() throws {
        let vault = CustomerJournalTestVault()
        let company = UUID()
        let scopeA = try scope(subject: "perfil-a", company: company)
        let original = try CustomerRegistrationJournal(vault: vault).begin(input, scope: scopeA, persist: true)
        let reopened = CustomerRegistrationJournal(vault: vault)
        let same = try scope(subject: "perfil-a", company: company)
        let pending = try #require(try reopened.pending(in: same, persist: true))
        #expect(pending.id == original.id)
        #expect(pending.input == input)
        #expect(pending.scope.allowsRetry(in: same))
        #expect(throws: ERPClientError.self) { try reopened.begin(input, scope: same, persist: true) }
        let changedClient = try scope(subject: "perfil-a", company: company, client: "iaerp-ios-otro")
        #expect(try reopened.pending(in: changedClient, persist: true)?.id == original.id)
        #expect(!pending.scope.allowsRetry(in: changedClient))
        #expect(try reopened.pending(in: scope(subject: "perfil-b", company: company), persist: true) == nil)
        #expect(try reopened.pending(in: scope(subject: "perfil-a", company: UUID()), persist: true) == nil)
        try reopened.finish(pending, persist: true)
        #expect(try reopened.pending(in: same, persist: true) == nil)
    }

    @Test func ephemeralDemoDoesNotWriteToVaultOrReadAnotherCompany() throws {
        let vault = CustomerJournalTestVault()
        let journal = CustomerRegistrationJournal(vault: vault)
        let company = CustomerCatalogScope.demo(UUID())
        let first = try journal.begin(input, scope: company, persist: false)
        #expect(try journal.pending(in: company, persist: false)?.id == first.id)
        #expect(try journal.pending(in: .demo(UUID()), persist: false) == nil)
        #expect(vault.data == nil)
        journal.clearEphemeral()
        #expect(try journal.pending(in: company, persist: false) == nil)
    }
}
