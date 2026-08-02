# Modulo tributario SRI — plan de trabajo y relevo

> Documento de **relevo**: cualquier persona o IA que retome este modulo debe
> leer esto y `docs/adrs/0012-tax-module-scope.md` antes de tocar codigo.
> Coordinacion general: [`COORDINACION_IA.md`](../COORDINACION_IA.md).

**Ultima actualizacion:** 2026-07-23

## Que es

Preparar declaraciones y anexos del SRI **desde evidencia real** (XML
autorizados, TXT del portal, PDF, reportes): guardarla por entidad/RUC/periodo
con hash, conciliarla, y entregar valores listos para declarar (tabla copiar y
pegar) y anexos XML/ZIP, sabiendo siempre que falta y de que documento sale cada
numero.

Las reglas vinculantes (no inventar valores, carga manual, PDF solo evidencia,
aprobacion humana, formato `1234.56`, claves solo por referencia a vault) estan
en el **ADR 0012** y no se cambian sin un ADR nuevo.

## Estado de las etapas

| # | Etapa | Estado | Notas |
|---|-------|--------|-------|
| E0 | ADR + alcance | ✅ Hecho | ADR 0012; `02-scope-and-restrictions.md` y `00-product-vision.md` actualizados |
| E1 | Fundacion (modelos + migracion + evidencia) | ⏳ Pendiente | `models/tax.py`, migracion, `POST /tax/evidence`, `GET /tax/periods` |
| E2 | Ingesta (XML/TXT + clasificacion) | ⏳ Pendiente | Extraer `sri_xml.py` compartido y extenderlo |
| E3 | IVA (motor + campos copiar-pegar + pantalla) | ⏳ Pendiente | Necesita confirmar codigos del F104 vigentes |
| E4 | ATS (XML/ZIP + validacion + correcciones) | 🚫 Bloqueado | Falta ficha tecnica/XSD vigente + una muestra aceptada por el SRI |
| E5 | Tareas del asistente + docs de usuario | ⏳ Pendiente | Ninguna automatizacion envia ni paga |
| F | RDEP / ADI | 🚫 Bloqueado | RDEP requiere origen de datos de nomina/IESS (fuera del alcance actual) |

## Insumos que faltan (bloqueantes reales, los provee el usuario)

1. **Muestras reales anonimizadas**: XML autorizados (factura, nota de credito,
   retencion), un TXT del portal y **un ATS XML aceptado por el SRI** (referencia
   del orden exacto de nodos).
2. **Ficha tecnica del ATS vigente** y su XSD si existe. No estan en el repo y el
   esquema cambia entre periodos; sin eso el generador se construiria a ciegas.
3. **Codigos del formulario 104 vigentes** (401, 411, 500, 510, 507, 517, 564,
   609): van en `TaxFormFieldMap`, configurables por vigencia, nunca en codigo.

## Que se reutiliza (no rehacer)

| Necesidad | Donde ya existe |
|---|---|
| Parseo del sobre SRI autorizado (`autorizacion` + comprobante interno) | `backend/app/services/receivables.py` (`_parse_authorized_retention_xml`), con `safe_fromstring` (defusedxml) |
| Guardar/leer archivos privados con checksum | `backend/app/services/storage.py`: `upload_private_object`, `download_artifact`, `generate_presigned_download_url` |
| Emitidos propios y su XML autorizado | `SalesDocument`, `SRITransmission`, `DocumentArtifact` (`models/billing.py`) |
| Entidad fiscal (un RUC por tenant, ADR 0007) | `Tenant.ruc` (`models/platform.py`) |
| Tarifas IVA con vigencia (12% -> 15%) | `tax_categories` (`sri_code`, `rate`, `valid_from`, `valid_to`) en `models/masters.py` |
| Auditoria e idempotencia | `append_audit`, `execute_idempotent` (`services/unit_of_work.py`) |
| Subida de archivo por API (`UploadFile` + `Form` + idempotencia) | `POST /organization/signing-certificate` en `api/router.py` |
| Tareas programadas | `workers/dispatcher.py`, patron `run_collection_scheduler` en `workers/collections.py` |

**No existe:** comprobantes **recibidos** (compras). Se construyen desde la
evidencia importada; IAERP no tiene payables.

## Diseno acordado

### Modelos (`backend/app/models/tax.py`, todos tenant-scoped)

`TenantTaxProfile` (perfil fiscal 1:1 con tenant, `vault_ref` sin claves) ·
`TaxPeriod` (entidad/anio/mes/obligacion/estado/fecha limite) · `FiscalDocument`
(EMITIDO/RECIBIDO, tipo, clave de acceso, `issue_date` real, contraparte,
`is_preliminary`, vinculo opcional a `SalesDocument`) · `FiscalDocumentTax`
(base, tarifa, codigo IVA, valor, base 0/exento/no objeto) · `FiscalRetention`
(`IVA` y `RENTA` siempre separados) · `TaxEvidence` (archivo, tipo, sha256,
`object_key`, origen; unico por tenant+sha256) · `TaxReturnDraft` ·
`TaxFormFieldMap` (configurable por formulario y vigencia; marca "para pegar" vs
"solo control") · `TaxAnnex` · `SRIValidationIssue` (linea, columna, mensaje,
estado) · `TaxTask`.

Estados de `TaxPeriod`: `PENDIENTE_DESCARGA` -> `EVIDENCIA_INCOMPLETA` ->
`LISTO_REVISAR` -> `LISTO_DECLARAR` -> `DECLARADO`.

### Servicios (`backend/app/services/tax/`)

`sri_xml.py` (parseo compartido, extraido de receivables y extendido a factura,
NC, ND y liquidacion) · `ingest.py` (hash, dedupe, ZIP, clasificacion por
**fecha real de emision**) · `txt_import.py` (si no separa mixtas: preliminar +
faltante) · `iva.py` (motor con trazabilidad por cifra; 609 solo retencion de
IVA) · `ats.py` (orden de nodos, mes con dos digitos, ZIP con un solo XML en
raiz) · `formatting.py` (`Decimal` -> `"1234.56"`).

### API (`backend/app/api/tax.py`, prefijo `/tax`, scopes `tax:read`/`tax:write`)

`POST /tax/evidence` · `GET /tax/periods` · `GET /tax/periods/{id}/summary` ·
`GET /tax/periods/{id}/iva` · `POST /tax/periods/{id}/ats` ·
`GET /tax/annexes/{id}/download` · `POST /tax/annexes/{id}/issues`.

### Frontend (`frontend/src/components/tax/`, seccion "08 Tributario")

Cargada con `React.lazy` (patron del CRM). Selector de entidad y periodo,
tarjetas por obligacion, tabla copiar-y-pegar (distinguiendo "para pegar" de
"solo control"), documentos usados, faltantes y errores del SRI, agrupado por
anio. Reutiliza `ErpPanel`, `ErpStatusBadge`, `ErpEmptyState` y el patron de
`InvoiceSpreadsheet.tsx`.

## Verificacion de cada etapa

- Backend: `cd backend && uv run --frozen pytest tests/test_tax_*.py -q`, mas
  `ruff`, `mypy` y `bandit` (todo XML externo con `defusedxml`).
- Frontend: `npm run build`, `npm run lint`, spec Playwright mockeado siguiendo
  `frontend/tests/invoice-spreadsheet.spec.ts`.
- Casos obligatorios: IVA con notas de credito, mixtas marcadas preliminares,
  retencion IVA vs renta separadas, dedupe por hash, asignacion por fecha real
  de emision, formato `1234.56`, y ZIP del ATS con **un solo XML en la raiz**.
- Validacion final del usuario: cargar un mes real, comparar contra la
  declaracion hecha a mano y subir el ATS generado al portal.

## Reglas de trabajo

- No commitear a `main` (produccion, Coolify despliega desde ahi) sin
  autorizacion explicita; ver politica de ramas en `AGENTS.md`.
- Nunca debilitar ni borrar tests para pasar el CI.
- Cerrar cada etapa con CI verde y actualizar la tabla de estado de este
  documento antes de dejar el trabajo.
