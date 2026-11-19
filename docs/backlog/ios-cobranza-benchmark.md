# Cobranza desde el iPhone

Propuesta para revisión · 19 de noviembre de 2026

## Decisión recomendada

Tocar **Por cobrar** en Inicio abre la cartera. Tocar **Vencido** abre la misma pantalla filtrada. La lista agrupa por cliente y muestra saldo pendiente, próxima acción y último correo. Las opciones **Vencidas**, **Vencen pronto** y **Todas las pendientes** permiten elegir a quién contactar. Cada cliente ve sólo sus propias facturas.

## Qué hacen otros sistemas

| Producto | Función documentada | Qué aprovechar en IAERP |
| --- | --- | --- |
| QuickBooks móvil | En el móvil permite ver facturas abiertas, pagadas y vencidas y enviar recordatorios. [Intuit](https://quickbooks.intuit.com/learn-support/en-us/help-article/invoicing/edit-invoice-payment-using-quickbooks-online-app/L4QlrKfOS_US_en_US) | Llegar al cliente desde el importe que ya se ve en Inicio. |
| Zoho Billing y Books | Permiten recordar una factura o varias en lote, registrar la fecha prometida y pausar avisos hasta ese día. [Envíos por lote](https://www.zoho.com/us/billing/help/invoice/managing-invoices.html) · [Promesa de pago](https://www.zoho.com/in/books/kb/reminders/prevent-rem-epd.html) | Seleccionar todos los pendientes y respetar los acuerdos individuales. |
| Xero | Permite programar avisos antes o después del vencimiento, definir un saldo mínimo y pausar avisos por cliente o por factura. [Reglas](https://central.xero.com/0/article/Set-up-invoice-reminders) · [Pausas](https://central.xero.com/0/article/Turn-invoice-reminders-on-or-off) | Dejar los días y las excepciones a elección de cada empresa. |

La comparación se basa en las guías oficiales. La documentación de Intuit describe el móvil. Las de Zoho y Xero describen funciones del producto.

## Qué puede reutilizarse

La web de IAERP ya tiene plantilla y correo de cobro por cuenta, envío inmediato o programado, historial, política general de cobranza y habilitación por factura. También permite corregir con motivo el vencimiento comercial de una cuenta de una cuota. La modificación queda auditada y conserva el XML autorizado y el RIDE. El botón de entregar una factura y sus adjuntos tiene otra finalidad y debe conservar su acción actual.

## Entregas y condiciones de aceptación

| Orden | Lo que verá el usuario | Qué debe pasar en pruebas |
| --- | --- | --- |
| 1. Cartera y correo individual | Desde el saldo de Inicio, abrir el cliente y ver facturas, abonos, retenciones, saldo, dirección de cobro y último contacto. El botón **Enviar recordatorio** usa la plantilla de la empresa y un toque final confirma el envío. | El saldo coincide con la web. Si falta el correo o la cobranza está pausada, la pantalla explica cómo resolverlo. Un doble toque o una reconexión produce un único envío. |
| 2. Fechas | **Próximo aviso** adelanta o retrasa el contacto, con atajos como mañana o en 7 días y un calendario. **Promesa de pago** guarda el día acordado y permite pausar avisos hasta entonces. **Cambiar vencimiento** permite sumar o restar días al plazo, o elegir una fecha exacta. Muestra la fecha anterior, la nueva y el motivo. | Mover un aviso o registrar una promesa conserva la mora contractual. Una prórroga formal recalcula el vencimiento comercial y su historial. Para varias cuotas se identifica la cuota concreta y su saldo antes de permitir cambios. |
| 3. Enviar a varios | **Seleccionar todos** respeta el filtro visible. Una sola revisión indica cuántos clientes, cuántas facturas y qué saldo incluye la selección. **Enviar a N clientes** prepara un correo privado por cliente con sus facturas. | Revalidar saldo, correo, permisos y pausas al enviar. Excluir pagadas, anuladas, clientes sin correo o con baja de avisos, promesas vigentes y duplicados. Si una factura se paga tras la selección, se omite. Mostrar aceptados, omitidos con motivo y fallidos. Reintentar sólo los fallidos confirmados y conciliar los de resultado incierto. |
| 4. Reglas opcionales | Cada empresa elige los días antes o después del vencimiento, los destinatarios y el saldo mínimo. | Probar primero en un buzón de captura. La regla respeta el calendario de Ecuador, las pausas y los envíos manuales recientes. |

El alcance aprobado para 0.8.0 comprende el correo individual, la promesa de pago y el cambio de vencimiento por cuota. Quedan en el backlog la programación manual del próximo aviso, el filtro de próximos vencimientos y el envío por lote. La automatización queda para cuando el equipo conozca su frecuencia de contacto. Cada entrega pasa por negocio, UI/UX y QA con clientes y movimientos sintéticos antes de probar el envío real desde el iPhone.
