# ADR 0027 · Emisión y correo de factura en pruebas desde el iPhone

**Alcance autorizado el 19 de noviembre de 2026.** Carlos eligió el simulador SRI y un buzón de captura para probar el recorrido de una factura. La conexión móvil de producción mantiene los permisos de los ADR 0024 a 0026.

## Decisión

La ficha de factura consulta qué acciones admite el entorno para ese documento. El usuario revisa la empresa, el número, el total y el ambiente antes de confirmar la emisión. Una solicitud aceptada abre el seguimiento del estado fiscal. La consulta del documento permite ver la autorización simulada o el motivo del rechazo.

La API expone estas acciones de prueba sólo en un entorno habilitado para el simulador. Comprueba la identidad iOS, el tenant autenticado, los permisos por acción y la membresía activa. Cada escritura lleva una clave de idempotencia y deja auditoría. Las operaciones siguen los casos de uso de facturación del servidor.

Con la factura autorizada y sus dos archivos listos, el usuario revisa el destinatario y los nombres del RIDE y del XML. Un segundo acto explícito confirma el correo al buzón de captura. El recibo identifica el mensaje y sus adjuntos. Al volver a abrir la ficha, la app consulta el estado de esa factura antes de ofrecer otra acción.

El simulador de iOS en Debug permite recorrer el proceso con datos ficticios. En el iPhone, la bienvenida ofrece acceso a la empresa y a las cuentas guardadas. El ensayo de BTOB-SAS se inicia desde la ficha del cliente tras entrar a la empresa. El cliente conectado usa la capacidad anunciada por el servidor. La demo local, las pruebas de integración del backend y la recepción en el SRI representan comprobaciones distintas.

## Criterios de cierre

Negocio comprueba que se distinguen la aceptación, la autorización, el rechazo y la captura del correo. UI/UX revisa las dos confirmaciones, los datos de la factura, el destino y la legibilidad con letra grande. QA prueba cancelaciones, permisos, reintentos y aislamiento por empresa. Inspecciona que un único mensaje contiene el PDF y el XML de la factura indicada.
