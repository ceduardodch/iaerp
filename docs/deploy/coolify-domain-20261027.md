# Coolify: dominio de administración vigente

Fecha: 2026-10-27. Cambio autorizado por Carlos en la sesión ATS.

`coolify.fractalsoft.io` devuelve NXDOMAIN en DNS público. La dirección vigente
es https://coolify.b2b.com.ec. Actions usa ese dominio tanto para solicitar el
despliegue como para consultar su estado; conserva token, UUID y entorno.

Se agregó un CNAME proxied en la zona activa b2b.com.ec al mismo túnel existente.
Se validó la pertenencia de zona y túnel a la misma cuenta antes de escribir.
En el servidor se añadieron solo las rutas del nuevo panel (puerto local 8000)
y terminal (6002), manteniendo las rutas previas y todos los otros servicios.
La configuración previa queda en:
`/etc/cloudflared/config.yml.before-coolify-b2b-20261026T174233Z`.

Verificación: DNS público resuelve; HTTPS válido devuelve 302 al login del nuevo
dominio y /api/health responde OK. /health/ready de IAERP confirma base/Redis.
No se emitieron credenciales ni se cambió la autenticación del panel.

No se desplegó la app por SSH ni ejecutando Docker de forma manual. El cambio
ATS ya está integrado por PR #85 como e19795f; su CI tiene aprobados backend,
frontend, seguridad y contratos. La llamada a Coolify falló por el dominio
anterior. Tras integrar esta corrección de workflow, ejecutar CI sobre main
con deploy=true, porque el filtro de rutas no publica cambios solo de workflow.
El éxito de esa ejecución y el ATS real se documentan aparte al cerrar.

## Cierre verificado

CI manual con deploy=true 40371809581 y Coolify terminaron en verde. API y web
ejecutan 5bd095d, están sanas y la sesión real generó el ATS de septiembre v1.
El FQDN principal de Coolify también quedó en coolify.b2b.com.ec. Valor previo
respaldado en /etc/cloudflared/coolify-fqdn-before-b2b-20261026.json.
No se alteraron credenciales del panel ni se presentó el anexo ante SRI.
