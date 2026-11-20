import IAERPClient
import SwiftUI

enum CollectionDates {
    static let zone = TimeZone(identifier: "America/Guayaquil")!
    static var calendar: Calendar {
        var result = Calendar(identifier: .gregorian)
        result.timeZone = zone
        return result
    }
    static func date(_ value: String) -> Date? {
        let f = DateFormatter()
        f.calendar = calendar
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = zone
        f.dateFormat = "yyyy-MM-dd"
        guard let date = f.date(from: value), f.string(from: date) == value else { return nil }
        return date
    }
    static func contactTime(_ stamp: String) -> String {
        let parse = ISO8601DateFormatter()
        parse.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = parse.date(from: stamp) ?? ISO8601DateFormatter().date(from: stamp) else { return stamp }
        return date.formatted(Date.FormatStyle(date: .abbreviated, time: .shortened,
            locale: Locale(identifier: "es_EC"), calendar: calendar, timeZone: zone))
    }
}

struct CollectionTermsForm: View {
    let account: CollectionAccount
    let kind: CollectionSheet
    let submit: (CollectionAction) async -> String?
    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var typeSize
    @State private var installmentID: UUID?
    @State private var date: Date
    @State private var reason = ""
    @State private var busy = false
    @State private var message: String?
    @State private var daysText = "7"
    private enum Entry { case days, reason }
    @FocusState private var focusedEntry: Entry?

    init(account: CollectionAccount, kind: CollectionSheet, submit: @escaping (CollectionAction) async -> String?) {
        self.account = account
        self.kind = kind
        self.submit = submit
        let today = CollectionDates.calendar.startOfDay(for: .now)
        let pending = account.installments.filter { $0.openAmount > 0 }
        let single = pending.count == 1 ? pending[0] : nil
        _installmentID = State(initialValue: single?.id)
        let current: Date
        if kind == .promise {
            current = max(account.promisedDate.flatMap(CollectionDates.date) ?? today, today)
        } else { current = single.flatMap { CollectionDates.date($0.dueDate) } ?? today }
        _date = State(initialValue: current)
    }

    private var installment: CollectionInstallment? {
        account.installments.first(where: { $0.id == installmentID && $0.openAmount > 0 })
    }
    private var iso: String { ERPDisplay.fiscalDate(date) }
    private var explanation: String? {
        if kind == .promise {
            return iso == account.promisedDate ? "Elige otra fecha para actualizar la promesa." : nil
        }
        guard let installment else { return "Elige la cuota que quieres ajustar." }
        if iso == installment.dueDate { return "Elige un vencimiento distinto del actual." }
        let count = reason.trimmingCharacters(in: .whitespacesAndNewlines).count
        if count < 3 || count > 500 { return "Escribe el motivo del cambio (entre 3 y 500 caracteres)." }
        return nil
    }

    private var fields: some View {
        Form {
            Section(account.customerName) {
                CollectionValue("Factura", value: account.invoiceNumber)
                if kind == .promise {
                    CollectionValue("Vencimiento actual", value: ERPDisplay.longFiscalDate(account.dueDate))
                }
            }
            if kind == .promise {
                Section {
                    DatePicker("Fecha prometida", selection: $date, in: CollectionDates.calendar.startOfDay(for: .now)...,
                               displayedComponents: .date)
                    Button("En 7 días") { adjust(7, from: .now) }
                } footer: {
                    Text("La promesa pausa los avisos hasta el día elegido inclusive. La factura conserva su vencimiento.")
                }
            } else {
                if account.installments.filter({ $0.openAmount > 0 }).count > 1 {
                    Section("Cuota por ajustar") {
                        ForEach(account.installments.filter { $0.openAmount > 0 }) { item in
                            Button {
                                installmentID = item.id
                                if let previous = CollectionDates.date(item.dueDate) { date = previous }
                            } label: {
                                HStack {
                                    VStack(alignment: .leading) {
                                        Text("Cuota \(item.sequence) · \(ERPDisplay.money(item.openAmount, currency: account.currency))")
                                        Text(ERPDisplay.longFiscalDate(item.dueDate)).font(.footnote)
                                    }
                                    Spacer()
                                    if installmentID == item.id { Image(systemName: "checkmark") }
                                }
                            }.accessibilityAddTraits(installmentID == item.id ? .isSelected : [])
                             .accessibilityIdentifier("collection-installment-\(item.sequence)")
                        }
                    }
                }
                if let installment {
                    Section {
                        CollectionValue("Vencimiento anterior", value: ERPDisplay.longFiscalDate(installment.dueDate))
                            .accessibilityIdentifier("collection-prior-installment-date")
                        DatePicker("Nuevo vencimiento", selection: $date, displayedComponents: .date)
                        LabeledContent("Días de ajuste") {
                            TextField("Días", text: $daysText)
                                .keyboardType(.numberPad).multilineTextAlignment(.trailing)
                                .focused($focusedEntry, equals: .days)
                                .accessibilityLabel("Número de días de ajuste")
                        }
                        if let days = Int(daysText), days > 0, daysText.count <= 4 {
                            ViewThatFits(in: .horizontal) {
                                HStack { dayButtons(days) }
                                VStack(alignment: .leading) { dayButtons(days) }
                            }
                        } else {
                            Text("Escribe de 1 a 9999 días o elige una fecha en el calendario.").font(.footnote)
                        }
                        TextField("Motivo del cambio", text: $reason, axis: .vertical)
                            .lineLimit(2...4).focused($focusedEntry, equals: .reason)
                            .accessibilityIdentifier("collection-reason")
                    } footer: {
                        Text("El cambio actualiza el vencimiento comercial de esta cuota.")
                    }
                }
            }
            Section {
                if let explanation { Text(explanation).font(.footnote) }
                if let message { Label(message, systemImage: "exclamationmark.circle") }
                Button {
                    if kind == .promise {
                        Task { await perform(.promise(date: iso, previous: account.promisedDate)) }
                    } else if let installment {
                        let action = CollectionAction.dueDate(installment: installment.id, date: iso,
                            previous: installment.dueDate, reason: reason.trimmingCharacters(in: .whitespacesAndNewlines))
                        Task { await perform(action) }
                    }
                } label: {
                    if busy { ProgressView() } else { Text(kind == .promise ? "Guardar promesa" : "Guardar vencimiento") }
                }
                .disabled(explanation != nil || busy).accessibilityIdentifier("collection-save")
            }
            if kind == .promise, let previous = account.promisedDate {
                Section {
                    Button("Retirar promesa", role: .destructive) {
                        Task { await perform(.promise(date: nil, previous: previous)) }
                    }
                } footer: { Text("Al retirar la promesa vuelven a regir los avisos de esta factura.") }
            }
        }
    }

    var body: some View {
        NavigationStack {
            GeometryReader { viewport in
                fields
                    .frame(width: viewport.size.width, height: viewport.size.height)
                    .clipped()
            }
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarBackground(Color(uiColor: .systemBackground), for: .navigationBar)
            .disabled(busy)
            .scrollEdgeEffectHidden(true, for: .vertical)
            .environment(\.timeZone, CollectionDates.zone)
            .environment(\.locale, Locale(identifier: "es_EC"))
            .navigationTitle(kind == .promise ? "Promesa de pago" : "Cambiar vencimiento")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    if focusedEntry != nil {
                        Spacer()
                        Button("Listo") { focusedEntry = nil }
                    }
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button { dismiss() } label: {
                        if typeSize.isAccessibilitySize {
                            Label("Cancelar", systemImage: "xmark").labelStyle(.iconOnly)
                        } else {
                            Text("Cancelar")
                        }
                    }.disabled(busy)
                }
            }
            .interactiveDismissDisabled(busy)
        }
    }

    @ViewBuilder private func dayButtons(_ days: Int) -> some View {
        let unit = days == 1 ? "día" : "días"
        Button("Restar \(days) \(unit)") { adjust(-days, from: date) }.buttonStyle(.bordered)
        Button("Sumar \(days) \(unit)") { adjust(days, from: date) }.buttonStyle(.bordered)
    }
    private func adjust(_ days: Int, from base: Date) {
        if let shifted = CollectionDates.calendar.date(byAdding: .day, value: days, to: base) { date = shifted }
    }
    private func perform(_ action: CollectionAction) async {
        guard !busy else { return }
        busy = true
        message = await submit(action)
        busy = false
        if message == nil { dismiss() }
    }
}
