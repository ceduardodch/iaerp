# ADR 0010: Enrutamiento de proveedores de WhatsApp por uso

- Estado: Accepted
- Fecha: 2026-07-27

## Contexto

IAERP necesita operar con Meta Cloud API y Evolution API en paralelo durante la
etapa inicial. Cobranza y CRM tienen riesgos y requisitos distintos: un tenant
puede requerir Meta para recordatorios críticos y Evolution para conversaciones
comerciales.

## Decisión

- Mantener las conexiones Meta y Evolution separadas, cifradas y asociadas al
  `tenant_id`.
- Elegir proveedor por tenant y propósito: `CRM` o `COLLECTIONS`.
- Los tenants existentes conservan `META` como valor por defecto en ambos usos.
- La URL de Evolution se configura exclusivamente en infraestructura mediante
  `EVOLUTION_API_BASE_URL`; ningún tenant puede suministrar una URL de backend.
- Evolution recibe un webhook con token aleatorio por integración. Los eventos
  son datos no confiables y solo crean actividades CRM idempotentes; no ejecutan
  acciones contables, fiscales ni de cobranza por sí mismos.

## Consecuencias

- Meta y Evolution pueden coexistir para el mismo tenant y número/instancia
  según la configuración operativa.
- Las plantillas Meta se envían como plantillas únicamente cuando Meta es el
  proveedor seleccionado. Evolution usa el texto ya preparado por IAERP.
- El operador debe configurar `EVOLUTION_API_BASE_URL` y `PUBLIC_API_URL` en
  Coolify antes de habilitar una conexión Evolution.
