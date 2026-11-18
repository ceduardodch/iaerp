import IAERPDemo
import SwiftUI

struct DemoClientsView: View {
    let directory: DemoDirectory
    @State private var query = ""

    init(directory: DemoDirectory = .example) {
        self.directory = directory
    }

    var body: some View {
        let clients = directory.clients(matching: query)
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 12) {
                        ERPStatusBadge(text: "Demo", systemImage: "testtube.2")
                            .accessibilityLabel("Modo de demostración")
                            .accessibilityIdentifier("demo-mode")
                        Text("Empresa de prueba")
                            .font(.title2.weight(.semibold))
                            .accessibilityAddTraits(.isHeader)
                    }
                    .padding(.vertical, 8)
                } footer: {
                    Text("Datos de prueba.")
                        .foregroundStyle(Color.primary)
                }

                Section {
                    if clients.isEmpty {
                        ContentUnavailableView.search(text: query)
                            .accessibilityIdentifier("demo-search-empty")
                    } else {
                        ForEach(clients) { client in
                            NavigationLink(value: client.id) {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(client.name)
                                        .font(.headline)
                                    Text(client.city)
                                        .font(.subheadline)
                                        .foregroundStyle(Color.primary)
                                }
                                .frame(minHeight: 44, alignment: .leading)
                                .padding(.vertical, 4)
                            }
                            .accessibilityIdentifier("demo-client-\(client.id.uuidString)")
                            .accessibilityHint("Abre la ficha del cliente de ejemplo")
                        }
                    }
                } header: {
                    Text("Clientes de ejemplo")
                        .foregroundStyle(Color.primary)
                } footer: {
                    Text("Resultados: \(clients.count)")
                        .foregroundStyle(Color.primary)
                }
            }
            .navigationTitle("Clientes")
            .searchable(
                text: $query,
                placement: .navigationBarDrawer(displayMode: .always),
                prompt: "Buscar"
            )
            .navigationDestination(for: UUID.self) { id in
                if let client = directory.client(id: id) {
                    DemoClientDetailView(client: client)
                } else {
                    ContentUnavailableView(
                        "Cliente no disponible", systemImage: "person.crop.circle.badge.questionmark",
                        description: Text("Vuelve a la lista y elige otro cliente.")
                    )
                }
            }
        }
    }
}

struct DemoClientDetailView: View {
    let client: DemoClient

    var body: some View {
        List {
            Section {
                ERPStatusBadge(text: "Demo", systemImage: "testtube.2")
                    .accessibilityLabel("Modo de demostración")
                ERPDetailRow(title: "Nombre", value: client.name)
                ERPDetailRow(title: "Ciudad", value: client.city)
                ERPDetailRow(title: "Empresa", value: "Empresa de prueba")
            } header: {
                Text("Datos del cliente")
                    .foregroundStyle(Color.primary)
            } footer: {
                Text("Ficha ficticia para probar IAERP. No contiene datos fiscales reales.")
                    .foregroundStyle(Color.primary)
            }
        }
        .navigationTitle("Cliente")
        .toolbarTitleDisplayMode(.inline)
    }
}

#if !COMMAND_LINE_PREVIEW
#Preview("Clientes") {
    DemoClientsView()
}

#Preview("Texto grande") {
    DemoClientsView()
        .environment(\.dynamicTypeSize, .accessibility3)
}

#Preview("Oscuro") {
    DemoClientsView()
        .preferredColorScheme(.dark)
}
#endif
