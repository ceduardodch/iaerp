# ADR 0011: expediente legal-comercial versionado y evidencia AWS

- Estado: Accepted
- Fecha: 2026-08-02

## Contexto

IAERP ya relaciona clientes, facturas, cuotas y cartera, pero no conserva el
instrumento comercial que explica por que se factura ni la evidencia de consumo
AWS. Los clientes pueden tener un cargo fijo mensual, consumo variable o ambos.

## Decision

Se incorpora un contexto `legal_commercial` tenant-scoped, separado de Billing
y del SRI. Sus contratos tienen versiones inmutables después de firmarse y cada
archivo se guarda privado con SHA-256, tipo, autor, fecha y control de descarga.

IAERP no edita cláusulas ni crea plantillas legales. La persona prepara el PDF
fuera del sistema, sube la versión final y la envía por Gmail. IAERP guarda el
ID del mensaje y del hilo; al revisar respuestas consulta solo ese hilo. Una
respuesta con PDF crea evidencia pendiente, nunca activa el contrato.

La revisión de firma busca estructuras técnicas básicas del PDF. Una persona
valida el archivo en FirmaEC, registra esa confirmación y luego activa la
versión. El PDF enviado y el firmado son inmutables; cualquier cambio crea otra
versión. Un contrato puede apuntar a una oportunidad ganada y otro contrato del
mismo cliente como documento accesorio.

Una versión contiene vigencia, plazo y reglas de cobro `FIXED_MONTHLY`,
`AWS_MONTHLY` o `MILESTONE`. Para AWS se guarda el reporte privado de StreamOne,
el total escrito por la persona y su confirmación. No se importan líneas ni se
consulta StreamOne de forma automática.

Una propuesta de facturación une versión, periodo, corte y regla de precio, y
guarda un snapshot comercial al crear el borrador de factura. El botón `Crear
borrador` usa la fecha fiscal actual; no emite ni envía al SRI. Los servicios
puntuales siguen el flujo normal de Facturas, nacen con cobranza apagada y no
requieren contrato.

Si el contrato exige informe, la factura puede emitirse, pero su correo queda
bloqueado hasta subir y aprobar el PDF. El envío incluye XML, RIDE e informe.
Los recordatorios exigen a la vez política general activa, permiso en la
factura y consentimiento del cliente.

No se extraen cláusulas ni se interpreta contenido legal. No se agregan tools
MCP de escritura. REST conserva aislamiento por tenant, idempotencia y
auditoría en cada acción.

## Consecuencias

- Se requiere migración, API, UI, artefactos privados y pruebas de aislamiento,
  integridad, duplicados de Gmail, vigencia, cobros e informes.
- La firma electrónica con proveedor y la asesoría/validación jurídica humana
  permanecen fuera de alcance.
- FirmaEC y Gmail siguen siendo sistemas externos; un fallo de integración no
  cambia por sí solo el estado legal ni fiscal.
