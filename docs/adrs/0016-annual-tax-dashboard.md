# ADR 0016: Avance anual de renta y retenciones

- Estado: Accepted
- Fecha: 2026-08-21

## Contexto

Tributario ya prepara el IVA mensual y el ATS desde comprobantes reales. El
usuario también necesita ver cómo avanza el año, cuántas compras ya confirmó
como deducibles y qué retenciones podrían formar un saldo a favor.

Una resta simple no equivale al impuesto a la renta. La declaración anual puede
requerir conciliación tributaria, participación laboral, depreciaciones, otros
ajustes y una tarifa que depende del perfil fiscal. Tampoco basta con acumular
retenciones para afirmar que ya procede una devolución.

## Decisión

1. Tributario se organiza en una sola página con pestañas accesibles para el
   mes, el año fiscal y las retenciones.
2. El avance anual usa ventas autorizadas, bases de compras recibidas y
   retenciones reales del tenant. Las notas de crédito restan en el mes que se
   emitieron. El corte acumula desde enero hasta el mes elegido y no incorpora
   meses posteriores aunque ya tengan documentos cargados.
3. Las compras se separan según la decisión guardada en Cuentas por pagar:
   deducibles confirmadas, no deducibles y pendientes de revisión. Una nota de
   crédito hereda la clasificación de su factura sustento cuando existe el
   enlace documental.
4. `ventas - compras deducibles confirmadas` se muestra como **resultado antes
   de ajustes**, nunca como base imponible ni impuesto causado.
5. IAERP no aplica una tarifa de renta hasta contar con el perfil fiscal y los
   ajustes del cierre. La vista enumera estas limitaciones.
6. Las retenciones de renta se muestran como crédito para revisar al cierre.
   Solo se habla de posible saldo a favor si la declaración anual determina que
   superan el impuesto causado.
7. Las retenciones de IVA siguen separadas. La pantalla explica que su posible
   devolución tiene reglas y respaldos propios; no declara elegibilidad.
8. El servidor calcula todos los importes con `Decimal` y alcance por tenant.
   El cliente solo presenta el resultado.

## Consecuencias

- El endpoint de dashboard tributario agrega un resumen anual y doce cortes
  mensuales sin crear tablas ni migraciones.
- Una compra pendiente no reduce el resultado anual hasta que una persona la
  confirme como deducible.
- La vista ayuda a anticipar el cierre, pero no reemplaza el formulario anual,
  la contabilidad ni la revisión de un profesional.

## Referencias normativas

- SRI, [Crédito tributario y reclamos de devolución](https://www.sri.gob.ec/credito-tributario-y-reclamos-de-devolucion).
- SRI, [Devolución de pago indebido y pago en exceso de impuesto a la renta](https://www.sri.gob.ec/devolucion-de-pago-indebido-y-pago-en-exceso-de-impuesto-a-la-renta).
- SRI, [Devolución del IVA sobre retenciones en la fuente](https://www.sri.gob.ec/devolucion-del-iva-sobre-retenciones-en-la-fuente).
