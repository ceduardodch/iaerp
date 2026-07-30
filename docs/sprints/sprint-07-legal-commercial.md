# Sprint 7: expediente legal-comercial y facturación AWS

## Objetivo

Entregar un expediente por cliente que conecte contratos firmados, adendas,
propuestas, evidencia AWS, facturas y cartera. El resultado permite preparar
facturas justificadas comercialmente sin alterar el ciclo fiscal SRI.

## Historias y criterios de aceptación

| ID | Pri | Historia | Aceptación automatizable |
| --- | --- | --- | --- |
| E10-01 | P0 | Gestionar contrato/versiones | Dos tenants aislados; versión firmada inmutable; adenda enlazada. |
| E10-02 | P0 | Guardar evidencia legal | PDF privado, SHA-256 verificado, autorización de descarga y auditoría. |
| E10-03 | P0 | Registrar corte AWS | Fuente conector/carga, periodo único, totales conciliados y revisión. |
| E10-04 | P0 | Crear propuesta comercial | Cargo fijo, consumo variable o mixto; precio reproducible con Decimal. |
| E10-05 | P0 | Vincular a factura | Snapshot contractual; alerta y excepción auditada sin contrato vigente. |
| E10-06 | P1 | Cliente 360 | Contratos, vencimientos, cortes, facturas, cartera y documentos relacionados. |
| E10-07 | P1 | Consulta IA/MCP | Resumen/evidencia de solo lectura, schema cerrado y resistencia a inyección. |

## Modelo y flujo

`Party -> CommercialContract -> ContractVersion -> LegalArtifact`; una versión
puede tener reglas fijas y variables. `AwsConsumptionCut` pertenece al cliente
y periodo. `BillingProposal` congela reglas, evidencia y total comercial; al
crear `SalesDocument` guarda la referencia y snapshot. `Receivable` continúa
naciendo solamente de la factura autorizada.

Estados: contrato `DRAFT`, `PENDING_SIGNATURE`, `SIGNED`, `ACTIVE`, `EXPIRED`,
`SUPERSEDED`, `CANCELLED`; corte `IMPORTED`, `RECONCILED`, `REVIEWED`,
`REJECTED`, `BILLED`; propuesta `DRAFT`, `READY_FOR_REVIEW`, `CONVERTED`,
`CANCELLED`. Transiciones sensibles son auditadas y no se borran documentos.

## Contratos públicos previstos

- REST: contratos/versiones y PDF firmado privado ya disponibles; cortes,
  propuestas y `GET /parties/{id}/dossier` siguen pendientes.
- La creación de factura recibe `billingProposalId` o una excepción explícita;
  el servidor, no el cliente, calcula y persiste el snapshot.
- MCP de solo lectura: `commercial.dossier.get`, `commercial.contracts.list`
  y `commercial.obligations.list`; sin `tenant_id` libre ni contenido completo
  de archivos.

## Seguridad y pruebas

- PDFs/CSV/XLSX son evidencia no confiable: validar tamaño/tipo, escanear,
  almacenar privado y extraer únicamente datos cerrados con evidencia y
  confianza.
- Probar aislamiento REST/MCP, roles, URLs vencidas, hash alterado, versiones,
  cargos fijo/variable/mixto, corte duplicado/inconsistente, snapshot,
  excepción, migración upgrade/downgrade, API contract y E2E desktop/móvil.
- Requiere revisión de Product ERP, Backend Platform, MCP AI Security y QA;
  Ecuador SRI revisa únicamente el límite entre snapshot comercial y factura.
