# Captación de clientes AWS con Meta Ads — análisis y plan

> **Estado:** análisis aprobado, implementación NO iniciada (2026-08-03).
> Presupuesto decidido: **USD 300/mes (~$10/día)**. Mercado: **solo Ecuador**.
> Objetivo: probar ángulos de oferta de servicios AWS y que toda la experiencia
> —campaña, leads, costo y resultado— quede dentro de IAERP.

---

## 1. Qué ya existe (verificado en código)

El circuito **anuncio → formulario → CRM ya está construido**. No hay que
inventarlo:

| Pieza | Dónde |
|---|---|
| Conexión con la API de Meta (token cifrado, cuenta publicitaria) | `MetaAdsIntegration`, `services/social_campaigns.py` |
| Campaña con presupuesto diario, edad y países (`["EC"]` por defecto) | `SocialCampaign` (`models/crm.py`) |
| Creación en Meta de campaña + adset + creativo + anuncio | `social_campaigns.prepare_campaign` |
| Activar / pausar desde el ERP | `activate_campaign`, `pause_campaign` |
| Compuerta de aprobación humana antes de gastar | `approved_at` / `approved_by` |
| Instant Form de Meta y **webhook de leads** | `lead_form_id`, `process_lead_webhook` |
| Atribución en el lead | `Lead.utm_source/utm_medium/utm_campaign/utm_content`, `campaign_id` |

## 2. Los tres huecos

**H1 — No hay ingesta de métricas. Cero.** No existe `spend`, `impressions`,
`clicks` ni `insights` en ningún punto del backend. El ERP puede *lanzar*
campañas pero no sabe cuánto gastaron. **Sin esto la pregunta "cuál variante
funcionó" no se puede responder**, y es el cimiento de todo lo demás.

**H2 — Una campaña = un solo anuncio.** `creative_object_key` y
`external_ad_id` son singulares. Tres variantes hoy serían tres campañas con
tres presupuestos separados, que es justo lo que no conviene (ver §3).

**H3 — El ciclo no cierra.** El lead entra, pero nada conecta "este lead costó
$4" con "este lead sirvió".

## 3. Por qué 3 campañas separadas NO funcionan con este presupuesto

Meta necesita **~50 conversiones por conjunto de anuncios por semana** para
salir de la fase de aprendizaje y optimizar. Partir $10/día en tres deja a cada
variante en ~$3,33/día: ninguna llega al umbral, las tres se quedan en
aprendizaje permanente y el resultado no son tres mediciones, es **ruido tres
veces**.

Si una variante da 4 leads y otra 6, esa diferencia es la que se espera por
azar. Decidir con eso es decidir sobre nada.

> **Decisión de diseño: las 3 variantes van como 3 CREATIVOS dentro de UN solo
> conjunto de anuncios**, no como 3 campañas. Meta reparte el tráfico hacia el
> que rinde y la señal llega en días en vez de nunca. Esto es lo que obliga al
> cambio de modelo de H2.

## 4. Qué medir, y con cuánta confianza

| Métrica | Volumen que necesita | Para qué sirve |
|---|---|---|
| **CTR** | miles de impresiones (días) | **Decidir qué creativo gana.** Señal rápida. |
| **Costo por lead (CPL)** | decenas de leads (1-2 semanas) | Confirmar la ganadora. |
| Tasa de calificación | ~30+ leads | Juzgar el **ángulo/producto**, agregando las 3 variantes |
| Ventas cerradas | meses | **No sirve** para comparar variantes a este presupuesto |

**Regla:** las variantes se juzgan por CTR y CPL. Si el producto interesa o no
se juzga por la tasa de calificación **sumando las tres**, nunca una por una.

## 5. Qué variar

Con presupuesto chico, variar colores o el texto del botón es inútil: el efecto
es más pequeño que el ruido. Se varía **el ángulo de la oferta**, donde las
diferencias son de 2x-3x y sí se ven rápido.

Ejemplo para un servicio de revisión de código y pentesting:

| Variante | Ángulo | Texto guía |
|---|---|---|
| A | Riesgo | "¿Cuándo fue la última vez que alguien revisó tu código buscando vulnerabilidades?" |
| B | Costo | "Pentesting continuo por lo que te cuesta una auditoría al año." |
| C | Cumplimiento | "Evidencia de revisión de seguridad para cuando tu cliente te la pida." |

Si una gana claro, aprendiste algo real del mercado ecuatoriano, no de un botón.

## 6. Realidad de Ecuador

- **Meta es barato aquí pero ciego para B2B.** El CPM es bajo, pero no existe
  una audiencia confiable de "responsable técnico de empresa con cargas en
  AWS". La segmentación por intereses (`Amazon Web Services`, `DevOps`,
  `cloud computing`) traerá **estudiantes y gente buscando empleo**. Es lo
  normal, no es un error de configuración.
- **Los Instant Forms dan más leads y de peor calidad** que una landing. Se
  compensa con **preguntas calificadoras en el formulario**: empresa, cargo,
  ¿ya usan AWS? Menos leads, pero utilizables.
- **El ahorro real no está en el CPC, está en no perder horas llamando leads
  basura.** Por eso el paso de calificación en el CRM vale más que afinar el
  anuncio.

### Pendiente del operador (no se puede resolver desde el código)

1. **Verificar el producto.** Confirmar nombre real, disponibilidad en Ecuador y
   condiciones antes de construir creativos alrededor de él.
2. **Preguntar por MDF a AWS.** Si B2B SAS es partner, AWS tiene fondos de
   marketing (MDF / co-op) que pueden financiar campañas como esta — dinero que
   no saldría del bolsillo. En la misma conversación conviene confirmar las
   **reglas de uso de marca** de AWS en publicidad.

## 7. Reglas de decisión de la primera prueba

Fijadas ANTES de gastar, para no racionalizar el resultado después.

| Momento | Qué se mira | Regla |
|---|---|---|
| Semana 1 | CTR por creativo | Pausar el peor **solo si** cada uno pasó ≥5.000 impresiones y la diferencia es grande. Antes de eso, no tocar nada. |
| Semanas 2-4 | CPL por creativo | La ganadora se queda con el presupuesto. |
| Al gastar los $300 | Leads calificados totales | Si hay **menos de 10 calificados**, el problema es el **ángulo o el producto**, no el creativo. Cambiar la oferta, no el anuncio. |

**Definición de lead calificado** (para que sea medible y no opinable): trabaja
en una empresa, la empresa ya usa o planea usar AWS, y la persona decide o
tiene acceso directo a quien decide.

> Los números de embudo (CPM, CTR, CPL esperados) **se dejan deliberadamente sin
> estimar**. Se llenan con lo medido en la semana 1 y recién ahí se proyecta.
> Poner cifras inventadas aquí solo serviría para justificar decisiones después.

## 8. Plan técnico, en orden

| # | Entregable | Por qué en este orden |
|---|---|---|
| **1** | **Ingesta de métricas de Meta Insights**: gasto, impresiones, clics y leads por anuncio, con corte diario y guardados por tenant | Sin esto no se puede decidir nada. Es el cimiento (H1). |
| **2** | **Variantes dentro de una campaña**: una campaña tiene N creativos, cada uno con su propio `external_ad_id`, todos en UN adset | Es lo que hace viable la prueba de §3 (H2). |
| **3** | **Pantalla de decisión**: CTR, CPL y costo por lead calificado **por variante** | Donde se toma la decisión de §7. |
| **4** | **Calificación**: campos calificadores del formulario al lead + estado calificado/descartado en el CRM | Cierra el ciclo (H3) y es donde se ahorra tiempo real. |

Con 1 y 2 ya se puede lanzar y aprender. 3 y 4 se construyen mientras corre la
primera campaña.

### Notas de implementación

- **Métricas por día y por anuncio, nunca solo el acumulado.** Un total no deja
  ver cuándo cambió algo, y Meta reescribe cifras recientes (atribución tardía):
  conviene re-consultar los últimos ~3 días en cada sincronización.
- **La moneda de la cuenta publicitaria puede no ser USD.** Guardar la moneda
  junto al gasto; no asumir.
- **El costo por lead calificado depende de un criterio humano** (§7). Se
  calcula, no se inventa: si no hay leads calificados todavía, el campo va vacío,
  no en cero.
- **Ojo con el alcance del webhook**: `process_lead_webhook` ya escribe leads sin
  sesión de usuario. Al agregar variantes hay que mantener la atribución
  (`utm_content` = variante) para poder cruzar lead ↔ creativo.

## 9. Coordinación

Este documento se escribe **sin tocar código**: al 2026-08-03 hay otra sesión de
IA trabajando el repo, y el plan toca CRM y modelos, justo donde se chocan las
sesiones. Antes de implementar, revisar [`COORDINACION_IA.md`](../COORDINACION_IA.md)
y confirmar que el área está libre.

---

**Última actualización:** 2026-08-03 (America/Guayaquil)
