# Migracion desde sky-franquicia

## Objetivo

Importar datos seleccionados a una base limpia, con ejecuciones repetibles y un
reporte de conciliacion. La migracion no modifica la fuente y no copia modulos
especificos de franquicias.

## Mapeo

| Origen | Destino | Regla |
| --- | --- | --- |
| `profiles` | `tenants` | Un tenant por RUC valido; conflictos se detienen |
| `franchises` | establishments/emission_points | Solo codigos y configuracion fiscal util |
| `users` + enlaces | users/memberships | Vincular por identidad verificada, no solo email |
| `customers` | parties | Rol customer; eliminar flags de farmacia |
| `providers` | parties | Rol supplier; fusionar por identificacion dentro del tenant |
| `products` | products | Normalizar impuestos, codigo y precision |
| `invoices` | sales_documents | Preservar secuencial, clave, XML, estado y fechas |
| `invoice_items` | sales_document_lines | Recalcular y comparar totales |
| `payments` | customer_payments/allocations | Conservar retenciones y descuentos |

Nomina, empleados, contratos, ventas de farmacia, email sync, metas, proyecciones,
campanas y configuracion de franquicias no se importan en el MVP.

## Tratamiento de facturas

1. Agrupar por emisor fiscal real, no solo por `franchise_id`.
2. Validar RUC, establecimiento, punto, secuencial y clave.
3. Recalcular subtotal, impuesto y total con Decimal.
4. Mantener XML original como objeto inmutable con checksum.
5. Para estados pendientes con clave, consultar autorizacion antes de decidir.
6. Nunca retransmitir automaticamente durante migracion.
7. Registrar diferencias entre estado local y SRI para revision.

## Certificados

No se copian desde rutas ni historial Git. El owner debe cargar un certificado
vigente mediante el flujo seguro, o un operador autorizado debe trasladarlo por
un canal cifrado y verificar fingerprint/fecha. No se imprime la contrasena.

## Pipeline

`extract -> stage -> validate -> transform -> load -> reconcile`

- Extract usa una cuenta de solo lectura y snapshot consistente.
- Stage contiene datos cifrados y tiene expiracion.
- Validate produce errores por registro sin cambiar destino.
- Transform es determinista y versionado.
- Load usa claves de migracion e idempotencia.
- Reconcile compara conteos, montos, claves y saldos.

## Reporte obligatorio

- Version del migrador y timestamps.
- Fuente, snapshot y tenant destino.
- Conteos leidos, validos, insertados, omitidos y fallidos.
- Suma de facturas, cobros y saldos por moneda.
- Duplicados por RUC, identificacion, secuencial y clave.
- Diferencias de estado SRI.
- Archivos faltantes o con checksum incorrecto.
- Firma del operador y aprobacion del owner.

## Rollback

Antes del corte se crea backup del destino. Una corrida usa `migration_run_id`;
si falla antes de aprobarse, se eliminan solo registros de esa corrida o se
restaura el backup. Despues de abrir produccion, las correcciones son nuevas
migraciones compensatorias, no edicion manual.

## Criterios de aceptacion

- Cero claves SRI duplicadas.
- Conteos explicados al 100%, incluso omisiones.
- Diferencia monetaria total igual a cero o documentada por registro.
- Usuarios sin acceso a tenants no asignados.
- Al menos una restauracion ensayada.
- El sistema origen permanece disponible en solo lectura durante validacion.
