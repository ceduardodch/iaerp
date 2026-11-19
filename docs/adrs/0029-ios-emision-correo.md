# ADR 0029 · Emisión de facturas y correo desde el iPhone

El usuario autorizó habilitar el flujo real tras las revisiones de negocio, UI/UX, QA y CI. La prueba con una factura real queda a cargo del usuario.

## Decisión

Guardar el borrador, emitirlo y enviar el correo son tres acciones. En la ficha, el usuario comprueba empresa, factura, cliente y total antes de confirmar la emisión. El servidor verifica el entorno fiscal y los permisos de la membresía. Encolar la transmisión significa que el SRI aún debe responder.

Una vez autorizada la factura, el iPhone solicita la vista previa de correo de la web. La segunda confirmación incluye el destinatario del cliente y los adjuntos. Cuando el contrato lo exige, también incluye su informe mensual aprobado. Si cambian los datos revisados, se requiere una vista previa nueva.

Ante una respuesta perdida, el iPhone consulta el estado de la operación de la misma empresa y factura. Un envío pendiente requiere conciliación. Una aceptación del proveedor se muestra con su referencia, destinatario y adjuntos. El buzón de destino puede recibir el mensaje después. La app de producción usa los permisos de emisión y correo de forma independiente. Los ensayos aislados siguen el [ADR 0027](0027-ios-test-invoice-delivery.md).
