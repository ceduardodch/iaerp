# ADR 0015: Clasificaciones analíticas por tenant

- Estado: Proposed
- Fecha: 2026-08-11

## Contexto

Los tenants necesitan clasificar documentos con sus propios catálogos: por
ejemplo franquicia y sucursal, grupo y subgrupo, o proyecto y fase. Un campo de
texto en cada documento produciría nombres distintos para el mismo concepto y
haría poco fiables los filtros y reportes. A la vez, imponer tres niveles a
todos los tenants bloquearía los casos que solo usan uno.

## Decisión

1. Cada tenant administra clasificaciones analíticas con código, nombre y un
   máximo de uno a tres niveles.
2. Los valores pertenecen al catálogo y pueden tener padre. Un valor de primer
   nivel se puede asignar directamente; los hijos no son obligatorios.
3. Facturas y CxP guardan solo valores controlados. Una asignación por
   clasificación evita combinaciones ambiguas y conserva una copia de la ruta
   visible al momento de clasificar.
4. La asignación es una relación tenant-safe y extensible por `target_type`;
   cada caso de uso valida la pertenencia del documento al tenant autenticado.
5. Se permite cambiar una factura solo mientras sea borrador y una CxP solo
   antes de registrar movimientos. Así la clasificación no reescribe hechos
   fiscales o financieros ya consolidados.
6. Los filtros de Facturas y CxP usan las asignaciones. La clasificación no
   cambia XML, RIDE, ATS, IVA, asientos ni saldos.
7. El catálogo usa scopes `analytics:read` y `analytics:write`, incluidos en
   el cliente web y disponibles para cuentas de servicio autorizadas.

## Consecuencias

- Empresa configura los valores antes de que el operador los use en Facturas o
  Compras.
- Los reportes y nuevos módulos pueden reutilizar la misma relación sin crear
  campos de texto ni duplicar catálogos.
- Renombrar o desactivar valores requerirá conservar las asignaciones ya
  guardadas; la ruta persistida mantiene el contexto histórico.

## Alternativas descartadas

- **Reutilizar `tags` planos existentes:** no soportan jerarquía ni una única
  selección por dimensión.
- **Columnas fijas de grupo, subgrupo y proyecto:** obliga una estructura que
  no todos los tenants necesitan y dificulta ampliar módulos.
- **Guardar JSON sin validar en cada documento:** no protege contra typos ni
  permite referencias tenant-safe a un catálogo administrado.
