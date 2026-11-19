import CryptoKit
import Foundation
import IAERPClient
import Testing
import UIKit
@testable import IAERP

@Suite("Formulario y privacidad") @MainActor
struct WorkspaceStateTests {
    @Test func invoiceDetailGivesNextStepsForRealAndSimulatedStates() async {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = WorkspaceStore(documents: TemporaryDocuments(root: root))
        let detail = WorkspaceInvoiceDetail(store: store, invoiceId: UUID())
        #expect(detail.statusGuidance(for: "DRAFT")?.contains("IAERP web") == true)
        #expect(detail.statusGuidance(for: "AUTHORIZED")?.contains("Preparar correo") == true)
        #expect(detail.statusGuidance(for: "PENDING_AUTHORIZATION")?.contains("consultar el estado") == true)
        #expect(detail.statusGuidance(for: "REJECTED")?.contains("mensaje de transmisión") == true)
        #expect(detail.statusGuidance(for: "VOIDED") == nil)
        await store.startDemo()
        #expect(detail.statusGuidance(for: "DRAFT") == nil)
        await store.startDemo(readOnly: true)
        #expect(detail.statusGuidance(for: "DRAFT")?.contains("sólo permite consultar") == true)
    }

    @Test(arguments: ["1,25", "1.25", "0", "999999.123456"])
    func decimalEntryIsExact(_ text: String) {
        #expect(DecimalEntry.parse(text) == Decimal(string: text.replacingOccurrences(of: ",", with: ".")))
    }
    @Test(arguments: ["1,000.25", "1e3", "-1", "NaN", "0.1234567", "", "12."])
    func ambiguousMoneyIsRejected(_ text: String) { #expect(DecimalEntry.parse(text) == nil) }

    @Test func reviewInvalidatesAfterChangingInputAndSaveRequiresPreview() async throws {
        let service = DemoERPService()
        let setup = try await service.invoiceSetup()
        let product = try #require(try await service.products(query: "").first)
        let customer = try #require(try await service.customers(query: "").first)
        let composer = InvoiceComposer(customerId: customer.id)
        composer.establishmentId = setup.establishments.first?.id
        composer.emissionPointId = setup.emissionPoints.first?.id
        composer.add(product, setup: setup)
        #expect(await composer.save(using: service, setup: setup) == nil)
        #expect(composer.pendingKey == nil)
        await composer.review(using: service, setup: setup)
        #expect(composer.preview?.total == 115)
        composer.lines[0].quantity = "2"
        composer.invalidatePreview()
        #expect(composer.preview == nil)
        #expect(await composer.save(using: service, setup: setup) == nil)
        await composer.review(using: service, setup: setup)
        #expect(composer.preview?.total == 230)
        let saved = await composer.save(using: service, setup: setup)
        #expect(saved?.status == "DRAFT")
        #expect(saved?.total == 230)
        #expect(await composer.save(using: service, setup: setup) == nil)
    }

    @Test func clearingWorkspaceInvalidatesSavedResults() async throws {
        let store = WorkspaceStore()
        await store.startDemo()
        let previous = store.generation
        let service = try #require(store.service)
        let invoice = try #require(try await service.invoices(query: "", status: nil).first)
        store.acceptSaved(invoice, generation: previous)
        await store.loadDashboard()
        await store.loadInvoices()
        let group = try #require(store.invoiceMonths.first)
        await store.loadInvoiceMonth(group)
        #expect(store.dashboard != nil)
        #expect(!store.invoiceMonths.isEmpty)
        #expect(store.monthRows[group.id]?.isEmpty == false)
        #expect(!store.invoices.isEmpty)
        store.clear()
        store.acceptSaved(invoice, generation: previous)
        #expect(store.context == nil)
        #expect(store.customers.isEmpty)
        #expect(store.invoices.isEmpty)
        #expect(store.dashboard == nil && store.dashboardError == nil)
        #expect(store.invoiceMonths.isEmpty && store.monthRows.isEmpty)
        #expect(store.monthErrors.isEmpty && store.loadingMonths.isEmpty && store.moreMonths.isEmpty)
        #expect(!store.loadingDashboard && !store.loadingInvoices)
        #expect(store.setup == nil)
    }

    @Test func documentResetPurgesRelaunchRemnantsAndRejectsOldSession() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("IAERP-test-\(UUID())")
        let vault = TemporaryDocuments(root: root)
        let epoch = UUID()
        try await vault.reset(generation: epoch)
        let file = try await vault.store(data: Data("<synthetic/>".utf8), fileName: "test.xml", generation: epoch)
        #expect(FileManager.default.fileExists(atPath: file.path))
        #expect(file.lastPathComponent == "test.xml")
        let duplicate = try await vault.store(data: Data("<other/>".utf8), fileName: "test.xml", generation: epoch)
        #expect(duplicate != file)
        #expect(try Data(contentsOf: file) == Data("<synthetic/>".utf8))
        let relaunched = TemporaryDocuments(root: root)
        let next = UUID()
        try await relaunched.reset(generation: next)
        #expect(!FileManager.default.fileExists(atPath: file.path))
        await #expect(throws: CancellationError.self) {
            _ = try await relaunched.store(data: Data(), fileName: "late.xml", generation: epoch)
        }
        try await relaunched.reset(generation: UUID())
    }

    @Test(arguments: ["../ride.pdf", "nested/ride.xml", "..\\ride.pdf", "ride.pdf\n", "ride.exe", ""])
    func unsafeDocumentNamesAreRejected(_ name: String) async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("IAERP-test-\(UUID())")
        let vault = TemporaryDocuments(root: root)
        let epoch = UUID()
        try await vault.reset(generation: epoch)
        await #expect(throws: CocoaError.self) {
            _ = try await vault.store(data: Data(), fileName: name, generation: epoch)
        }
        #expect(!FileManager.default.fileExists(atPath: root.path))
    }

    @Test func statusLabelsDoNotMisstateAuthorization() {
        #expect(ERPDisplay.status("RECEIVED") != ERPDisplay.status("AUTHORIZED"))
        #expect(ERPDisplay.status("HISTORICAL_ISSUED") == "Histórica")
        #expect(ERPDisplay.status("DRAFT") == "Borrador")
    }

    @Test func privacyCoverSitsAboveEveryVisibleAppWindow() throws {
        let windows = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows).filter { !$0.isHidden }
        #expect(!windows.isEmpty)
        PrivacyShield.update(visible: true)
        defer { PrivacyShield.update(visible: false) }
        for window in windows {
            let cover = try #require(window.viewWithTag(PrivacyShield.tag))
            #expect(window.subviews.last === cover)
            #expect(cover.frame == window.bounds)
            #expect(cover.alpha == 1)
            #expect(cover.backgroundColor?.cgColor.alpha == 1)
        }
        PrivacyShield.update(visible: false)
        #expect(windows.allSatisfy { $0.viewWithTag(PrivacyShield.tag) == nil })
    }
}

extension WorkspaceStateTests {
    @Test func onlyThisTrialsRejectionIsDisplayed() throws {
        let selectionFile = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: selectionFile) }
        let selection = Data("synthetic selection".utf8)
        let digest = SHA256.hash(data: selection).map { String(format: "%02x", $0) }.joined()
        let data = try JSONEncoder().encode(["selectionSHA256": digest, "reason": "customerOutsideTrial"])
        try selection.write(to: selectionFile)
        #expect(try PreparedBTOBTrial.read(data, matching: "other", selectionFile: selectionFile) == nil)
        #expect(try Data(contentsOf: selectionFile) == selection)
        for newerSelection in [true, false] {
            try (newerSelection ? Data("another selection".utf8) : selection).write(to: selectionFile)
            do {
                _ = try PreparedBTOBTrial.read(data, matching: digest, selectionFile: selectionFile)
                Issue.record("El cliente fuera del ensayo requiere un mensaje")
            } catch let error as ERPClientError {
                #expect(error.localizedDescription.contains("cliente"))
                #expect(FileManager.default.fileExists(atPath: selectionFile.path) == newerSelection)
            }
        }
    }

    @Test func connectionFieldsIdentifyTheCorrection() throws {
        func config(_ alias: String, _ host: String) throws {
            _ = try IAERPConnection.formConfiguration(api: "https://api.example.org", issuer: "https://login.example.org", client: "iaerp-ios", alias: alias, documentHost: host)
        }
        for (alias, host, field) in [("", "", "alias"), ("@", "", "Alias"), ("valid", "https://example.org", "Servidor de documentos")] {
            do {
                try config(alias, host)
                Issue.record("Debía señalar el campo")
            } catch {
                #expect(error.localizedDescription.contains(field))
            }
        }
        try config("valid", "")
    }
}
