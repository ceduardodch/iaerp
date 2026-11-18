# Sistema de interfaz ERP

Este documento define las plantillas y posiciones de acciones obligatorias de
IAERP. Una pantalla nueva debe componerse con los componentes compartidos antes
de introducir variantes locales.

## Principios

### Cliente nativo iOS

El selector de cuentas (ADR 0023) muestra nombre, usuario y empresa; distingue
proveedores cuando hay varios. Nunca identifica una cuenta sólo por nombre.
Elegir cuenta y abrir sus opciones son controles distintos, con objetivos de
44 pt y etiquetas VoiceOver completas. En tamaños de accesibilidad, la fila
pasa a vertical y retira iconos decorativos para dar ancho al texto; no reduce
la fuente. `AnyLayout` conserva identidad y controles al cambiar la disposición.
La etiqueta nativa del botón reúne los textos visibles de la cuenta; se conserva
ese anuncio junto con el hint de desbloqueo. Quitar confirma nombre,
usuario y empresa y ofrece Cancelar; completar el proveedor es un P2 registrado.
Cambiar cuenta conserva accesos; Cerrar sesión quita sólo el activo. La pantalla
Cuenta muestra la identidad activa y explica esa diferencia.

Desde [ADR 0022](adrs/0022-native-ios-client.md), las pantallas SwiftUI usan
equivalentes nativos compartidos en `ios/IAERP/App/ERPComponents.swift`.
React `Erp*` sigue siendo obligatorio en web; no se copia su DOM en iOS.
La autorización de inicio cubre estas equivalencias del primer incremento:

| Patrón ERP | SwiftUI |
| --- | --- |
| Encabezado y volver | `NavigationStack`, `navigationTitle` y navegación del sistema |
| Toolbar y búsqueda | `ERPSearchField` compartido bajo el encabezado; `searchable` sólo en la demo de regresión |
| Panel/listado/ficha | `List`, `Section`, `NavigationLink` y `ERPDetailRow` |
| Estado visible | `ERPStatusBadge`, texto e icono; nunca sólo color |
| Vacío | `ContentUnavailableView`, con motivo y filtro visible |
| Crear/editar | Textos `Nuevo`, `Editar`, `Guardar`, `Cancelar` intactos; fuera de la demo inicial |

No hay cambio de posición de las acciones de formulario en esta parte.
Usar fuentes semánticas, mínimo táctil 44 pt, colores de sistema, VoiceOver,
modo oscuro y tamaños de accesibilidad. Datos de demostración claramente
marcados. No mostrar botones para funciones aún sin conectar.

La demo inicial de regresión mantiene `searchable` bajo el título. En las
pantallas de trabajo, la auditoría nativa identificó contraste en
`UISearchBarTextField` y textos junto al material de la barra. Se usa
`ERPSearchField`: `TextField` SwiftUI con prompt/texto `Color.primary`, icono
oculto a VoiceOver y limpieza con objetivo de 44 pt, dentro de la primera
sección de la lista. Evita otra barra, conserva teclado de búsqueda, Dynamic
Type y los contratos de consulta. Listas/formularios usan borde de scroll
`.hard` para contenido denso; no se excluyen hallazgos de la auditoría.
`ERPListSummary` muestra «Resultados: n» y «Hasta 100 por consulta» en textos
separados con fuente `footnote` y altura intrínseca, junto al buscador.
Los títulos de trabajo usan tamaño inline para dejar espacio al contenido.

`ERPStatusBadge` usa `HStack` y texto con altura intrínseca, sin limitar Dynamic
Type; el estado corto `Demo` anuncia «Modo de demostración». Avisos, encabezados
y ficha usan `Color.primary` explícito. El aviso de datos de prueba ocupa un
footer corto. La ficha distingue estado del documento/SRI y estado de cobro.
Nueva factura usa formulario nativo y barra inferior `Cancelar` → `Guardar`,
vertical con tamaños de accesibilidad. Un preview vencido deshabilita guardar;
rechazos definitivos permiten corregir, respuesta incierta conserva operación.
`ERPPrimaryActionStyle` conserva texto legible al deshabilitar Guardar; usa
colores semánticos de fondo/texto en ambos modos. Los campos de líneas tienen
foco por UUID y el teclado comparte una acción «Listo». El formulario y su
barra de acciones son vistas hermanas, sin superponer controles al contenido.
Formulario y fichas ocultan el efecto de borde y usan fondo opaco en la barra
de navegación para que el material no desvanezca datos fiscales. Las fichas
de cliente/factura ocultan las pestañas; Volver recupera la navegación principal.

Cuenta abre los datos de empresa en una hoja propia para evitar que RUC y
permisos queden bajo la barra de pestañas con texto máximo. Empresa y visor
comparten `ERPCloseButton`: icono del sistema, objetivo de 44 pt y etiqueta
VoiceOver «Cerrar».

El escudo de ventana opaco cubre el selector de apps, incluidas hojas y visor,
al recibir `willResignActive`; se retira al volver a primer plano. No se marca
el contenedor completo con `privacySensitive`: esa marca redactaba también
el acceso y otros controles en iOS 26.5. No se muestran datos sintéticos como
sustituto de una consulta real fallida.

- Consistencia operativa antes que decoracion.
- Una accion primaria visible por pantalla.
- El usuario siempre sabe si esta consultando, creando o editando.
- Acciones frecuentes no dependen de menus ocultos.
- Los estados `loading`, vacio, error, sin permisos y guardado son parte de la
  plantilla, no decisiones de cada modulo.
- Desktop y movil mantienen la misma jerarquia y nombres.

## Plantillas

### Dashboard

- `ErpPageHeader` con periodo/contexto y acciones globales.
- KPIs en `ErpMetricGrid`.
- Secciones de seguimiento ordenadas por urgencia.
- No incluye formularios de alta dentro del dashboard.

### Listado

- `ErpPageHeader`: titulo a la izquierda y `Nuevo <entidad>` arriba a la derecha.
- `ErpToolbar`: busqueda, filtros, vista y exportacion debajo del encabezado.
- `ErpPanel`: tabla o tarjetas con conteo visible.
- La ultima columna se llama `Acciones`.
- `Editar` es accion directa; acciones secundarias van en menu contextual.
- Excepcion Compras (2026-11-17): `Anular` va visible bajo el numero de la
  compra en su fila, para no depender de `Pagar` ni del desplazamiento horizontal.
  Abre el modal de confirmacion existente; nunca aplica el cambio al pulsarlo.
- La seleccion masiva, cuando exista, reemplaza temporalmente la toolbar.

### Ficha

- Breadcrumb/contexto sobre el titulo.
- Estado y metadatos junto al titulo.
- `Editar` arriba a la derecha.
- Informacion agrupada en secciones estables, no como un formulario deshabilitado.
- Actividad, auditoria y documentos relacionados aparecen despues de los datos
  principales.

### Crear y editar

- El mismo `ErpFormPanel` sirve para alta y edicion.
- Titulo explicito: `Nuevo contacto` o `Editar contacto`.
- Campos agrupados por significado y ordenados segun el flujo del negocio.
- Barra de acciones al final: `Cancelar` primero y `Guardar` despues.
- En movil la barra queda visible al final del viewport.
- Errores de campo aparecen junto al campo; errores generales usan `role=alert`.
- El boton guardar muestra estado pendiente y evita doble envio.

### Configuracion

- Navegacion secundaria a la izquierda en desktop y tabs en movil.
- Cada seccion guarda de forma independiente.
- Acciones destructivas viven en una zona separada y nunca junto a `Guardar`.

## Acciones estandar

| Accion | Posicion | Variante | Texto |
| --- | --- | --- | --- |
| Crear | Encabezado, derecha | Primary | `Nuevo <entidad>` |
| Editar ficha | Encabezado, derecha | Secondary | `Editar` |
| Editar fila | Ultima columna | Ghost | `Editar` |
| Guardar | Final del formulario, derecha | Primary | `Guardar` |
| Cancelar | Inmediatamente antes de guardar | Secondary | `Cancelar` |
| Eliminar/revocar | Zona de peligro o menu | Danger | Verbo explicito |
| Volver | Breadcrumb o enlace superior | Ghost | `Volver a <lista>` |

No se usaran sinonimos para la misma accion (`Crear`, `Agregar`, `Añadir`) dentro
de la interfaz. IAERP usa `Nuevo`, `Editar`, `Guardar`, `Cancelar` y
`Eliminar/Revocar`.

## Componentes base

- `ErpButton`
- `ErpPageHeader`
- `ErpToolbar`
- `ErpPanel`
- `ErpFormPanel`
- `ErpStatusBadge`
- `ErpEmptyState`
- `ErpActionCell`

Los componentes viven en `frontend/src/components/erp/`. Los modulos pueden
componerlos, pero no duplicar estructura, espaciado, variantes de botones o
posiciones de acciones.

## Accesibilidad

- Todos los botones conservan nombre accesible y foco visible.
- Iconos sin texto requieren `aria-label`; iconos decorativos son
  `aria-hidden`.
- Formularios anuncian errores y estados pendientes.
- Tablas mantienen encabezados reales y acciones por fila identificables.
- La barra fija movil no cubre campos ni mensajes.
- `prefers-reduced-motion` elimina movimientos no esenciales.

## Navegacion principal

- Los modulos conservan estos grupos: `Resumen`; `Comercial` (`CRM`,
  `Contactos`, `Contratos`); `Operaciones` (`Facturas`, `Cartera`, `Compras`,
  `Tributario`); y `Administracion` (`Catalogos`, `Empresa`).
- En desktop, `Resumen` es un acceso directo y los otros grupos abren menus
  cortos. El grupo y el modulo activos deben quedar señalados.
- En movil, la cabecera muestra la marca, la seccion actual y un boton `Menu`.
  El boton abre un panel lateral con todos los grupos; no se usa una fila
  horizontal de modulos.
- El panel movil se cierra con `Escape`, clic exterior, el boton de cierre o al
  elegir un modulo. Atrapa el foco mientras esta abierto y lo devuelve al boton
  `Menu` al cerrar.
- Todos los destinos y controles moviles miden al menos 44 por 44 pixeles. La
  lista permite desplazamiento vertical sin crear scroll horizontal en la
  pagina.
- Al elegir un modulo, el foco pasa a `#main-content` para evitar que usuarios
  de teclado recorran otra vez toda la cabecera.

## Cobro rápido y retenciones

- Al entrar a Cartera, un usuario con permiso de escritura cruza los XML de
  retención ya importados; las consultas GET no cambian saldos.
- `Registrar cobro` prepara el saldo en el servidor antes de abrir el formulario.
  Precarga el neto pendiente y la fecha de Guayaquil. No asigna un método de pago
  ni calcula retenciones desde porcentajes esperados del cliente.
- El usuario elige el método y confirma con `Guardar`. Puede cambiar el monto
  para un abono parcial. XML adicionales, retenciones y descuentos viven en una
  sección desplegable; lo ya aplicado no se vuelve a ingresar.
- Un error de preparación no abre el formulario ni registra dinero. Los
  reintentos conservan la clave de idempotencia; cambiar el cobro usa otra clave.
- Si una retención requiere revisión, el aviso lo explica sin presentar códigos
  internos ni asumir que se descontó del saldo.

## Revision

Una pantalla no cumple Definition of Done si:

- crea una variante local de boton ya existente;
- mueve acciones estandar sin una decision documentada;
- no contempla estados vacio/error/permisos;
- solo funciona con mouse o en desktop;
- introduce una sexta plantilla sin actualizar este documento.
