# ADR 0025: Recuperación durable de un borrador desde iPhone

- Estado: Accepted
- Fecha: 2026-11-18
- Solicitud: Carlos pide hacer lo necesario para conectar IAERP y dejar lista
  la instalación/prueba, tras explicar el bloqueo de guardados interrumpidos.
- Sustituye sólo la exclusión de persistencia de negocio de ADR 0022 para el
  registro mínimo de una operación pendiente; conserva la exclusión de caché
  general y de escrituras offline. Complementa ADR 0023/0024.

## Decisión

Antes de cualquier POST de creación, guardar UUID de idempotencia y payload
original, fecha, identidad y destino en Keychain `WhenUnlockedThisDeviceOnly`,
sin sincronización, archivos de negocio o tokens en ese registro. La escritura
del registro debe completarse antes de la red. Máximo una operación pendiente
por identidad financiera y empresa, con colección acotada a 2 MiB.

Detectar pendientes por issuer, sujeto, organización, tenant y API canónica.
Canonicalizar scheme/host/puerto HTTPS y slash terminal, conservando el caso de
la ruta. Cambiar el UUID local del perfil, cliente OIDC, alias o host de documentos
no puede ocultar una operación incierta ni permitir otra clave. Conservar la
configuración completa original y UUID del perfil como procedencia.

Cada recuperación exige sesión actual desbloqueada, contexto y membresía activa
revalidados contra el servidor, y guardas de generación/perfil tras cada await.
Consultar primero la operación mediante el endpoint de ADR 0024; con factura
identificada, consultar ese documento y comprobar sus campos antes de borrar el
registro. Permitir normalización de cuotas del servidor cuando no se enviaron
cuotas explícitas y estados que hayan avanzado legítimamente. No recalcular
impuestos en el cliente.

La conciliación por lookup/GET requiere consulta. Un primer envío requiere
además escritura vigente y configuración original completa; una conexión
modificada sólo puede conciliar. Otro usuario, empresa o API no puede recuperar
ni ver esa operación.

**Corrección de seguridad y producto en 0.4.1:** si ya se persistió al menos un
intento y no hay ID confirmado ni lookup positivo, conservar el pendiente y
exigir conciliación humana. No enviar otro POST, tampoco dentro del mismo
proceso. La retención declarada de 24 horas y un reloj local de 23 horas no
permiten probar que una clave sigue viva: un retroceso parcial del reloj puede
superar `now >= createdAt`. Un 404 no demuestra que nunca existió una factura.

El contador cero, persistido antes de toda llamada, acredita que todavía no hubo
intento. Sólo ese caso puede iniciar el POST original. Se conserva una ventana
cautelar de 23 horas para la vigencia del primer envío; no garantiza reenvíos.
Si el proceso muere entre incrementar el contador y enviar, puede ser necesaria
conciliación aunque la red nunca haya recibido nada. Producto acepta ese límite
para evitar duplicados. Un ID confirmado siempre permite conciliar por GET.

Persistir contador de intentos antes del POST y, cuando llegue respuesta válida,
el ID confirmado antes del GET final. Un rechazo inicial definitivo 400/422
permite editar; 401/403/409, respuesta inválida o error de red conservan clave y
payload para lookup/GET, sin autorizar otro POST. Cancelar, cambiar cuenta, olvidar perfil,
logout o terminar iOS no descartan incertidumbre financiera. No hay un botón
de borrado/reinicio arbitrario. Evitar concurrencia por UUID entre instancias
del journal en el mismo proceso.

## Interfaz y pruebas

Al abrir una cuenta, revisar sus pendientes antes de habilitar Nuevo. Mostrar
«Guardado pendiente» y Recuperar, sin datos de otra identidad. Se puede consultar
clientes/facturas mientras la creación queda bloqueada. Contador cero usa
«Continuar guardado» y explica que intentará enviar el borrador por primera vez;
un intento previo usa «Consultar guardado» y sólo lee. Cerrar el formulario
conserva la operación pendiente y no se presenta como borrado del guardado. Una recuperación sólo
sale de pendiente tras confirmar el documento del servidor.

Probar purga tras 26 horas reales con reloj local de sólo dos horas: no hay
segundo POST ni documento duplicado y el pendiente queda intacto. Probar además
reinicio antes del envío, commit sin respuesta y respuesta antes de
confirmación, manteniendo un único documento. Cubrir fallos de Keychain antes
de red, permisos/tenant cambiados, expiración, respuesta inválida, cambio de
configuración pública y dos instancias. Pruebas de proceso y Keychain usan sólo
fixtures sintéticos del simulador; no acreditan Face ID o el servidor productivo.

La prueba de Keychain necesita un host firmado. El simulador usa firma ad hoc
y entitlements exclusivos de ese SDK; iPhone requiere firma/provisioning del
titular. No excluir la prueba cuando el host carece de acceso al Llavero.

Producto, plataforma y seguridad mantienen los límites de las decisiones
previas. Este registro no implementa sincronización general, emisión SRI o
autorización para retransmitir otro comprobante.
