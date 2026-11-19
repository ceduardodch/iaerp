import Foundation
import IAERPClient

enum CustomerCatalogScope: Codable, Equatable {
    case live(InvoiceRecoveryScope)
    case demo(UUID)

    func includes(_ other: Self) -> Bool {
        if case .live(let a) = self, case .live(let b) = other {
            return a.representsSameFinancialIdentity(as: b)
        }
        return self == other
    }

    func allowsRetry(in other: Self) -> Bool {
        if case .live(let a) = self, case .live(let b) = other {
            return a.representsSameIdentity(as: b)
        }
        return self == other
    }
}

struct CustomerRegistrationAttempt: Codable, Identifiable {
    let id: UUID
    let scope: CustomerCatalogScope
    let input: ERPCustomerRegistrationInput
}

@MainActor final class CustomerRegistrationJournal {
    private let vault: any InvoiceRecoveryVault
    private var ephemeral: [CustomerRegistrationAttempt] = []

    init(vault: any InvoiceRecoveryVault = KeychainInvoiceRecoveryVault(service: "ec.com.b2b.iaerp.customer-registration")) {
        self.vault = vault
    }

    func clearEphemeral() { ephemeral.removeAll() }

    private func read(persist: Bool) throws -> [CustomerRegistrationAttempt] {
        guard persist else { return ephemeral }
        guard let data = try vault.read() else { return [] }
        do { return try JSONDecoder().decode([CustomerRegistrationAttempt].self, from: data) }
        catch { throw InvoiceRecoveryError.storageFailure }
    }

    private func write(_ records: [CustomerRegistrationAttempt], persist: Bool) throws {
        if persist { try vault.write(JSONEncoder().encode(records)) }
        else { ephemeral = records }
    }

    func pending(in scope: CustomerCatalogScope, persist: Bool) throws -> CustomerRegistrationAttempt? {
        try read(persist: persist).first { scope.includes($0.scope) }
    }

    func begin(_ input: ERPCustomerRegistrationInput, scope: CustomerCatalogScope, persist: Bool) throws -> CustomerRegistrationAttempt {
        var records = try read(persist: persist)
        guard !records.contains(where: { scope.includes($0.scope) }) else {
            throw ERPClientError.invalidInput("Hay un alta pendiente. Consulta su estado antes de guardar.")
        }
        let attempt = CustomerRegistrationAttempt(id: UUID(), scope: scope, input: input)
        records.append(attempt)
        try write(records, persist: persist)
        return attempt
    }

    func finish(_ attempt: CustomerRegistrationAttempt, persist: Bool) throws {
        var records = try read(persist: persist)
        records.removeAll { $0.id == attempt.id && attempt.scope.includes($0.scope) }
        try write(records, persist: persist)
    }
}

extension WorkspaceStore {
    var canRegisterCustomer: Bool {
        context?.permits("customers:create") == true && context?.permits("parties:read") == true
            && service is any ERPCustomerRegistrationService
    }

    var persistsCustomerRegistration: Bool { !isDemo || persistsDemoDelivery }

    func customerRegistrationScope() throws -> CustomerCatalogScope {
        guard canRegisterCustomer, phase == .ready, let context else { throw ERPClientError.forbidden }
        return isDemo ? .demo(context.tenantId) : .live(try currentInvoiceRecoveryScope())
    }
}
