import Foundation

public protocol ERPCustomerRegistrationService: Sendable {
    /// A missing record is nil. An unavailable or non-customer identity must not be interpreted as missing.
    func findCustomer(identificationType: String, identificationNumber: String) async throws -> ERPParty?
    func createCustomer(_ input: ERPCustomerRegistrationInput, idempotencyKey: String) async throws -> ERPParty
}

struct CustomerIdentification: Codable, Equatable, Sendable {
    let identificationType: String
    let identificationNumber: String

    init(type: String, number: String) throws {
        identificationType = type.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        identificationNumber = number.trimmingCharacters(in: .whitespacesAndNewlines)
        guard ["RUC", "CEDULA"].contains(identificationType),
              identificationNumber.utf8.count == (identificationType == "RUC" ? 13 : 10),
              identificationNumber.utf8.allSatisfy({ (48...57).contains($0) }) else {
            throw ERPClientError.invalidInput("Revisa el RUC de 13 dígitos o la cédula de 10 dígitos.")
        }
    }
    func matches(_ party: ERPParty) -> Bool {
        party.identificationType == identificationType && party.identificationNumber == identificationNumber
    }
}

public struct ERPCustomerRegistrationInput: Codable, Equatable, Sendable {
    public var identificationType: String
    public var identificationNumber: String
    public var name: String
    public var address: String?
    public var email: String?

    public init(identificationType: String, identificationNumber: String, name: String, address: String? = nil, email: String? = nil) {
        self.identificationType = identificationType
        self.identificationNumber = identificationNumber
        self.name = name
        self.address = address
        self.email = email
    }

    public func validated() throws -> Self {
        let id = try CustomerIdentification(type: identificationType, number: identificationNumber)
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let address = address?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let email = email?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !name.isEmpty, name.count <= 200, address.count <= 500 else {
            throw ERPClientError.invalidInput("Revisa el nombre y la dirección del cliente.")
        }
        if !email.isEmpty {
            let parts = email.split(separator: "@", omittingEmptySubsequences: false)
            guard parts.count == 2, !parts[0].isEmpty, !parts[1].isEmpty,
                  email.count <= 254, email.rangeOfCharacter(from: .whitespacesAndNewlines) == nil else {
                throw ERPClientError.invalidInput("Revisa el correo del cliente.")
            }
        }
        return Self(identificationType: id.identificationType, identificationNumber: id.identificationNumber,
                    name: name, address: address.isEmpty ? nil : address, email: email.isEmpty ? nil : email)
    }
}
