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

## ⚠️ Accion requerida en Keycloak de produccion

El modulo exige los scopes `tax:read` y `tax:write`. Estaban declarados en el
modo dev (`ALL_DEV_SCOPES`, `api/router.py`) pero **faltaban en el realm**, asi
que en produccion la seccion Tributario responde `Missing scopes: tax:write`.

`infra/keycloak/iaerp-realm.json` ya quedo corregido (scopes del realm +
`defaultClientScopes` de `iaerp-web`). Como la instancia de produccion **no se
reimporta**, hay que aplicarlo a mano una sola vez:

1. Consola admin de Keycloak → realm **iaerp** → **Client scopes** → *Create*:
   - Nombre `tax:read`, protocolo `openid-connect`, tipo **None**.
   - En *Settings*, activar **Include in token scope**; desactivar *Display on
     consent screen*.
   - Repetir con `tax:write`.
2. **Clients** → `iaerp-web` → pestaña **Client scopes** → *Add client scope* →
   seleccionar `tax:read` y `tax:write` → agregar como **Default**.
3. Cerrar sesion en IAERP y volver a entrar (el token se emite de nuevo).

Los clientes CLI y de agentes (`iaerp-mcp-cli`, `iaerp-agent-*`) **no** reciben
estos scopes a proposito: los agentes no operan lo tributario.

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
| E4 | ATS (XML/ZIP + validacion + correcciones) | ✅ Hecho con faltantes visibles | `sri_xml.py` lee `formaPago` del XML autorizado y `ats_builder.py` toma documentos, impuestos, pagos y retenciones del periodo. La API genera y custodia XML/ZIP privados, permite descargar y registrar/ver errores del SRI. Si falta respaldo o hay evidencia preliminar, no inventa nada: rechaza la generación y explica el faltante. |
| E5 | Tareas del asistente + docs de usuario | ✅ Hecho | El scheduler crea pendientes de bajar evidencia, completar respaldo, revisar IVA y preparar ATS; todos llevan `requires_approval=true`. No envía, entrega ni paga. |
| E6 | Ventas propias sin descargar del portal | ✅ Hecho | `own_documents.py` importa las facturas AUTORIZADAS que emitio IAERP leyendo su artefacto `xml-signed` (la autorizacion sale de `SRITransmission`). `POST /tax/periods/{id}/import-issued` y el boton **Importar mis ventas**. Sin autorizacion o sin XML firmado se omite explicando el motivo. |
| E7 | Carga en bloque con previo | ✅ Hecho | `bulk.py` + `POST /tax/evidence/bulk` (hasta 50 archivos, ZIP incluido). Clasifica por contenido, ubica cada comprobante en el periodo de su fecha real de emision y muestra un **previo que no escribe nada**. Al confirmar guarda evidencia y documentos; con `applyRetentions` delega en `receivables.import_retention_xml_batch`. Un archivo ilegible no aborta el lote. |
| E8 | Expediente del comprobante | ✅ Hecho | `dossier.py` + `GET /tax/documents/{id}/dossier` y tarjeta desplegable: cada documento muestra `ID IAERP` copiable y clave SRI por separado; factura → retencion (IVA y renta separadas) → cobro con referencia bancaria → neto esperado (`total − retenciones`) y saldo. El comprobante de retención muestra su propio desglose. Una retencion por si sola NO cuenta como cobro. |
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

1. **Definir el credito aplicable del 564 con respaldo contable.** La guia del
   SRI vigente al 15 de junio de 2026 confirma que el **507** contiene
   adquisiciones y pagos, incluidos activos fijos, gravados con tarifa 0%; el
   mapa separa su valor bruto del neto del 517. También se corrigieron el 411
   (ventas gravadas netas) y las columnas bruta/neta de 401, 500 y 510. La misma
   guia define el **564** como credito tributario aplicable segun el factor de
   proporcionalidad o la contabilidad. Por eso el 500, 510 y 564 siguen
   `needs_review`: los XML no prueban por sí solos el derecho a crédito. El
   **609** conserva solo la retencion de IVA recibida. Todo es editable en
   `TaxFormFieldMap` sin tocar codigo.
2. **Ficha tecnica del ATS vigente** y su XSD si existe. Las dos muestras
   aceptadas fijan el orden de nodos, pero no cubren todos los casos (notas de
   credito, reembolsos, exportaciones, retenciones emitidas).
3. Muestras de **notas de credito emitidas en XML** para cerrar el lado de
   ventas. Los comprobantes emitidos **ya no dependen del portal**: se importan
   del XML firmado que IAERP guarda al emitirlos (boton "Importar mis ventas" /
   `POST /tax/periods/{id}/import-issued`). Solo hacen falta muestras de los
   documentos que el sistema todavia no emite.

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

La ingesta mueve automáticamente los tres primeros estados según los
comprobantes del periodo. Los dos últimos requieren confirmación humana por la
API y quedan bajo idempotencia y auditoría.

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

**Tarea 1 — Conectar el ATS al periodo: terminada el 2026-08-02.**

- `ats_builder.py` arma el `AtsInput` desde `FiscalDocument`,
  `FiscalDocumentTax` y `FiscalRetention`; compras, ventas, retenciones y
  establecimientos salen de esos registros, sin defaults fiscales.
- `POST /tax/periods/{id}/ats` es idempotente y guarda XML/ZIP privados en un
  `TaxAnnex`; `GET /tax/annexes/{id}/download` da una URL temporal. Generar no
  entrega ni envia el anexo al SRI.
- `POST`/`GET /tax/annexes/{id}/issues` conservan los errores del SRI y la
  pantalla los muestra junto al ZIP generado.
- `FiscalDocument.payment_methods` conserva los códigos `formaPago` del XML
  autorizado. Transferencias respaldadas como `20` llegan al ATS; compras sobre
  el umbral y ventas sin ese dato se detienen con 422. No se aplican códigos por
  defecto ni se cambia un comprobante autorizado.

**Tarea 2 — E5: tareas del asistente: terminada el 2026-08-02.**
`services/tax/tasks.py` se ejecuta desde el dispatcher y crea pendientes
idempotentes de bajar comprobantes, completar evidencia, revisar IVA y preparar
ATS. Todas nacen con `requires_approval=true`; el scheduler no declara,
entrega, paga ni abre comunicación externa.

**Tarea 3 — Estado del periodo: terminada el 2026-08-02.**
La ingesta mantiene `PENDIENTE_DESCARGA` sin comprobantes, usa
`EVIDENCIA_INCOMPLETA` si alguno es preliminar y pasa a `LISTO_REVISAR` con
evidencia completa. `POST /tax/periods/{id}/status` exige confirmación humana e
idempotencia para avanzar primero a `LISTO_DECLARAR` y después a `DECLARADO`.
La pantalla expone ambas confirmaciones y no permite saltar pasos.

**Siguiente trabajo.** La prioridad documental y la conciliación bancaria ya
están integradas en `main`. Carlos continúa con julio de 2026: cargar y revisar
compras, ventas y retenciones, generar el ATS y validarlo con evidencia real en
el portal del SRI. Repetir el cierre hacia atrás, un mes a la vez. La
conciliación usa el período elegido y da prioridad al archivo subido: conserva
el cobro manual y crea un reverso auditable. Si el manual está en otra factura
del mismo cliente, solo propone corregirlo cuando la fecha del banco demuestra
que esa factura todavía no existía. También falta definir el 564 con el factor
de proporcionalidad o el respaldo contable del contribuyente. No automatizar
la presentación ni el pago.

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
