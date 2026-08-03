# Sprint 7: contratos simples y preparación de facturas

## Objetivo

Ordenar el flujo actual de PDF, Gmail, FirmaEC y cobros sin crear un editor
legal ni alterar el ciclo fiscal SRI.

## Historias y criterios de aceptación

| ID | Pri | Historia | Aceptación automatizable |
| --- | --- | --- | --- |
| E10-01 | P0 | Gestionar contrato/versiones | Dos tenants aislados; versión firmada inmutable; adenda enlazada. |
| E10-02 | P0 | Guardar evidencia legal | PDF privado, SHA-256 verificado, autorización de descarga y auditoría. |
| E10-03 | P0 | Registrar corte AWS | Reporte privado, periodo único, total manual y revisión. |
| E10-04 | P0 | Crear propuesta comercial | Mensual fijo, AWS o hito reproducible con Decimal. |
| E10-05 | P0 | Vincular a factura | Snapshot contractual; alerta y excepción auditada sin contrato vigente. |
| E10-06 | P1 | Entregar factura | Informe aprobado cuando aplica, más RIDE y XML. |
| E10-07 | P1 | Cobranza opt-in | Política general, factura y consentimiento deben permitir el mensaje. |

## Modelo y flujo

`Party -> CommercialContract -> ContractVersion`; el contrato puede vincular
una oportunidad `WON` y un contrato principal. La versión guarda PDF enviado,
hilo Gmail, PDF firmado y confirmación FirmaEC. `AwsConsumptionCut` pertenece
al cliente y periodo. `BillingProposal` congela regla, evidencia, periodo y
total; `SalesDocument` conserva el snapshot. `Receivable` continúa naciendo
solo de la factura autorizada.

Estados: contrato `DRAFT`, `PENDING_SIGNATURE`, `SIGNED`, `ACTIVE`, `EXPIRED`,
`SUPERSEDED`, `CANCELLED`; corte `IMPORTED`, `RECONCILED`, `REVIEWED`,
`REJECTED`, `BILLED`; propuesta `DRAFT`, `READY_FOR_REVIEW`, `CONVERTED`,
`CANCELLED`. Transiciones sensibles son auditadas y no se borran documentos.

## Contratos públicos entregados

- REST: contratos/versiones, PDF enviado/firmado, Gmail, confirmación FirmaEC,
  activación, cortes AWS, propuestas, informes y conversión a borrador.
- El servidor arma y persiste el snapshot; el navegador no calcula impuestos.
- No hay firma automática, editor de cláusulas, importador de StreamOne ni
  herramientas MCP de escritura.

## Seguridad y pruebas

- PDFs/CSV/XLSX son evidencia no confiable: validar tamaño/tipo y guardar
  privado con SHA-256. Los PDF reales del cliente no entran al repo ni a tests.
- Probar aislamiento, inmutabilidad, correo duplicado, PDF sin firma, contrato
  vencido, mensual fijo, AWS, hitos, informe faltante y cobranza apagada.
- Requiere revisión de Legal Commercial, Product ERP, Backend Platform, QA,
  Frontend A11y y Ecuador SRI para el límite comercial/fiscal.
