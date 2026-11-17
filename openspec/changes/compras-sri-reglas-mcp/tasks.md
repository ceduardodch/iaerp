## 1. Diagnóstico y acceso SRI

- [x] 1.1 Confirmar la ruta entre Administración, importador y SRI.
- [x] 1.2 Validar el RUC antes de guardar, añadir una comprobación sin importación, tratar un mes vacío como resultado válido y cubrir el diagnóstico con pruebas sintéticas.
- [ ] 1.3 Verificar la descarga real para BTOB, con intervención humana si el SRI pide CAPTCHA.

## 2. Clasificación fiscal

- [x] 2.1 Añadir configuración de reglas por RUC dentro de cada empresa.
- [x] 2.2 Aplicar la regla sobre XML recuperado con protección de período, política, idempotencia y auditoría.
- [x] 2.3 Probar con dos empresas, comprobantes preliminares, períodos declarados y reintentos.

## 3. Compras

- [x] 3.1 Añadir tablero y acciones directas para clasificar compras por arrastre, clic o teclado.
- [x] 3.2 Permitir crear o desactivar la regla por proveedor y editar etiquetas desde Compras.
- [x] 3.3 Probar el recorrido en escritorio y móvil.

## 4. MCP y cierre

- [x] 4.1 Reproducir el problema del descubrimiento de OAuth y correr pruebas MCP locales.
- [x] 4.2 Corregir el proxy y verificar los metadatos, el catálogo y una consulta autenticada en el entorno local.
- [x] 4.3 Validar OpenSpec, migraciones y pruebas, y registrar los resultados.
- [x] 4.4 Verificar en release y en el entorno publicado según autorización.

## Evidencia del 16 de noviembre de 2026

- 60 pruebas dirigidas con PostgreSQL 17, 40 recorridos de navegador en
  escritorio y móvil y 18 pruebas Node del importador. Compilación web,
  lint, validación de tipos y validación estricta de OpenSpec correctas.
- La corrida amplia de backend registró 840 casos correctos y 30 omisiones.
  La prueba de salud falló sin Redis y pasó al repetirla con Redis disponible.
- Alembic instaló, revirtió y volvió a instalar la migración sin diferencias.
  Las revisiones fiscal y MCP detectaron casos cubiertos en el cambio.
- Nginx local devolvió JSON en la ruta de descubrimiento OAuth. A través del
  mismo proxy, el cliente MCP listó el catálogo permitido y leyó el tenant
  de un token sintético. El sitio publicado aún devuelve HTML en la ruta OAuth.
- La cuenta BTOB abrió el módulo de recibidos. La consulta de facturas en
  un perfil nuevo pidió CAPTCHA. La prueba de descarga admite que el
  operador complete el desafío en la misma ventana antes de descargar.
- MCP público aceptó el token de BTOB y listó `tax.process_received_reports`.
  La ruta de metadatos pública aún devuelve HTML. El despliegue depende de
  integrar el PR en `main`.

## En revisión

- [PR #97](https://github.com/ceduardodch/iaerp/pull/97) integrado a `main`
  el 17 de noviembre de 2026 como `3077ee6`. Excepción puntual de picomatch
  autorizada y documentada en `docs/security-exceptions.md` para continuar la publicación.
- La automatización existente conserva las 08:00 de Ecuador y apunta a los
  cuatro perfiles dedicados. Sigue pausada hasta verificar una descarga real.


## 5. Ejecución en b2b

- [x] 5.1 Separar el acceso técnico del Llavero y mantenerlo en un archivo privado del servidor.
- [x] 5.2 Mantener cuatro contextos de navegador y perfiles persistentes separados.
- [x] 5.3 Programar las 08:00 de Guayaquil y conservar el estado de cada corrida.
- [x] 5.4 Preparar acceso local por túnel SSH para continuar un CAPTCHA en la misma consulta.
- [x] 5.5 Publicar el servicio por Coolify y comprobar navegadores, credenciales y programación en b2b.
- [ ] 5.6 Comprobar la descarga de BTOB y registrar cualquier atención pendiente.

## Publicación verificada del 17 de noviembre

PR #97 y #98 publicados en `7fc3f81` por
[CI/Coolify](https://github.com/ceduardodch/iaerp/actions/runs/44139651424).
API, base, Redis, OAuth JSON, catálogo MCP de BTOB, OpenAPI y paquete web
verificados. La tarea del Mac permanece pausada durante el traslado al servidor.

## Servicio publicado en b2b, 17 de noviembre

PR #99/#100, `1444bdd`, CI/Coolify `44150525336` correctos. Cuatro contextos,
VNC con autenticación y puerto localhost verificados. El archivo de cuentas
conserva 600 por configuración persistente de Coolify. BTOB inició sesión y
descargó factura.txt de noviembre: 3103 bytes, 16 filas y receptor validado
con el preflight del tenant. Prueba sin carga. El lote espera CAPTCHA en
liquidaciones de compra; 5.6 sigue pendiente hasta completar todos los tipos.
ANA KARINA no tiene acceso SRI configurado; las otras sesiones necesitan
su primera entrada en el servidor. La tarea del Mac sigue pausada.

## 6. Persistencia después de reiniciar

- [x] 6.1 Reproducir el bloqueo Singleton heredado al reemplazar el contenedor.
- [x] 6.2 Tomar un bloqueo exclusivo antes de limpiar enlaces y abrir perfiles.
- [x] 6.3 Probar SIGKILL, contenedor nuevo, cuatro cookies conservadas y exclusión de una segunda instancia.
- [x] 6.4 Publicar por CI/Coolify y comprobar cuatro perfiles sanos sin borrar las sesiones existentes.

Las anulaciones se publicaron en `b586aeb`, CI/Coolify `44161725575` correctos;
el reinicio de SRI expuso enlaces de la instancia anterior y exige este
arreglo de arranque. Sólo se limpiarán los tres enlaces previstos tras
excluir cualquier otro orquestador. Node, Docker y revisión de seguridad GO.

## Verificación tras publicar las anulaciones

Producción `fb0537e`, CI/Coolify `44169331013` correctos; archivo de cuentas 0600, VNC protegido, cuatro perfiles y horario servidor verificados. MCP autenticado volvió a inicializar y listar sólo el caso de uso autorizado. Descarga completa sigue pendiente de CAPTCHA; prueba BTOB de 16 filas válida y sin importar. LEXCODE tiene acceso verificado, DATA-CLIP requiere atención y ANA KARINA debe guardar el acceso SRI en Admin.
