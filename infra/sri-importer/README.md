# Perfiles persistentes y reinicios

El entrypoint conserva abierto el descriptor 9 de `/data/importer.lock` y adquiere
un `flock` exclusivo antes de leer o limpiar los perfiles y lanzar Chrome. El
archivo de bloqueo nunca se elimina ni se reemplaza: todos los contenedores que
compartan el volumen deben usar este entrypoint. Un segundo orquestador sale con
código 75 sin tocar los perfiles.

Después de un SIGKILL, Chrome puede dejar tres enlaces simbólicos obsoletos.
El arranque valida el perfil y su padre, comprueba `/proc` para no tocar un Chrome
local activo con el mismo `--user-data-dir` y sólo desvincula `SingletonSocket`,
`SingletonCookie` y, al final, `SingletonLock`. No sigue enlaces ni elimina
archivos, directorios, `Default/Cookies`, `Local State` o sesiones.

Un hostname anterior en `SingletonLock` no identifica un proceso de este
contenedor. La exclusión por kernel del volumen compartido impide que otro
orquestador actual esté activo durante esa limpieza. En la primera migración
desde una versión sin `flock`, el despliegue debe detener todos los contenedores
anteriores antes de arrancar la nueva versión. No se borra ni recrea un perfil
cuando Chrome falla al abrirlo.

La prueba `sh infra/sri-importer/restart-smoke.sh <imagen>` usa sólo datos
sintéticos: guarda una cookie persistente y un marcador por empresa, abre los
cuatro navegadores, rechaza un contenedor simultáneo, mata el primero con
SIGKILL y abre otro con hostname distinto sobre el mismo volumen. Comprueba
los cuatro navegadores y vuelve a leer las cookies y marcadores conservados.
No consulta el SRI ni la API de IAERP.
