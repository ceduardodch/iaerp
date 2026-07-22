# Guía de Administración — IAERP

Configuración del sistema para administradores de tenant: empresa, maestros,
condiciones de pago, usuarios y cuentas de servicio.

> Complementa: [`USER_GUIDE.md`](USER_GUIDE.md) (uso diario) y
> [`DEV_SETUP.md`](DEV_SETUP.md) (entorno de desarrollo).

## 1. Modelo multi-tenant

Cada organización es un **tenant** con aislamiento completo de datos: todas las
consultas incluyen `tenant_id`. Los usuarios pertenecen a un tenant mediante
**memberships** con **scopes** (permisos granulares).

## 2. Empresa: establecimientos y puntos de emisión (sección 05)

La facturación electrónica SRI requiere:
- **Establecimientos:** cada local/sucursal con su código (p.ej. `001`).
- **Puntos de emisión:** por establecimiento, con su código (p.ej. `001`).

Toda factura se emite desde un establecimiento + punto de emisión. Configúralos
antes de facturar.

## 3. Condiciones de pago

Existen dos niveles, con **override** del cliente sobre la empresa:

1. **Predeterminado de la empresa** (`default_payment_terms_days`): días de
   crédito por defecto para toda la organización.
2. **Override por cliente** (`payment_terms_days` en el contacto): si se define,
   prevalece sobre el valor de la empresa. Si se deja en *"Usar valor de la
   empresa"*, se hereda el default.

Al crear una factura, el formulario muestra qué condición aplica (indicador
`data-terms-source` = `customer` | `company`). La lógica efectiva es:
`condición del cliente ?? condición de la empresa`.

## 4. Maestros

- **Contactos (parties):** clientes/proveedores con tipo y número de
  identificación (RUC, cédula, pasaporte, consumidor final), roles y condición
  de pago.
- **Productos:** con **categoría tributaria** (define la tarifa de IVA aplicada
  por el SRI). El cálculo de impuestos es siempre server-side.

## 5. Usuarios y permisos (scopes)

La autorización es por **scopes** granulares. Ejemplos:

| Scope | Permite |
|-------|---------|
| `context:read` | Leer el contexto del tenant |
| `parties:read` / `parties:write` | Contactos |
| `products:read` / `products:write` | Productos |
| `invoices:read` / `invoices:write` | Facturación |
| `receivables:*` | Cartera y cobranza |
| `leads:read` / `leads:write` | CRM |
| `communications:read` / `communications:write` | Integración de correo |

## 6. Cuentas de servicio y agentes IA (MCP)

IAERP expone un **servidor MCP** (Model Context Protocol) para que agentes de IA
operen con permisos limitados:
- Autenticación con **cuentas de servicio** y scopes acotados.
- Herramientas disponibles: facturas, cartera, contactos, productos.
- Las escrituras automatizadas están **deshabilitadas por defecto**
  (`automationWritesEnabled`); actívalas explícitamente por tenant.
- Prompts con protección anti-inyección.

Ver [`05-ai-mcp.md`](05-ai-mcp.md) y
[`06-security-threat-model.md`](06-security-threat-model.md).

## 7. Zona horaria fiscal

Todas las validaciones de fecha fiscal usan **America/Guayaquil**
(`app/core/timezones.py`). La fecha de emisión de una factura no puede ser
futura respecto a *hoy* en esa zona.

## 8. Auditoría

Las operaciones sensibles (movimientos de cartera, cambios de estado) se
registran con `append_audit`. Los movimientos de cartera admiten reverso
auditado.

## 9. Seguridad operativa

- **Idempotencia:** las escrituras aceptan `Idempotency-Key` para evitar
  duplicados ante reintentos.
- **Autenticación:** OAuth 2.1 + OIDC (Keycloak) en producción; modo `dev`
  para desarrollo local.
- No compartas credenciales por canales inseguros; usa contraseñas fuertes y
  rótalas periódicamente.
