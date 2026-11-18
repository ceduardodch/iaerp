import Foundation
import IAERPDemo
import Testing

@Suite("Clientes sintéticos: búsqueda y aislamiento")
struct DemoDirectoryTests {
    @Test("Nombre sin tildes y sin distinguir mayúsculas")
    func accentInsensitiveSearch() {
        let results = DemoDirectory.example.clients(matching: "  ALAMO\n")
        #expect(results.map(\.name) == ["Cliente de ejemplo Álamo"])
    }

    @Test("Búsqueda por ciudad")
    func citySearch() {
        let results = DemoDirectory.example.clients(matching: "guayaquil")
        #expect(results.map(\.name) == ["Cliente de ejemplo Costa"])
    }

    @Test("Una búsqueda sin coincidencias no inventa clientes")
    func noMatches() {
        #expect(DemoDirectory.example.clients(matching: "no existe").isEmpty)
    }

    @Test("Una consulta vacía conserva la lista y sus identificadores", arguments: ["", " \n\t"])
    func blankSearch(query: String) {
        let directory = DemoDirectory.example
        let clients = directory.clients(matching: query)
        #expect(clients.count == 3)
        #expect(Set(clients.map(\.id)).count == 3)
        #expect(clients.allSatisfy { directory.client(id: $0.id) == $0 })
    }

    @Test("No se muestra ni se abre un cliente de otra empresa", arguments: ["", "Ajeno", "Quito"])
    func rejectsForeignTenant(query: String) {
        let currentTenant = UUID()
        let foreign = DemoClient(id: UUID(), tenantID: UUID(), name: "Ajeno", city: "Quito")
        let directory = DemoDirectory(tenantID: currentTenant, clients: [foreign])
        #expect(directory.clients(matching: query).isEmpty)
        #expect(directory.client(id: foreign.id) == nil)
    }
}
