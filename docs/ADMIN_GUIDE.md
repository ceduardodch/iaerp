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
| `communications:read` / `communications:write` | Correo, WhatsApp y campañas Meta |

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

## 6.1 Conectar Gmail (Google Workspace)

La app registra **un solo** OAuth client de Google (identidad de IAERP, la
configura el operador una vez); luego **cada tenant** conecta su propio correo con
un botón y sus tokens se guardan cifrados por `tenant_id`. Paso a paso completo
(Google Cloud + variables de entorno + verificación) en
[`GMAIL_SETUP.md`](GMAIL_SETUP.md).

## 6.2 WhatsApp: Meta y Evolution

En **Empresa → WhatsApp** se configuran los dos proveedores de forma separada
y se escoge cuál usa cada flujo: **CRM** y **recordatorios de cobranza**. Los
tenants existentes conservan Meta en ambos flujos hasta que un administrador lo
cambie.

Para Evolution, el operador de plataforma configura en Coolify:

- `EVOLUTION_API_BASE_URL`: URL privada o pública del servidor Evolution. En
  el despliegue integrado queda como `http://evolution:8080` y no se expone a
  Internet.
- `PUBLIC_API_URL`: URL pública del API IAERP, incluida la ruta `/api/v1`.
- `EVOLUTION_API_KEY` y `EVOLUTION_POSTGRES_PASSWORD`: secretos de plataforma
  administrados solo en Coolify; no se versionan ni se comparten con tenants.

Después el administrador del tenant indica el nombre de instancia y número en
IAERP, y selecciona **Generar QR y conectar WhatsApp**. IAERP crea o reutiliza
la instancia, configura el webhook y muestra el QR; la API key de plataforma no
se expone al navegador. El token del webhook se almacena cifrado. No uses
Evolution para acciones fiscales ni para ejecutar automáticamente instrucciones
recibidas por WhatsApp.

## 6.3 Meta Ads y formularios de leads

En **Empresa → Canales e integraciones → Meta Ads** registra Ad Account ID,
Page ID, Instagram Actor ID opcional, el formulario instantáneo por defecto y
las tres credenciales. IAERP cifra los secretos y muestra la URL pública del
webhook. Registra esa URL en la app de Meta para el campo `leadgen` y usa el
mismo Verify Token ingresado en IAERP.

En **CRM → Campañas** se crea el borrador y se carga una imagen JPG o PNG. El
usuario puede añadir varias variantes; todas comparten público, presupuesto y
conjunto de anuncios. **Preparar todas en Meta** guarda el pedido y crea cada
anuncio pausado en segundo plano; la pantalla muestra **Preparando** hasta que
termine.

Antes del primer uso, un dueño o administrador debe activar **Permitir gasto en
campañas** y fijar el **tope diario del tenant**. IAERP suma campañas activas y
en activación y bloquea cualquier alta que supere ese tope. Revisa nombre,
público y presupuesto antes de usar **Activar campaña**: la pantalla muestra
**Activando** y solo el worker habilita Meta. **Pausar campaña** detiene anuncios,
conjunto y campaña mediante **Pausando**. Al apagar **Permitir gasto**, IAERP
cancela activaciones pendientes y encola la pausa de las campañas activas.
**Actualizar métricas** reconsulta tres días de Insights y
muestra CTR, CPL y costo por lead calificado. Cada acción queda idempotente y
auditada. Mantén el worker de outbox activo; sin él una campaña queda en
**Preparando**, **Activando** o **Pausando** y no debe corregirse con llamadas
manuales a Meta. Pausa las campañas antes de rotar credenciales o activos.

En el Instant Form usa las claves `company_name`, `job_title`, `uses_aws` y
`decision_authority` para precargar los campos de calificación. El usuario debe
confirmar la decisión en la ficha del lead; el webhook nunca se autocalifica.

No reutilices el token de WhatsApp ni pegues secretos en tickets, capturas o
logs. La conexión real y el webhook se prueban primero en preproducción.

### 6.4 LinkedIn y TikTok

IAERP ya puede recibir capturas normalizadas con origen `LINKEDIN_LEAD_GEN` y
`TIKTOK_LEAD_GEN` mediante el endpoint autenticado de conectores. No lo registres
directamente como webhook público: LinkedIn y TikTok requieren validación,
permisos y mapeo propios.

LinkedIn necesita acceso aprobado a Lead Sync, además del OAuth orgánico. TikTok
necesita cuenta Ads, Instant Form y Custom API con Webhooks. Hasta completar esos
pasos, la pantalla no debe mostrarlos como conectados ni permitir gasto. Consulta
`docs/SOCIAL_CRM_CHANNEL_MATRIX.md` para el estado probado.

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
