# ADR 0018 — Identificaciones ATS y validación oficial antes de exportar

Fecha: 2026-10-27. Estado: aceptado para corregir el rechazo reportado;
publicación hasta producción autorizada en la sesión vigente.

## Problema

El ATS exportaba guiones en idCliente y deducía el tipo contando solo dígitos,
lo que podía perder la distinción de identificadores con letras. No validaba
el XML completo antes de guardarlo. El operador confirmó que el cliente del
rechazo es persona natural; esa confirmación no se infiere del número.

## Decisión

- Solo en la proyección ATS, quitar espacios ASCII y guiones de presentación.
  Preservar letras y números, sin rellenos ni truncamiento. La identificación
  resultante debe cumplir ASCII alfanumérico de 3 a 13 caracteres.
- Inferir RUC/cédula solo con cadena enteramente numérica ASCII de 13/10
  posiciones. Consumidor final se reconoce antes de RUC; no lleva parteRelVtas.
  Otros identificadores admitidos usan el código ATS extranjero correspondiente.
  Las identificaciones extranjeras puramente numéricas de 10/13 posiciones
  conservan una ambigüedad preexistente: el modelo no guarda el tipo XML.
- Agrupar ventas por ID normalizado, tipo de identificación y comprobante.
  Nunca cambiar el XML autorizado, el maestro ni el documento fuente.
- Para ventas de tipo 06, exigir tipoCliente confirmado (01 natural / 02 sociedad)
  y denoCli desde el nombre real del documento. Su representación ATS se
  translitera a ASCII; el nombre fuente permanece intacto.
- Guardar la clasificación en ats_customer_declarations, única por tenant e
  identificación, dentro de la misma UOW auditada e idempotente de generación.
  Solo se aceptan clientes extranjeros presentes en ventas del período propio.
  La UI consulta lo confirmado y lo reutiliza en otros períodos, sin adivinar.
- POST ATS admite foreignCustomerTypes. GET /tax/ats/customer-types exige
  tax:read y solo devuelve declaraciones del tenant autenticado. POST mantiene
  tax:write; actor, elecciones y solicitud quedan auditados.
- Validar el XML completo con la copia local del XSD oficial antes de ZIP,
  uploads o TaxAnnex. Si falla, 422 con campo/línea y sin valores fiscales;
  toda declaración nueva se revierte. No se resuelven entidades, DTD ni red.

## Fuente y límite

https://descargas.sri.gob.ec/download/anexos/ats/ats.xsd

La procedencia y SHA256 están en backend/app/services/tax/schemas/README.md.
Ficha ATS (sección Ventas, tablas 2/14):
https://descargas.sri.gob.ec/download/anexos/ats/FICHA_TECNICA_ATS_JULIO2016.pdf

El XSD comprueba estructura y formato; las condiciones de tipoCliente/denoCli
se validan además en el builder. Pasar XSD no prueba aceptación final del SRI.
No se modifica ni se presenta una declaración ante SRI con este cambio.

## Evidencia requerida

Fixtures sintéticos: guiones, espacios, letras con dígitos, consumidor final,
ID de tres letras, puntuación no admitida, agrupación canónica, conservación
fuente, clasificación persistente, tenant ajeno, reintentos y rollback sin
artefactos al fallar XSD. Migración reversible y validación PostgreSQL/CI antes
de publicar. La clasificación real se confirma en la sesión autenticada.
