# Seguridad y modelo de amenazas

## Activos

- Identidad, membresias y permisos.
- RUC, datos personales y contactos.
- Certificados de firma y sus contrasenas.
- Facturas, notas de credito, XML y PDF.
- Saldos, cobros, obligaciones y pagos.
- Tokens OAuth, API keys de proveedores y webhooks.
- Historial de agentes, politicas y auditoria.

## Fronteras de confianza

- Navegador y agentes externos hacia Keycloak/API/MCP.
- API hacia PostgreSQL, Redis y MinIO.
- Workers hacia SRI, OpenAI, email y WhatsApp.
- Documentos y mensajes entrantes hacia extraccion.
- Administradores de infraestructura hacia datos y secretos.

## Amenazas y controles

| Amenaza | Control obligatorio |
| --- | --- |
| Fuga entre tenants | Tenant desde token, repositories obligatorios, pruebas negativas y respuesta 404 |
| Escalada de agente | Service accounts, scopes por tool, politicas y prohibicion de autoasignar roles |
| Factura duplicada | Secuencial atomico, clave unica, idempotencia y consulta SRI previa |
| Prompt injection | Contenido untrusted, extraccion estructurada y sin tool calls desde documentos |
| Robo de certificado | Cifrado envelope, storage privado, rotacion, fingerprint y acceso auditado |
| Replay de webhook | Firma, timestamp, nonce e idempotencia |
| Manipulacion de auditoria | Append-only, acceso restringido y hash encadenado por particion |
| Exposicion en logs | Redaccion de secretos/PII y allowlist de campos |
| Dependencia externa caida | Timeout, circuit breaker, reintento acotado y dead letter |
| Agente fuera de control | Limites, presupuesto, rate limit y kill switch global/tenant |
| Archivo malicioso | Limite de tamano, MIME real, antivirus, sandbox de parser y checksum |
| Abuso de URLs firmadas | Expiracion corta, objeto privado y autorizacion antes de emitir URL |

## Reglas de secretos

- Nunca guardar certificados o secretos en Git.
- Secretos de infraestructura viven en Coolify/secret manager.
- Claves maestras no se guardan junto a datos cifrados.
- Contrasenas no se muestran nuevamente despues de guardarlas.
- Rotacion documentada para Keycloak, SRI, OpenAI, email y WhatsApp.
- Revocar y reemplazar cualquier certificado encontrado en un historial Git
  previo antes de usarlo en IAERP.

## Auditoria

Cada evento incluye:

- tenant, actor humano/agente y client;
- accion y entidad;
- timestamp, correlation ID e idempotency key;
- politica evaluada y decision;
- before/after reducido o hash cuando contiene datos sensibles;
- resultado, error normalizado y servicio externo.

Auditoria no equivale a logs. Los eventos tienen retencion y permisos propios.

## Privacidad

- Minimizar datos enviados al modelo.
- No entrenar modelos con datos de tenants por defecto.
- Registrar proveedor y region cuando aplique.
- Permitir exportacion y eliminacion conforme a obligaciones legales, preservando
  documentos fiscales y auditoria que deban conservarse.
- Definir contrato de tratamiento de datos antes del piloto.

## Validacion de seguridad

- Threat model revisado en cada modulo.
- SAST, dependency scan y secret scan en CI.
- DAST en preproduccion.
- Pruebas de aislamiento y autorizacion por cada endpoint/tool.
- Ejercicios de restauracion y revocacion de credenciales.
- Revision externa antes de habilitar agentes autonomos en produccion.
