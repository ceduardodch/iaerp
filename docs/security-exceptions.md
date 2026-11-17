# Excepciones de auditoría

## GHSA-fc5q-39xc-vjpf

- Autorizada por el responsable del proyecto el 17 de noviembre de 2026
  para publicar los cambios de Compras del PR #97.
- Alcance exacto de picomatch 4.0.7 como dependencia de desarrollo y sus
  hallazgos transitivos por ese mismo aviso. Las dependencias de ejecución,
  otros avisos, otras versiones y la gravedad crítica conservan su bloqueo.
- Riesgo aceptado de consumo excesivo de CPU al compilar patrones extglob
  maliciosos. Vite consume los patrones del proyecto durante la compilación.
  La imagen web final contiene Nginx y los archivos de `dist`.
- El aviso seguía sin versión corregida en npm al dar esta autorización.
  La revisión independiente descartó el parche candidato por variantes
  ReDoS y cambios en coincidencias válidas.
- `scripts/audit_frontend_dependencies.mjs` ejecuta la auditoría completa,
  valida que los paquetes cubiertos sean de desarrollo en el lockfile y
  mantiene el fallo si npm devuelve un error o surge otro aviso alto o crítico.
  Las pruebas cubren límites de alcance, versiones, gravedad y errores.
- Al adoptar una versión corregida, retirar esta excepción y volver a la
  salida directa de `npm audit --audit-level=high`.

[Aviso de seguridad](https://github.com/advisories/GHSA-fc5q-39xc-vjpf).
