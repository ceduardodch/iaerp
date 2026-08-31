# Estado actual y relevo

Este archivo es la fuente de verdad para retomar la implementacion. Debe
actualizarse al cerrar una sesion de trabajo o cambiar el estado de un sprint.
Los documentos de producto y arquitectura siguen siendo vinculantes para el
alcance y las decisiones.

## Corte verificado

- Automatización SRI multiempresa probada con datos reales: 2026-08-31
  `America/Guayaquil`. El comando local `--all` procesó en secuencia DATA-CLIP
  y BTOB SAS con RUC y clave SRI, cuenta IAERP y perfil de navegador separados.
  DATA-CLIP listó 468 comprobantes en tres reportes; BTOB SAS listó 18 en dos
  reportes (17 facturas y una retención). Ambas corridas terminaron y encolaron
  la recuperación XML. El formulario ahora borra, fija y verifica localmente
  cada campo antes de enviarlo para impedir que Chrome restaure otro acceso.
  La tarea está activa todos los días a las 08:00 con `--all`. Pasan las cinco
  pruebas de selección y aislamiento de empresas, `node --check` y
  `git diff --check`. El cambio llegó a `main` por el PR `#71`, merge
  `b2154d9`; los CI `33420223753` de `main` y `33420362315` de la
  sincronización de `release` terminaron verdes. No hubo despliegue Coolify
  porque el cambio afecta solo scripts locales y documentación.
  El procedimiento de recuperación quedó en
  `docs/runbooks/sri-multicompany-recovery.md`, con el mapa de Llavero y
  perfiles, rotación de cuentas IAERP, pruebas por empresa y diagnóstico sin
  exponer secretos.

- Automatización local mensual de comprobantes SRI probada con datos reales:
  2026-08-31 `America/Guayaquil`. El ejecutor visible entra por `SRI en Línea`
  con el acceso cifrado en el Llavero de macOS, calcula el mes de ayer,
  selecciona día `Todos` y recorre los cinco tipos sin usar el módulo legado ni
  un scraper remoto. La prueba de agosto descargó los tres tipos con filas,
  listó 468 registros, creó 131 preliminares, omitió 337 ya conocidos y encoló
  la recuperación XML. La tarea local quedó activa cada día a las 08:00. Si el
  SRI presenta CAPTCHA, MFA o cambia el formulario, se detiene y pide atención.
  PR `#69`, merge `af64e3d` y CI `33415359865` verdes. Una segunda corrida real
  devolvió el mismo conjunto y reutilizó las claves idempotentes por contenido;
  no repitió la escritura fiscal.

- Refresco mensual de comprobantes SRI listo para promoción: 2026-08-31
  `America/Guayaquil`. La tarea toma el mes de la fecha de ayer y lo consulta
  completo con el día `Todos`; el día 1 consulta solo el mes anterior, para
  incluir los comprobantes del último día que el SRI publica al día siguiente.
  REST y MCP reciben
  `reportYear` y `reportMonth`, aceptan fechas distintas dentro del periodo y
  rechazan cualquier fila de otro mes. La repetición queda protegida por hash
  de evidencia, idempotencia y la clave única `tenant_id + access_key`; un TXT
  no degrada un XML autorizado. Si ya existe una recuperación XML en cola, el
  refresco agrega solo los documentos nuevos; si está corriendo, la reutiliza
  y el siguiente corte recogerá cualquier preliminar pendiente. Pasan Ruff,
  mypy, 43 pruebas dirigidas, los contratos YAML y las 23 huellas MCP. La suite
  total deja 609 aprobadas y 36 omitidas; sus seis fallos son preexistentes de
  entorno (clave Fernet de prueba, Redis de salud y unicidad SQLite de nómina),
  fuera de este flujo. Falta promoción por CI, reactivar la tarea y la
  autenticación inicial de DATA-CLIP para la prueba real.

- Flujo diario de comprobantes recibidos publicado en producción: 2026-08-31
  `America/Guayaquil`. El Mac consulta en el portal SRI el día anterior y los
  cinco tipos de comprobante; no descarga reportes vacíos. IAERP expone el caso
  de uso compartido por REST y MCP para importar de uno a cinco TXT ya
  custodiados y crear un solo trabajo durable de recuperación XML. El servidor
  deriva el tenant del token, exige `tax:write`, política de automatización,
  idempotencia y auditoría, rechaza archivos que mezclen fechas y no devuelve
  RUC, claves de acceso ni contenido fiscal. La sesión y contraseña del portal
  se quedan en Chrome en el Mac. Ruff y mypy están verdes; las 8 pruebas
  dirigidas de REST/MCP pasan, junto con el contrato YAML y las 22 huellas MCP.
  La suite completa dejó 599 aprobadas y
  36 omitidas; sus seis fallos locales son previos y ajenos (clave Fernet de
  ejemplo, Redis apagado y contrato PostgreSQL de nómina). La repetición con
  una clave Fernet sintética dejó solo el caso de nómina que SQLite no traduce.
  El commit `4b7eaca` llegó a `main` por el PR `#63` como merge `f37743b`.
  El CI `33392739692`, el despliegue Coolify, `/health/live`,
  `/health/ready`, `/health/startup`, OpenAPI y la ruta MCP autenticada quedaron
  verdes. Falta emitir la cuenta local `SRI Daily Import`, guardarla en el
  Llavero de macOS y acordar la hora antes de activar la tarea diaria.

- Correctivo de edición masiva de compras publicado en `main`: 2026-08-22
  `America/Guayaquil`. En producción quedaron seleccionadas 36 compras de enero
  a junio, todas con uso tributario `No deducible`, control interno pendiente y
  periodos ya declarados. El lote bloqueaba primero el cambio fiscal y por eso
  tampoco guardaba la marca interna permitida. Ahora conserva el uso tributario
  del periodo declarado, pero sí aplica `Gasto real`, `Solo tributario` y tags;
  el resultado indica cuántas compras quedaron protegidas y muestra el motivo
  exacto de cualquier fallo. Pasan Ruff, mypy, 25 pruebas de CxP, lint, build y
  34 recorridos Playwright en escritorio/móvil con WCAG y zoom. PR #60, CI de
  producción `32598659878`, Coolify, salud pública, OpenAPI y paquete web
  terminaron verdes.

- Edición masiva de compras publicada en `main`: 2026-08-22
  `America/Guayaquil`. La vista Compras permite seleccionar hasta 100 filas
  visibles y cambiar en un solo guardado el uso tributario, el control interno
  y los tags. Cada campo puede quedar en `No cambiar`, por lo que el lote no
  pisa datos distintos por accidente; también permite reemplazar o limpiar los
  tags. Un cambio tributario exige motivo y conserva el bloqueo de periodos ya
  declarados. El servidor procesa cada compra con idempotencia y auditoría,
  guarda las válidas, conserva las fallidas y las reintenta con una clave nueva.
  Pasan Ruff, mypy, las 24 pruebas de CxP, lint, build y los 32 recorridos
  Playwright del módulo en escritorio y móvil, incluidos WCAG y reflow. Dos
  revisiones independientes dieron GO. PR #57 quedó en `main`; el workflow
  manual `32594481883`, Coolify y la salud pública (`live`, `ready`, `startup`)
  terminaron verdes. El OpenAPI y el paquete web públicos ya exponen la edición
  masiva.

- Dashboard tributario one-page y escenario de renta listos localmente:
  2026-08-22 `America/Guayaquil`. El estado `DECLARADO` de un periodo IVA solo
  identifica los documentos de meses cuyo IVA se marcó como presentado; no se
  confunde con una declaración anual de renta ni con un cierre inmutable. Los
  meses abiertos quedan separados en la proyección. IAERP no infiere el régimen
  ni la tarifa por el RUC: el usuario puede elegir un escenario manual al 25 %,
  que el backend calcula con `Decimal` y rotula como referencia antes de
  conciliación. Tributario usa una sola página
  con accesos a renta, mes/declaración, detalle anual y retenciones. El dashboard
  principal muestra el corte de compras y resultado de meses con IVA presentado,
  junto con el escenario manual. Pasan las pruebas dirigidas de backend y UI;
  la suite completa conserva fallos ajenos por la clave Fernet local y un caso
  de nómina de otra sesión. Pendiente promoción por CI.

- Dashboard y clasificación tributaria/interna de compras listos localmente:
  2026-08-22 `America/Guayaquil`. El tratamiento tributario queda separado del
  control interno: una compra puede ser deducible o no deducible ante el SRI y,
  de forma independiente, ser `Gasto real`, `Solo tributario` o quedar pendiente
  de revisión interna. El dashboard alterna ambos ejes; Compras filtra por cada
  uno y agrupa los gastos reales por sus tags de proyecto. `Editar
  clasificación` corrige las dos marcas sin salir del listado. Un cambio fiscal
  exige motivo y se bloquea si el periodo está `DECLARADO`; la marca interna sí
  puede corregirse luego porque no cambia IVA, ATS ni renta. La migración pasó
  upgrade, validación, downgrade, re-upgrade y `alembic check` en PostgreSQL.
  Pasan Ruff, mypy, 47 pruebas backend y 30 recorridos Playwright en
  escritorio/móvil, con WCAG y zoom al 400 %. Pendiente autorización para
  commit, push y promoción.

- Corrección del avance anual en el dashboard principal lista localmente:
  2026-08-21 `America/Guayaquil`. La API ya entregaba el acumulado anual, pero
  el dashboard solo mostraba el IVA y las compras del mes; por eso el usuario
  no encontraba lo publicado. Ahora el bloque Tributario muestra resultado
  antes de ajustes, retenciones de renta, compras pendientes y el aviso de
  respaldos incompletos. `Ver detalle anual` abre directamente la pestaña Año
  fiscal. Pasa lint, build, 28 recorridos Playwright del archivo afectado y la
  prueba dirigida en escritorio/móvil. El usuario autorizó commit, push y
  promoción por `release -> PR -> main`.

- Avance anual tributario publicado en `main`: 2026-08-21
  `America/Guayaquil`. Tributario usa una sola página con pestañas para mes y
  declaración, año fiscal y retenciones. El año muestra ventas netas, compras
  deducibles confirmadas, no deducibles y pendientes, resultado antes de
  ajustes, doce cortes mensuales hasta el mes elegido y retenciones de renta e
  IVA separadas. No
  inventa una tarifa ni afirma una devolución: explica que el saldo a favor de
  renta solo puede evaluarse contra el impuesto causado al cierre y que el IVA
  tiene otro trámite. Las notas de crédito restan y heredan la clasificación de
  su factura sustento cuando está enlazada; una nota sin enlace queda pendiente.
  La vista avisa cuando hay documentos preliminares y pide sus XML antes de
  evaluar un saldo a favor. Pasan Ruff, mypy, lint, build, 34 pruebas fiscales
  dirigidas y los recorridos críticos Playwright de teclado, foco visible,
  móvil, reflow, errores y axe. La base completa de 500 pruebas backend estaba
  verde antes del cierre y los cambios fiscales posteriores quedaron cubiertos
  por la suite dirigida. Los 46 recorridos Playwright de Tributario pasaron en
  serie en escritorio y móvil. Dos revisiones independientes (fiscal/backend y
  UI/UX/accesibilidad) dieron GO. PR #53 quedó en `main` como `f2be77d`; CI
  `32538361277`, Coolify, salud pública y paquete web terminaron en verde.

- Correctivo de recuperación SRI para persona natural publicado en `main`:
  2026-08-21 `America/Guayaquil`. Algunos XML autorizados identifican al
  receptor con su cédula de 10 dígitos aunque el tenant use el RUC natural de
  13 dígitos. La recuperación acepta esa equivalencia solo cuando el RUC
  termina en `001`, su base es una cédula válida y los primeros 10 dígitos son
  exactos; conserva el rechazo para empresas, RUC inválidos, otra cédula y otro
  tenant. El selector permite cargar juntos los reportes de facturas, notas de
  crédito y retenciones, y el trabajo usa todas sus claves válidas para buscar
  los XML. Las pruebas confirman factura, nota de crédito con ajuste de CxP y
  retención con IVA y renta separadas. Pasan Ruff, mypy, 95 pruebas dirigidas,
  lint/build y 36 recorridos Playwright de Tributario en escritorio/móvil. Dos
  revisiones independientes dieron GO. PR #52 quedó en `main` como `e09b467`;
  CI `32531454470`, despliegue Coolify y salud pública quedaron verdes.

- Recuperación de XML recibidos desde el SRI publicada en `main`:
  2026-08-21 `America/Guayaquil`. Tributario ofrece `Completar XML desde el
  SRI` para las compras preliminares que ya tienen una clave válida del listado
  mensual. La solicitud crea un trabajo durable y auditable; el worker consulta
  una clave a la vez fuera de la transacción, valida autorización, clave, RUC
  receptor y período, guarda el sobre XML en MinIO privado e ingiere el mismo
  caso de uso fiscal existente. Las fallas temporales del SRI, MinIO o la base
  se reintentan sin perder el ítem; un lease evita el doble proceso y el período
  se bloquea al crear el trabajo. Cada comprobante tiene una fila durable propia,
  por lo que el avance no reescribe un JSON creciente; una prueba con 1.201
  documentos confirma que tampoco hay corte de 1.000. La pantalla
  informa recuperados, no disponibles y errores, identifica por proveedor,
  fecha y total los que requieren carga manual, y no habilita cifras hasta
  tener el desglose real. El servicio SOAP conserva ahora el XML autorizado.
  La migración completó upgrade, insert real, downgrade, re-upgrade y
  `alembic check` en PostgreSQL 17. Ruff, mypy, contratos, lint/build, 109
  pruebas fiscales y 36 recorridos Playwright de Tributario en escritorio/móvil están
  verdes; incluye replay idempotente, scope/tenant, lease, reintento técnico y
  nota de crédito que reduce la CxP. Dos revisiones independientes dieron GO.
  PR #50 quedó en `main` como `e6b2b23`; CI `32525550098`, despliegue Coolify
  y salud pública (`live`, `ready`, `startup`) quedaron verdes. El OpenAPI y
  el paquete web productivos ya exponen la recuperación desde el SRI.

- Claridad de compras para la declaración IVA lista en `release` local:
  2026-08-21 `America/Guayaquil`. Tributario ya no presenta cifras parciales
  como listas para copiar: mientras falten XML autorizados bloquea los botones
  de copia, explica que el TXT sirve solo para control y lleva el foco directo
  a la carga de XML o ZIP. El resumen muestra por separado compras gravadas con
  IVA, tarifa 0 %, exentas y no objeto, usando el desglose que ya calcula el
  servidor desde `FiscalDocumentTax`. Cuando la evidencia está completa anuncia
  que el periodo puede pasar a revisión; el crédito tributario y los casilleros
  marcados siguen sujetos a la revisión contable prevista en el plan fiscal.
  Pasan lint, build y 32 recorridos Playwright de Tributario en escritorio y
  móvil. Pendiente revisión independiente y autorización para commit, push y
  promoción.

- Correctivo de compras TXT sin desglose publicado en `main`:
  2026-08-21 `America/Guayaquil`. El listado TXT del portal puede traer
  subtotal, IVA y total, pero no separa las bases por tarifa; IAERP lo estaba
  marcando como completo y por eso contaba 417 comprobantes mientras mostraba
  compras y crédito tributario en cero. Ahora todo comprobante TXT queda
  preliminar hasta cargar su XML autorizado, el motor detecta también registros
  heredados sin `FiscalDocumentTax` y la pantalla muestra por separado la
  cantidad y el total general de compras pendientes de XML sin usarlo en los
  casilleros. La migración corrige documentos ya cargados, la evidencia de la
  CxP enlazada y los periodos no declarados; nunca reabre un periodo
  `DECLARADO`. También descarta tareas abiertas de revisión/ATS que nacieron de
  esa evidencia incompleta. Pasan Ruff, mypy, 112 pruebas fiscales/CxP, 74
  pruebas dirigidas en PostgreSQL, contratos, lint/build y 28 recorridos
  Playwright de Tributario en escritorio/móvil. La migración completó upgrade
  desde el head previo con backfill, downgrade a base, re-upgrade y
  `alembic check`; una prueba adicional confirmó aislamiento entre dos tenants,
  conservación de `DECLARADO` y documentos con desglose intactos. Dos revisiones
  independientes dieron GO. PR #48, CI `32517346780`, despliegue Coolify y
  salud pública (`live`, `ready`, `startup`) quedaron verdes; el OpenAPI
  productivo ya expone los cuatro campos de compras pendientes.

- Notas de crédito recibidas publicadas en `main`:
  2026-08-21 `America/Guayaquil`. IAERP conserva el tipo y número del
  comprobante modificado, enlaza la nota con la compra por tenant, sentido,
  RUC del proveedor, tipo y serie, y funciona aunque se cargue antes o después
  de la factura. Solo el XML autorizado aplica el crédito a la CxP; el TXT del
  portal queda preliminar aun cuando traiga un total. Reprocesar el XML no
  duplica el movimiento, una CxP anulada no se reabre y una nota autorizada no
  puede cambiar luego de factura sustento. IVA resta base e impuesto; el ATS
  informa el detalle tipo `04` con valores positivos y los cinco datos
  obligatorios del comprobante modificado, incluso si pertenece a otro mes.
  Pasan Ruff, mypy, 68 pruebas dirigidas SQLite, 60 PostgreSQL, migración
  completa con `alembic check` y validación del XML sintético contra el XSD
  oficial del SRI. Dos revisiones independientes dieron GO. El listado real
  entregado contiene 23 notas válidas para enlazar, pero las 23 carecen de
  importe total y siguen preliminares: se debe reingerir el TXT y
  cargar los XML autorizados para cerrar cifras y saldos. El usuario autorizó
  la promoción. PR `#46` quedó en `main` como `d7fae21`; CI
  `32508035636`, despliegue Coolify y salud pública (`live`, `ready`,
  `startup`, base, Redis, esquema y OIDC) terminaron bien. `main` y `release`
  tienen el mismo árbol de archivos; los hashes difieren solo por el squash
  del PR.

- Alta rápida de maestros desde Nueva factura publicada en `main`:
  2026-08-20 `America/Guayaquil`. El usuario puede crear un cliente
  con sus datos básicos o un producto con precio e impuesto y dejarlo
  seleccionado sin salir ni perder cantidad, descuento o fecha del borrador.
  La factura muestra la dirección fiscal del establecimiento y permite
  cambiarla allí mismo o desde Empresa, solo con `organization:write`. El
  código fiscal queda inmutable. Para que XML y RIDE nunca difieran, IAERP
  bloquea el cambio mientras existan comprobantes `SIGNED`, `RECEIVED` o
  `PENDING_AUTHORIZATION`, usando el mismo lock que la emisión. Pasan Ruff,
  mypy, contratos, 27 pruebas backend dirigidas (2 omitidas) y 22 recorridos
  Playwright de factura en escritorio/móvil con axe; lint y build están
  verdes. Dos revisiones independientes dieron GO. PR `#43` quedó en `main`
  como `800c043`; CI, despliegue Coolify, salud pública y contrato OpenAPI
  terminaron bien. `main` y `release` quedaron alineadas en el mismo corte.

- Identidad del proveedor visible en el RIDE publicada en `main`: 2026-08-20
  `America/Guayaquil`. Las facturas y notas de crédito nuevas muestran en
  `Información adicional` a BTOB SAS y su RUC 1793113192001, el mismo RUC que
  ya se incorpora al XML conforme a la Resolución NAC-DGERCGC26-00000027.
  La identidad viene de la configuración central de plataforma y no puede ser
  alterada por un tenant. El cambio no modifica XML firmado, montos, clave de
  acceso, autorización ni comprobantes históricos. La configuración central
  normaliza el nombre y rechaza al arrancar un RUC que no tenga 13 dígitos
  ASCII. Pasan Ruff, mypy, contratos y la suite backend aislada con 468
  pruebas aprobadas, 36 omitidas y la prueba de salud local excluida porque
  Redis no está levantado; el PDF sintético fue renderizado y revisado sin
  cortes ni desbordes. Dos revisiones independientes dieron GO. PR `#41`
  quedó en `main` como `3eb7494`; CI, despliegue Coolify y salud pública
  (`live`, `ready` y `startup`) terminaron bien. `main` y `release` quedaron
  alineadas al mismo commit.

- Revisión masiva de compras SRI lista en el árbol local de `release`:
  2026-08-18 `America/Guayaquil`. La bandeja permite seleccionar hasta 100
  comprobantes visibles y aplicar en un solo paso su uso tributario, tags y
  estado de pago. El modo seguro no registra pagos ni borra tags; marcar varias
  como pagadas exige una confirmación final con cantidad y total. Las CxP con
  movimientos conservan pagos y tags, incluso cuando el XML se reconcilia en
  ese momento con una compra manual. Los resultados separan revisadas,
  protegidas, omitidas y fallidas; un reintento conserva la clave idempotente y
  solo mantiene seleccionados los fallos. Pasan Ruff, mypy, 20 pruebas backend,
  contratos OpenAPI, lint/build y 22 recorridos Playwright de Compras en
  escritorio/móvil. Dos revisiones independientes quedaron en GO. El usuario
  autorizó commit, push y promoción por `release -> PR -> main`.

- Revisión rápida de compras SRI publicada en `main`:
  2026-08-18 `America/Guayaquil`. Compras prioriza una bandeja de comprobantes
  SRI pendientes sobre el alta manual. En un solo guardado el usuario decide
  si la compra es gasto deducible, solo registro tributario/no deducible o
  queda pendiente; registra si ya se pagó, fija una fecha prevista o deja el
  pago sin confirmar; y aplica valores de los catálogos analíticos existentes.
  El caso de uso enlaza o reutiliza la CxP creada por la carga SRI, conserva el
  XML y sus importes, exige scopes de extracción y escritura, y usa la unidad
  de trabajo idempotente con auditoría. Una fecha desconocida se guarda como
  tal y no entra al filtro de vencidas; pagos posteriores reducen o cancelan
  la agenda para que nunca quede una CxP saldada con pago futuro activo. Pasan
  Ruff, mypy, 17 pruebas backend dirigidas (una PostgreSQL ajena omitida),
  contratos OpenAPI, DDL offline de subida/bajada, build y 18 recorridos
  Playwright de Compras en escritorio/móvil con axe. Dos revisiones
  independientes quedaron en GO. `origin/main` y `origin/release` apuntan al
  mismo corte publicado `47f946a`.

- Corrección de permisos de cobranza lista en `release`: 2026-08-17
  `America/Guayaquil`. La regla general del tenant estaba activa, pero las
  facturas emitidas conservaban `collection_enabled=false` y la única pantalla
  para cambiarlo desaparecía después del borrador. Cartera ahora muestra cuál
  permiso falta, bloquea el envío hasta resolverlo y permite habilitar la
  cobranza de esa cuenta sin cambiar XML, RIDE, autorización SRI, importes ni
  saldo. Los envíos manuales programados sin cuota concreta usan el saldo total
  y el vencimiento abierto más antiguo al ejecutarse, en vez de fallar por
  contexto incompleto; usan la plantilla general y rechazan un texto propio
  que no pueda conservarse. Si la cuenta se paga antes de ejecutar un correo
  programado, el worker lo omite y no contacta al cliente. La escritura es
  tenant-safe, idempotente y auditada; mantiene
  iguales el permiso operativo de la cuenta y el metadato comercial de la
  factura. Pasan Ruff, mypy, 24 pruebas backend dirigidas, contratos YAML, lint/build y
  24 recorridos Playwright de Cartera en escritorio/móvil con WCAG 2.1 AA.
  Dos revisiones independientes quedaron en GO y el usuario autorizó commit,
  push y promoción a producción.

- Correctivo de clasificaciones analíticas listo en `release`: 2026-08-12
  `America/Guayaquil`. Producción no guardaba el primer catálogo: la migración
  creó `created_at` y `updated_at` obligatorios sin `DEFAULT now()`, PostgreSQL
  rechazaba el `INSERT`, la transacción se revertía y el manejador general lo
  mostraba como conflicto de clave. Una migración nueva repara los defaults en
  clasificaciones, valores y asignaciones; el validador de migraciones prueba
  ahora un alta real en PostgreSQL. La pantalla además valida el código antes
  de enviar, muestra en español los conflictos `409` y deja de renderizar los
  `422` como `[object Object]`. El manejador global distingue violaciones
  únicas de otros fallos de integridad y el contrato asyncpg se prueba contra
  PostgreSQL real. Pasan Ruff, mypy, 4 pruebas backend dirigidas,
  lint/build frontend, 4 recorridos Playwright en escritorio/móvil y la
  reproducción PostgreSQL antes/después. Falta autorización para commit, push
  y promoción.

- Correctivo de operación preparado para `main`: 2026-08-11
  `America/Guayaquil`. Tributario conserva grupos compactos y su prueba de
  historia abre el grupo correspondiente antes de consultar el expediente.
  Cartera muestra los días desde la fecha de factura y ordena de mayor a
  menor. CRM deja crear prospectos sin RUC o cédula mediante una referencia
  interna no fiscal; facturación conserva sus validaciones de identificación.
  El resumen de campañas queda plegado para que el pipeline aparezca primero.
  Pasan Ruff, mypy, 21 pruebas backend dirigidas, lint/build frontend y los
  26 recorridos Playwright de Tributario en escritorio y móvil. Pendiente CI,
  despliegue Coolify y comprobación pública.

- Clasificaciones analíticas por tenant en promoción a `main`: 2026-08-11
  `America/Guayaquil`. Empresa configura catálogos de uno a tres niveles y
  valores controlados; Facturas y Compras los asignan sin texto libre. Compras
  permite clasificar una CxP existente en línea y agrupar la lista por tag.
  Tributario hereda esos tags desde la CxP enlazada y agrupa los comprobantes
  de forma compacta, cerrados por defecto. Cada documento conserva su ruta de
  clasificación; una factura solo cambia en borrador y una CxP antes de tener
  movimientos. No modifica XML, RIDE, SRI, ATS, IVA, asientos ni saldos. La
  relación genérica permite que nuevos módulos reutilicen el catálogo sin
  columnas fijas. Se añadieron scopes OIDC web y de cuentas de servicio. Pasan
  lint/build frontend, Ruff, mypy, 16 pruebas backend dirigidas y 13 recorridos
  Playwright de Tributario. Pendiente CI, despliegue Coolify y comprobación
  pública para declararlo operativo en producción.

- Navegacion principal responsive lista en el arbol local de `release`:
  2026-08-11 `America/Guayaquil`. Los diez modulos dejaron de competir en una
  fila plana: escritorio usa `Resumen` y tres grupos (`Comercial`,
  `Operaciones`, `Administracion`); hasta 960 px muestra una barra de 56 px y
  un panel lateral con todos los destinos. El panel tiene controles tactiles de
  44 px, scroll vertical, cierre con `Escape` y clic exterior, trampa y retorno
  de foco, estado actual y sesion. Al navegar, el foco pasa al contenido. Lint
  y build pasan; 28 recorridos dirigidos de navegacion y WCAG pasan en
  escritorio/movil, junto con 49 recorridos de Facturas, Cartera, Compras y
  Tributario. Pendiente CI, PR, despliegue Coolify y comprobacion publica.
- Acceso seguro de agentes al CRM operativo en producción: 2026-08-10
  `America/Guayaquil`. MCP expone consulta, alta de leads y actividades con
  esquemas cerrados, scopes `leads:read/write`, paridad con REST, idempotencia,
  auditoría, apagado común y límite durable por tenant, actor y herramienta.
  La captación fuerza estado `NEW` y origen `MCP`; un agente no puede suplantar
  Meta, asignar dueño, valor, puntaje ni marcar un lead como ganado. El catálogo
  exige la huella aprobada de cada herramienta y el contrato valida paridad con
  el runtime. El cliente local usa `client_credentials`, renueva tokens cortos
  y reintenta una vez ante `401`; no guarda Bearer fijos. Ruff, mypy, contratos,
  45 pruebas dirigidas, tres omisiones PostgreSQL y el DDL PostgreSQL de
  subida/bajada pasan. Los conectores sociales usan el scope separado
  `leads:capture`; la cuenta CRM no puede falsear atribución. PR #33 quedó en
  `main` como `02012e2`; CI `31348855398`, despliegue Coolify y salud pública
  pasaron. La cuenta `Claude CRM BTOB` está activa hasta 2027-08-10 solo con
  `leads:read` y `leads:write`; el tenant permite escrituras automatizadas.
  `backend/.env` guarda el client id y secreto con modo `0600`, sin Bearer fijo,
  y `crm_agent_cli.py leads --limit 1` obtuvo una respuesta real válida.
- Corrección OIDC de CxP lista en copia aislada de `origin/main`: 2026-08-05
  `America/Guayaquil`. Producción responde `403 Missing scopes:
  payables:read` porque el cliente `iaerp-web` no recibió los scopes de CxP al
  integrar la función. El realm y el configurador idempotente ahora asignan
  `payables:read` y `payables:write`; el detector de cambios de CI incluye
  `infra/keycloak/` en OIDC, configuración de despliegue y despliegue. El E2E
  inicia sesión con PKCE y abre Compras sin alertas en escritorio y móvil.
  Pasan Ruff, mypy, lint, build, validación de shell/JSON/Compose, 8 pruebas
  OIDC de backend y 4 recorridos Playwright OIDC. Falta revisión independiente,
  integración por `release -> PR -> main` y despliegue; producción conserva el
  403 hasta completar esas puertas.
- CxP operativa y conciliación bancaria compartida listas en un worktree
  aislado de `origin/main`: 2026-08-05 `America/Guayaquil`. Compras permite
  registrar `Pagado ahora` o `Pagar después`, proveedor y factura opcionales,
  abonos, historial, ajustes, reversos y reglas para gastos frecuentes. El mismo
  TXT conserva créditos para CxC y débitos para CxP; soporta cruces exactos,
  pagos parciales, reparto manual, evidencia para pagos ya registrados y
  bloqueo de duplicados. Las reglas solo preparan el gasto y el banco no crea
  IVA crédito ni ATS. REST y las cinco herramientas `payables.*` usan los
  mismos servicios. Contratos YAML, Ruff, mypy dirigido, 395 pruebas backend y
  18 recorridos Playwright pasan localmente; 33 pruebas opcionales se omiten.
  La única falla de la suite completa es `test_health.py`: el Redis local no
  está disponible. La cadena completa de migraciones y 13 pruebas dirigidas de
  CxP, banco y MCP pasan contra un PostgreSQL 16 temporal; el contenedor de
  prueba se eliminó al terminar. El commit `39631d2` está en `release` y la PR
  `#31` quedó lista para revisión con CI verde. Además, Cartera ya toma el aging
  calculado por el servidor y muestra `—` para cuentas saldadas o anuladas, aun
  si conservan una fecha de vencimiento antigua; lint, build y 24 recorridos
  Playwright pasan localmente. La corrección queda incluida en la PR `#31`; su
  nueva CI queda pendiente. No se hizo merge ni despliegue.
- Contrato de captación multicanal ampliado en local: 2026-08-04. El caso de uso
  autenticado de captura acepta `META_LEAD_AD`, `LINKEDIN_LEAD_GEN` y
  `TIKTOK_LEAD_GEN`; los tres entran a `Nuevo` con tenant, consentimiento,
  atribución, deduplicación e historial. La interfaz permite calificarlos con el
  mismo flujo comercial. Dos pruebas dirigidas pasan. Esto no declara conectores
  externos completos: Meta respondió `200`; el token LinkedIn venció el
  2026-07-14 y respondió `401`, además no tiene Lead Sync; TikTok no tiene app,
  OAuth ni env. La evidencia y los criterios de cierre están en
  `docs/SOCIAL_CRM_CHANNEL_MATRIX.md`.

- Campañas Meta y captura de leads listas en el árbol local de `main`:
  2026-08-04 `America/Guayaquil`. Empresa configura una conexión Meta Ads por
  tenant con secretos cifrados; CRM crea el borrador, guarda la imagen privada y
  prepara campaña, conjunto, creativo y anuncio siempre pausados mediante
  intención durable y outbox (`PREPARING`). Activar gasto queda reservado en
  `ACTIVATING`, exige dueño/administrador, confirmación, política habilitada,
  tope diario por tenant, permiso, idempotencia y auditoría; el worker activa
  hijos antes del padre y compensa con pausa ante error. Pausar y el corte
  general usan intención durable `PAUSING`; apagar gasto cancela reservas y
  encola la pausa de campañas activas. El consumidor usa entrega tardía y ocho
  reintentos. No se pueden rotar credenciales mientras una campaña está en
  curso. El webhook de Meta valida firma, limita cuerpo, lote y frecuencia por
  tenant, guarda cada intento firmado en una transacción propia, obtiene el formulario y
  crea el lead en `Nuevo` con origen, campaña, anuncio, UTM, consentimiento y
  deduplicación. Cada respuesta conserva un historial de contacto por campaña,
  aun cuando el lead ya exista. CRM muestra la atribución y el resumen por campaña. El prospecto
  conserva identidad fiscal provisional y no pasa a ganado hasta completarla.
  Ruff y mypy pasan; 13 pruebas dirigidas backend y una de concurrencia
  PostgreSQL lista para CI, build/lint frontend y 26
  recorridos Playwright CRM en escritorio/móvil pasan. La suite completa deja
  395 aprobadas y 34 omitidas; solo falla salud porque Redis local no está
  levantado, condición previa ya documentada. El DDL PostgreSQL aislado de
  `da1e2f3a4b5c:e5f6a7b8c9d0` se genera bien. No se llamó a Meta real, no se
  activó gasto y no se hizo push, PR ni despliegue. Faltan PostgreSQL/CI en vivo,
  configurar la conexión/webhook real y luego autorizar la publicación. El corte
  también incluye varias variantes bajo un solo adset, Meta Insights diarios por
  anuncio y moneda real, tabla de CTR/CPL/costo por calificado, atribución por
  variante y calificación humana con empresa, cargo, uso AWS, acceso al decisor,
  motivo, actor y fecha. Las pantallas nuevas pasan axe WCAG 2.1 AA y teclado.

- Feature local pendiente de integración: 2026-08-03 `America/Guayaquil`.
  Cartera suma una historia de cobranza por factura: envíos, entrega o lectura
  solo cuando WhatsApp Meta lo confirma, y gestiones manuales de llamada,
  correo, WhatsApp o nota. Un envío manual igual se bloquea para evitar
  duplicados; un reenvío exige motivo. No modifica saldos ni crea cobros. La
  migración agrega trazabilidad de proveedor y contactos. Ruff, mypy, 9
  pruebas de cobranza, build, lint y el recorrido Playwright del historial
  pasan localmente. Falta validar la migración en PostgreSQL y autorización
  para integrar; no se hizo push, PR ni despliegue.

- Facturas históricas desde RIDE PDF listas localmente en `release`:
  2026-08-03 `America/Guayaquil`. Facturas permite cargar el PDF emitido por
  Sky para conservar una venta que no llegó por XML. IAERP valida RUC, cliente,
  número, clave de acceso, autorización, fechas, detalle y totales antes de
  crear el estado `HISTORICAL_ISSUED`; guarda el PDF original y muestra
  `XML faltante`. El documento suma en la evolución mensual de ventas, pero no
  entra a Cartera, ATS ni al cálculo tributario del mes, y no permite emitir,
  retransmitir, duplicar, enviar por correo ni crear nota de crédito. El flujo
  sirve para futuras facturas de la Universidad con el mismo formato, leyendo
  cada PDF por separado. Ruff, mypy, 79 pruebas tributarias/backend, build,
  lint y 46 recorridos Playwright de Facturas y Tributario pasan. Falta push y
  promoción autorizada.

- Dashboard mensual y lectura de compras listos en `develop`: 2026-08-02
  `America/Guayaquil`. Resumen muestra la evolución neta de ventas autorizadas
  de los últimos 12 meses y compara el mes actual con compras recibidas desde
  evidencia tributaria. El IVA a pagar se etiqueta como estimación: queda
  preliminar si faltan ventas por importar a Tributario o si el crédito de IVA
  requiere validar el campo 564 con respaldo contable. El menú Compras lista
  facturas, notas y liquidaciones recibidas por mes, con proveedor, número,
  subtotal, total y desglose de IVA tomado del XML/TXT; no permite crear cifras
  manuales. Ruff, mypy y 71 pruebas tributarias pasan; la suite completa deja
  375 aprobadas y 33 omitidas. Solo falla `test_health.py` porque Redis/Docker
  local no está levantado, condición previa ya documentada. Build y lint pasan,
  con tres avisos previos; 78 recorridos Playwright de Dashboard, Compras,
  Tributario y accesibilidad pasan en escritorio y móvil. Falta promoción
  autorizada; `main` no cambió.

- Contratos simples integrados en `main`: 2026-08-02
  `America/Guayaquil`. Contratos enlaza cliente, oportunidad ganada y
  documentos accesorios; cada versión guarda vigencia, plazo y tipo de cobro.
  La persona sube el PDF terminado, lo envía por Gmail y revisa solo ese hilo.
  Un PDF recibido pasa una revisión técnica básica, pero no queda firmado ni
  activo hasta que una persona lo valide en FirmaEC. PDF enviado y firmado son
  inmutables. Mensual fijo, AWS con reporte StreamOne privado y total manual, e
  hitos preparan una tarea comercial; `Crear borrador` genera la factura con
  fecha fiscal actual y snapshot, sin emitirla. Un informe obligatorio bloquea
  el correo, no la emisión, y el envío añade informe aprobado, RIDE y XML. La
  cobranza exige política general, permiso de factura y consentimiento del
  cliente; servicios puntuales nacen apagados. Validado con Ruff, mypy, OpenAPI,
  SQL offline de migración PostgreSQL, 365 pruebas backend (33 omitidas por
  dependencias opcionales), build/lint frontend y Playwright de Contratos en
  escritorio y móvil. Docker/Redis local no estaba activo, por lo que la prueba
  aislada de salud y la migración PostgreSQL en vivo quedan para CI. El cambio
  quedó unido a la tolerancia documental y al remitente de facturas antes del
  push autorizado a producción.

- Remitente de facturas por alias: 2026-08-02 `America/Guayaquil`. Cada tenant
  puede configurar en `Empresa -> Envío de facturas` un correo y nombre de
  remitente habilitados por Gmail como `Enviar como`. La vista previa muestra
  el remitente antes de confirmar; el mensaje usa ese alias tanto en `From`
  como en `Reply-To`, mientras la cuenta personal conectada queda oculta. Si
  Google rechaza el alias, no se envía el correo y se pide revisar su alta en
  Gmail. RIDE y XML siguen adjuntos. Ruff, mypy, 64 pruebas tributarias, 25
  pruebas dirigidas de configuración/facturación/Gmail, build, lint y 44
  recorridos Playwright de Facturas y Tributario pasan sobre el conjunto unido.

- Tolerancia documental de cartera: 2026-08-02 `America/Guayaquil`. Al aplicar
  un XML autorizado de retención, IAERP permite cerrar una diferencia máxima
  de `0.01` frente al saldo de la factura. Conserva completos y separados el
  abono bancario y las retenciones de IVA/renta; no modifica los valores de la
  evidencia. La diferencia queda visible en el previo y en auditoría. Desde
  `0.02` el archivo sigue en revisión y no crea movimientos. El caso reproducido
  de `65.41 - 57.74 - 7.68` cierra en `0.00`. Ruff, mypy, 64 pruebas
  tributarias, 31 pruebas dirigidas de cartera, build, lint y 24 recorridos
  Playwright tributarios pasan sobre el conjunto unido en `main`.

- Entrega de factura y orden tributario local: 2026-08-02
  `America/Guayaquil`. La factura autorizada muestra ahora un bloque claro de
  entrega al cliente. Antes de enviar, la persona revisa destinatario, asunto,
  mensaje, vencimiento, plazo y nombres de los adjuntos; el correo usa siempre
  el RIDE PDF y XML firmado vigentes. La plantilla se configura por tenant en
  `Empresa -> Envío de facturas`, separada de la plantilla de Cobranza, y sus
  datos de pago salen del plan guardado en la factura. Tributario agrupa los
  comprobantes del periodo en ventas emitidas, compras recibidas, retenciones
  recibidas y otros; cada grupo muestra cantidad y total, se puede plegar y
  conserva el ID IAERP y la historia por documento. Ruff, mypy, build, lint,
  pruebas API de plantilla/envío y 44 recorridos Playwright pasan localmente.

- Corrección histórica local: 2026-08-02 `America/Guayaquil`. Al aplicar un
  XML de retención, Cartera usa ahora `fechaEmision` del comprobante como fecha
  efectiva, no el día en que se cargó. Si la misma autorización ya existe con
  importes y tipos iguales pero fecha técnica incorrecta, el previo propone la
  corrección y la confirmación ajusta solo la fecha con auditoría; no duplica
  IVA/renta ni cambia el saldo. Reaplicar un XML SRI 1.0 ya guardado vuelve a
  construir su detalle tributario sin crear otro comprobante. La pantalla
  muestra la fecha del XML antes de confirmar y avisa que un archivo ya cargado
  se validará otra vez. Junio de 2025 quedó cubierto como mes bancario elegido,
  separado de abonos de julio. Ruff, mypy, 64 pruebas tributarias, 22 pruebas
  históricas dirigidas, build, lint y 46 recorridos Playwright pasan localmente.
  Cambio integrado en `main` con autorización del operador.

- Corrección local: 2026-08-02 `America/Guayaquil`. La confirmación de una
  corrección bancaria ya no excede el límite de 128 caracteres de PostgreSQL:
  deriva claves internas cortas y estables, y el reverso recalcula el saldo
  después de guardar el movimiento. Los comprobantes de retención SRI 1.0
  también alimentan Tributario; IVA y renta siguen separados. Facturas añade
  un envío manual para comprobantes autorizados, con destinatario visible,
  confirmación y los dos adjuntos vigentes: RIDE PDF y XML firmado. El envío es
  idempotente y deja auditoría. Ruff, mypy, 63 pruebas tributarias, 23 pruebas
  de banco/facturación, build, lint y 24 recorridos Playwright tributarios
  pasan. Cambio integrado en `main` con autorización del operador.

- Reconciliación de ramas: 2026-08-02 `America/Guayaquil`. Se revisó la rama
  local `release` contra `main`. Sus cambios útiles ya llegaron a producción:
  perfiles de retención esperada, transmisión SRI, control de ambiente y RIDE,
  duplicado de facturas rechazadas, contratos, contactos sin WhatsApp y
  correcciones de migraciones. Una prueba de integración aislada mostró
  conflictos con versiones más nuevas de Contratos, Tributario, el visor PDF y
  la navegación; por eso no se mezcló la rama antigua. `main` conserva la
  versión vigente y la puerta completa de CI/CD terminó correctamente.

- Actualización local: 2026-08-02 `America/Guayaquil`. La carga documental
  prevalece sobre cobros manuales sin borrar su historia. Si un abono bancario
  ya está ligado a la factura correcta y existe un cobro manual igual en otra
  factura del mismo cliente, IAERP propone el reverso solo con prueba
  inequívoca: la factura manual fue emitida después del abono. La persona ve la
  corrección antes de confirmarla; el movimiento original queda en auditoría.
  Tributario separa cada comprobante en una tarjeta, muestra y permite copiar
  su `ID IAERP`, conserva aparte la clave SRI y desglosa el IVA y la renta en el
  propio comprobante de retención. La regla usa el período elegido, por lo que
  sirve para julio, junio y los meses anteriores. Ruff, mypy, 67 pruebas de
  banco/tributario, build, lint y 42 recorridos Playwright pasan en una copia
  aislada de `origin/main`. El cambio ya está integrado en `main`.

- Actualización local: 2026-08-02 `America/Guayaquil`. Cartera permite cargar
  el TXT de Banco Bolivariano y conciliar un mes elegido. Factura y abono deben
  pertenecer al mismo período; esto permite separar pagos iguales que se
  repiten cada mes. La evidencia subida tiene prioridad: si abono bancario más
  retenciones documentadas cuadran el total, se revierte el cobro manual sin
  referencia y se crea uno con respaldo bancario, sin borrar el original ni
  tocar las retenciones. La fecha efectiva conserva el día real del banco.
  Descuentos, notas de crédito, pagos con referencia, cruces ambiguos y montos
  parciales quedan para revisión. El TXT real tiene 205 movimientos, 23 abonos;
  para julio hay 6 abonos y uno de `1780.92`, fechado `2026-07-14`. Ruff, mypy,
  75 pruebas dirigidas y 42 pruebas Playwright pasan; build y lint también.

- Actualización local: 2026-08-02 `America/Guayaquil`. Los periodos
  tributarios cambian de estado al ingerir evidencia: sin comprobantes quedan
  pendientes, con algún documento preliminar muestran evidencia incompleta y
  con respaldo completo quedan listos para revisar. La pantalla exige una
  confirmación humana para marcar primero "Listo para declarar" y otra para
  registrar que ya fue declarado; la API impide saltar pasos, usa idempotencia
  y deja auditoría. Un periodo declarado no se reabre de forma automática.
  Validado con Ruff, mypy, 41 pruebas tributarias, build, lint y 16 pruebas
  Playwright de Tributario.

- Revisión documental: la guía del formulario IVA publicada por el SRI y
  actualizada el 15 de junio de 2026 confirma que el casillero 507 corresponde
  a adquisiciones y pagos brutos gravados con tarifa 0%, mientras el 517 es el
  valor neto. También se corrigió el 411 como ventas gravadas netas y se
  separaron los valores brutos y netos de 401, 500 y 510. El 500, 510 y 564
  quedan para revisión humana: el SRI exige probar el derecho a crédito y
  determinar el crédito aplicable por proporcionalidad o contabilidad; los XML
  por sí solos no prueban esos datos.

- Actualización local: 2026-08-02 `America/Guayaquil`. Tributario conecta ATS
  al periodo: toma comprobantes fiscales y sus impuestos/retenciones, genera
  XML y ZIP privados idempotentes, permite descarga temporal y registra los
  errores del SRI. La pantalla tiene "Generar ATS", descarga y lista los
  errores registrados. La ingesta conserva `formaPago` desde cada XML
  autorizado; una transferencia `20` llega al ATS y se muestra como tal. No
  genera un anexo si el documento es preliminar o falta ese respaldo, y nunca
  completa el dato con un código ficticio. Ruff, mypy, 39 pruebas
  tributarias, build, lint y Playwright tributario pasan localmente. El
  dispatcher además crea pendientes idempotentes para bajar evidencia,
  completarla, revisar IVA y preparar ATS; todos exigen aprobación humana y no
  hacen envíos, entregas ni pagos. Pendiente commit y push.

- Actualización local: 2026-07-31 `America/Guayaquil`.
  Cartera muestra el número de factura de cada cuenta y permite abrir su
  historial de movimientos. Ahí se ven cobros, retenciones, descuentos, notas
  de crédito y reversos, con fecha, valor y referencia; una retención muestra
  la autorización SRI asociada. Facturas expone el total de retenciones
  activas en el listado y el detalle. “Sin retención” significa que todavía no
  existe una retención registrada, no que el cliente esté excluido de retener.
  Los reversos dejan de contar en el total. Validado con Ruff, mypy, pruebas
  API de facturas/cartera y lint/build frontend; pendiente commit, CI y
  promoción autorizada.

- Actualización local: 2026-07-31 `America/Guayaquil`.
  Cartera permite cargar hasta 50 XML de comprobantes de retención en una sola
  operación. Primero muestra el cruce verificable de cada archivo con su
  factura (establecimiento, punto de emisión y secuencial), autorización y
  valor; después una persona confirma el registro de las coincidencias. Los
  archivos no se guardan. Cada retención confirmada crea sus movimientos contra
  la cuenta por cobrar y reduce el saldo de la factura; los XML que no cuadran
  quedan marcados para revisión sin modificar cartera. La confirmación exige
  idempotencia, conserva auditoría y no puede duplicar una autorización.
  Validado con Ruff, mypy, pruebas API de XML/batch y lint/build frontend;
  pendiente commit, CI y promoción autorizada.

- Actualización local: 2026-07-31 `America/Guayaquil`.
  Todo PDF disponible en IAERP se visualiza dentro de la aplicación: tanto el
  RIDE de Facturas como el PDF firmado de Contratos usan un visor común,
  accesible y con cierre por teclado. La URL privada vence en cinco minutos y
  el visor pide al almacenamiento una respuesta `inline`; la descarga normal
  sigue usando `attachment`. No modifica XML, RIDE ni el estado de un
  comprobante fiscal existente. Facturas además traduce el estado persistido
  de cartera (`PAID`/`PARTIALLY_PAID`) a su etiqueta pública antes de responder;
  evita que una factura cobrada deje el listado en error 500. Validado con
  Ruff, mypy, pruebas API de artefactos/facturas, lint, build y Playwright de
  Facturas.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  Cartera queda limitada a cuentas por cobrar, aging, cobros y recordatorios.
  La política de mensajes automáticos se configura únicamente en Empresa →
  Automatizaciones de cobranza. Validado con lint, build y Playwright de
  Cartera en escritorio y móvil.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  Contratos ya tiene interfaz: menú propio, filtro por cliente, alta de
  contrato, versiones comerciales y carga privada de PDF firmado con checksum
  SHA-256 y descarga temporal autorizada. Las versiones firmadas quedan
  inmutables; una nueva condición se registra como otra versión. No crea ni
  emite comprobantes SRI. Validado con Ruff, mypy, pruebas API focalizadas,
  lint, build y Playwright desktop/móvil; pendiente CI y promoción autorizada.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  Cartera permite corregir el vencimiento de una factura histórica de una sola
  cuota, con motivo obligatorio. Sin cambiar XML, autorización ni RIDE SRI,
  actualiza tanto la cuota de cartera como el plan comercial que muestra la
  factura; aging y cobranza usan de inmediato la fecha corregida. El antes y
  después queda en auditoría. Pruebas de cartera/facturación, Ruff, mypy,
  lint y build pasan; pendiente promoción autorizada.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  Contactos exige y guarda móviles de WhatsApp en formato ecuatoriano E.164:
  `+593991041297`. También normaliza una entrada local de diez dígitos antes
  de guardarla. Meta y Evolution reciben el número internacional sin el signo
  `+`, como requieren sus APIs; un formato inválido se rechaza antes de enviar.
  Pruebas de contactos/CRM y build pasan; pendiente promoción autorizada.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  Resumen cuenta únicamente facturas `AUTHORIZED` del mes; rechazos y no
  autorizadas no afectan ese indicador. Por cobrar y vencido continúan
  partiendo de cartera creada al autorizarse una factura. Pipeline abierto se
  identifica explícitamente como oportunidades CRM, separado de facturación.
  Facturas muestra `Archivar` directamente en cada comprobante `REJECTED` o
  `NOT_AUTHORIZED`; exige motivo, conserva evidencia y lo retira de la lista.
  Pruebas de facturación, Ruff, mypy, lint y build pasan; pendiente promoción
  autorizada.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  Cartera muestra ahora la configuración visible de cobranza automática. Cada
  tenant puede definir asunto, texto y datos para pago del correo; admite
  `{{cliente}}`, `{{empresa}}`, `{{saldo}}`, `{{vencimiento}}`,
  `{{dias_atraso}}` y `{{cuenta_bancaria}}`. Al vencimiento programado el
  correo agrega una tabla HTML con el saldo abierto de la cuota, vencimiento,
  días de atraso y los datos de pago. El envío sigue exigiendo política activa,
  contacto con consentimiento y Google Workspace conectado. Pruebas de
  plantilla, scheduler, cartera y frontend pasan; pendiente migración y
  promoción autorizada.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  Registrar cobro puede leer un XML de comprobante de retención autorizado por
  SRI y proponer sus valores exactos de IVA/renta, base, porcentaje, código y
  autorización. Antes de cargar los valores valida el estado `AUTORIZADO`, la
  clave, el RUC del cliente, el RUC de la empresa y la factura sustentada. El
  XML se procesa solo en memoria: no se guarda, no crea movimientos y exige la
  confirmación humana con Guardar. Pruebas sintéticas cubren lectura y rechazo
  de XML no autorizado o de otro cliente; pendiente promoción autorizada.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  Empresa identifica a BTOB SAS (RUC 1793113192001) como creador y proveedor
  central de IAERP. Es un dato de plataforma, separado del RUC de cada emisor
  y no editable por tenants. En comprobantes nuevos, antes de su firma, el XML
  agrega el RUC en `infoAdicional/campoAdicional`; aplica a facturas y notas de
  crédito. Desde el corte de 2026-08-20, el RIDE de comprobantes nuevos
  también muestra el nombre y RUC del proveedor, sin cambiar documentos ya
  firmados. Pruebas de configuración fiscal/XML, lint, build, Ruff y mypy
  pasan. Sigue pendiente el alta o actualización de las actividades J62021002
  o J62021003 en el RUC de BTOB.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  Al abrir “Registrar cobro”, una cuenta sin movimientos precarga las
  retenciones de IVA/renta configuradas en el cliente y calcula el monto neto.
  La persona puede corregir los valores, pero debe adjuntar la referencia del
  comprobante de retención antes de guardar; cobros parciales o con saldo ya
  modificado no se rellenan automáticamente. Pruebas de retenciones/cobros,
  lint, build, Ruff y mypy pasan. Pendiente promoción autorizada.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  Facturas incorpora un archivado operativo para comprobantes `REJECTED` y
  `NOT_AUTHORIZED`: exige motivo, permiso de escritura, idempotencia y
  auditoría; los retira de Facturas sin eliminar XML, RIDE ni la respuesta del
  SRI. Un comprobante `AUTHORIZED` no se puede archivar. También se conserva
  una sola versión vigente por tipo de artefacto en la interfaz y el RIDE se
  puede visualizar sin descargar. Pruebas API focalizadas, Ruff, mypy, lint y
  build pasan. Pendiente promover y archivar las pruebas en producción.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  La firma de comprobantes se sustituyó por XAdES-BES con `xades`/`xmlsig`,
  el mismo perfil funcional de Sky Franquicia: conserva `SignedProperties`,
  `SigningCertificate` y los certificados intermedios del PKCS#12. Las
  pruebas de firma, carga de certificado y facturación pasan (27 pruebas
  focalizadas); Ruff y mypy pasan. La suite completa local queda bloqueada por
  el chequeo de salud local (`/health/ready` devuelve 503 por dependencias no
  levantadas), ajeno a la firma; la puerta CI completa (backend, migraciones,
  frontend, OIDC y seguridad) y Coolify finalizaron correctamente. Las
  facturas rechazadas se mantienen inmutables y se duplican para reemisión.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  CI clasifica el impacto de cada cambio antes de ejecutar jobs: documentación,
  pruebas y flujo no despliegan la aplicación; UI, backend y OIDC ejecutan solo
  sus puertas aplicables; firma SRI, facturación, migraciones e infraestructura
  fuerzan el recorrido completo. Producción solo se activa tras las puertas
  requeridas y no se cancela un despliegue activo para publicar este control.
  Validación de sintaxis YAML local; pendiente CI.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  Los estados técnicos de comprobante y transmisión ahora se traducen a nombres
  legibles en Facturas y en el RIDE: por ejemplo, `SIGNED` pasa a “Firmada y
  pendiente de envío” y `NOT_AUTHORIZED` a “No autorizada”. Un estado futuro
  desconocido mantiene una etiqueta segura de pendiente de clasificación, sin
  dejar la interfaz vacía. Validado con pruebas del RIDE, lint y build
  frontend; pendiente CI y promoción autorizada.

- Actualización local: 2026-07-30 `America/Guayaquil`.
  La firma XAdES conserva e incorpora en el XML los certificados intermedios
  incluidos en el PKCS#12, en vez de descartarlos al cargarlo. Esto permite al
  SRI construir la cadena de confianza del certificado firmante. Se validó con
  un PKCS#12 sintético de emisor + firmante, pruebas de firma, emisión y
  configuración fiscal; pendiente CI y promoción autorizada. Un comprobante
  rechazado por firma se conserva inmutable y se duplica/emite como nuevo tras
  confirmar que el certificado cargado proviene de una entidad certificadora
  acreditada y contiene su cadena.

- Actualización local: 2026-07-29 `America/Guayaquil`.
  El detalle y el cuadro de totales del RIDE comparten ahora el mismo ancho y
  borde derecho; se verificó mediante renderizado visual del PDF y pruebas
  del servicio. Pendiente CI y promoción autorizada.

- Actualización local: 2026-07-29 `America/Guayaquil`.
  La generación XML ya no usa el UUID interno como `codigoPrincipal`: conserva
  el código comercial facturado y, para históricos o códigos mayores a 25
  caracteres, emite un identificador corto compatible con SRI. Empresa permite
  cargar de forma privada el logo PNG/JPEG para los nuevos RIDE; se conserva
  el respaldo textual cuando no exista logo. Validado con Ruff, mypy, pruebas
  de XML/Empresa/RIDE, pruebas de emisión y lint/build frontend; pendiente CI
  y promoción autorizada. Un comprobante ya rechazado no se modifica: debe
  duplicarse/reemitirse como documento nuevo tras la promoción.

- Actualización local: 2026-07-29 `America/Guayaquil`.
  El RIDE se rediseñó a partir de la referencia fiscal entregada: cabecera
  compacta, bloque de RUC/documento, clave de acceso, ambiente, comprador,
  detalle y totales alineados. Al autorizarse un comprobante se conserva el
  RIDE inicial y se genera la versión 2 con número y fecha/hora de
  autorización SRI. Validado con Ruff, mypy, pruebas del RIDE y revisión
  visual renderizada; pendiente de la puerta CI antes de promoción.

- Actualización local: 2026-07-29 `America/Guayaquil`.
  El RIDE de nuevos comprobantes adopta formato A4 con cabecera fiscal, bloque
  de clave de acceso, comprador, detalle y totales consistentes. La emisión
  SOAP ahora bloquea antes de firmar si el ambiente fiscal del tenant no
  coincide con `SRI_ENVIRONMENT`, evitando XML que el SRI devolvería por
  discrepancia de ambiente. Validado localmente con Ruff y seis pruebas
  focalizadas; pendiente CI y promoción autorizada. Los documentos históricos
  no se alteran y un rechazo SRI se reemite únicamente como comprobante nuevo.
  Facturas incorpora **Duplicar**: copia una factura del tenant como borrador
  nuevo, recalcula con la política vigente y nunca arrastra XML/RIDE, clave de
  acceso, autorización, transmisión ni cobros. Conserva las cuotas relativas
  solo si el total permanece igual; de otro modo deja el nuevo total para
  revisión antes de emitir.

- Actualización local: 2026-07-29 `America/Guayaquil`.
  El RIDE de nuevos comprobantes adopta formato A4 con cabecera fiscal, bloque
  de clave de acceso, comprador, detalle y totales consistentes. La emisión
  SOAP ahora bloquea antes de firmar si el ambiente fiscal del tenant no
  coincide con `SRI_ENVIRONMENT`, evitando XML que el SRI devolvería por
  discrepancia de ambiente. Validado localmente con Ruff y seis pruebas
  focalizadas; pendiente CI y promoción autorizada. Los documentos históricos
  no se alteran y un rechazo SRI se reemite únicamente como comprobante nuevo.
  Facturas incorpora **Duplicar**: copia una factura del tenant como borrador
  nuevo, recalcula con la política vigente y nunca arrastra XML/RIDE, clave de
  acceso, autorización, transmisión ni cobros. Conserva las cuotas relativas
  solo si el total permanece igual; de otro modo deja el nuevo total para
  revisión antes de emitir.

- Actualización local: 2026-07-29 `America/Guayaquil`.
  Contactos puede guardar un perfil esperado de retención de IVA/renta, con
  vigencia, para facilitar cobros recurrentes como UASB. Cartera puede
  precargar ese perfil en una cuenta sin movimientos, pero exige la referencia
  del comprobante antes de registrar una retención que reduzca saldo. No hay
  importación automática de banco/SRI ni se crean retenciones por la mera
  coincidencia de un extracto; esa conciliación permanece como candidato
  revisable. Validado localmente con Ruff, mypy, pruebas focalizadas, contrato,
  lint y build; falta validación de migración contra PostgreSQL/CI y promoción.

- Actualización local: 2026-07-29 `America/Guayaquil`.
  Catálogos incorpora el alta tenant-scoped e idempotente de categorías
  tributarias (código SRI, tarifa y vigencia) y agrupa Productos y categorías
  en una sola entrada de navegación. Cartera inicia mostrando únicamente
  cuentas pendientes (abiertas, parciales y vencidas); saldadas y anuladas se
  consultan mediante el filtro. Validado localmente con Ruff, mypy, pruebas
  API focalizadas, lint y build; pendiente CI y promoción autorizada.

- Expediente legal-comercial / AWS: diseño preparado en
  `docs/sprints/sprint-07-legal-commercial.md`, ADR 0011 en estado
  `Proposed`, skill y perfil experto. Primer corte local: migración,
  contratos/versiones, cortes AWS y propuestas comerciales tenant-scoped con
  API idempotente, auditoría y pruebas focalizadas. Pendiente: custodia/carga
  de PDF, conciliación real Cost Explorer/CSV, activación de versiones,
  snapshot en la factura, MCP de lectura y UI Cliente 360.

- Actualización local: 2026-07-28 `America/Guayaquil`.
- Migración Sky Franquicia / BTOB: se agregó localmente el primer gate
  `backend/scripts/dry_run_sky_franquicia_migration.py`; usa una URL de origen
  solo lectura por variable de entorno, no imprime datos personales y no
  escribe en origen ni destino. El inventario productivo de BTOB detectó 15
  facturas (12 `AUTHORIZED`, 3 `CANCELLED`), sin cobros; todas concilian por
  líneas y subtotal. El dry-run bloquea una factura autorizada cuyo XML falta
  en Sky y no fue devuelto por SRI en la consulta puntual. Pendiente construir
  y aprobar la fase de carga idempotente y la conciliación final.
- Carga de autorizadas Sky Franquicia / BTOB: se agregó localmente un cargador
  transaccional e idempotente para las facturas `AUTHORIZED` con XML y número
  de autorización. Conserva clave de acceso, XML, autorización, líneas,
  secuencia y una cuenta por cobrar sin pagos (vencimiento = fecha histórica);
  no llama al SRI ni agenda recordatorios. La autorizada sin XML se excluye
  explícitamente. Pendiente promover a producción y ejecutar el corte con
  conciliación de conteos/totales.
- Provisionamiento de primer tenant: el comando `backend/scripts/provision_tenant_owner.py`
  fue promovido a `main` el 2026-07-28. Reconcilia una organización y un
  usuario ya creados en Keycloak con `Tenant`, `User`, `Membership` Owner/Admin,
  automatizaciones desactivadas y auditoría. La imagen backend incluye
  `scripts/` para ejecutarlo desde el servicio desplegado; no usa SQL libre.
  Pendiente: finalizar el despliegue y ejecutar el alta productiva autorizada.
  aprobados; la suite backend completa conserva una falla preexistente de
  SQLite en `tests/test_billing_api.py` (`emission_points` ausente).

- Actualización: 2026-07-27 `America/Guayaquil`.
- Producción: `main` en commit `1ec404c` desplegado por Coolify tras CI
  `30293169564` (backend, frontend, OIDC, migraciones, contratos, seguridad y
  despliegue aprobados). La aplicación y OIDC responden HTTP 200 públicamente.
- Evolution: se incorpora como servicio interno de Coolify con PostgreSQL,
  Redis y volúmenes persistentes; falta promover esta configuración y enlazar
  el primer número mediante QR.

- Fecha: 2026-07-23 `America/Guayaquil`.
- Rama de trabajo: `release` (CI `30043763940` verde). `main` = producción
  (Coolify/SRI).
- Commit de producción verificado: `2f7f323`.
- Estado: **plan UI/UX (Sprints 1-9) completo** + cliente SRI real + integración
  Gmail listos. En preparación de **go-live** (faltan pasos de config del
  operador; ver "Go-live" abajo).
- WhatsApp multi-proveedor preparado en `release`: Meta y Evolution coexisten
  por tenant, con selector independiente para CRM y cobranza; Meta es el
  valor por defecto. La migración `e8f9a0b1c2d3` y el ciclo PostgreSQL
  upgrade/downgrade/check fueron verificados. Pendiente de operador: definir
  `EVOLUTION_API_BASE_URL` y `PUBLIC_API_URL` en Coolify, registrar la
  instancia y probar un número dedicado.
- Rediseño visual IAERP preparado en `release`: sistema slate + azul sobrio,
  cabecera superior con navegación visible, KPIs de cobranza/emisión/pipeline
  y Kanban sin gradientes ni animación. Se preservaron los contratos
  funcionales del catálogo, facturación y cartera. Validado localmente con
  lint, build y Playwright completo contra API, PostgreSQL y Redis (174
  aprobadas, 2 omitidas; incluye WCAG AA y reflow móvil). Pendiente la nueva
  validación remota de CI antes de promover a `main`.
- El estado ejecutable descrito aqui debe estar publicado en `release`. Si
  `git status` muestra cambios, una IA debe revisarlos antes de continuar.

## Estado por fase

| Fase | Estado | Evidencia o siguiente puerta |
| --- | --- | --- |
| Sprint 0 | Aprobado | Documentos, ADR, contratos y backlog inicial |
| Sprint 1 (backend) | Done | Plataforma, maestros, MCP; CI verde |
| Sprint 2 (backend) | Done | Ciclo SRI simulado completo verificado en vivo |
| Sprint 3 (backend) | Done | Cartera E5 + E7 MCP; CI verde |
| CRM MVP | Done | Leads, Activities, Pipeline |
| UI/UX Sprints 1-9 | **Done + rediseño visual en validación CI** | Sistema slate/azul sobrio, cabecera superior, Kanban, Invoice Spreadsheet, pagos por cliente, code-splitting, polish y pruebas. |
| **SRI cliente real** | **Done (código)** | `SoapSRIClient` (recepción+autorización) — falta certificar contra celcer con cert real (operador) |
| **Integración Gmail** | **Done (código)** | Botón conectar + tokens por tenant — falta OAuth client de Google (operador) |
| Migración de facturas | No iniciado | Plan en `docs/07-data-migration.md`; requiere data de origen + dry-run |

## Go-live (estado real 2026-07-23)

Lo que **está en código y verde**, y lo que **depende del operador** (config,
credenciales, red del SRI) y por tanto NO se puede completar desde el repo/CI:

| Ítem | Código | Pendiente del operador |
| --- | --- | --- |
| **Facturación electrónica** | Firma XAdES-BES + `SoapSRIClient` (celcer/cel) | Instalar `.p12` + la contraseña del certificado como secreto de entorno; configurar transmisión SOAP en ambiente de pruebas; certificar contra celcer. Ver `docs/SRI_GOLIVE.md` |
| **Subida del .p12 por UI** | Endpoint `/organization/signing-certificate`; corregida la separación TLS entre MinIO interno (HTTP) y URL pública (HTTPS), con pruebas de configuración | Pendiente confirmar el despliegue de `main` y repetir la carga con certificado de pruebas |
| **Gmail (cobranza + CRM)** | Botón conectar, tokens cifrados por tenant, envío/sync | Crear OAuth client de Google (1 vez) + `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI`. Ver `docs/GMAIL_SETUP.md` |
| **Login OIDC** | Solicita un alias sin prellenar una empresa demo, persiste solo la empresa confirmada, evita recuperar SSO sin contexto tenant y libera la UI si la inicialización OIDC queda pendiente | Verificado en producción: alias inválido vuelve al formulario con error recuperable, recarga limpia y servicios web/Keycloak HTTP 200; CI `30034987915` verde |
| **Migración de facturas** | Plan documentado, sin migrador construido | Entregar data de origen; construir migrador + dry-run con conciliación en staging antes de tocar producción |

Guías de operación: `docs/SRI_GOLIVE.md`, `docs/GMAIL_SETUP.md`,
`docs/ADMIN_GUIDE.md`, `docs/USER_GUIDE.md`, `docs/DEV_SETUP.md`.

## Implementado en Sprint 1

- Stack local con PostgreSQL 17, Redis 7.4, MinIO, Keycloak 26.6.4, API,
  worker, scheduler y web.
- FastAPI, SQLAlchemy 2 y Alembic con modelos de tenant, usuario, membresia,
  service account, auditoria, idempotencia, outbox, inbox y dead letter.
- Maestros REST tenant-scoped: establecimientos, puntos de emision, categorias
  tributarias, tags, clientes/proveedores y productos.
- Scopes, validacion de membresia activa, politicas de automatizacion y kill
  switch.
- MCP Streamable HTTP con `context.get`, `parties.search`, `parties.create`,
  `products.search` y `products.create`.
- Frontend React/Vite con login de desarrollo y flujo OIDC con Keycloak.
- Seed local repetible, realm de Keycloak importable y Dockerfiles de API/web.
- Pruebas de aislamiento, scopes, idempotencia, auditoria, outbox/inbox/dead
  letter, MCP y accesibilidad.
- PoC automatizado de service accounts contra el stack real
  (`backend/tests/test_service_account_poc.py`): client credentials con claims
  y lifespan <= 300 s, alta/revocacion via API con provisioning en Keycloak,
  rechazo inmediato de un token todavia vigente tras revocar, bloqueo de nueva
  emision con el cliente deshabilitado y rechazo de tokens expirados. Se ejecuta
  con `IAERP_POC=1 uv run pytest tests/test_service_account_poc.py` y el stack
  levantado con `AUTH_MODE=oidc`; sin esa variable la suite se omite.
- Cambio de tenant OIDC multi-tenant probado de extremo a extremo. A nivel API
  (`backend/tests/test_tenant_switch_poc.py`, misma puerta `IAERP_POC=1`):
  `owner` obtiene contexto Norte (roles owner/admin) o Sur (viewer) segun la
  `organization:<alias>` autorizada, un token con `organization:*` (dos
  organizaciones) se rechaza con 403 y un usuario sin membresia en la
  organizacion recibe token sin claim `organization` que la API rechaza con
  403. A nivel UI (`frontend/tests/oidc.spec.ts`, puerta `E2E_OIDC=1` con
  `E2E_USE_RUNNING_APP=1 PLAYWRIGHT_BASE_URL=http://localhost:8088`): login
  PKCE en Norte, datos de Norte visibles, logout, login en Sur y verificacion
  de que los datos de Norte no aparecen; aprobado en escritorio y movil.
- MCP validado con el Inspector oficial en modo CLI contra el stack real:
  Protected Resource Metadata, 401 con `resource_metadata`, catalogo de tools
  filtrado por scopes por tenant y aislamiento de datos. Evidencia sanitizada
  en `docs/evidence/sprint-01-mcp-inspector.md`.
- Dataset `sprint-01-v1` verificado: el seed (`app/initial_data.py`) crea dos
  tenants, usuario multi-tenant, usuarios exclusivos, usuario sin membresia,
  cinco roles, una service account por tenant y maestros distinguibles; se
  ejecuto dos veces seguidas contra PostgreSQL sin errores (idempotente).
- E2E funcionales (`frontend/tests/functional.spec.ts`) aprobados con la API
  en modo dev: alta/edicion de contacto y producto contra la API real,
  aislamiento al cambiar de tenant y error de autorizacion accesible para un
  token restringido. Junto con `a11y.spec.ts` y `oidc.spec.ts` cubren los
  cuatro recorridos E2E del plan en escritorio y movil (12 pruebas).
- Suite de migraciones Alembic validada contra PostgreSQL 17
  (`backend/scripts/validate_migrations.py`): creacion desde cero, downgrade a
  base sin tablas remanentes, upgrade nuevamente y `alembic check` sin drift.
  Se ejecuta local con `DATABASE_URL=...iaerp_migrations` y en el job
  `migrations` del CI.
- CI configurado en `.github/workflows/ci.yml` sin deploy: jobs de backend
  (Ruff, mypy, pytest con PostgreSQL/Redis y reporte JUnit), migraciones,
  contratos (OpenAPI y referencias MCP), frontend (lint, build, Playwright con
  API real), stack OIDC completo (keycloak_poc, validate_oidc_runtime, suites
  PoC de service account y cambio de tenant, PKCE E2E) y seguridad
  (detect-secrets, pip-audit, bandit, npm audit). Todos los pasos reproducibles
  en local fueron ejecutados y aprobados el 2026-07-03; el backend tambien pasa
  contra PostgreSQL (16 pruebas con la de concurrencia incluida).
- Worker Celery saneado: el contenedor corre como usuario `iaerp` (sin
  advertencia de superusuario), worker/scheduler/web tienen healthcheck y
  reportan `healthy`, y se corrigio en `app/workers/tasks.py` un bug de
  event loop (asyncio.run por task ataba el pool asyncpg a un loop cerrado y
  producia fallos intermitentes "attached to a different loop"); tras el fix,
  cero errores en logs con trafico real de outbox.
- ADR 0009 aceptado el 2026-07-03: los siete puntos del PoC bloqueante quedaron
  demostrados y automatizados, incluida la revocacion de membresia con token
  vigente y el rechazo cruzado de audiences API/MCP
  (`backend/tests/test_tenant_switch_poc.py`, 5 pruebas en vivo). Perfil
  adoptado: `fixed-audience-with-resource-server-validation`.
- Revision independiente de arquitectura sobre los cambios OAuth/worker:
  aprobada con observaciones; se aplicaron el hook `worker_process_shutdown`
  (cierre del loop y dispose del engine) y la aclaracion de unicidad de
  `client_id` en `auth.py`. Observacion abierta: si el job `oidc` de CI muestra
  flakiness por el `sleep(3)` del test de expiracion, subir el margen o usar
  retry acotado.

## Validacion del corte

Comandos ejecutados el 2026-07-03:

```bash
cd backend
uv run ruff check .
uv run mypy app
uv run pytest -q

cd ../frontend
npm run lint
npm run build
npm run test:e2e
```

Resultados:

- Backend y migraciones: Ruff aprobado.
- Backend: mypy estricto aprobado sobre 31 archivos.
- Backend: 15 pruebas aprobadas en SQLite y 16 contra PostgreSQL (incluye la
  de concurrencia). Las 8 del PoC en vivo pasan con `IAERP_POC=1` y el stack
  OIDC arriba (3 de service account + 5 de cambio de tenant/audiences).
- Se corrigio en `app/core/auth.py` la comparacion de `expires_at` de service
  accounts: SQLite devuelve datetimes sin zona y rompia la validacion de
  expiracion en pruebas.
- Frontend: lint y build aprobados.
- Frontend: 14 pruebas Playwright aprobadas en escritorio y movil (a11y con
  reflow a 320 CSS px y 200% zoom, y funcionales con API dev), mas el recorrido
  OIDC PKCE con el stack completo en ambos viewports (`npm run test:e2e:oidc`).
- `http://localhost:8000/health/ready`: HTTP 200.
- `http://localhost:8088`: HTTP 200.
- Discovery OIDC de Keycloak: HTTP 200.
- Los ocho servicios de Compose estan ejecutandose; los servicios con
  healthcheck reportan `healthy`.

El PoC de Keycloak confirma organization unica, audience fija y discovery. No
confirma soporte RFC 8707 estricto: Keycloak acepta un `resource` ajeno. IAERP
debe mantener validacion estricta de audience/resource en API y MCP.

## Pendiente para cerrar Sprint 1

- Los ocho pendientes tecnicos del corte anterior quedaron cerrados el
  2026-07-03 (ver "Implementado en Sprint 1" y la matriz del ADR 0009).
- QA Reliability ejecuto la revision independiente el 2026-07-03: NO-GO
  condicional con dos brechas, ambas atendidas en la misma sesion: (a) se
  agrego la prueba de reflow a 320 CSS px y 200% zoom en `a11y.spec.ts`
  (aprobada en escritorio y movil) y (b) `test:e2e:oidc` ahora corre en ambos
  viewports. La condicion final quedo cumplida el 2026-07-04 con el push
  autorizado a `release` y el primer run verde del CI (run 28705977016, seis
  jobs incluidos OIDC full stack y seguridad, artefactos publicados):
  https://github.com/ceduardodch/iaerp/actions/runs/28705977016
  Sprint 1 queda marcado como Done.
- Observaciones menores del QA sin bloquear: los specs de a11y usan API
  mockeada; `pytest-randomly` valido la independencia de orden pero no esta en
  la configuracion permanente del proyecto.

## Avance de Sprint 2 (corte 2026-07-04)

Plan y criterios en `docs/sprints/sprint-02.md`. Trabajo sin commitear en
`release` mientras avanza el sprint.

- ADR 0008 aceptado (2026-07-04) por Ecuador SRI Expert con la Ficha Tecnica
  SRI v2.26 verificada de primera mano: IVA por grupo de tarifa sobre base
  agregada, ROUND_HALF_UP, 7 vectores oficiales en el ADR.
- Fase base implementada y verificada: `fiscal_policy.py` (`ec-iva-v1`),
  modelos y migracion de facturacion (`billing.py`, `57e96c2e2562`),
  secuencial atomico con FOR UPDATE (probado con 5 emisiones concurrentes en
  PostgreSQL sin huecos ni duplicados), borrador de factura con totales
  recalculados por backend, endpoints `POST/GET /invoices` con idempotencia y
  auditoria. Suite: 44 pruebas en SQLite, 46 en PostgreSQL, migraciones
  validadas desde cero.
- Fase 3 verificada: clave de acceso modulo 11 (`access_key.py`), XML SRI
  v1.1.0 (`sri_xml.py`, IVA por grupo segun ADR 0008), firma XAdES con
  certificado de prueba fuera de Git y fingerprint auditado (`signing.py`),
  RIDE PDF (`ride.py`) y MinIO privado con checksum y URL prefirmada
  (`storage.py`); bucket `iaerp-documents` se crea idempotente.
- Fase 4 verificada: emision completa (`POST /invoices/{id}/issue`, 202 con
  Operation), simulador SRI `/sri-sim` (6 escenarios, prohibido fuera de
  dev/test), worker `sri_transmission` con dispatch por event_type,
  reconciliacion E4-05 (clave conocida jamas se retransmite) y reintentos
  con backoff hasta dead letter. Backend: 119 pruebas SQLite / 121 PostgreSQL.
- UI de facturacion implementada (seccion "04 Facturas": lista, borrador con
  lineas dinamicas, detalle con estado SRI y polling, emitir, artefactos,
  nota de credito), 14 pruebas a11y nuevas en verde; su prueba funcional
  espera `GET /invoices` (fase 5).
- Nota operativa: la migracion `57e96c2e2562` se edito in-place durante el
  sprint; la BD dev del contenedor se recreo desde cero (drop/create +
  upgrade + seed) el 2026-07-04.
- Fase 5 verificada: nota de credito con tarifa historica del documento de
  sustento (politica `ec-iva-v0` al 12%, vectores 6 y 7 del ADR), control de
  saldo acreditable que reserva documentos en curso, `POST /credit-notes` y
  `GET /invoices` agregados (contrato aditivo validado).
- Fase 6 verificada: tools MCP `invoices.get/create_draft/issue` y
  `credit_notes.create_and_issue` con kill switch en escrituras, idempotencia
  y equivalencia REST/MCP probada. Scopes nuevos en el realm: `iaerp-web` los
  recibe por defecto, `iaerp-mcp-cli` como opcionales y los agentes seeded NO
  reciben scopes de facturacion. Nota: el realm JSON cambio; un stack ya
  inicializado no reimporta el realm (recrear el volumen de Keycloak para
  reflejar los scopes nuevos en OIDC vivo).
- UI cerrada: prueba funcional de facturas en vivo aprobada tras exponer
  `GET /invoices` (16/16 con a11y de facturas).
- Backend al corte: 144 pruebas SQLite / 146 PostgreSQL, ruff y mypy limpios.
- Dataset `sprint-02-v1` en el seed: dos tenants con factura AUTHORIZED,
  PENDING_AUTHORIZATION y REJECTED, mas nota de credito AUTHORIZED; idempotente
  (seed x2 sin duplicar). Backend al cierre: 149 pruebas SQLite / 151
  PostgreSQL; frontend 30 Playwright.
- Bugs de integracion encontrados y corregidos durante el ciclo en vivo
  (no cubiertos por las pruebas unitarias de los agentes):
  1. MinIO no cableado en compose: `api`/`worker` usaban `localhost:9000`
     (invalido en la red de contenedores). Se agrego `MINIO_ENDPOINT=minio:9000`
     y un `MINIO_PUBLIC_ENDPOINT=localhost:9000` separado para firmar URL
     prefirmadas alcanzables desde el navegador, con `MINIO_REGION` fija para
     evitar el round-trip de resolucion de region.
  2. Certificado de firma: la autogeneracion importaba `scripts.*` (no
     empaquetado en la imagen). Se movio a `app/services/dev_certificate.py`;
     la ruta apunta al home escribible del usuario del contenedor.
  3. Worker SRI: la re-consulta de autorizacion nunca se reprogramaba cuando el
     documento quedaba `PENDING_AUTHORIZATION`, y el reintento reabria el mismo
     `OutboxEvent` que el `InboxEvent` ya deduplicaba (el documento se quedaba
     colgado). Se reescribio para encolar un `OutboxEvent` FRESCO por
     re-consulta (id nuevo -> nuevo InboxEvent), con backoff y dead letter al
     tope. Fue el fallo que bloqueaba la autorizacion end-to-end.
- QA go/no-go: GO. Ciclo en vivo verificado el 2026-07-04 con worker real y
  simulador: borrador -> emision (202) -> firma XAdES -> XML+RIDE en MinIO ->
  transmision -> autorizacion. Evidencia: factura AUTHORIZED con clave de
  acceso de 49 digitos y numero de autorizacion; segunda emision con la misma
  Idempotency-Key sin duplicar transmision (1 sola fila); descarga del XML
  firmado via URL prefirmada con checksum SHA-256 identico al registrado y
  totales que cuadran con `fiscal_policy` (39.25/4.39/43.64); nota de credito
  parcial AUTHORIZED (total 11.21) y nota de credito excedida rechazada con
  422; bucket privado (GET anonimo 403); cero errores no controlados en el
  worker.
- Pendiente para produccion (fuera de Sprint 2, ya en "No incluido"): CI aun no
  ejecuta el ciclo SRI en vivo (worker+simulador) como job dedicado; el realm
  de Keycloak gano scopes de facturacion pero un stack ya inicializado no
  reimporta el realm (recrear volumen para OIDC vivo). Falta commit autorizado.

## Avance Sprint 3 (corte 2026-07-06)

Plan y criterios en `docs/sprints/sprint-03.md`. Trabajo sin commitear en
`release` mientras avanza el sprint.

- Fase 1 verificada: modelos `Receivable`, `ReceivableInstallment`, `Movement`
  y `CustomerCredit` (`models/receivables.py`), migracion `f170c0d8901c`,
  servicio de lectura `list_receivables` con calculo de saldo on-demand
  (`services/receivables.py`), evento `invoice.authorized` y worker
  `handle_invoice_authorized` que crea receivables automaticamente desde
  facturas AUTHORIZED, endpoint `GET /receivables` (tenant-scoped, con
  filtros `status`/`dueBefore`). Suite: 9 pruebas nuevas.
- Fase 2 verificada: cobro parcial con retenciones y descuentos (E5-03/E5-04),
  `record_payment` con lock `FOR UPDATE` sobre el receivable (evita
  sobreaplicacion concurrente), endpoint `POST /receivables/{id}/payments`
  con idempotencia y auditoria, evento `credit_note.authorized` y aplicacion
  automatica de NC contra cartera (E5-08) con creacion de `CustomerCredit`
  cuando excede saldo, test de concurrencia real (dos cobros simultaneos ->
  exactamente uno 201 y uno 422, sin sobreaplicar). Bug encontrado y corregido:
  `append_audit` sin flush duplicaba secuencias de auditoria. Suite: 22
  pruebas SQLite / 24 PostgreSQL.
- Fase 3 verificada: aging por buckets reproducible (E5-05) con fecha de corte
  local `America/Guayaquil` (`classify_aging_bucket` funcion pura,
  `compute_aging_summary` agrega por tenant y por cliente, buckets fijos
  CURRENT/1-15/16-30/31-60/61-90/90+, `GET /receivables/aging` con query
  param `asOf` overrideable para pruebas), reverso de movimiento (E5-09)
  `reverse_movement` que crea Movement REVERSAL sin editar el original,
  maneja reduccion de CustomerCredit si el original era CREDIT_NOTE, endpoint
  `POST /receivables/{id}/movements/{movementId}/reversal` con idempotencia.
  Contrato OpenAPI actualizado con path de reverso y campo `aging` aditivo
  en `AccountItem`. Suite: 27 pruebas aging (15) + reverso (12) = 27 pruebas.
- Fase 4 verificada: tools MCP `receivables.list` (solo lectura, scope
  `receivables:read`), `receivables.record_payment` (escritura con kill switch
  e idempotencia, scope `receivables:write`) y `receivables.send_reminder`
  (external-write con StubNotifier P1/parcial, scope `receivables:notify`).
  Interfaz de notificaciones implementada (`integrations/notifications/`),
  modelo `CollectionReminder` agregado con `party.consent_opt_out`, migracion
  `add_collection_reminder_and_party_consent`. Servidor MCP actualizado con
  scopes y tools siguiendo el patron de `invoices.*`.
- Backend al corte: 196 pruebas pasando, 19 con problemas menores (atributos
  de dataclass vs schema Pydantic en recreacion de archivo), ruff y mypy limpios.
- Pendiente: Fase 4 (tools MCP de cartera), UI de cartera, dataset
  `sprint-03-v1` y QA en vivo.

## Avance de Sprint 3 y Epic E7 (corte 2026-07-09)

- Backend de cartera (E5-01..E5-09) implementado y verificado: 228 pruebas
  SQLite / 231 PostgreSQL, migraciones limpias (`alembic check` sin drift),
  contratos validos.
- Durante la estabilizacion se corrigieron bugs reales que los tests de los
  agentes no atraparon: (1) el saldo no excluia movimientos revertidos; (2)
  retencion/descuento sin `flush()` (sesion autoflush=False) sobrestimaban el
  saldo; (3) el estado `OVERDUE` no se derivaba de cuotas vencidas; (4) el
  reverso no auditaba con `original_movement_id`; (5) la migracion de
  recordatorios tenia FK de tipos incompatibles y drift de indices; (6)
  `compute_aging_summary` con firma incompatible con sus llamadores.
- Epic E7 (IA y MCP): E7-01/02/03 ya estaban; E7-04 (cartera/pagos MCP) y
  E7-07 (resistencia a prompt injection) quedaron completos con 13 pruebas
  nuevas (`test_mcp_receivables.py`, `test_mcp_prompt_injection.py`):
  aislamiento por tenant, equivalencia REST/MCP, sin saldo negativo ni
  sobreaplicacion, kill switch solo en escrituras, idempotencia, y fixtures de
  inyeccion tratados como datos inertes (resistencia estructural: tools
  tipadas Pydantic + SQL parametrizado, sin tool de SQL libre). Sin hallazgos
  de seguridad en las tools; el catalogo MCP es un conjunto cerrado esperado.
  E7-05 (agente OpenAI), E7-06 (medicion consumo/costo) y E7-08 (resumen) son
  alcance de Sprint 5 y no se implementan aqui.
- Seguridad: se elimino un endpoint de debug `/api/v1/debug/mcp-token` (dejado
  por depuracion de MCP en una fase previa) que decodificaba cualquier token
  bearer y devolvia sus claims sin gate; era fuga de internos del token y
  rompia el lint.
- Pendiente Sprint 3: dataset `sprint-03-v1`, ciclo en vivo (factura ->
  receivable -> cobro -> aging -> reverso) y QA go/no-go. UI de cartera base
  hecha (16 pruebas a11y); reconciliar el detalle con el contrato extendido.

## Ejecucion local

```bash
docker compose up -d
docker compose ps
```

Accesos locales:

- Aplicacion: `http://localhost:8088`
- API/OpenAPI: `http://localhost:8000/docs`
- Keycloak: `http://localhost:8080`
- MinIO: `http://localhost:9001`

Usuario demo OIDC, solo local:

- Usuario: `owner`
- Clave: `DemoPass123!`

El modo de desarrollo de Vite puede usar `owner@iaerp.local` y el tenant
`11111111-1111-4111-8111-111111111111` sin password. No habilitar
`AUTH_MODE=dev` en ambientes compartidos o productivos.

## Siguiente trabajo recomendado

1. Ejecutar la revision independiente de QA y actualizar Sprint 1 a `Done` solo
   si todos sus criterios de aceptacion tienen evidencia.
2. Con autorizacion humana, commitear el estado de esta sesion en `release`
   para que el corte publicado coincida con este archivo.
3. Iniciar la planificacion de Sprint 2 (facturacion, nota de credito y SRI).

## Regla de relevo

Una IA nueva debe leer, en este orden:

1. `AGENTS.md`.
2. Este archivo.
3. `docs/sprints/sprint-01.md`.
4. `docs/09-testing-quality.md`.
5. Los ADR relacionados con el cambio que vaya a realizar.

Antes de modificar codigo debe ejecutar `git status`, comprobar los servicios y
no descartar cambios existentes. No debe crear ramas, hacer push, merge ni abrir
PR sin autorizacion explicita.
