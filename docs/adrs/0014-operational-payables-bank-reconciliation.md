# ADR 0014: CxP operativa y conciliación bancaria compartida

- Estado: Proposed
- Fecha: 2026-08-05

## Contexto

IAERP ya concilia los créditos de un TXT bancario con CxC, pero descarta los
débitos. Las compras fiscales existen en Tributario, mientras los gastos sin
factura, las obligaciones, los pagos y el movimiento del banco no tienen un
modelo común. Mezclar esos hechos limitaría el registro diario y podría dar a
un débito un efecto fiscal que no está respaldado.

## Decisión

Se crea una CxP operativa que separa cuatro hechos: compra u obligación, pago,
movimiento bancario y evidencia fiscal.

1. Una compra puede quedar `PAID_NOW` o `PAY_LATER`. Proveedor y factura son
   opcionales; total y movimientos usan `NUMERIC`/`Decimal`.
2. Una CxP abierta admite abonos, cuotas, retenciones, notas de crédito y
   reversos. Los reversos agregan un movimiento; no borran historia.
3. El lector bancario conserva `CREDIT` y `DEBIT`. El mismo archivo y registro
   de importación alimentan CxC y CxP.
4. Un cruce exacto y único puede quedar preseleccionado, pero solo la
   confirmación con permiso, idempotencia y auditoría escribe movimientos.
5. Un reparto manual puede aplicar un débito a varias CxP sin superar el monto
   bancario ni el saldo de cada obligación.
6. Si el pago ya existe, el banco enlaza evidencia sin crear otro pago.
7. Reglas por texto, cuenta y monto solo preparan un gasto. Una persona confirma
   proveedor, categoría y clasificación.
8. Transferencias internas, liquidaciones de tarjeta, comisiones, impuestos y
   reversos bancarios se clasifican aparte para evitar falsos gastos.
9. Un débito prueba el pago, pero no reemplaza XML, factura o retención. Sin XML
   válido no hay crédito IVA ni ATS; una compra nueva queda deducible pendiente
   de revisión hasta validar su soporte.
10. REST y MCP llaman los mismos servicios de aplicación y siempre obtienen el
    `tenant_id` de la identidad autenticada.

Esta fase no crea asientos de partida doble ni inicia transferencias bancarias.

## Consecuencias

- Compras deja de ser solo una lectura fiscal y suma vistas operativas: todas,
  por pagar, pagadas, conciliación e historial.
- Tributario sigue siendo la fuente del efecto fiscal. La CxP enlaza su
  documento, pero no copia ni inventa valores fiscales.
- El registro bancario compartido impide usar el mismo movimiento en CxC y CxP.
- Los formatos de otros bancos se añaden detrás de la interfaz del lector; la
  primera versión conserva el TXT que ya usa Banco Bolivariano.

## Alternativas descartadas

- **Crear gastos definitivos desde cada débito:** no distingue transferencias,
  tarjeta, impuestos ni movimientos internos y daría soporte fiscal falso.
- **Exigir factura para todo gasto:** impide el registro simple de gasolina y
  otros pagos directos.
- **Guardar CxP dentro de Tributario:** mezcla saldo operativo con evidencia y
  estado fiscal.
- **Hacer un segundo importador bancario:** permitiría duplicar movimientos y
  repetiría reglas de idempotencia, permisos y auditoría.
