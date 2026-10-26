# ADR 0017 — Forma de pago declarada para generar ATS

Fecha: 2026-10-27. Estado: aceptado y publicado con autorización humana.
PR #85 y #86; ejecución de producción 40371809581 aprobada.

## Contexto

Hay ventas históricas sin forma de pago en su proyección fiscal. El operador
confirmó el código 20 (otros con sistema financiero). El bloqueo general impedía
generar el ATS aunque el operador conociera el dato. Se amplía ADR 0012 para
admitir esa declaración explícita, sin atribuirla al XML.

## Decisión

POST /tax/periods/{period_id}/ats admite el cuerpo opcional
`missingSalesPaymentMethod`: null, 01 o 20. Por instrucción expresa posterior
del operador, sin cuerpo, con objeto vacío o null usa 20 automáticamente. La
interfaz inicia en 20 y vuelve a 20 al cambiar de período; permite elegir 01. Solo completa ventas sin dato, nunca compras ni valores existentes.
No cambia comprobantes, XML autorizados, cobros ni saldos.

La elección explícita entra en el hash de idempotencia; las solicitudes sin
campo conservan el hash legado. La auditoría registra actor, período y método
efectivo, con fuente `operator_declaration` para valor explícito o
`operator_authorized_default` para el valor automático por ausencia/null. El tenant sigue viniendo de la identidad.
REST invoca el mismo servicio generador. Los demás faltantes siguen bloqueando.
No se envía el archivo al SRI ni se marca el período como declarado.

## Validación y límites

Pruebas sintéticas cubren ZIP con código 20, conservación de la proyección,
valor XML prioritario, compras sin respaldo, código inválido, auditoría,
reintento idempotente y conflicto al cambiar la elección. La interfaz prueba
valor preseleccionado, cambio a efectivo y envío del dato en escritorio y móvil.
La declaración del operador no prueba aceptación del ATS por el SRI.

## Corrección del alcance confirmada

El operador pidió que 20 se aplique automáticamente en todos los meses,
incluidos julio y agosto. Esta instrucción sustituye la elección obligatoria
por período. No modifica XML ni completa otros datos fiscales desconocidos.

Publicación del valor automático: PR #88, CI/Coolify 40376868467 verdes.
Revisión ejecutada 5bc215d: julio y agosto generados sin elegir el método,
con ZIP/XML descargados y verificados; sin presentación ante SRI.
