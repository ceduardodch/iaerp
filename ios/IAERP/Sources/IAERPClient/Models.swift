import Foundation

/// The API's Decimal contract is a JSON string. No conversion through Double.
@propertyWrapper
public struct ERPDecimal: Codable, Equatable, Sendable {
    public var wrappedValue: Decimal
    public init(wrappedValue: Decimal) { self.wrappedValue = wrappedValue }
    public init(from decoder: any Decoder) throws {
        let box = try decoder.singleValueContainer()
        let text = try box.decode(String.self)
        guard !text.isEmpty, text.utf8.count <= 64, text.filter(\.isNumber).count <= 38, text.range(of: #"^-?[0-9]+(\.[0-9]+)?$"#, options: .regularExpression) != nil,
              let value = Decimal(string: text, locale: Locale(identifier: "en_US_POSIX")), !value.isNaN else {
            throw DecodingError.dataCorruptedError(in: box, debugDescription: "Invalid decimal string")
        }
        wrappedValue = value
    }
    public func encode(to encoder: any Encoder) throws {
        guard !wrappedValue.isNaN else { throw ERPClientError.invalidInput("Importe no válido.") }
        var box = encoder.singleValueContainer()
        try box.encode(NSDecimalNumber(decimal: wrappedValue).stringValue)
    }
}

public enum ERPClientError: Error, Equatable, Sendable, LocalizedError {
    case invalidConfiguration, authenticationRequired, forbidden, notFound, invalidResponse
    case rateLimited(retryAfter: Int?)
    case server(Int)
    case invalidInput(String)
    case customerIdentificationUnavailable, customerRegistrationConflict
    case productCodeUnavailable, productRegistrationConflict
    case fixtureUnsupported
    case idempotencyConflict
    case unsupportedOverviewCurrency
    case documentTooLarge
    public var errorDescription: String? {
        switch self {
        case .invalidConfiguration: "Revisa la configuración de conexión."
        case .authenticationRequired: "Tu sesión terminó. Vuelve a entrar."
        case .forbidden: "No tienes permiso para esta acción."
        case .notFound: "El registro ya no está disponible."
        case .invalidResponse: "El servidor devolvió una respuesta no válida."
        case .rateLimited(let seconds): seconds.map { "Espera \($0) segundos antes de reintentar." } ?? "Espera antes de reintentar."
        case .server: "El servicio no está disponible. Inténtalo más tarde."
        case .invalidInput(let message): message
        case .productCodeUnavailable: "El código corresponde a un producto inactivo."
        case .productRegistrationConflict: "El producto ya existe o cambió la solicitud. Consulta el código para continuar."
        case .customerIdentificationUnavailable: "Esta identificación ya existe y no está disponible como cliente."
        case .customerRegistrationConflict: "El registro ya existe o cambió la solicitud. Consulta la identificación antes de continuar."
        case .fixtureUnsupported: "La demo admite los productos de ejemplo, cantidades 1, 2 o 3, sus precios originales y descuento cero."
        case .unsupportedOverviewCurrency: "La cartera incluye cuentas en otra moneda. El resumen está disponible para cartera en dólares."
        case .idempotencyConflict: "La operación cambió. Revisa el borrador antes de guardarlo otra vez."
        case .documentTooLarge: "El documento supera el tamaño permitido."
        }
    }
}

public struct ERPContext: Codable, Equatable, Sendable {
    public let tenantId: UUID
    public let ruc: String
    public let name: String
    public let roles: [String]
    public let scopes: [String]
    public let automationWritesEnabled: Bool
    public let defaultPaymentTermsDays: Int
    public init(tenantId: UUID, ruc: String, name: String, roles: [String], scopes: [String], automationWritesEnabled: Bool = false, defaultPaymentTermsDays: Int = 0) {
        self.tenantId = tenantId; self.ruc = ruc; self.name = name; self.roles = roles; self.scopes = scopes
        self.automationWritesEnabled = automationWritesEnabled; self.defaultPaymentTermsDays = defaultPaymentTermsDays
    }
    public func permits(_ scope: String) -> Bool { scopes.contains(scope) }
}

public struct ERPMembership: Codable, Equatable, Identifiable, Sendable {
    public var id: UUID { tenantId }
    public let tenantId: UUID
    public let organizationId: String?
    public let ruc: String
    public let tenantName: String
    public let roles: [String]
    public let active: Bool
    public init(tenantId: UUID, organizationId: String?, ruc: String, tenantName: String, roles: [String], active: Bool) {
        self.tenantId = tenantId; self.organizationId = organizationId; self.ruc = ruc; self.tenantName = tenantName
        self.roles = roles; self.active = active
    }
}

public struct ERPParty: Codable, Equatable, Identifiable, Sendable {
    public let id: UUID
    public let name: String
    public let identificationType: String
    public let identificationNumber: String
    public let roles: [String]
    public let email: String?
    public let phone: String?
    public let address: String?
    public let paymentTermsDays: Int?
    public init(id: UUID, name: String, identificationType: String, identificationNumber: String, roles: [String] = ["CUSTOMER"], email: String? = nil, phone: String? = nil, address: String? = nil, paymentTermsDays: Int? = nil) {
        self.id = id; self.name = name; self.identificationType = identificationType; self.identificationNumber = identificationNumber
        self.roles = roles; self.email = email; self.phone = phone; self.address = address; self.paymentTermsDays = paymentTermsDays
    }
}

public struct ERPProduct: Codable, Equatable, Identifiable, Sendable {
    public let id: UUID
    public let name: String
    public let code: String?
    @ERPDecimal public var unitPrice: Decimal
    public let taxCategoryId: UUID
    public init(id: UUID, name: String, code: String? = nil, unitPrice: Decimal, taxCategoryId: UUID) {
        self.id = id; self.name = name; self.code = code; self.unitPrice = unitPrice; self.taxCategoryId = taxCategoryId
    }
}

public struct ERPEstablishment: Codable, Equatable, Identifiable, Sendable {
    public let id: UUID
    public let code: String
    public let name: String
    public let address: String
    public let active: Bool
    public init(id: UUID, code: String, name: String, address: String, active: Bool = true) {
        self.id = id; self.code = code; self.name = name; self.address = address; self.active = active
    }
}
public struct ERPEmissionPoint: Codable, Equatable, Identifiable, Sendable {
    public let id: UUID
    public let establishmentId: UUID
    public let code: String
    public let active: Bool
    public init(id: UUID, establishmentId: UUID, code: String, active: Bool = true) {
        self.id = id; self.establishmentId = establishmentId; self.code = code; self.active = active
    }
}
public struct ERPTaxCategory: Codable, Equatable, Identifiable, Sendable {
    public let id: UUID
    public let sriCode: String
    public let name: String
    @ERPDecimal public var rate: Decimal
    public let validFrom: String
    public let validTo: String?
    public let active: Bool
    public init(id: UUID, sriCode: String, name: String, rate: Decimal, validFrom: String, validTo: String? = nil, active: Bool = true) {
        self.id = id; self.sriCode = sriCode; self.name = name; self.rate = rate; self.validFrom = validFrom; self.validTo = validTo; self.active = active
    }
    public func isValid(on date: String) -> Bool { active && validFrom <= date && (validTo == nil || date <= validTo!) }
}
public struct ERPInvoiceSetup: Equatable, Sendable {
    public let establishments: [ERPEstablishment]
    public let emissionPoints: [ERPEmissionPoint]
    public let taxCategories: [ERPTaxCategory]
    public init(establishments: [ERPEstablishment], emissionPoints: [ERPEmissionPoint], taxCategories: [ERPTaxCategory]) {
        self.establishments = establishments; self.emissionPoints = emissionPoints; self.taxCategories = taxCategories
    }
}

public struct ERPInvoiceLineInput: Codable, Equatable, Identifiable, Sendable {
    /// Local identity is not serialized to the backend.
    public var id: UUID { localID }
    private var localID: UUID = UUID()
    public var productId: UUID?
    public var description: String
    @ERPDecimal public var quantity: Decimal
    @ERPDecimal public var unitPrice: Decimal
    @ERPDecimal public var discount: Decimal
    public var taxCode: String
    enum CodingKeys: String, CodingKey { case productId, description, quantity, unitPrice, discount, taxCode }
    public init(productId: UUID? = nil, description: String, quantity: Decimal, unitPrice: Decimal, discount: Decimal = 0, taxCode: String) {
        self.productId = productId; self.description = description; self.quantity = quantity; self.unitPrice = unitPrice; self.discount = discount; self.taxCode = taxCode
    }
    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.productId == rhs.productId && lhs.description == rhs.description && lhs.quantity == rhs.quantity && lhs.unitPrice == rhs.unitPrice && lhs.discount == rhs.discount && lhs.taxCode == rhs.taxCode
    }
}
public struct ERPInstallment: Codable, Equatable, Sendable {
    public var dueDate: String
    @ERPDecimal public var amount: Decimal
    public init(dueDate: String, amount: Decimal) { self.dueDate = dueDate; self.amount = amount }
}
public struct ERPPreviewInput: Codable, Equatable, Sendable {
    public var issueDate: String
    public var lines: [ERPInvoiceLineInput]
    public init(issueDate: String, lines: [ERPInvoiceLineInput]) { self.issueDate = issueDate; self.lines = lines }
}
public struct ERPInvoiceInput: Codable, Equatable, Sendable {
    public var customerId: UUID
    public var establishmentId: UUID
    public var emissionPointId: UUID
    public var issueDate: String
    public var installments: [ERPInstallment]
    public var lines: [ERPInvoiceLineInput]
    public var collectionEnabled: Bool
    public var analyticValueIds: [UUID]
    public init(customerId: UUID, establishmentId: UUID, emissionPointId: UUID, issueDate: String, lines: [ERPInvoiceLineInput], installments: [ERPInstallment] = [], collectionEnabled: Bool = false, analyticValueIds: [UUID] = []) {
        self.customerId = customerId; self.establishmentId = establishmentId; self.emissionPointId = emissionPointId; self.issueDate = issueDate; self.lines = lines; self.installments = installments; self.collectionEnabled = collectionEnabled; self.analyticValueIds = analyticValueIds
    }
}
public struct ERPPreviewLine: Codable, Equatable, Sendable {
    public let description: String
    @ERPDecimal public var quantity: Decimal
    @ERPDecimal public var unitPrice: Decimal
    @ERPDecimal public var discount: Decimal
    @ERPDecimal public var baseAmount: Decimal
    public let taxCode: String
    @ERPDecimal public var taxRate: Decimal
    @ERPDecimal public var taxAmount: Decimal
    @ERPDecimal public var total: Decimal
    public init(description: String, quantity: Decimal, unitPrice: Decimal, discount: Decimal, baseAmount: Decimal, taxCode: String, taxRate: Decimal, taxAmount: Decimal, total: Decimal) {
        self.description = description; self.quantity = quantity; self.unitPrice = unitPrice; self.discount = discount; self.baseAmount = baseAmount; self.taxCode = taxCode; self.taxRate = taxRate; self.taxAmount = taxAmount; self.total = total
    }
}
public struct ERPInvoicePreview: Codable, Equatable, Sendable {
    public let lines: [ERPPreviewLine]
    @ERPDecimal public var subtotal: Decimal
    @ERPDecimal public var taxTotal: Decimal
    @ERPDecimal public var total: Decimal
    public init(lines: [ERPPreviewLine], subtotal: Decimal, taxTotal: Decimal, total: Decimal) {
        self.lines = lines; self.subtotal = subtotal; self.taxTotal = taxTotal; self.total = total
    }
}
public struct ERPInvoiceLine: Codable, Equatable, Identifiable, Sendable {
    public let id: UUID
    public let lineNumber: Int
    public let productId: UUID?
    public let description: String
    @ERPDecimal public var quantity: Decimal
    @ERPDecimal public var unitPrice: Decimal
    @ERPDecimal public var discount: Decimal
    @ERPDecimal public var baseAmount: Decimal
    public let taxCode: String
    @ERPDecimal public var taxRate: Decimal
    @ERPDecimal public var taxAmount: Decimal
    public init(id: UUID, lineNumber: Int, productId: UUID?, description: String, quantity: Decimal, unitPrice: Decimal, discount: Decimal, baseAmount: Decimal, taxCode: String, taxRate: Decimal, taxAmount: Decimal) {
        self.id = id; self.lineNumber = lineNumber; self.productId = productId; self.description = description; self.quantity = quantity; self.unitPrice = unitPrice; self.discount = discount; self.baseAmount = baseAmount; self.taxCode = taxCode; self.taxRate = taxRate; self.taxAmount = taxAmount
    }
}
public struct ERPSRITransmission: Codable, Equatable, Sendable {
    public let status: String
    public let message: String?
    public let lastAttemptAt: String
    public let authorizationNumber: String?
    public init(status: String, message: String? = nil, lastAttemptAt: String, authorizationNumber: String? = nil) {
        self.status = status; self.message = message; self.lastAttemptAt = lastAttemptAt; self.authorizationNumber = authorizationNumber
    }
}
public struct ERPInvoice: Codable, Equatable, Identifiable, Sendable {
    public let id: UUID
    public let type: String
    public internal(set) var status: String
    public let sequential: String
    public let issueDate: String
    public internal(set) var accessKey: String?
    @ERPDecimal public var subtotal: Decimal
    @ERPDecimal public var tax: Decimal
    @ERPDecimal public var total: Decimal
    public let currency: String
    public let partyId: UUID
    public let establishmentId: UUID
    public let emissionPointId: UUID
    public let fiscalPolicyVersion: String
    public let reason: String?
    public internal(set) var authorizationNumber: String?
    public internal(set) var authorizedAt: String?
    public internal(set) var sriTransmission: ERPSRITransmission?
    public let collectionStatus: String?
    public let collectionEnabled: Bool
    public let lines: [ERPInvoiceLine]
    public let installments: [ERPInstallment]
    public init(id: UUID, type: String = "INVOICE", status: String, sequential: String, issueDate: String, accessKey: String? = nil, subtotal: Decimal, tax: Decimal, total: Decimal, currency: String = "USD", partyId: UUID, establishmentId: UUID, emissionPointId: UUID, fiscalPolicyVersion: String = "demo-fixture", reason: String? = nil, authorizationNumber: String? = nil, authorizedAt: String? = nil, sriTransmission: ERPSRITransmission? = nil, collectionStatus: String? = nil, collectionEnabled: Bool = false, lines: [ERPInvoiceLine] = [], installments: [ERPInstallment] = []) {
        self.id = id; self.type = type; self.status = status; self.sequential = sequential; self.issueDate = issueDate; self.accessKey = accessKey; self.subtotal = subtotal; self.tax = tax; self.total = total; self.currency = currency; self.partyId = partyId; self.establishmentId = establishmentId; self.emissionPointId = emissionPointId; self.fiscalPolicyVersion = fiscalPolicyVersion; self.reason = reason; self.authorizationNumber = authorizationNumber; self.authorizedAt = authorizedAt; self.sriTransmission = sriTransmission; self.collectionStatus = collectionStatus; self.collectionEnabled = collectionEnabled; self.lines = lines; self.installments = installments
    }
}
public struct ERPArtifact: Codable, Equatable, Identifiable, Sendable {
    public let id: UUID
    public let artifactType: String
    public let sha256: String
    public let version: Int
    public let createdAt: String
    public init(id: UUID, artifactType: String, sha256: String, version: Int, createdAt: String) {
        self.id = id; self.artifactType = artifactType; self.sha256 = sha256; self.version = version; self.createdAt = createdAt
    }
}
public struct ERPArtifactDownload: Codable, Equatable, Sendable {
    public let downloadUrl: String
    public let expiresInSeconds: Int
    public let fileName: String
    public init(downloadUrl: String, expiresInSeconds: Int, fileName: String) { self.downloadUrl = downloadUrl; self.expiresInSeconds = expiresInSeconds; self.fileName = fileName }
}
public struct ERPDocument: Codable, Equatable, Sendable {
    public let data: Data
    public let fileName: String
    public let mimeType: String
    public init(data: Data, fileName: String, mimeType: String) { self.data = data; self.fileName = fileName; self.mimeType = mimeType }
}

public protocol ERPService: Sendable {
    func context() async throws -> ERPContext
    func memberships() async throws -> [ERPMembership]
    func customers(query: String) async throws -> [ERPParty]
    func products(query: String) async throws -> [ERPProduct]
    func invoiceSetup() async throws -> ERPInvoiceSetup
    func invoices(query: String, status: String?) async throws -> [ERPInvoice]
    func invoice(id: UUID) async throws -> ERPInvoice
    func preview(_ input: ERPPreviewInput) async throws -> ERPInvoicePreview
    func createDraft(_ input: ERPInvoiceInput, idempotencyKey: String) async throws -> ERPInvoice
    func artifacts(invoiceID: UUID) async throws -> [ERPArtifact]
    func document(invoiceID: UUID, artifact: ERPArtifact) async throws -> ERPDocument
}
