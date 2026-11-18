# Qué le falta a IAERP en el iPhone

**Propuesta para revisión de Carlos · 18 de noviembre de 2026 · versión instalada 0.4.2 (6)**

Carlos quiere reconocer en el iPhone su forma de trabajar en IAERP. Al entrar verá un resumen de la empresa, podrá abrir las facturas por mes y tendrá «Nueva factura» a mano. El recorrido termina cuando el SRI autoriza el comprobante y el usuario puede enviar el RIDE y el XML por correo desde esa misma ficha.

En la web, Facturas ya agrupa por mes y año de emisión, abre el período más reciente y muestra cantidad e importe por grupo. El tablero destaca por cobrar, vencido y cobrado este mes. La ficha de factura reutiliza los servicios de emisión, consulta previa de correo y envío confirmado. Estos son los puntos de referencia para el iPhone. [Interfaz web](../../frontend/src/App.tsx) · [Servicios de factura y correo](../../backend/app/api/router.py)

## Punto de partida · 0.4.2

| Tarea | Disponible | Qué falta comprobar o desarrollar |
| --- | --- | --- |
| Entrar y elegir cuenta | Carlos confirma que el inicio de sesión funciona en su iPhone. El código admite varios perfiles y desbloqueo con Face ID o código. | Probar dos perfiles en el teléfono, cancelar Face ID y verificar qué empresa queda activa al volver. |
| Consultar clientes | Hay búsqueda, ficha fiscal y acción «Nueva factura» con el cliente seleccionado. | La ficha carece de historial de facturas. En el listado inicial la acción de facturar requiere entrar primero en la ficha o cambiar de pestaña. |
| Preparar una factura | Se pueden elegir productos, revisar importes calculados por IAERP y guardar un borrador. Existe recuperación si se pierde la respuesta de guardado. | Desde la ficha del cliente, al cerrarse el formulario falta una confirmación en esa pantalla y un acceso al borrador. Queda probar el guardado en el teléfono con una empresa de pruebas. |
| Encontrar y entregar un comprobante | Hay lista, detalle, estados, vista PDF/XML y opción de compartir los archivos disponibles. | Buscar el número completo con guiones puede fallar. La lista corta a 100 documentos antes de que el iPhone descarte las notas de crédito. El nombre del cliente puede faltar si la app aún no lo cargó. |
| Corregir y emitir | La app distingue el borrador del comprobante autorizado. | Falta editar un borrador guardado. La política móvil vigente permite preparar y guardar. La emisión desde el iPhone requiere un permiso nuevo y pruebas del ciclo SRI. |

La revisión de producto y UX cubrió el código Swift, el contrato REST y seis capturas sintéticas de versiones anteriores. La confirmación física de esta versión corresponde al ingreso. Los tiempos de las tareas y su aspecto actual en el teléfono quedan por medir. [Pantallas](../../ios/IAERP/App/Workspace/WorkspaceLists.swift) · [Formulario](../../ios/IAERP/App/Workspace/InvoiceComposer.swift) · [Estado de clientes y documentos](../../ios/IAERP/App/Workspace/WorkspaceStore.swift) · [Servicio iOS](../../ios/IAERP/Sources/IAERPClient/LiveERPService.swift) · [API](../../backend/app/api/router.py) · [Búsqueda en el servidor](../../backend/app/services/billing.py) · [Capturas](../../ios/validation/screenshots)

## Qué aportan tres apps comparables

Se consultaron fichas iOS y guías de los fabricantes. Las funciones descritas son referencias de diseño. Su rapidez y facilidad de uso no se midieron en dispositivos.

| App | Qué documenta | Decisión propuesta para IAERP |
| --- | --- | --- |
| Contífico Uno · Ecuador | Permite crear el cliente mientras se prepara la factura, ajustar líneas y ver el RIDE en PDF. [Ficha iPhone del fabricante](https://apps.apple.com/ec/app/cont%C3%ADfico-uno/id1516540185) | Dar de alta al cliente sin perder la venta en curso (IOS-032). Probar que el PDF existente corresponde a la factura autorizada (IOS-013). |
| Alegra | En móvil se puede iniciar una factura desde la acción de creación y buscar comprobantes por contacto o por número. La guía de búsqueda corresponde a Colombia. [Guía móvil](https://ayuda.alegra.com/col/crea-facturas-electronicas-con-la-app) | Hacer visible «Nueva factura» y permitir encontrar un documento a partir del dato que Carlos ya tiene, el cliente o el número completo (IOS-028 a IOS-030). |
| Zoho Invoice | Su app iOS permite compartir documentos desde el teléfono y ofrece bloqueo biométrico. [Producto iOS](https://www.zoho.com/us/invoice/mobile-apps/?app=ios) | IAERP ya cubre ambas funciones en código. Antes de ampliar el alcance, probar el archivo compartido y el cambio entre dos perfiles en el iPhone (IOS-013/020/026). |

## Backlog para decidir

Orden propuesto dentro de cada entrega. S, M y L indican esfuerzo relativo. Las referencias IOS-001 a IOS-026 conservan los criterios del [backlog original](ios-backlog.md). Los identificadores nuevos describen mejoras concretas.

### Entrega 1 · Inicio y facturas por mes

Carlos aprobó IOS-034, IOS-035 y la búsqueda de IOS-028. La versión 0.5.0 muestra los tres saldos de cartera de la web. El servidor calcula los totales de cada mes y moneda antes de paginar las filas. Desde Inicio se puede abrir el formulario de factura y volver a consultar el borrador guardado.

**Revisión por entrega.** Negocio contrasta saldos, reglas fiscales, roles y límites de empresa. UI/UX comprueba navegación, legibilidad y texto máximo. QA comprueba contratos, errores, regresiones y flujo completo con datos sintéticos. Cada hallazgo que incumpla un criterio vuelve a desarrollo y al revisor correspondiente. Tras las tres revisiones favorables y CI verde se publica por el flujo de IAERP y se instala por cable. Carlos autorizó las consultas de lectura y el permiso de resumen para perfiles autorizados.

| Orden | Historia | Criterio para aceptarla |
| --- | --- | --- |
| 1 | **IOS-034 · M · Inicio con resumen de la empresa.** Nueva pantalla inicial. | Mostrar empresa activa, «Por cobrar» y «Vencido» al corte, «Cobrado este mes» y acción «Nueva factura». Reusar definiciones y fuentes de la web. Las cifras sólo se muestran con permiso y datos completos. Un error de carga tiene su propio estado. Cambiar de perfil descarta el resumen anterior. Comparar los tres valores contra la web para la misma empresa y fecha fiscal. |
| 2 | **IOS-035 · M · Facturas agrupadas por mes.** Amplía IOS-012 y depende de la consulta completa de IOS-028. | Agrupar por fecha de emisión, con mes y año, más reciente abierto. Cada cabecera muestra cantidad y suma exacta de las facturas del grupo según filtros activos. Abrir un mes anterior, entrar a una factura y volver conserva mes y posición. Verificar dos años, meses con más de 100 documentos y notas de crédito fuera del total de facturas. |
| 3 | **IOS-028 · M · Localizar una factura por su número.** Completa la búsqueda de IOS-012/014. | Pegar el número visible, por ejemplo `001-002-000000123`, devuelve el comprobante del establecimiento y punto correctos, aunque otro punto tenga el mismo secuencial. Se conserva la búsqueda por clave de acceso. El filtro por tipo se aplica antes del límite y hay continuidad entre páginas. Verificar con más de 100 documentos mixtos. |

**Prueba de Carlos en el teléfono.** Elegir la misma empresa en IAERP web y en el iPhone. En Inicio, tocar la fecha y comparar las tres cifras al mismo corte. En Facturas, abrir un mes anterior y cotejar cantidad e importe con la web usando los mismos filtros. Entrar a una factura y volver para comprobar que el mes y la posición se conservan. Repetir con un segundo perfil y comprobar qué puede consultar. Probar con VoiceOver el botón «Nueva factura» y verificar que se distingue la empresa activa. [Resultados de la entrega](../STATUS.md)

### Entrega 2 · Nueva factura, emisión y envío por correo

| Orden | Historia | Criterio para aceptarla |
| --- | --- | --- |
| 1 | **IOS-027 · S · Ver el borrador recién guardado.** Amplía IOS-010. | Al guardar desde Clientes o Facturas, se ve «Borrador guardado», cliente, total y «Ver borrador». El detalle abre el mismo ID que devolvió IAERP. Si se corta la red después del guardado, la app indica que está comprobando el resultado. Un doble toque o una reapertura dejan un solo documento. |
| 2 | **IOS-011 existente · L · Emitir en pruebas.** Depende del guardado verificado y de permiso por acción y ambiente. | Mostrar empresa, ambiente y total antes de confirmar. Una demora o una reapertura retoman la consulta de estado. Probar autorización y rechazo con datos sintéticos. Conservar el motivo y comprobar que una misma solicitud no dispara otra emisión. |
| 3 | **IOS-013/014 existentes · M · Comprobar los documentos de salida.** | Tras la autorización de prueba, abrir el RIDE y el XML del mismo comprobante. Ante un rechazo, mostrar la causa y la acción disponible. Validar archivos aún pendientes, enlace vencido y acceso con otro perfil. |
| 4 | **IOS-033 · M · Enviar por correo desde el comprobante.** Requiere IOS-011/013 y permiso móvil específico. | En la misma ficha, habilitar «Enviar por correo» tras la autorización y con los adjuntos disponibles. Reutilizar la vista previa de IAERP para confirmar destinatario, RIDE y XML. Un doble toque produce un solo envío en el entorno de pruebas. Distinguir enviado, pendiente y fallido según la respuesta del servicio. |

**Demostración de cierre.** Desde Inicio, crear un borrador en una empresa de pruebas, emitirlo en SRI de pruebas y seguir su estado en la ficha. Cuando figure autorizado, confirmar el correo y verificar la recepción de un solo mensaje con ambos archivos en un buzón de pruebas. Si hay rechazo, ver el motivo en la misma ficha. La emisión y el envío reales requieren habilitación posterior de los permisos móviles.

### Entrega 3 · Facturar con menos pasos y corregir errores

| Orden | Historia | Criterio para aceptarla |
| --- | --- | --- |
| 1 | **IOS-030 · M · Agilizar la captura.** Amplía IOS-009/017. | Desde Clientes se abre «Nueva factura» en un toque cuando el rol lo permite. Cliente y productos aparecen antes de los ajustes precargados. Al cambiar cantidades, la app exige revisar los nuevos totales del servidor. Se comparan pasos y tiempo con una medición previa del mismo formulario. |
| 2 | **IOS-031 · L · Editar el mismo borrador.** Requiere IOS-027 y contrato de edición en el servidor. | Al corregir cantidad y guardar se conserva el ID y se recalculan los totales. Dos ediciones simultáneas muestran un conflicto recuperable. El servidor comprueba empresa, permiso y estado DRAFT, y audita el cambio. Una factura emitida conserva sus datos. |
| 3 | **IOS-032 · M · Crear un cliente durante la factura.** Requiere aprobar permiso móvil de alta. | Si el cliente no existe, un usuario autorizado lo crea desde el selector y vuelve a la factura con las líneas intactas. Un identificador duplicado permite seleccionar el cliente existente de la misma empresa. Con rol de consulta sólo se ofrece la búsqueda. |
| 4 | **IOS-029 · M · Ver las facturas de un cliente desde su ficha.** Amplía IOS-008/012 y usa IOS-028 para listas largas. | «Ver facturas» usa el filtro de cliente que ya ofrece el servidor. Se ve el nombre correcto aunque esté fuera de los primeros 100 clientes. Se puede abrir un documento y volver con la búsqueda intacta. Probar cliente sin facturas, acceso de solo lectura, dos empresas y error de red. |

El orden propuesto prioriza clientes y facturas. Compras, cartera y avisos conservan su lugar en el backlog original. La decisión sobre emisión fiscal real se toma después de revisar los resultados de la entrega 2. [Política móvil](../adrs/0024-ios-production-connection-policy.md) · [Recuperación del borrador](../adrs/0025-ios-durable-draft-recovery.md)
