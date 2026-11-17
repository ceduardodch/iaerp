## ADDED Requirements

### Requirement: Regla explícita por proveedor
El sistema SHALL aplicar la decisión para renta configurada por un administrador para el RUC exacto solo a facturas recibidas con XML recuperado y validado, pendientes, dentro de un período abierto y con permiso de automatización vigente.

#### Scenario: Factura pendiente coincide con la regla
- **WHEN** se recupera el XML de una factura y su proveedor coincide con la regla activa del tenant
- **THEN** se guarda la clasificación y una referencia auditable a la regla sin cambiar pagos ni etiquetas

#### Scenario: Documento excluido
- **WHEN** el documento carece de XML recuperado, ya fue clasificado, corresponde a otro tenant o la factura o una nota de crédito vinculada pertenece a un período declarado
- **THEN** la regla conserva la clasificación existente

### Requirement: Tablero de revisión
Compras SHALL permitir clasificar y editar etiquetas y control interno desde una sola vista.

#### Scenario: Mover una compra
- **WHEN** el operador arrastra la tarjeta o pulsa una acción equivalente con clic, toque o teclado
- **THEN** el servidor aplica las mismas protecciones y el tablero muestra la decisión guardada o el error
