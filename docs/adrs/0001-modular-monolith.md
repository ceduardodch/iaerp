# ADR 0001: Monolito modular

- Estado: Accepted
- Fecha: 2026-07-02

## Contexto

Facturacion, cartera y pagos requieren consistencia transaccional. El equipo
inicial es de 2-3 personas y no existe evidencia que justifique microservicios.

## Decision

Implementar FastAPI como monolito modular, con contextos que se comunican mediante
casos de uso y eventos, no mediante acceso cruzado a tablas.

## Consecuencias

- Despliegue y transacciones mas simples.
- Fronteras deben vigilarse con estructura y pruebas.
- Un modulo solo se extrae ante escala, seguridad o ownership medidos.
