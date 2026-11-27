# ADR 0012: Modulo tributario Ecuador (declaraciones y anexos SRI)

- Estado: Accepted
- Fecha: 2026-07-23

## Contexto

IAERP emite comprobantes electronicos y los transmite al SRI, pero no ayuda a
**declarar**. La preparacion mensual del IVA (formulario 104) y del ATS se hace
fuera del sistema, cruzando a mano XML autorizados, TXT del portal, PDF de
retenciones y reportes. Ese trabajo es repetitivo, propenso a error y no deja
trazabilidad de que documento respalda cada cifra declarada.

`docs/02-scope-and-restrictions.md` y `docs/00-product-vision.md` listaban
"Declaraciones tributarias y anexos" como **fuera del MVP**. Este ADR revierte
esa exclusion de forma explicita, porque preparar la declaracion es hoy el
trabajo manual mas costoso del usuario y el sistema ya custodia la mayor parte
de la evidencia (comprobantes emitidos, XML autorizados, retenciones).

## Decision

Se incorpora un **modulo tributario** que recibe evidencia real, la concilia por
entidad/RUC/periodo y produce valores listos para declarar y anexos XML/ZIP.

Reglas vinculantes del modulo:

1. **La fuente de verdad son documentos reales.** XML autorizados, TXT del SRI,
   PDF y reportes del portal. El sistema **no inventa** valores, autorizaciones,
   formas de pago, retenciones ni datos de terceros. Si falta soporte, el dato se
   marca preliminar y se reporta como faltante.
2. **Carga manual del listado y recuperación oficial por clave.** El usuario
   descarga del portal el listado mensual TXT, porque el SRI no ofrece un API
   pública para enumerar todos los comprobantes recibidos. Con las claves de
   acceso que ya constan en esa evidencia, IAERP puede consultar el servicio
   oficial `autorizacionComprobante` y custodiar el XML autorizado que este
   devuelva. No se automatiza ni se raspa el portal y no se guarda su clave.
   Las respuestas ausentes quedan pendientes para reintento o carga manual.
3. **Los PDF son solo evidencia.** Se guardan con hash y vinculo al documento,
   pero los valores se toman del XML/TXT. No se hace OCR: extraer cifras de un
   PDF de formato variable contradice la regla de no inventar valores.
4. **Trazabilidad por cifra.** Todo valor declarado expone los documentos que lo
   componen. Todo archivo se guarda por entidad, RUC, anio, mes, tipo de
   obligacion, archivo fuente, fecha de carga, origen y hash.
5. **Las claves nunca se guardan en la base.** Solo una referencia a vault
   (1Password, Bitwarden o variable segura), coherente con el ADR 0005.
6. **Toda accion sensible exige aprobacion humana**: declarar, entregar anexo,
   pagar, aceptar deuda o cerrar tramite. Ninguna automatizacion envia ni paga.
7. **IVA mensual y renta anual no se mezclan.** La retencion de IVA recibida
   (campo 609) es distinta de la retencion de renta, que se reserva para la
   conciliacion/renta anual.
8. **El mapa de campos del formulario es configurable** por formulario y
   vigencia, no codificado. Cada campo se marca como "para pegar" o "solo
   control" para no pisar los valores que el SRI autocalcula.
9. **Formato de salida fijo** para copiar al formulario: punto decimal, dos
   decimales, sin separador de miles (`1234.56`).
10. **IVA presentado y proyección no se mezclan.** `DECLARADO` es el estado del
    periodo IVA: permite mostrar un corte documental de esos meses, pero no
    prueba una declaración anual de renta ni congela sus cifras. La evidencia de
    meses abiertos alimenta una proyección separada. Una referencia de impuesto
    a la renta exige que el usuario elija el escenario y debe indicar tarifa,
    supuestos y ajustes no incluidos; nunca se infiere la tarifa por el RUC.

Alcance por etapas: fundacion + ingesta + IVA + ATS primero; RDEP y ADI despues.
**RDEP queda bloqueado** hasta definir el origen de los datos de nomina/IESS,
que hoy estan fuera del alcance del producto.

## Consecuencias

### Retención bancaria de ISD (2026-11-26)

Un comprobante autorizado de tipo 07 puede incluir el impuesto a la salida de
divisas (código de impuesto 6). Tributario registra su código de retención, base,
porcentaje y valor según cada línea del XML, incluso cuando el sustento es
«OTROS» y carece de número de factura. El total documental incluye el ISD. El
resumen lo presenta por separado de los importes de IVA y de renta. Su registro
no genera automáticamente un crédito fiscal, una compra ni un abono de cartera.
En comprobantes mixtos, solo las líneas de IVA y renta respaldadas por una
factura pueden aplicarse a su saldo. Una categoría desconocida requiere revisión
del documento completo. La reingesta de su XML autorizado permite corregir el
detalle de un registro histórico usando la misma clave de acceso.

Referencia: [ficha técnica SRI 2.34, tablas 19 y 20](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/f8d9bb36-5632-4f96-b463-b9265b55338c/FICHA%20TE%CC%81CNICA%20COMPROBANTES%20ELECTRO%CC%81NICOS%20ESQUEMA%20OFFLINE%20Versio%CC%81n%202.34.pdf).

### Cruce documental de retenciones con Cartera (2026-10-13)

El XML autorizado de una retención recibida también respalda un movimiento
comercial `RETENTION`: rebaja el saldo, nunca registra ingreso en dinero. Se
exigen el tenant receptor, el emisor que corresponde al cliente, el número
completo y el tipo de factura autorizada. Se aplica una sola vez por
autorización y factura, bajo el bloqueo de Cartera y con auditoría.

Un conflicto comercial no elimina ni invalida la evidencia tributaria. Si la
cuenta está saldada, anulada, tiene una aplicación diferente o un reverso, el
cruce queda pendiente; no se altera un cobro anterior. Los históricos se
reconcilian con una escritura explícita y autorizada, no mediante un GET.

La conciliación bancaria compara el depósito con el neto respaldado. Su
vista previa calcula el cruce dentro de un savepoint y lo revierte completo:
no guarda movimientos ni auditoría hasta que el usuario confirma. El registro
vuelve a validar el neto actual, sin inferir una retención por una diferencia
de importes ni modificar el XML autorizado.

- `Tenant` sigue siendo la entidad fiscal (un RUC por tenant, ADR 0007). El
  perfil tributario se agrega en una tabla aparte para no modificar `Tenant`.
- Aparecen los **comprobantes recibidos (compras)**, que el sistema no modelaba:
  se construyen desde la evidencia importada, no desde captura manual.
- El parseo del sobre SRI que hoy vive en `services/receivables.py` se extrae a
  un modulo compartido y se extiende a factura, nota de credito, nota de debito
  y liquidacion. El comportamiento actual de retenciones no cambia.
- Todo XML de origen externo se parsea con `defusedxml` (ver ADR 0005 y el
  control de bandit B314 ya aplicado en el cliente SOAP del SRI).
- El generador ATS depende de la **ficha tecnica y el XSD vigentes del SRI**, que
  no viven en el repositorio y cambian entre periodos. Sin esa referencia, el
  anexo no se construye a ciegas.

## Alternativas descartadas

- **Automatizar el portal del SRI** para listar o descargar comprobantes:
  rechazada por fragilidad, custodia de credenciales y riesgo respecto a los
  términos de uso. Esto no impide consultar el web service oficial de
  autorización para una clave de acceso ya aportada por el usuario.
- **OCR de PDF** para extraer valores: rechazada porque introduce cifras sin
  respaldo verificable y contradice la regla 1.
- **Calcular la declaracion desde los datos internos de facturacion**: rechazada
  como fuente unica; los emitidos propios se reconcilian contra su XML
  autorizado, y las compras solo existen como evidencia recibida.

### Compras de servicios digitales al exterior

Compras conserva por separado emisión, vencimiento y pagos. El usuario identifica el servicio importado al crear la compra o al revisar una existente. Los registros anteriores requieren clasificación expresa. La fecha efectiva y el importe de cada pago vigente determinan el mes y la base comercial que Tributario muestra para revisión. La factura extranjera y una transferencia acreditan la operación comercial. Para sustentar el tratamiento del IVA se revisan la liquidación, el comprobante de retención o percepción y el derecho a crédito que corresponda.

El formulario 104 muestra en el casillero 731 las retenciones de IVA del 100 % respaldadas por XML autorizado que emitió el contribuyente. Un ISD recibido se conserva en su propio comprobante. La liquidación emitida como comprador queda fuera de ventas y de cartera. Mientras se requiera conciliar la importación, el 104 interno es parcial y el ATS se prepara externamente. Al archivar el acuse de IVA del período se conserva la evidencia del cierre externo. La presentación del ATS se verifica por separado.

Fuentes: [Reglamento, artículo 146.1](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/03995ac1-408a-4694-b24c-447d93774c52/3.1%20REGLAMENTO%20A%20LA%20LRTI.pdf), [servicios digitales, SRI](https://www.sri.gob.ec/ley-organica-de-simplificacion-y-progresividad-tributaria), [guía de la declaración de IVA](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/e084fae5-9677-450c-8161-21e7c3a9f65b/Gu%C3%ADa%20para%20el%20llenado%20del%20Formulario%20Impuesto%20al%20Valor%20Agregado%20IVA.PDF).
