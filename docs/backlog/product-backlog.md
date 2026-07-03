# Product backlog

Prioridades:

- P0: necesario para una entrega segura y util.
- P1: necesario para completar el MVP.
- P2: mejora posterior al MVP.

## Epic E0 - Producto y gobierno

| ID | Pri | Historia | Aceptacion |
| --- | --- | --- | --- |
| E0-01 | P0 | Definir vision y alcance | Documentos aprobados sin contradicciones |
| E0-02 | P0 | Dimensionar TAM/SAM/SOM | Fuentes, fecha, formulas e hipotesis visibles |
| E0-03 | P0 | Registrar ADR | Cada decision durable tiene estado y consecuencias |
| E0-04 | P0 | Gobernar ramas y entrega | Solo develop/release/main; CI sin deploy |

## Epic E1 - Identidad y aislamiento

| ID | Pri | Historia | Aceptacion |
| --- | --- | --- | --- |
| E1-01 | P0 | Autenticar con OIDC/PKCE | Sesion valida, rotacion y logout |
| E1-02 | P0 | Crear tenant por RUC | RUC valido y unico |
| E1-03 | P0 | Gestionar membresias y roles | Permisos efectivos por tenant |
| E1-04 | P0 | Cambiar tenant activo | Solo membresias activas; nuevo contexto/token |
| E1-05 | P0 | Crear service account | Scopes acotados, expiracion y revocacion |
| E1-06 | P0 | Probar aislamiento | REST, MCP y worker sin fuga |

## Epic E2 - Plataforma segura

| ID | Pri | Historia | Aceptacion |
| --- | --- | --- | --- |
| E2-01 | P0 | Auditoria append-only | Actor, tenant, accion, resultado y correlacion |
| E2-02 | P0 | Idempotencia | Repeticion devuelve resultado sin duplicar |
| E2-03 | P0 | Outbox y workers | Evento y negocio son atomicos |
| E2-04 | P0 | Politicas de agente | Scope, monto, horario y listas evaluados |
| E2-05 | P0 | Kill switch | Bloquea escrituras de IA global/tenant |
| E2-06 | P0 | Storage privado | Hash, version, autorizacion y URL corta |
| E2-07 | P1 | RLS de defensa | Evaluacion documentada y pruebas si se habilita |

## Epic E3 - Maestros

| ID | Pri | Historia | Aceptacion |
| --- | --- | --- | --- |
| E3-01 | P0 | Configurar empresa/RUC | Datos fiscales y ambiente SRI validos |
| E3-02 | P0 | Gestionar establecimientos/puntos | Codigos SRI de tres digitos |
| E3-03 | P0 | Gestionar contacts | Customer/supplier sin duplicar identificacion |
| E3-04 | P0 | Gestionar productos | Precio Decimal e impuesto vigente |
| E3-05 | P1 | Etiquetar entidades | Tags tenant-scoped en entidades soportadas |
| E3-06 | P1 | Importar maestros | Plantilla, validacion y reporte de errores |

## Epic E4 - Facturacion electronica

| ID | Pri | Historia | Aceptacion |
| --- | --- | --- | --- |
| E4-01 | P0 | Crear borrador de factura | Totales recalculados por backend |
| E4-02 | P0 | Reservar secuencial | Concurrencia sin duplicados |
| E4-03 | P0 | Firmar XML | Certificado cifrado, fingerprint auditado |
| E4-04 | P0 | Enviar y autorizar SRI | Estados y mensajes persistidos |
| E4-05 | P0 | Reconciliar por clave | Nunca retransmite una clave ya conocida sin consulta |
| E4-06 | P0 | Generar XML/PDF | Artefactos con checksum y datos consistentes |
| E4-07 | P0 | Emitir nota de credito | Relacion y limite contra factura autorizada |
| E4-08 | P1 | Reintentar fallos tecnicos | Backoff, limite y dead letter |
| E4-09 | P0 | Versionar calculo fiscal | Algoritmo/redondeo aprobado con vectores SRI |

## Epic E5 - Cuentas por cobrar

| ID | Pri | Historia | Aceptacion |
| --- | --- | --- | --- |
| E5-01 | P0 | Crear receivable desde factura | Monto y origen trazables |
| E5-02 | P0 | Definir vencimientos | Cuotas suman monto original |
| E5-03 | P0 | Registrar cobro parcial | Saldo exacto y sin sobreaplicar |
| E5-04 | P0 | Aplicar retenciones/descuentos | Tipo, soporte y auditoria |
| E5-05 | P0 | Ver aging | Rangos reproducibles por fecha local |
| E5-06 | P1 | Enviar recordatorio email | Plantilla, entrega y opt-out |
| E5-07 | P1 | Enviar recordatorio WhatsApp | Consentimiento, plantilla y estado |
| E5-08 | P0 | Aplicar nota de credito | Cartera o saldo a favor sin valor negativo |
| E5-09 | P1 | Revertir movimiento | Compensacion auditada sin editar original |

## Epic E6 - Cuentas por pagar

| ID | Pri | Historia | Aceptacion |
| --- | --- | --- | --- |
| E6-01 | P0 | Crear obligacion manual | Proveedor, documento, monto y vencimiento |
| E6-02 | P0 | Cargar XML/PDF | Archivo privado, seguro y sin duplicados |
| E6-03 | P1 | Extraer datos con IA | Esquema valido, confianza y evidencia |
| E6-04 | P0 | Programar pago | Fecha/prioridad sin transferencia |
| E6-05 | P0 | Registrar pago parcial | Aplicaciones y saldo correctos |
| E6-06 | P1 | Alertar vencimientos | Regla configurable y trazable |
| E6-07 | P0 | Detectar obligacion duplicada | Identidad canonica o excepcion auditada |
| E6-08 | P1 | Revertir pago/ajuste | Movimiento compensatorio y saldo reconciliado |

## Epic E7 - IA y MCP

| ID | Pri | Historia | Aceptacion |
| --- | --- | --- | --- |
| E7-01 | P0 | Publicar MCP OAuth | Discovery, token y Streamable HTTP |
| E7-02 | P0 | Consultar maestros | Resultados estructurados y tenant-scoped |
| E7-03 | P0 | Operar facturacion | Tool, politica, idempotencia y auditoria |
| E7-04 | P0 | Operar cartera/pagos | Sin saldo negativo ni bypass de permisos |
| E7-05 | P1 | Agente interno | OpenAI via interfaz reemplazable |
| E7-06 | P0 | Medir consumo/costo | Modelo, tokens, latencia y costo por tenant |
| E7-07 | P0 | Resistir prompt injection | Fixtures maliciosos no ejecutan tools |
| E7-08 | P1 | Resumen operativo | Metricas no contables con definicion y ventana |

## Epic E8 - Migracion y produccion

| ID | Pri | Historia | Aceptacion |
| --- | --- | --- | --- |
| E8-01 | P0 | Extraer snapshot solo lectura | Fuente identificada y consistente |
| E8-02 | P0 | Migrar tenant piloto | Conteos, claves y montos reconciliados |
| E8-03 | P0 | Restaurar backup | RTO/RPO medidos con evidencia |
| E8-04 | P0 | Observar operacion | Dashboards, alertas y runbooks |
| E8-05 | P0 | Cutover controlado | Checklist, rollback y responsables |
| E8-06 | P0 | Migrar delta final | Cero operaciones perdidas entre snapshot y corte |
| E8-07 | P0 | Inicializar secuencias | Siguiente valor mayor que todo importado |

## Post-MVP

- Plan de cuentas y asientos.
- Conciliacion bancaria.
- Retenciones electronicas.
- Guias, notas de debito y liquidaciones.
- Inventario y ordenes de compra.
- Aplicacion movil.
- Integraciones adicionales de IA/modelos.
