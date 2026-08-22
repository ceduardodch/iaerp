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
