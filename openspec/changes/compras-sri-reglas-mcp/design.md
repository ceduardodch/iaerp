## Context

El importador local ya lee el acceso cifrado guardado por empresa, abre el navegador con perfil temporal y valida el receptor antes de subir el TXT. Las reglas bancarias existentes trabajan sobre texto de un débito. Compras distingue el uso tributario, el uso interno y las etiquetas. MCP usa OAuth y Streamable HTTP.

## Goals / Non-Goals

**Objetivos:** diagnóstico de acceso sin importar, clasificación con reglas verificables, revisión masiva accesible y descubrimiento OAuth funcional.

**Fuera de alcance:** inferir deducibilidad con IA, seleccionar reglas reales sin decisión del responsable fiscal y presentar declaraciones.

## Decisions

- Conservar el importador local. Añadir comprobación del acceso y del módulo antes de descargar, distinguiendo el mes vacío de un error.
- Reusar el perfil dedicado por empresa. La tarea diaria conserva las sesiones vigentes y deja las sesiones vencidas al operador.
- Configurar una regla por RUC exacto dentro de cada empresa, con opción de desactivarla. Las reglas nuevas solo aplican a facturas recibidas con XML recuperado y validado por IAERP, cuando las escrituras automatizadas están habilitadas. Conservar pendientes sin regla, cambios manuales, pagos, etiquetas y períodos declarados.
- Aprovechar las acciones de clasificación existentes en el tablero. El arrastre y el botón accesible llaman al mismo caso de uso.
- Enviar la ruta de metadatos OAuth anunciada por MCP al mismo backend que sirve `/mcp`.

## Risks / Trade-offs

- Un proveedor puede vender artículos de distinto uso. La regla por RUC se activa de forma explícita para facturas de tratamiento uniforme. Los demás casos se revisan en el tablero.
- Un CAPTCHA o segundo factor del SRI requiere intervención del operador.
