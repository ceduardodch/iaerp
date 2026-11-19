import Foundation

public protocol ERPCatalogProductRegistrationService: Sendable {
    func findProduct(code: String) async throws -> ERPProduct?
    func createProduct(_ input: ERPProductRegistrationInput, idempotencyKey: String) async throws -> ERPProduct
}

public struct ERPProductRegistrationInput: Codable, Equatable, Sendable {
    public var code: String
    public var name: String
    @ERPDecimal public var unitPrice: Decimal
    public var taxCategoryId: UUID

    public init(code: String, name: String, unitPrice: Decimal, taxCategoryId: UUID) {
        self.code = code
        self.name = name
        self.unitPrice = unitPrice
        self.taxCategoryId = taxCategoryId
    }

    static func validatedCode(_ code: String) throws -> String {
        let value = code.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, value.count <= 80 else {
            throw ERPClientError.invalidInput("Escribe un código de hasta 80 caracteres.")
        }
        return value
    }

    public func validated() throws -> Self {
        let code = try Self.validatedCode(code)
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, name.count <= 300 else { throw ERPClientError.invalidInput("Revisa el nombre del producto.") }
        guard ERPInputValidation.validDecimal(unitPrice, positive: false, integerDigits: 12, fractionDigits: 6) else {
            throw ERPClientError.invalidInput("Revisa el precio. Admite hasta seis decimales.")
        }
        return Self(code: code, name: name, unitPrice: unitPrice, taxCategoryId: taxCategoryId)
    }
}
