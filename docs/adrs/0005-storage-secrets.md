# ADR 0005: Objetos privados y secretos fuera de Git

- Estado: Accepted
- Fecha: 2026-07-02

## Contexto

XML, PDF y certificados son sensibles y no deben depender del filesystem de un
contenedor ni del historial Git.

## Decision

Usar MinIO privado para objetos versionados. PostgreSQL conserva metadatos y
hash. Certificados se protegen con envelope encryption; claves y contrasenas
viven en el gestor de secretos de infraestructura.

## Consecuencias

- Se requieren backup y monitoreo de MinIO.
- Descargas son autorizadas y temporales.
- Certificados heredados deben recargarse o trasladarse de forma cifrada.
