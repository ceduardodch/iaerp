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

La conciliación por lookup/GET requiere consulta. El reenvío requiere además
escritura vigente y configuración original completa; una conexión modificada
puede conciliar por lectura, pero no trasladar ni reenviar el payload. Otro
usuario, empresa o API no puede recuperar ni ver esa operación.

El UOW declara retención de idempotencia de 24 horas. Antes de 23 horas, sin
confirmación, se puede reenviar sólo la misma clave y payload. Fuera de esa
ventana, con reloj retrocedido o configuración distinta, sólo conciliar por
lectura: si no existe prueba autoritativa, bloquear sin generar otra clave.
No asumir que un 404 demuestra ausencia después de vencer la retención.

Persistir contador de intentos antes del POST y, cuando llegue respuesta válida,
el ID confirmado antes del GET final. Un rechazo inicial definitivo 400/422
permite editar; después de incertidumbre se conservan clave/payload incluso si
un reintento recibe 400/401/403/409. Cancelar, cambiar cuenta, olvidar perfil,
logout o terminar iOS no descartan incertidumbre financiera. No hay un botón
de borrado/reinicio arbitrario. Evitar concurrencia por UUID entre instancias
del journal en el mismo proceso.

## Interfaz y pruebas

Al abrir una cuenta, revisar sus pendientes antes de habilitar Nuevo. Mostrar
«Guardado pendiente» y Recuperar, sin datos de otra identidad. Se puede consultar
clientes/facturas mientras la creación queda bloqueada. Una recuperación sólo
sale de pendiente tras confirmar el documento del servidor.

Probar reinicio antes del envío, commit sin respuesta y respuesta antes de
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
