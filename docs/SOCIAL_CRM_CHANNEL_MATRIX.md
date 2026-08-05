# Matriz de canales sociales del CRM

Última verificación: 2026-08-04, `America/Guayaquil`.

Esta matriz separa cuatro capacidades distintas: publicar contenido, crear
campañas pagadas, recibir formularios y convertir cada respuesta en un lead de
IAERP. Un canal no se considera conectado solo porque tenga publicación
orgánica o porque el CRM acepte su formato.

| Canal | Estado externo verificado | Campañas desde IAERP | Entrada al CRM | Pendiente real |
| --- | --- | --- | --- | --- |
| Facebook / Instagram | Token Meta válido; consulta de identidad respondió `200` | Lista local: preparar, activar y pausar mediante outbox, con corte y tope por tenant | Webhook firmado Meta crea `META_LEAD_AD` en `Nuevo` | PostgreSQL, Redis, CI, credenciales por tenant y prueba controlada con Meta |
| LinkedIn | Token local venció el 2026-07-14; consulta actual respondió `401`; scopes solo orgánicos | No construida | El contrato autenticado acepta `LINKEDIN_LEAD_GEN`, pero no existe webhook ni descarga automática | Renovar OAuth y solicitar Lead Sync por separado; requiere `r_marketing_leadgen_automation`. Para crear formularios/campañas también se requiere acceso de Advertising API |
| TikTok | No existe env, app, OAuth ni cuenta conectada en el workspace | No construida | El contrato autenticado acepta `TIKTOK_LEAD_GEN`, pero no existe webhook automático | Crear app/cuenta Ads, Instant Form y conexión Custom API con Webhooks; luego validar firma, tenant y lead de prueba |

## Contrato común ya disponible

`POST /api/v1/crm/leads/captures` acepta los tres orígenes de formulario y
exige OAuth de IAERP, scope `leads:write`, `Idempotency-Key`, referencia externa,
correo o teléfono, fecha de consentimiento con zona horaria y versión del texto
aceptado. El servicio:

- obtiene el `tenant_id` de la identidad autenticada;
- crea la oportunidad en `NEW`;
- conserva campaña, anuncio y UTM;
- deduplica por proveedor y referencia;
- reutiliza un contacto existente sin perder el nuevo toque de campaña;
- deja auditoría e historial comercial.

Este endpoint sirve para conectores confiables o una carga controlada. No debe
exponerse directamente como webhook público de LinkedIn o TikTok: cada proveedor
necesita su propia verificación y transformación antes de invocar el caso de uso.

## Evidencia externa y accesos

- LinkedIn Lead Sync es un programa separado de Advertising API. La recepción
  usa `leadNotifications` y la lectura usa `leadFormResponses`. Desde el 16 de
  marzo de 2026, los webhooks nuevos deben validarse.
- TikTok ofrece Custom API con Webhooks para enviar Instant Form leads a un CRM.
  También permite conexión directa con otros CRM, pero IAERP necesita su propia
  app y mapeo por tenant.

Fuentes oficiales:

- https://learn.microsoft.com/en-us/linkedin/marketing/lead-sync/leadsync
- https://learn.microsoft.com/en-us/linkedin/marketing/lead-sync/getting-access-leadsync
- https://ads.tiktok.com/help/article/about-available-crm-integrations-tiktok-lead-generation

## Criterio de cierre por canal

Un canal queda completo solo cuando existe evidencia de:

1. acceso aprobado y secreto cifrado por tenant;
2. campaña o formulario de prueba sin gasto, cuando el proveedor lo permita;
3. webhook validado o sincronización autorizada;
4. lead sintético recibido una sola vez en `Nuevo`;
5. atribución, consentimiento e historial visibles;
6. pausa/corte de gasto probados;
7. PostgreSQL, Redis, CI y despliegue verificados.
