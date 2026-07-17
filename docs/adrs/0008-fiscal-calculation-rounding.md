# ADR 0008: Calculo fiscal y redondeo versionado

- Estado: Accepted
- Fecha: 2026-07-02 (propuesto), 2026-07-04 (aceptado con reglas verificadas por
  el Ecuador SRI Expert)

## Contexto

Definir `Decimal` y precision de base de datos no determina el orden de
descuentos, base imponible, IVA, cuantizacion por linea ni reconciliacion entre
XML, PDF y total. Una diferencia minima puede producir rechazo SRI (error 52
"Error en diferencias", validado en fase de AUTORIZACION) o saldos
inconsistentes.

Fuente primaria verificada: Ficha Tecnica de Comprobantes Electronicos Esquema
Offline del SRI (se reviso el texto completo de la version 2.26; el portal SRI
publica como vigente la version 2.32, noviembre 2025, con esquemas XSD de
factura 1.0.0/1.1.0/2.0.0/2.1.0 y nota de credito 1.0.0/1.1.0, actualizados a
febrero 2022). Datos confirmados en la ficha:

- Numeral 8.17: todo campo de valores usa formato `123456.98` con punto como
  separador y maximo dos decimales, excepto `precioUnitario` y `cantidad`, que
  admiten hasta 6 decimales en la version 1.1.0 de comprobantes (Anexo 3).
- Preguntas frecuentes de la ficha: version 1.0.0 admite 2 decimales; version
  1.1.0 admite 6 en cantidad y precio unitario.
- Tabla 17 (tarifa del IVA): 0% -> codigo 0; 12% -> 2; 14% -> 3; 15% -> 4;
  5% -> 5; No objeto -> 6; Exento -> 7; IVA diferenciado -> 8; 13% -> 10.
- Formato XML de factura: por linea `cantidad`, `precioUnitario`, `descuento`,
  `precioTotalSinImpuesto` e `impuestos` (codigo, codigoPorcentaje, tarifa,
  baseImponible, valor); en cabecera `totalSinImpuestos`, `totalDescuento`,
  `totalConImpuestos` (un `totalImpuesto` por tarifa), `propina` e
  `importeTotal`.
- Formato XML de nota de credito: `codDocModificado`, `numDocModificado`,
  `fechaEmisionDocSustento`, `totalSinImpuestos`, `valorModificacion` y nota
  explicita: "La tarifa de IVA correspondera a la fecha de emision del
  documento de sustento".
- El ejemplo oficial de `descuentoAdicional` calcula el `valor` del grupo sobre
  la base ya descontada ((309750.00 - 5.00) x 12% = 37169.40), lo que confirma
  que el `valor` de cada `totalImpuesto` se calcula a nivel de grupo, no como
  suma de valores por linea.

Tarifas vigentes a 2026-07-04: IVA general 15% (codigo 4) desde 2024-04-01
(Decreto Ejecutivo 198; mantenido por Decreto Ejecutivo 470 y, para 2026, por
la regla de supervivencia del Decreto Ejecutivo 213 confirmada por la circular
SRI NAC-DGECCGC25-00000006). IVA 5% (codigo 5) para transferencia local de
materiales de construccion del listado de la Resolucion NAC-DGERCGC24-00000013,
vigente desde 2024-04-01. IVA 0% (codigo 0) para bienes y servicios de los
articulos 55 y 56 de la LRTI.

Limite declarado: la ficha tecnica define formatos, campos y la existencia de
la validacion de diferencias, pero no publica el algoritmo de redondeo ni la
tolerancia exacta del validador. El modo `ROUND_HALF_UP` se adopta como
politica interna: es el redondeo comercial estandar, es consistente con los
ejemplos numericos de la ficha y elimina la dependencia de una tolerancia no
documentada porque cada campo declarado se deriva de una unica regla.

## Decision

Crear un `FiscalCalculationPolicy` inmutable y versionado por vigencia. La
version `ec-iva-v1` (vigencia desde 2024-04-01) implementa las reglas de abajo.
La misma version calcula backend, XML, PDF, migracion y pruebas. El frontend
solo muestra el resultado. Cambiar una regla o tarifa crea una nueva version
con fecha de vigencia; nunca se recalculan documentos autorizados.

Toda la aritmetica usa Python `Decimal` con contexto de 28 digitos. Los `float`
estan prohibidos en cualquier punto del calculo o serializacion (ADR 0004).

### 1. Orden de cantidad, precio y descuento (por linea)

1. Entradas: `cantidad` y `precioUnitario` se cuantizan al ingresar a
   `Decimal("0.000001")` con `ROUND_HALF_UP` (maximo 6 decimales, esquema
   1.1.0/2.1.0); `descuento` es un valor absoluto en moneda, cuantizado a
   `Decimal("0.01")` con `ROUND_HALF_UP`. Los descuentos porcentuales de UI se
   convierten a valor absoluto antes de entrar a la politica.
2. `bruto = cantidad * precioUnitario` sin cuantizar (precision intermedia
   completa).
3. `precioTotalSinImpuesto = (bruto - descuento).quantize(Decimal("0.01"),
   ROUND_HALF_UP)`. Este es el unico punto de redondeo de la linea y no puede
   ser negativo (`descuento <= bruto`).
4. `baseImponible` de la linea = `precioTotalSinImpuesto`.
5. `valor` de IVA por linea = `(baseImponible * tarifa / 100)
   .quantize(Decimal("0.01"), ROUND_HALF_UP)`. Se declara en el bloque
   `impuestos` del detalle y es informativo: los totales del documento nunca se
   derivan de el.

`descuentoAdicional` de cabecera no se usa en `ec-iva-v1`: todo descuento se
registra por linea. Asi cada `baseImponible` de grupo es exactamente la suma de
bases por linea y `totalDescuento` es la suma de descuentos por linea.

### 2. Base imponible por tarifa (agregacion)

Las lineas se agrupan por `(codigo, codigoPorcentaje)` (tabla 16 y tabla 17).
Para cada grupo:

- `baseImponible` del grupo = suma exacta de los `precioTotalSinImpuesto` de
  sus lineas. No se re-redondea: es suma de valores ya cuantizados a 2
  decimales.
- `valor` del grupo = `(baseImponible * tarifa / 100).quantize(Decimal("0.01"),
  ROUND_HALF_UP)`. Se recalcula sobre la base agregada; NO es la suma de los
  `valor` por linea (pueden diferir en centavos, ver vector 3). Esta es la
  regla que el validador del SRI aplica sobre `totalImpuesto`, confirmada por
  el ejemplo oficial de `descuentoAdicional`.

### 3. Totales del documento

- `totalSinImpuestos` = suma exacta de `precioTotalSinImpuesto` de todas las
  lineas (equivale a la suma de bases de todos los grupos).
- `totalDescuento` = suma exacta de `descuento` por linea.
- `propina` se cuantiza a 2 decimales; en B2B se emite `0.00`.
- `importeTotal = totalSinImpuestos + suma(valor de cada grupo) + propina`.
  Suma exacta de cantidades ya cuantizadas; no hay redondeo final adicional.
- Serializacion XML: `cantidad` y `precioUnitario` con hasta 6 decimales; todo
  otro campo de valores con exactamente 2 decimales y punto decimal (numeral
  8.17). Nunca notacion cientifica ni separador de miles.

### 4. Precision intermedia y cuantizacion (resumen normativo)

| Punto | Regla |
|---|---|
| Contexto Decimal | 28 digitos, sin cuantizar productos intermedios |
| `cantidad`, `precioUnitario` | `quantize(0.000001, ROUND_HALF_UP)` al ingresar |
| `precioTotalSinImpuesto` (linea) | `quantize(0.01, ROUND_HALF_UP)` |
| `valor` IVA por linea (informativo) | `quantize(0.01, ROUND_HALF_UP)` |
| `baseImponible` por grupo | suma exacta, sin re-redondeo |
| `valor` por grupo | base agregada x tarifa, `quantize(0.01, ROUND_HALF_UP)` |
| `importeTotal` | suma exacta, sin re-redondeo |

Unico modo de redondeo permitido: `decimal.ROUND_HALF_UP`. Queda prohibido
`ROUND_HALF_EVEN` (default de `decimal`) y cualquier redondeo implicito de
`float`.

### 5. Notas de credito (esquema 1.1.0)

- Misma politica y misma version de `FiscalCalculationPolicy` que el documento
  de sustento cuando las tarifas difieren por vigencia: la tarifa y el
  `codigoPorcentaje` de la nota de credito son los vigentes a la
  `fechaEmisionDocSustento`, no a la fecha de emision de la NC (regla textual
  de la ficha tecnica). Ejemplo: sustento de marzo 2024 con 12% (codigo 2) se
  acredita al 12% aunque la NC se emita en 2026.
- NC parcial: se construye por lineas, con la cantidad devuelta, el
  `precioUnitario` original del sustento y el descuento original prorrateado
  por cantidad devuelta (`descuento_nc = (descuento_original * cantidad_devuelta
  / cantidad_original).quantize(0.01, ROUND_HALF_UP)`). Luego aplican las
  reglas 1-3 identicas a factura.
- `valorModificacion` = `importeTotal` de la NC.
- Control de saldo: la suma de `valorModificacion` de todas las NC autorizadas
  de un sustento no puede exceder el `importeTotal` del sustento; se valida
  antes de firmar. La NC referencia `codDocModificado`, `numDocModificado` y la
  autorizacion del sustento (perfil del Ecuador SRI Expert).

### 6. Tarifas vigentes en `ec-iva-v1`

| codigoPorcentaje (tabla 17) | Tarifa | Vigencia | Uso IAERP |
|---|---|---|---|
| 0 | 0% | permanente | Bienes/servicios tarifa 0 (LRTI art. 55/56) |
| 4 | 15% | desde 2024-04-01 | Tarifa general |
| 5 | 5% | desde 2024-04-01 | Materiales de construccion del listado NAC-DGERCGC24-00000013 |
| 2 | 12% | hasta 2024-03-31 | Solo NC sobre sustentos historicos |
| 6 / 7 | No objeto / Exento | permanente | Fuera de alcance v1; base sin `valor` |

## Vectores de prueba

Obligatorios en la suite de la politica (`ec-iva-v1`). `cp` =
`codigoPorcentaje`. Montos en USD, 2 decimales.

| # | Caso | Lineas (cantidad x precioUnitario - descuento, cp) | precioTotalSinImpuesto por linea | baseImponible por grupo | valor IVA por grupo | importeTotal |
|---|---|---|---|---|---|---|
| 1 | Linea simple 15% | 2 x 50.00 - 0.00, cp 4 | 100.00 | 100.00 | 15.00 | 115.00 |
| 2 | Descuento + 6 decimales | 3.5 x 9.333333 - 1.17, cp 4 | 31.50 (31.4966655 -> half-up) | 31.50 | 4.73 (4.7250 -> half-up) | 36.23 |
| 3 | Redondeo linea vs total, misma tarifa | 3 lineas de 1 x 1.05 - 0.00, cp 4 | 1.05 / 1.05 / 1.05 (valor por linea informativo 0.16 c/u) | 3.15 | 0.47 (0.4725 -> 0.47; suma por linea daria 0.48) | 3.62 |
| 4 | Tarifa 0% | 4 x 12.25 - 0.00, cp 0 | 49.00 | 49.00 | 0.00 | 49.00 |
| 5 | Mezcla de tarifas | 1 x 100.00 cp 4; 2 x 25.00 cp 0; 10 x 8.457 cp 5 | 100.00 / 50.00 / 84.57 | 100.00 (cp 4), 50.00 (cp 0), 84.57 (cp 5) | 15.00 / 0.00 / 4.23 (4.2285 -> half-up) | 253.80 |
| 6 | NC parcial, tarifa vigente | Sustento: 10 x 3.14 cp 4 (importeTotal 36.11). NC devuelve 3 unidades | 9.42 | 9.42 | 1.41 (1.4130 -> 1.41) | valorModificacion 10.83 |
| 7 | NC parcial, tarifa historica del sustento | Sustento 2024-03-15: 5 x 20.00 cp 2 (12%, importeTotal 112.00). NC 2026 devuelve 2 unidades | 40.00 | 40.00 | 4.80 al 12% (cp 2, tarifa del sustento) | valorModificacion 44.80 |

Asserts adicionales del vector 3: el XML declara `valor` 0.16 en cada detalle y
0.47 en `totalImpuesto`; `importeTotal` debe ser 3.62 y nunca 3.63. Assert del
vector 6/7: la suma de `valorModificacion` de las NC del sustento no excede su
`importeTotal`.

## Fuentes

- Ficha Tecnica de Comprobantes Electronicos Esquema Offline, SRI (texto
  completo revisado en la version 2.26; numeral 8.17, tablas 16/17, formatos
  XML de factura y nota de credito, codigos de error 35/52):
  https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/ed555352-46c7-4917-9f61-011b6a9f4600/FICHA%20TE%CC%81CNICA%20COMPROBANTES%20ELECTRO%CC%81NICOS%20ESQUEMA%20OFFLINE%20Versio%CC%81n%202.26.pdf
- Portal de facturacion electronica del SRI (ficha vigente 2.32 de noviembre
  2025; XSD factura 1.0.0-2.1.0 y nota de credito 1.0.0-1.1.0):
  https://www.sri.gob.ec/facturacion-electronica
- Resolucion NAC-DGERCGC24-00000013 (listado de materiales de construccion con
  IVA 5%, vigente desde 2024-04-01):
  https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar?id=6b8588f2-a4bf-44bb-ac40-085391ba2aed&nombre=NAC-DGERCGC24-00000013.pdf
- Decreto Ejecutivo 198 (IVA 15% desde 2024-04-01):
  https://www.ey.com/es_ec/technical/tax/tax-alerts-ecuador/decreto-ejecutivo-no--198-tarifa-de-iva--15-
- Vigencia del 15% en 2026 (circular SRI NAC-DGECCGC25-00000006 y Decreto
  Ejecutivo 213):
  https://www.eluniverso.com/noticias/economia/iva-tarifa-15-sri-circular-2025-nota/
- Impuesto al Valor Agregado, SRI:
  https://www.sri.gob.ec/impuesto-al-valor-agregado-iva

## Consecuencias

- Sprint 2 queda desbloqueado: las reglas numericas son deterministas y
  reproducibles en backend, XML, PDF y pruebas.
- Los siete vectores son el contrato de regresion de `ec-iva-v1`; cualquier
  refactor del motor debe pasarlos byte a byte en la serializacion XML.
- Cambiar una tarifa o una regla crea una version nueva con fecha de vigencia
  (ejemplo: si un decreto modifica la tarifa general, se agrega la vigencia a
  la tabla y nace `ec-iva-v2`); no se reescriben documentos historicos ni
  autorizados.
- Las notas de credito exigen conservar la version de politica y las tarifas
  del documento de sustento; el modelo de datos debe guardar
  `fiscal_policy_version` por documento.
- Si el SRI publica una tolerancia o algoritmo de redondeo explicito que
  contradiga `ROUND_HALF_UP`, se abre revision de este ADR con nueva version de
  politica; mientras tanto ningun componente puede redondear fuera de los
  puntos definidos en la seccion 4.
