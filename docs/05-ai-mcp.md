# IA y MCP

## Objetivo

Permitir que la interfaz interna y agentes externos consulten y operen IAERP con
el mismo nivel de control que la API. MCP es un adaptador; no contiene reglas de
facturacion ni finanzas.

## Transporte y autenticacion

- Streamable HTTP en `/mcp`.
- OAuth 2.1 con Keycloak y Protected Resource Metadata.
- SDK oficial Python estable fijado a `>=1.27,<2` inicialmente.
- Respuestas estructuradas con modelos Pydantic.
- Sin transporte SSE heredado para nuevas integraciones.

Cada token contiene subject, client, scopes y tenant activo. Las herramientas no
aceptan un `tenant_id` libre. Para cambiar de tenant el cliente obtiene un token
con contexto permitido.

## Catalogo inicial

### Consulta

- `context.get`: empresa, permisos, limites y estado del kill switch.
- `parties.search`: buscar clientes/proveedores.
- `products.search`: buscar productos.
- `invoices.get`: detalle y estado local/SRI.
- `receivables.list`: cartera vencida o por vencer.
- `payables.list`: obligaciones y pagos programados.
- `finance.summary`: ventas, cobros, pagos y flujo proyectado.

### Escritura

- `parties.upsert`
- `products.upsert`
- `invoices.create_draft`
- `invoices.issue`
- `credit_notes.create_and_issue`
- `receivables.record_payment`
- `receivables.send_reminder`
- `payables.create`
- `payables.create_from_document`
- `payables.schedule_payment`
- `payables.record_payment`

No existen herramientas `query_sql`, `execute_code`, acceso a filesystem o
actualizacion generica de tablas.

## Flujo de una escritura

1. Validar token, client, tenant, rol y scope.
2. Validar JSON contra el esquema cerrado.
3. Verificar kill switch y politica de la herramienta.
4. Reservar o recuperar idempotency key.
5. Ejecutar el caso de uso en transaccion.
6. Escribir auditoria y outbox.
7. Devolver resultado estructurado, estado y correlation ID.

Repetir la misma idempotency key devuelve el resultado previo cuando los
argumentos coinciden. Si cambian, se rechaza por conflicto.

## Politicas autonomas

Una politica se configura por tenant y herramienta:

- habilitada/deshabilitada;
- roles o service accounts permitidas;
- monto maximo por operacion y por dia;
- clientes/proveedores o tags permitidos/bloqueados;
- horario operativo;
- estados de origen aceptados;
- canales y plantillas autorizadas.

El owner puede desactivar todas las escrituras de IA. Un administrador global
puede activar el kill switch de plataforma. El cambio siempre queda auditado.

## Proveedor de IA

El modulo `AIProvider` define generacion estructurada, embeddings si se aprueban,
uso y costo. OpenAI sera el primer adaptador. Ningun caso de uso importa el SDK
del proveedor directamente.

Se registra modelo, version, tokens, costo estimado, latencia y resultado, sin
guardar secretos ni documentos completos en trazas.

## Documentos no confiables

- XML se valida contra esquema y reglas fiscales.
- PDF se trata como evidencia, no como fuente definitiva.
- Texto extraido se marca como untrusted y no se mezcla con instrucciones del
  sistema.
- El modelo solo devuelve un esquema de extraccion.
- El backend recalcula montos y valida RUC, fechas, clave, impuestos y duplicados.
- Una confianza baja crea excepcion operativa; no inventa campos.
- Links, scripts, instrucciones o tool calls contenidos en archivos se ignoran.

## Versionado

Cada tool tiene nombre estable, version de esquema y ejemplos. Un cambio
incompatible crea una nueva version o pasa por una ventana de deprecacion. Los
contratos se prueban con MCP Inspector y clientes automatizados.
