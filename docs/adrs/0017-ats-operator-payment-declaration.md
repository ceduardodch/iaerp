# ADR 0017 — Forma de pago declarada para generar ATS

Fecha: 2026-10-27. Estado: aceptado para implementación local por solicitud del
operador; publicación pendiente de autorización.

## Contexto

Hay ventas históricas sin forma de pago en su proyección fiscal. El operador
confirmó el código 20 (otros con sistema financiero). El bloqueo general impedía
generar el ATS aunque el operador conociera el dato. Se amplía ADR 0012 para
admitir esa declaración explícita, sin atribuirla al XML.

## Decisión

POST /tax/periods/{period_id}/ats admite el cuerpo opcional
`missingSalesPaymentMethod`: null, 01 o 20. Sin cuerpo conserva el bloqueo anterior.
El operador elige el dato en cada período; la selección se reinicia al cambiar
el período. Solo completa ventas sin dato, nunca compras ni valores existentes.
No cambia comprobantes, XML autorizados, cobros ni saldos.

La elección entra en el hash de idempotencia y en la auditoría con fuente
`operator_declaration`, actor y período. El tenant sigue viniendo de la identidad.
REST invoca el mismo servicio generador. Los demás faltantes siguen bloqueando.
No se envía el archivo al SRI ni se marca el período como declarado.

## Validación y límites

Pruebas sintéticas cubren ZIP con código 20, conservación de la proyección,
valor XML prioritario, compras sin respaldo, código inválido, auditoría,
reintento idempotente y conflicto al cambiar la elección. La interfaz prueba
selección explícita y envío del dato en escritorio y móvil.
La declaración del operador no prueba aceptación del ATS por el SRI.
