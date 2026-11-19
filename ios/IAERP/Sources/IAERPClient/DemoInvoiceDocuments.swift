import CoreGraphics
import CoreText
import Foundation

/// Local example documents for edited demo invoices. The fixed BTOB case uses the server's original files.
enum DemoInvoiceDocuments {
    static func render(invoice: ERPInvoice, company: String, customer: String) throws -> [ERPDocument] {
        let number = "001-001-\(invoice.sequential)"
        let name = "DEMO-\(number)"
        let notice = "Datos ficticios, sin validez fiscal ni firma real."
        let rows = NSMutableAttributedString()
        func append(_ text: String, size: CGFloat = 12, bold: Bool = false) {
            let font = CTFontCreateWithName((bold ? "Helvetica-Bold" : "Helvetica") as CFString, size, nil)
            rows.append(NSAttributedString(string: text + "\n", attributes: [NSAttributedString.Key(kCTFontAttributeName as String): font]))
        }
        func amount(_ value: Decimal) -> String { invoice.currency + " " + money(value) }
        append("RIDE · Simulador SRI", size: 22, bold: true)
        append(notice)
        append("\n\(company)", size: 16, bold: true)
        append("Cliente: \(customer)")
        append("Factura: \(number)")
        append("Fecha: \(invoice.issueDate)")
        append("Moneda: \(invoice.currency)")
        append("\nDetalle", size: 15, bold: true)
        var linesXML = ""
        for line in invoice.lines {
            let quantity = NSDecimalNumber(decimal: line.quantity).stringValue
            let price = NSDecimalNumber(decimal: line.unitPrice).stringValue
            append("\(line.lineNumber). \(line.description)", bold: true)
            append("Cantidad: \(quantity)   Precio unitario: \(invoice.currency) \(price)")
            append("Base: \(amount(line.baseAmount))   IVA: \(amount(line.taxAmount))   Descuento: \(amount(line.discount))")
            linesXML += """
                <detalle><descripcion>\(xml(line.description))</descripcion><cantidad>\(quantity)</cantidad>
                <precioUnitario>\(price)</precioUnitario><descuento>\(money(line.discount))</descuento>
                <base>\(money(line.baseAmount))</base><iva>\(money(line.taxAmount))</iva></detalle>
                """
        }
        append("\nSubtotal: \(amount(invoice.subtotal))")
        append("IVA: \(amount(invoice.tax))")
        append("Total: \(amount(invoice.total))", size: 15, bold: true)

        var documents = [ERPDocument(data: try pdf(rows), fileName: name + ".pdf", mimeType: "application/pdf")]
        if invoice.status == "AUTHORIZED" {
            let body = """
                <?xml version="1.0" encoding="UTF-8"?>
                <documentoDemostracion><ambiente>Simulador SRI</ambiente><aviso>\(notice)</aviso>
                <empresa>\(xml(company))</empresa><cliente>\(xml(customer))</cliente>
                <numero>\(xml(invoice.sequential))</numero><numeroCompleto>\(xml(number))</numeroCompleto>
                <fecha>\(xml(invoice.issueDate))</fecha><moneda>\(xml(invoice.currency))</moneda>
                <detalles>\(linesXML)</detalles><subtotal>\(money(invoice.subtotal))</subtotal>
                <iva>\(money(invoice.tax))</iva><total>\(money(invoice.total))</total></documentoDemostracion>
                """
            documents.append(ERPDocument(data: Data(body.utf8), fileName: name + ".xml", mimeType: "application/xml"))
        }
        return documents
    }

    private static func money(_ value: Decimal) -> String {
        let format = NumberFormatter()
        format.locale = Locale(identifier: "en_US_POSIX")
        format.numberStyle = .decimal
        format.usesGroupingSeparator = false
        format.minimumFractionDigits = 2
        format.maximumFractionDigits = 2
        return format.string(from: NSDecimalNumber(decimal: value)) ?? NSDecimalNumber(decimal: value).stringValue
    }

    private static func xml(_ string: String) -> String {
        let valid = string.unicodeScalars.filter {
            switch $0.value {
            case 9, 10, 13, 0x20...0xD7FF, 0xE000...0xFFFD, 0x10000...0x10FFFF: true
            default: false
            }
        }
        return String(valid).replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;").replacingOccurrences(of: ">", with: "&gt;")
    }

    private static func pdf(_ text: NSAttributedString) throws -> Data {
        let data = NSMutableData()
        var media = CGRect(x: 0, y: 0, width: 595, height: 842)
        guard let consumer = CGDataConsumer(data: data),
              let context = CGContext(consumer: consumer, mediaBox: &media, [kCGPDFContextTitle: "RIDE · Simulador SRI"] as CFDictionary) else {
            throw ERPClientError.invalidResponse
        }
        let framesetter = CTFramesetterCreateWithAttributedString(text)
        let area = CGPath(rect: media.insetBy(dx: 44, dy: 44), transform: nil)
        var location = 0
        while location < text.length {
            let frame = CTFramesetterCreateFrame(framesetter, CFRange(location: location, length: 0), area, nil)
            let length = CTFrameGetVisibleStringRange(frame).length
            guard length > 0 else { throw ERPClientError.invalidResponse }
            context.beginPDFPage(nil)
            context.textMatrix = .identity
            CTFrameDraw(frame, context)
            context.endPDFPage()
            location += length
        }
        context.closePDF()
        return data as Data
    }
}
