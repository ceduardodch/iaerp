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
- GitHub Actions ejecuta lint, pruebas y build. En `release`, el job de CD
  llama a la API de Coolify solo despues de que todos los jobs de CI pasan.
- No desplegar por SSH ni ejecutar Docker manualmente para sustituir el flujo
  CI/CD. Coolify sigue siendo el unico ejecutor del despliegue.
- No hacer push, merge ni abrir PR sin autorizacion explicita.

## Puerta documental

- Sprint 0 y sus ADR fueron aprobados el 2 de julio de 2026.
- Sprint 1 puede iniciar respetando los ADR aceptados y el backlog aprobado.
- Antes de trabajar, leer `docs/STATUS.md`; al cerrar una sesion, actualizar su
  corte, evidencia y pendientes si el estado cambio.
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

## Pruebas

- Cada historia debe incluir datos sinteticos reproducibles, pruebas unitarias y
  las pruebas de integracion/contrato/E2E que correspondan segun
  `docs/09-testing-quality.md`.
- No usar datos productivos ni datos personales en fixtures, seeds, capturas o
  artefactos de CI.
- Una historia no se considera terminada si sus criterios de aceptacion no estan
  automatizados.

## Interfaz

- Toda pantalla nueva o modificada debe usar las plantillas y componentes de
  `docs/12-frontend-design-system.md`.
- No duplicar botones, encabezados, toolbars, paneles o barras de formulario
  cuando exista un componente en `frontend/src/components/erp/`.
- Mantener las posiciones y textos estandar de `Nuevo`, `Editar`, `Guardar` y
  `Cancelar`; una excepcion requiere actualizar la documentacion.

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
