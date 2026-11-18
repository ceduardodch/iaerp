import Foundation

/// Read-only reconciliation of the caller's own tenant/actor-scoped request.
/// A missing record does not prove that a request outside its retention window
/// can be submitted again; the durable journal decides whether retry is safe.
public protocol ERPInvoiceDraftLookup: Sendable {
    func findDraft(idempotencyKey: String) async throws -> UUID?
}
