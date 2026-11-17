## ADDED Requirements

### Requirement: Registro de anulación con respaldo
IAERP SHALL permitir a un usuario autorizado registrar una factura recibida ya anulada ante el SRI con fecha, motivo y evidencia, conservando el original.

#### Scenario: Compra pendiente sin movimientos
- **WHEN** el usuario confirma la anulación con respaldo válido y permiso de escritura
- **THEN** la compra queda anulada con historial auditable e idempotencia
- **AND** deja de aumentar la deuda y los totales fiscales abiertos

#### Scenario: Documento con pagos o movimientos aplicados
- **WHEN** la compra contiene pagos, retenciones u otros movimientos que requieren conciliación
- **THEN** IAERP impide la anulación automática y explica la revisión necesaria
- **AND** conserva los movimientos originales sin inventar devoluciones

#### Scenario: Período declarado
- **WHEN** la anulación afecta un período declarado
- **THEN** IAERP bloquea el cambio automático y explica que se requiere revisión del ajuste
- **AND** no altera cifras ni documentos de la declaración cerrada

#### Scenario: Nota de crédito
- **WHEN** existe una nota de crédito vinculada
- **THEN** se conserva su aplicación y no se descuenta otra vez mediante anulación directa

#### Scenario: Otro tenant o permiso insuficiente
- **WHEN** un cliente intenta cambiar una compra ajena o sin permiso
- **THEN** IAERP rechaza la operación sin revelar datos de otra empresa

#### Scenario: Historial visible
- **WHEN** el operador abre una compra anulada
- **THEN** ve el estado, motivo, fecha y respaldo
- **AND** no puede registrar pagos ni volver a clasificarla como compra vigente
