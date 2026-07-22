# Guía de Usuario — IAERP

Manual para el uso diario de IAERP: facturación electrónica SRI, cartera y CRM.

> Complementa: [`ADMIN_GUIDE.md`](ADMIN_GUIDE.md) (configuración) y
> [`DEV_SETUP.md`](DEV_SETUP.md) (entorno de desarrollo).

## 1. Ingreso

Al abrir la aplicación pulsa **Continuar** para entrar con tu sesión. Si tu
organización usa inicio de sesión corporativo (OIDC/Keycloak), serás redirigido
al proveedor de identidad.

## 2. La barra lateral

El menú de la izquierda organiza el sistema en secciones numeradas:

| # | Sección | Para qué sirve |
|---|---------|----------------|
| 01 | **Resumen** | Panel de indicadores y estado general |
| 02 | **Contactos** | Clientes y proveedores (parties) |
| 03 | **Productos** | Catálogo con categorías tributarias |
| 04 | **Facturas** | Emisión electrónica y seguimiento SRI |
| 05 | **Empresa** | Establecimientos y puntos de emisión |
| 06 | **Cartera** | Cuentas por cobrar, aging y cobranza |
| 07 | **CRM** | Pipeline de oportunidades (kanban) |

- **Colapsar el menú:** botón de la flecha en la cabecera del sidebar, o
  atajo **⌘/Ctrl + B**. Colapsado, cada ícono muestra su nombre al pasar el
  cursor. El estado se recuerda entre sesiones.

## 3. Contactos (02)

Registra clientes y proveedores. Al crear/editar un contacto puedes fijar su
**condición de pago predeterminada** (o dejar "Usar valor de la empresa"). Esa
condición se aplicará automáticamente al facturarle (ver §4).

## 4. Facturas (04)

### Crear una factura
1. Pulsa **Nueva factura**.
2. Elige el **cliente**. Debajo verás un indicador de qué condición de pago se
   aplica: *"configurada para este cliente"* o *"predeterminada de la empresa"*.
3. Selecciona **establecimiento** y **punto de emisión**, y la **fecha de
   emisión** (no puede ser futura respecto a la hora de Ecuador).
4. Completa las **líneas** en la hoja de cálculo editable:
   - Elige el producto (autocompleta descripción, precio e impuesto).
   - Ajusta **cantidad**, **precio unitario** y **descuento** directamente en la
     celda. Usa **↑/↓** para moverte entre filas y **Enter** en la última fila
     para agregar una nueva.
   - Las columnas **Base**, **IVA** y **Total** se calculan en el servidor en
     tiempo real (el cliente nunca calcula impuestos).
   - Una celda con cantidad ≤ 0 o precio < 0 se marca en rojo.
5. Revisa los totales en el pie de la tabla y pulsa **Guardar**. Verás una
   notificación de confirmación con el número de la factura.

### Emitir al SRI
Desde el detalle de una factura en borrador, pulsa **Emitir**. El sistema
transmite el comprobante al SRI y muestra el estado de autorización, los
artefactos generados (XML/PDF) y los intentos de transmisión.

### Nota de crédito
Desde una factura **autorizada**, usa **Nota de crédito** para generar el
documento relacionado.

## 5. Cartera (06)

Consulta las cuentas por cobrar con su **aging** por buckets (corriente, vencido
por tramos). Registra pagos y da seguimiento a la cobranza. Cada movimiento
queda auditado.

## 6. CRM (07)

Tablero **kanban** de oportunidades por etapa (Nuevo → Contactado → Calificado →
Propuesta → Negociación).

- **Crear rápido:** botón **+** en la cabecera de una columna (abre un modal).
- **Nueva oportunidad:** formulario completo con datos del contacto.
- **Mover:** arrastra una tarjeta entre columnas (respeta transiciones válidas).
- **Abrir detalle:** clic en una tarjeta.
- **Selección múltiple y acciones masivas:** selecciona varias tarjetas para
  moverlas juntas.
- **Filtros:** búsqueda, responsable, valor, temperatura y rango de fechas.
- **Teclado:** flechas para moverte entre tarjetas; **Esc** cierra el panel de
  ayuda o limpia la selección.

## 7. Accesibilidad

IAERP sigue WCAG 2.1 AA: navegación completa por teclado, indicadores de foco
visibles, etiquetas en todos los controles, contraste suficiente y respeto por
`prefers-reduced-motion` (si reduces el movimiento en tu sistema, se desactivan
las animaciones). Usa el enlace **"Saltar al contenido"** (primer Tab) para ir
directo al área principal.

## 8. Problemas comunes

- **"issueDate cannot be in the future":** la fecha de emisión es posterior a
  hoy en hora de Ecuador (America/Guayaquil). Ajusta la fecha.
- **Una sección no carga:** aparecerá una tarjeta de error con **Reintentar** /
  **Recargar página**. Si persiste, recarga o contacta a soporte.
- **Los totales no cuadran:** el servidor es la fuente autoritativa; guarda y
  vuelve a revisar el detalle.
