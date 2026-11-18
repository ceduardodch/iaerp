# ADR 0026 · Resumen de cartera y facturas por mes en el iPhone

**Decisión aceptada el 18 de noviembre de 2026.** Carlos autorizó publicar estas consultas tras las revisiones de negocio, UI/UX, QA y CI. Amplía la política de lectura de [ADR 0024](0024-ios-production-connection-policy.md).

El cliente iOS recibe el scope firmado `receivables:read` por defecto. La API exige además una membresía vigente de la empresa con rol owner, admin, collections o auditor y limita el uso móvil del scope a `GET /receivables/overview`. El servidor entrega por cobrar, vencido y cobrado este mes, con fecha fiscal de Guayaquil. Cobrado incluye efectivo y retenciones. La cartera con moneda distinta de USD devuelve una respuesta de conflicto hasta que el resumen pueda representar sus importes por moneda.

Con `invoices:read`, el servidor agrupa facturas por fecha de emisión y moneda, filtra antes de sumar y pagina las filas con orden por fecha e ID. La app abre el grupo reciente y consulta sus filas al expandirlo. El detalle conserva la ruta de factura existente. Todas las consultas resuelven la empresa a partir de la identidad autenticada.
