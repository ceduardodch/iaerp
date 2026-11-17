# ADR 0020 — Importador SRI en b2b

- Estado: Accepted
- Fecha: 2026-11-17
- Autorización del responsable para ejecutar la descarga en el servidor b2b.

El servicio se administra por Coolify y conserva un contexto de navegador
por empresa. Un volumen mantiene los perfiles y el estado diario. Las cuentas
técnicas existentes conservan sus permisos y se montan desde un archivo privado
del servidor. Los secretos SRI se leen de IAERP por su endpoint auditado.

La tarea consulta a las 08:00 de Guayaquil y recupera una corrida interrumpida
con las claves de idempotencia actuales. Se mantiene la validación de cada
receptor y del tenant antes de importar.

La interacción humana para login o CAPTCHA usa un escritorio en localhost,
accesible por túnel SSH y protegido por una clave VNC privada persistente.
Coolify puede añadir su red compartida, por lo que no se confía sólo en el
aislamiento de red. El contenedor usa usuario sin privilegios, el perfil
seccomp oficial de Playwright 1.61.1 y una red dedicada. Las sesiones permanecen
abiertas después de cada corrida.

[Operación y pruebas](../runbooks/sri-server.md).

El perfil seccomp procede de
[Playwright 1.61.1](https://github.com/microsoft/playwright/blob/v1.61.1/utils/docker/seccomp_profile.json).

## Recuperación del perfil después de una caída

Un cierre abrupto puede dejar enlaces Singleton de Chrome que apuntan al
hostname del contenedor anterior. El arranque toma primero un bloqueo de
archivo exclusivo de todo el importador y conserva su inode durante la vida
del proceso. Con esa exclusión, retira sólo SingletonSocket, SingletonCookie
y SingletonLock obsoletos: nunca Cookies, Local State ni el directorio del
perfil. Un Chrome activo con ese perfil impide la limpieza. La transición
desde una versión sin bloqueo exige detener antes el contenedor anterior;
Coolify hace esa sustitución.

La aceptación automatizada simula SIGKILL y un hostname nuevo, comprueba
cuatro cookies persistentes y rechaza un segundo orquestador sin tocar sus
enlaces. El cierre normal de contextos se hace en paralelo.
