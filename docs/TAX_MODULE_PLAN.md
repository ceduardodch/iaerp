# Modulo tributario SRI — plan de trabajo y relevo

> Documento de **relevo**: cualquier persona o IA que retome este modulo debe
> leer esto y `docs/adrs/0012-tax-module-scope.md` antes de tocar codigo.
> Coordinacion general: [`COORDINACION_IA.md`](../COORDINACION_IA.md).

**Ultima actualizacion:** 2026-08-02

## Estado de git (leer antes de tocar)

- **Rama de trabajo: `feature/tax-module`** (autorizada por el usuario porque
  `release` estaba tomada por otra sesion y `main` es produccion).
- Sale de `main`; PR **draft #26** abierto contra `main`. No mergear todavia.
- ⚠️ **El CI no corre en ramas `feature`** (solo `develop`/`release`/`main`, por
  push o PR). La validacion se hace en local y en el PR.
- ⚠️ `main` ya venia con **CI en rojo** por `receivables-a11y.spec.ts`, ajeno a
  este modulo.
- Commits del modulo, en orden: `0e39cec` (E0), `335b732` (E1), `3511f7b` (E2
  lectores), `ff975f0` (E2 persistencia + E4 generador), `1c9573e` (E3 backend),
  `64c6bf2` (E3 pantalla).

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
| E1 | Fundacion (modelos + migracion + evidencia) | ✅ Hecho | 11 tablas en `models/tax.py` + migracion `e4f5a6b7c8d9`; `services/tax/{evidence,periods}.py`; `api/tax.py` con scopes `tax:read`/`tax:write`; 9 pruebas en `tests/test_tax_foundation.py` |
| E2 | Ingesta (XML/TXT + clasificacion) | ✅ Hecho | `sri_xml.py`, `txt_import.py`, `ingest.py` y el endpoint `POST /tax/evidence/{id}/ingest` |
| E3 | IVA (motor + campos copiar-pegar + pantalla) | ✅ Hecho | `iva.py` (trazabilidad por cifra), `form_fields.py` (seed 104 editable), endpoints y la seccion **Tributario** (`components/tax/TaxPage.tsx`, lazy) con carga de evidencia, periodos por anio, tabla copiar-y-pegar, resumen y documentos usados. 12 pruebas E2E |
| E4 | ATS (XML/ZIP + validacion + correcciones) | ✅ Generador hecho | `ats.py`: orden de nodos **identico** al ATS aceptado (verificado nodo a nodo), mes de dos digitos, umbral de forma de pago, ZIP con un solo XML y validador que detecta `__MACOSX`. Falta conectarlo a los datos del periodo y al ciclo de `SRIValidationIssue` |
| E5 | Tareas del asistente + docs de usuario | ⏳ Pendiente | Ninguna automatizacion envia ni paga |
| F | RDEP / ADI | 🚫 Bloqueado | RDEP requiere origen de datos de nomina/IESS (fuera del alcance actual) |

## Hallazgos de las muestras reales (2026-08-02)

El usuario entrego archivos reales de su RUC. **No se versionan** (traen RUC,
nombres, correos, telefonos y certificados X509 de terceros): en
`backend/tests/fixtures/sri/` viven equivalentes **anonimizados** con la misma
estructura. Lo aprendido:

1. **El TXT del portal es ISO-8859-1, no UTF-8.** Decodificarlo como UTF-8 falla
   ("Retenci�n"). `decode_portal_text` intenta UTF-8 y cae a latin-1.
2. **El nombre de la carpeta miente.** Un archivo dentro de "Diciembre 2025"
   contenia facturas emitidas el 11/11 y el 30/11. El periodo SIEMPRE sale de la
   fecha de emision del comprobante.
3. **El TXT no trae valores de las retenciones** (columnas vacias): esas filas se
   marcan `is_preliminary` con motivo y se pide el XML. No se inventan cifras.
4. **En la retencion, `codigo` distingue el concepto:** `1` = RENTA, `2` = IVA.
   Confirmado en un comprobante real (renta 2.75% cod. 3440 e IVA 70% cod. 2
   sobre la misma factura sustento).
5. **ATS y ADI usan raiz y orden DISTINTOS** (por eso los rechazos previos):
   - ATS: raiz `<iva>`, etiqueta `TipoIDInformante` (con "ID"), y `razonSocial`
     va **antes** de `Anio`/`Mes`.
   - ADI: raiz `<adi>`, etiqueta `TipoIdInformante` (con "Id"), y `razonSocial`
     va **despues** de `Mes`.
6. **`formasDePago` aparece solo sobre cierto monto** en `detalleCompras` (en las
   muestras, sobre ~500 USD); en `detalleVentas` viene siempre.
7. `detalleVentas` incluye `tipoEmision` y `numeroComprobantes` **despues** de el
   — los dos errores conocidos que reporto el usuario.
8. El ATS de 2025-07 trae `ivaComp` en `ventaEst` y el de 2026-04 no: el esquema
   cambia entre periodos, asi que el generador debe versionarse por vigencia.
9. **Umbral de `formasDePago` confirmado con datos reales**: en compras aparece
   sobre ~500 USD (sin el: 49.97 / 15.10 / 67.55 / 26.70; con el: 522.89 y
   5389.89). En ventas viene siempre.
10. **El ZIP del usuario venia con `__MACOSX/._AT-112025.xml`**: comprimir desde
    el Finder de macOS agrega metadatos y el SRI rechaza el anexo. El generador
    arma el ZIP entrada por entrada y `validate_ats_zip` detecta ese caso.
11. Los **emitidos** del usuario son PDF, no XML: las ventas del ATS deben salir
    de los comprobantes que IAERP emite (`SalesDocument`), no de esos PDF.

## Insumos que faltan (bloqueantes reales, los provee el usuario)

1. **Confirmar dos codigos del formulario 104.** El seed de `form_fields.py` los
   marca `needs_review` y la API los expone con `needsReview: true`:
   - **507** — hoy apunta a "total de adquisiciones y pagos".
   - **564** — hoy apunta a "IVA en adquisiciones / credito tributario".
   El **609** esta confirmado por el usuario (solo retencion de IVA recibida);
   401, 411, 500, 510 y 517 son los habituales. Todo es editable en
   `TaxFormFieldMap` sin tocar codigo.
2. **Ficha tecnica del ATS vigente** y su XSD si existe. Las dos muestras
   aceptadas fijan el orden de nodos, pero no cubren todos los casos (notas de
   credito, reembolsos, exportaciones, retenciones emitidas).
3. Muestras de **comprobantes emitidos en XML** y de **notas de credito**: los
   emitidos que entrego el usuario son PDF, asi que las ventas del periodo aun no
   se pueden conciliar desde evidencia descargada.

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

## Donde retomar (siguiente tarea concreta)

El modulo ya es usable de punta a punta: cargar evidencia -> ingerir -> ver el
IVA con valores para copiar. **Lo siguiente es conectar el ATS**, cuyo generador
ya existe y esta verificado, pero todavia no se alimenta de los datos reales.

**Tarea 1 — Conectar el ATS al periodo (cierra E4).**
1. Crear `services/tax/ats_builder.py` (o una funcion en `ats.py`) que arme el
   `AtsInput` desde los `FiscalDocument` del periodo:
   - `purchases` <- documentos `RECIBIDO` (factura/liquidacion/ND menos NC), con
     su desglose de `FiscalDocumentTax` en `base_zero_rate` / `base_taxed`.
   - `sales` <- documentos `EMITIDO`, **agrupados por cliente y tipo**, con
     `document_count` y las retenciones que le hicieron (`valorRetIva`,
     `valorRetRenta`) desde `FiscalRetention`.
   - `sales_by_establishment` <- suma por `establishment_code`.
2. Endpoint `POST /tax/periods/{id}/ats` que genere XML+ZIP, los suba con
   `storage.upload_private_object` y persista un `TaxAnnex` (usar
   `execute_idempotent`, como el resto de escrituras).
3. `GET /tax/annexes/{id}/download` con URL prefirmada.
4. Boton "Generar ATS" en `TaxPage.tsx` + descarga del ZIP.
5. `POST /tax/annexes/{id}/issues` para registrar los errores que devuelva el SRI
   (linea, columna, mensaje) en `SRIValidationIssue`, y mostrarlos en la pantalla
   con su estado de correccion.

**Tarea 2 — E5: tareas del asistente.** Generar `TaxTask` (revisar IVA, bajar
comprobantes, preparar anexo) desde el scheduler existente
(`workers/dispatcher.py`, patron de `collections.py`). **Ninguna automatizacion
envia, entrega ni paga**: todas nacen con `requires_approval=true`.

**Tarea 3 — Estado del periodo.** Hoy los periodos se quedan en
`PENDIENTE_DESCARGA`. Falta la transicion automatica a `EVIDENCIA_INCOMPLETA` /
`LISTO_REVISAR` segun haya comprobantes y si alguno es preliminar, y la accion
manual (con confirmacion) para marcar `DECLARADO`.

Notas utiles para quien retome:
- `.section-number` y `.kicker` estan **ocultas globalmente** por el rediseno
  (`index.css`): usa clases propias (`.tax-year-label`, `.tax-subhead`) en vez de
  reutilizarlas, o el texto no se vera.
- Las claves de `amounts` viajan en camelCase (`ventasBrutas`), igual que
  `sourceKey`, para poder cruzarlas desde el frontend.
- Los tests de evidencia mockean MinIO con el fixture `stored_objects`
  (`monkeypatch` sobre `evidence_service.storage.upload_private_object`), asi que
  corren sin Docker.
- Los campos de formulario multipart necesitan `alias` camelCase
  (`Form(alias="taxPeriodId")`); sin el, FastAPI los recibe como `None` en
  silencio.
- Sin Docker levantado fallan de forma pre-existente `test_health.py` y dos
  pruebas de receivables (flake de fecha `OVERDUE`/`PARTIAL`): no son de este
  modulo.

## Reglas de trabajo

- No commitear a `main` (produccion, Coolify despliega desde ahi) sin
  autorizacion explicita; ver politica de ramas en `AGENTS.md`.
- Nunca debilitar ni borrar tests para pasar el CI.
- Cerrar cada etapa con CI verde y actualizar la tabla de estado de este
  documento antes de dejar el trabajo.
