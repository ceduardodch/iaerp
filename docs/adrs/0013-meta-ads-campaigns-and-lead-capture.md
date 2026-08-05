# ADR 0013: campañas Meta y captura de leads en CRM

- Estado: aceptado para implementación local
- Fecha: 2026-08-04

## Contexto

IAERP necesita crear campañas de formularios en Facebook e Instagram y recibir
cada respuesta como una oportunidad del CRM. La acción puede iniciar gasto
publicitario y el webhook escribe sin una sesión humana, por lo que ambos flujos
requieren límites claros.

## Decisión

- La conexión de Meta Ads se guarda por `tenant_id`. Token, App Secret y Verify
  Token se cifran y nunca vuelven al navegador.
- Cada página de Meta solo puede pertenecer a un tenant en IAERP para resolver
  el webhook sin ambigüedad.
- Crear una campaña en IAERP solo crea un borrador local. `Preparar en Meta`
  guarda primero una intención `PREPARING` en el outbox. El worker crea campaña,
  conjunto, creativos y anuncios con estado `PAUSED` y luego marca `PREPARED`.
- Activar exige una confirmación humana separada, rol `owner` o `admin`, permiso
  `communications:write`, clave de idempotencia y auditoría con aprobador y
  fecha. También exige que el dueño habilite la política de gasto del tenant y
  fije un tope diario. La reserva queda en `ACTIVATING`; el worker habilita
  anuncios y conjunto antes de la campaña padre. Si falla, pausa los objetos
  conocidos y deja la campaña en `ERROR`. Pausar guarda `PAUSING` antes de
  llamar a Meta. Apagar la política cancela activaciones pendientes y encola la
  pausa de todas las campañas activas.
- Los nombres enviados a Meta incluyen el UUID estable de IAERP. Un reintento
  busca esos nombres antes de crear objetos y evita duplicarlos tras una falla.
- El webhook valida `X-Hub-Signature-256`, limita cuerpo, lote y frecuencia por
  tenant y guarda cada intento firmado en una transacción propia, incluso si el
  lote falla. Luego obtiene el tenant desde la página registrada y usa el
  `leadgen_id` como referencia idempotente.
- El lead nace en `NEW` con campaña, anuncio, UTM, formulario y fecha de
  consentimiento. Se deduplica por referencia de Meta y por correo o teléfono.
  Cada respuesta conserva además un `LeadCampaignTouch`: si el contacto ya
  existía, IAERP no duplica la oportunidad pero sí guarda la nueva campaña.
- Un contacto de campaña usa identidad provisional `FINAL_CONSUMER` y no puede
  pasar a `WON` hasta completar una identidad fiscal válida.
- Las imágenes se guardan en almacenamiento privado y solo se aceptan JPEG o
  PNG de hasta 5 MB.
- Una campaña contiene varias variantes bajo un solo conjunto de anuncios. El
  presupuesto y el público se comparten; cada variante conserva texto, imagen,
  creativo, anuncio y clave de atribución propios.
- IAERP reconsulta y sustituye los últimos días de Meta Insights por anuncio.
  Guarda gasto, moneda real de la cuenta, impresiones, clics y leads por día;
  CTR, CPL y costo por lead calificado se calculan desde esa evidencia.
- La calificación es una decisión humana distinta del pipeline. Para marcar un
  lead calificado se exige empresa, uso de AWS y acceso a quien decide; el
  motivo, actor y fecha quedan guardados.
- REST y procesos automáticos llaman los mismos servicios de aplicación. No se
  expone acceso directo a tablas ni secretos por MCP.
- El consumidor usa entrega tardía y reintentos con espera. Si cae tras una
  llamada a Meta, el inbox no queda confirmado y el evento se repite; las
  operaciones externas usan IDs o nombres estables.

## Consecuencias

- IAERP puede lanzar y detener una campaña Meta sin activar gasto por accidente.
- La atención del lead sigue el pipeline y la historia normal del CRM.
- La pantalla de decisión permite comparar variantes con métricas diarias y
  resultados calificados sin dividir el presupuesto en varias campañas.
- LinkedIn y TikTok requieren conectores y permisos propios; no reutilizan las
  credenciales de Meta.
- El caso de uso común puede recibir `LINKEDIN_LEAD_GEN` y `TIKTOK_LEAD_GEN`
  desde un conector autenticado, pero los webhooks públicos y la creación de
  campañas siguen separados por proveedor. Ver `docs/SOCIAL_CRM_CHANNEL_MATRIX.md`.
