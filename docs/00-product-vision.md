# Vision de producto

## Problema

Las pymes ecuatorianas suelen separar facturacion, cartera, obligaciones,
documentos y comunicaciones en herramientas distintas. Esto produce registros
duplicados, vencimientos invisibles, tareas manuales y poca trazabilidad sobre
las decisiones tomadas por personas o automatizaciones.

## Propuesta

IAERP centraliza facturacion electronica, cuentas por cobrar y cuentas por pagar.
Cada capacidad se puede usar desde la interfaz web, API REST o herramientas MCP.
La IA no es un chat agregado al final: opera sobre casos de uso tipados, con
permisos, politicas, idempotencia y auditoria.

## Cliente ideal

- Pyme ecuatoriana con RUC activo.
- Entre 1 y 50 usuarios administrativos.
- Factura electronicamente y necesita controlar cartera y proveedores.
- Opera principalmente en servicios o comercio.
- No requiere que IAERP sea su sistema contable en el MVP.

## Principios

1. Exactitud antes que velocidad en dinero y documentos fiscales.
2. Una sola fuente de verdad para web, API, workers y agentes.
3. Autonomia verificable: toda accion de IA es identificable y reversible cuando
   el dominio lo permita.
4. Aislamiento estricto por RUC.
5. Integraciones idempotentes: una repeticion no duplica efectos.
6. Configuracion simple para una pyme, sin trasladarle complejidad tecnica.

## Resultados esperados del MVP

- Emitir una factura y una nota de credito validas ante el SRI.
- Evitar duplicados por secuencial y clave de acceso.
- Conocer saldos vencidos y registrar cobros parciales correctamente.
- Registrar obligaciones desde captura manual o XML/PDF.
- Programar y registrar pagos sin iniciar transferencias bancarias.
- Permitir que un agente consulte y opere mediante MCP sin escapar de su tenant.
- Explicar quien o que realizo cada cambio y con que resultado.

## Indicadores iniciales

- Tasa de emision SRI exitosa y tiempo hasta autorizacion.
- Comprobantes duplicados: objetivo cero.
- Diferencia entre saldos calculados y aplicaciones: objetivo cero.
- Porcentaje de documentos de proveedor extraidos sin correccion.
- Recordatorios entregados por email y WhatsApp.
- Acciones de IA rechazadas por politica, repeticion o datos invalidos.
- Tiempo para recuperar el servicio y restaurar un backup probado.

## No objetivos del MVP

Contabilidad general, declaraciones tributarias, conciliacion bancaria,
transferencias, nomina, RRHH, marketing, campanas Telegram, operacion de
farmacias y procesos de franquicias.
