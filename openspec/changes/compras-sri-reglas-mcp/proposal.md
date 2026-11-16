## Why

Guardar el acceso SRI en Empresa no confirma que el importador pueda iniciar sesión. Clasificar las compras una por una exige abrir varios formularios. El MCP publicado anuncia metadatos OAuth que hoy devuelven el HTML del portal.

## What Changes

- Hacer verificable el acceso SRI desde el importador y distinguir una consulta sin comprobantes de un fallo.
- Dar a Compras un tablero arrastrable y acciones directas para clasificar y etiquetar.
- Permitir reglas fiscales explícitas por RUC de proveedor para facturas con XML confirmado, con registro de la regla aplicada.
- Servir el descubrimiento OAuth del MCP y verificar el catálogo y una consulta autenticada con datos sintéticos.

## Capabilities

### New Capabilities

- `compras-sri`: diagnóstico de acceso e importación de comprobantes recibidos.
- `clasificacion-compras`: reglas por proveedor y tablero de revisión.
- `mcp`: descubrimiento OAuth y validación de transporte y herramientas.

### Modified Capabilities

## Impact

Administración, Compras, importador local, API de cuentas por pagar, procesamiento XML, proxy web y pruebas MCP. Las pruebas y el cierre siguen `docs/09-testing-quality.md`.
