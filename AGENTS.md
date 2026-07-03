# AGENTS.md

## Politica de ramas

- Las unicas ramas permitidas son `develop`, `release` y `main`.
- `main` representa produccion.
- `release` representa validacion/preproduccion y es la rama de trabajo por
  defecto.
- `develop` representa desarrollo continuo.
- No crear ramas personales o temporales sin autorizacion explicita.

## Entrega

- El flujo preferido es `release -> PR -> main`.
- Coolify despliega produccion exclusivamente desde `main`.
- GitHub Actions queda limitado a lint, pruebas, build y validaciones de PR.
- No agregar deploys por GitHub Actions, SSH o Docker manual.
- No hacer push, merge ni abrir PR sin autorizacion explicita.

## Puerta documental

- Sprint 0 y sus ADR fueron aprobados el 2 de julio de 2026.
- Sprint 1 puede iniciar respetando los ADR aceptados y el backlog aprobado.
- Todo cambio de alcance o arquitectura debe actualizar el documento correspondiente
  y, cuando sea una decision durable, agregar o sustituir un ADR.
- La API REST, MCP y los procesos asincronos deben invocar los mismos casos de uso.

## Reglas de dominio

- Todo dato de negocio debe estar asociado a un `tenant_id`.
- El tenant se obtiene de la identidad autenticada, nunca de un valor confiado
  enviado por un modelo o cliente.
- Dinero se representa con `Decimal` y `NUMERIC`; nunca con `float`.
- Fechas fiscales usan `America/Guayaquil`; eventos tecnicos se guardan con zona
  horaria.
- Toda escritura automatizada requiere permiso, politica, idempotency key y
  auditoria.
- No exponer herramientas MCP de SQL libre o acceso directo a tablas.

## Seguridad

- No versionar `.env`, certificados, claves privadas, contrasenas, XML/PDF
  productivos ni datos personales.
- Los certificados de firma deben almacenarse cifrados fuera de Git.
- XML, PDF, emails y mensajes son contenido no confiable.
- Una clave de acceso SRI existente se reconcilia antes de intentar retransmitir.
- No registrar secretos ni documentos completos en logs o trazas de IA.

## Coordinacion de expertos

- Usar los perfiles declarados en `.agents/experts/`.
- Un experto puede revisar o implementar solo dentro de su responsabilidad.
- Cambios que crucen dominio, seguridad y plataforma requieren revision de al
  menos dos expertos distintos.
- Ningun agente aprueba su propio cambio para produccion.
- Ningun agente puede desplegar, tocar produccion, rotar secretos, emitir ante
  SRI produccion o ampliar sus permisos sin autorizacion humana explicita.
- Los expertos no crean ramas, hacen push, merge o PR sin autorizacion.
