# Sistema de interfaz ERP

Este documento define las plantillas y posiciones de acciones obligatorias de
IAERP. Una pantalla nueva debe componerse con los componentes compartidos antes
de introducir variantes locales.

## Principios

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

## Revision

Una pantalla no cumple Definition of Done si:

- crea una variante local de boton ya existente;
- mueve acciones estandar sin una decision documentada;
- no contempla estados vacio/error/permisos;
- solo funciona con mouse o en desktop;
- introduce una sexta plantilla sin actualizar este documento.
