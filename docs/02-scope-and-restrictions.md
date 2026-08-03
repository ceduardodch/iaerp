# Alcance y restricciones

## Alcance MVP

### Plataforma

- Un tenant corresponde exactamente a un RUC.
- Un usuario puede pertenecer a varios tenants.
- Roles iniciales: owner, admin, billing, collections, payables, auditor y agent.
- Establecimientos y puntos de emision pertenecen al tenant.
- Etiquetas por tenant para contactos, productos y documentos financieros.

### Facturacion

- Facturas y notas de credito.
- Borrador, emision, firma, recepcion, autorizacion y reconciliacion SRI.
- PDF y XML versionados.
- Secuencial seguro por establecimiento, punto de emision y tipo de documento.
- Consulta por clave de acceso antes de cualquier retransmision.

### Cuentas por cobrar

- Cuenta por cobrar originada por factura o carga historica controlada.
- Una o varias fechas de vencimiento.
- Cobros parciales, retenciones, descuentos autorizados y aplicaciones.
- Antiguedad de cartera y recordatorios por email/WhatsApp.

### Cuentas por pagar

- Obligacion manual o extraida desde XML/PDF.
- Proveedor, documento, vencimientos, adjuntos y estado.
- Programacion y registro de pagos parciales.
- No se inicia movimiento bancario.

### IA y MCP

- Consultas y operaciones tipadas.
- Ejecucion autonoma cuando token, rol, politica y estado lo permitan.
- Interruptor global y por tenant.
- OpenAI como primer adaptador; el dominio no depende del proveedor.

### Expediente legal-comercial

- Contratos de clientes versionados, PDF firmado privado, adendas y evidencia
  comercial asociada al cliente.
- Cortes de consumo AWS por carga o consulta autorizada de solo lectura,
  conciliados antes de una propuesta de facturación.
- Propuestas comerciales de cargo fijo, consumo variable o ambas, vinculables
  a factura y cartera sin sustituir el comprobante SRI.

### Modulo tributario (ADR 0012)

- Carga manual de evidencia del SRI (XML, TXT, PDF, ZIP) por entidad, RUC y
  periodo, con hash y trazabilidad; el portal del SRI no se automatiza.
- Comprobantes recibidos (compras) construidos desde la evidencia importada.
- Preparacion del IVA mensual (formulario 104) con valores listos para copiar y
  la lista de documentos que respalda cada cifra.
- Generacion del ATS (XML y ZIP) con validacion previa y ciclo de correccion de
  los errores devueltos por el SRI.
- Los PDF son solo evidencia: los valores se toman del XML o del TXT.
- El sistema no inventa valores; lo que carece de soporte queda marcado como
  preliminar y se reporta como faltante.
- Declarar, entregar un anexo o pagar exige aprobacion humana explicita.
- RDEP y ADI quedan fuera hasta definir el origen de los datos de nomina/IESS y
  contar con la ficha tecnica vigente del anexo.

## Restricciones vinculantes

- Pais Ecuador, moneda USD y zona `America/Guayaquil`.
- Montos con `Decimal/NUMERIC`; API serializa decimales sin perdida.
- Identidad y tenant provienen del token validado.
- Toda escritura acepta una idempotency key.
- Claves de acceso SRI son unicas globalmente cuando existan.
- Un documento autorizado es inmutable; correcciones usan documentos relacionados.
- Certificados y contrasenas se cifran y nunca se almacenan en Git.
- Todo acceso y mutacion sensible genera auditoria.
- Contenido de documentos y mensajes no se considera una instruccion confiable.
- La eliminacion de registros financieros es logica o mediante reverso; no fisica.

## Fuera del MVP

- Contabilidad general, diario, mayor, balances y cierres.
- Conciliacion o integracion bancaria.
- Ejecucion de transferencias.
- Inventario, compras con ordenes y logistica.
- Nomina, RRHH y comunidad.
- Firma electrónica integrada, asesoría/validación jurídica automatizada y
  administración de infraestructura AWS.
- Marketing, promociones y Telegram.
- Farmacias, franquicias, metas y proyecciones especificas.
- Operacion fiscal multi-pais o varias monedas funcionales.

## Limites de autonomia

El usuario eligio autonomia sin aprobacion humana obligatoria. Esto no elimina
controles: una accion se rechaza si falta permiso, excede politica, repite
idempotency key, viola estado o no pasa validaciones fiscales.

Acciones como emitir, enviar recordatorios o registrar pagos pueden ejecutarse
automaticamente. Anular o emitir notas de credito requiere una politica explicita
habilitada por el owner. El kill switch detiene nuevas escrituras de agentes sin
afectar consultas ni operaciones humanas.
