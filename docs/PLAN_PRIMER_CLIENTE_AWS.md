# Plan: primer cliente AWS por esfuerzo de marketing

> **Estado:** plan acordado 2026-08-04. Sin implementación de código.
> **Meta:** un cliente cerrado en 30 días, venido de un esfuerzo deliberado.
> **Complementa** a [`CAPTACION_AWS_META_PLAN.md`](CAPTACION_AWS_META_PLAN.md),
> que queda subordinado: Meta es el canal 5 de 5, no el primero.

---

## 1. El punto de partida real

No se está empezando de cero, y eso cambia todo el orden:

- **Ya hay clientes pagando por servicios AWS.** Existe prueba de que la oferta
  funciona, hay referencias reales y hay un caso que contar.
- **Partner de AWS, Select Tier, con partner manager asignado.**

Por eso "primer cliente" significa *el primero venido de un esfuerzo deliberado*,
no el primero de la historia. Un plan de arranque desde cero sería el plan
equivocado.

### 1.1 Los clientes actuales revelan DOS negocios, no uno

Al mirar la cartera real aparece una separación que este plan mezclaba:

| | **A — Brazo de AWS** | **B — Seguridad gestionada** |
|---|---|---|
| Clientes hoy | Trantotech (AWS $1.800/mes), Infinit (AWS $600/mes) | Universidad Andina |
| Qué es el cliente | empresa de software que revende a clientes finales | institución con superficie pública expuesta |
| Su dolor | no quiere operar infraestructura | **la están atacando ahora** |
| Servicio | operación de AWS, guardias, control de costo | WAF gestionado, pentesting, code review |
| Ingreso | recurrente, atado a su gasto en AWS | mayor por cliente, pero depende del momento |
| Segmento | CIIU J62/J63 — **157 empresas** | educación CIIU P85 — **125 con 25+ empleados** |

**El negocio A ya está validado: dos de tres clientes.** El mensaje no es una
hipótesis de marketing, es cómo ya funciona con Trantotech e Infinit:

> "Operamos el AWS de empresas de software que venden a sus clientes: ustedes
> construyen, nosotros corremos la infraestructura con guardias y control de
> costo. ¿Quién les opera hoy?"

Y da un **filtro de calificación** que antes no existía: preguntar cuánto pagan
de AWS al mes. Con Infinit en $600 y Trantotech en $1.800 ya se conoce el rango
donde el negocio funciona; debajo de cierto monto no vale la conversación.

**El negocio B es el mejor caso y estaba fuera de la lista.** Una universidad no
es CIIU J62, así que las 157 nunca la habrían incluido.

### 1.2 Dos prioridades que salen de esto

**Escribir el caso de la Universidad Andina.** Una página: tenían ataques
constantes, se implementó WAF gestionado, se contuvieron. Con números si los
autorizan. Es la mejor herramienta de venta disponible y sin ella cada
conversación empieza de cero.

**Pedir una presentación, no una referencia.** El sector educativo es el más
referencial que existe: los responsables de TI de las universidades se conocen,
van a los mismos foros, y todos saben que si atacaron a una, siguen ellos. Una
presentación con nombre y correo a su par en otra universidad vale más que las
157 empresas juntas.

### 1.3 Un hilo indirecto

Trantotech le vende a OCP. La operación de AWS ya está, indirectamente, debajo
de un cliente industrial grande. Vale preguntarle a Trantotech por ese mundo —
**no para venderle a OCP directo**, que sería pasarle por encima al cliente,
sino para ver si hay más empresas de software sirviendo a industria pesada,
donde los tickets son otros.

## 2. El universo, medido (no estimado)

Perfilado el 2026-08-04 sobre el registro societario público
(`stg.cia`, 179.888 filas):

```
179.888   empresas en el registro
130.865   VIGENTES (fecha_cancelacion = '0000-00-00')
 12.948   vigentes con 10+ empleados
 92.553   vigentes con correo institucional
```

| Segmento objetivo | Empresas | Con dominio propio |
|---|---:|---:|
| Tecnología (CIIU J62/J63), 10+ empleados | **157** | **131** |
| Educación (CIIU P85), 25+ empleados | **125** | — |
| Sectores que consumen nube, 25+ empleados | 6.282 | 4.196 |

**Dentro de las 157, el orden importa tanto como el filtro:**

| Tamaño | Empresas | Cómo tratarlas |
|---|---:|---|
| 30-99 empleados | **29** | **Punto dulce.** Gasto real en AWS y nadie adentro que lo optimice: los ingenieros sacan features, no revisan facturas. Empezar aquí. |
| 10-29 | 94 | Sienten más el costo pero tienen menos presupuesto, y muchas veces el fundador *es* el técnico. |
| 100+ | 8 | **Verificar en AWS Partner Finder antes de contactar.** A ese tamaño ya tienen equipo de nube propio y pueden ser partners de AWS — o sea, competencia. Si lo son, tratarlos como pares para co-selling, no como prospectos. |

La primera versión del cargador ordenaba por empleados descendente, así que
ponía de primero a la empresa de 2.275 personas: el peor prospecto de los 131.
El script ahora prioriza el punto dulce y marca a los 8 grandes.

**El 77% de las empresas con 10+ empleados están en Pichincha (5.161) y Guayas
(4.829).** El mercado son dos ciudades, no un país: eso abarata todo, incluido
ir a comunidades y eventos en vez de pagar alcance.

Esto confirma con datos lo que el plan de Meta asumía: el universo son
**cientos**, no millones. Por eso la lista nombrada le gana a la publicidad.

## 3. El orden de los canales

Ordenado por probabilidad y velocidad, no por lo que suena moderno:

| # | Canal | Costo | Tiempo | Por qué está donde está |
|---|---|---|---|---|
| **1** | **ACE / partner manager de AWS** | $0 | días | AWS reparte oportunidades a los partners que participan. Es el trabajo del partner manager. |
| **2** | **Referidos de clientes AWS actuales** | $0 | días | Ya hay prueba de que funciona; el referido llega precalificado. |
| **3** | **Clientes de fractalsoft** | $0 | 1-2 sem | Ya pagan y ya confiaron su clave del SRI. Ese nivel de confianza no se compra. |
| **4** | **Las 157 de tecnología** | tiempo | 2-4 sem | Lista fría, pero acotada y con dominio. |
| **5** | Meta ($300) | $300 | meses | Laboratorio de mensaje, no canal de cierre. |

Los tres primeros son gratis y más rápidos que cualquier anuncio.

## 4. El imán: la revisión gratuita

Con ticket alto, "contáctanos para servicios AWS" no lo llena nadie. Se ofrece
algo con valor real que **se auto-califica**: quien lo pide tiene una cuenta AWS.

| Nivel | Qué se pide | Qué se entrega | Cuándo |
|---|---|---|---|
| **Bajo** | La factura de AWS del último mes | Informe de dónde está pagando de más | **Primer contacto, siempre** |
| **Alto** | Rol de solo lectura en la cuenta | Revisión de seguridad completa | Cuando ya hay conversación |

**Se empieza SIEMPRE por el bajo.** Pedir acceso a la cuenta AWS en un primer
contacto es una barrera enorme; mandar un PDF que ya tienen, no. Esa diferencia
decide entre un sí y un no.

El informe **es** la reunión: se llega con hallazgos de su propia cuenta, no con
un pitch.

## 5. Plan de 30 días

### Semana 1 — Lo que ya está caliente

**Llamar al partner manager** (llamar, no escribir). Tres pedidos concretos:

1. Entrar al flujo de oportunidades de **ACE**: registrar las que ya se trabajan
   y pedir ser considerado para las que AWS origine en Ecuador.
2. **MDF** (fondos de marketing para partners) para la prueba de Meta. Si se
   aprueba aunque sea parcial, esa prueba no sale del bolsillo propio.
3. Qué hace falta para subir de tier — la respuesta dice qué mira AWS.

> Los requisitos exactos de cada programa cambian y dependen del tier. El partner
> manager los resuelve en una llamada; no se asumen aquí.

**Pedir referidos** a cada cliente AWS actual, con esta pregunta exacta:

> "¿Conoces a alguien más que esté en AWS y le esté costando más de lo que debería?"

Es específica a propósito. "¿Conoces a alguien que necesite servicios en la nube?"
no funciona porque nadie sabe responderla.

### Semana 2 — Venta cruzada a los clientes de fractalsoft

Mensaje directo y personal, sin campaña:

> Además de los comprobantes hacemos revisión de seguridad y costo en AWS.
> Si usas AWS, mándame tu última factura y te digo dónde estás pagando de más.
> Sin costo y sin compromiso.

### Semanas 3-4 — Las 157

La lista fría, con el mismo imán. Tercera línea, no primera: para entonces ya
hay referidos y venta cruzada corriendo.

## 6. Qué medir, y qué decidir con eso

Metas a 30 días. Números chicos y reales:

| Indicador | Meta |
|---|---:|
| Conversaciones abiertas | 15 |
| Facturas AWS recibidas | 8 |
| Informes entregados | 6 |
| Propuestas enviadas | 2 |
| **Cliente cerrado** | **1** |

**Regla de decisión:** si se entregan 6 informes y no sale ninguna propuesta, el
problema no es el canal — es **la oferta o el precio**. Eso se sabe en 30 días en
vez de en seis meses, y es el verdadero valor de fijar la meta antes de empezar.

## 7. Qué NO hacer todavía

- **Meta.** No para el primer cliente. Va después, y con MDF si se aprueba.
- **Contenido, blog, LinkedIn orgánico.** Lento, y el mercado son 157 empresas.
- **Automatizar el outbound.** Solo hay 157 nombres; uno quemado no se repone.
  Aprobación humana en cada envío.
- **Construir el módulo de Insights de Meta.** No hace falta para cerrar uno.

## 8. Qué construir en IAERP — lo mínimo

No se construye una máquina para conseguir un cliente:

1. **Cuenta nombrada en el CRM**: las 157 y los clientes de fractalsoft, con
   dueño, estado y fecha del próximo contacto.
2. **Un `Lead` por conversación abierta**, con su próximo paso.

Casi todo eso ya existe en el CRM. Lo que falta es cargarlo.

## 9. Calidad de datos: dos cosas a corregir antes de usar `stg.cia`

**Textos corrompidos.** Las descripciones CIIU vienen con mojibake (`DISEÃâO`,
`GALERÃÂAS`, `SUPERVISIÃâN`): UTF-8 leído como Latin-1 en la carga. Si
`nombre_compania` tiene el mismo daño, la lista saldría con nombres rotos.
Comprobar antes de exportar:

```sql
SELECT count(*) FROM stg.cia WHERE nombre_compania LIKE '%Ã%';
```

**`empleados` es texto y `'0'` significa "no reportado"**, no cero: 122.029
empresas están así. No se descartan por tamaño — simplemente no se sabe.

**`fecha_cancelacion = '0000-00-00'` significa VIGENTE**, no nulo. Filtrar por
`IS NULL` devuelve cero filas.

## 10. Límite de datos — decisión firme

El servidor de origen contiene también `master.clientes`: 19,1 millones de
registros de personas con cédula, filiación de padre y madre, salarios,
empleadores del IESS, títulos, licencias y estado de fallecimiento.

**Nada de este plan se construye sobre esa tabla ni sobre las tablas `stg` que la
alimentan** (`citizen`, `iess_v2`, `finanzas`, `degree`, `license`), ni sobre las
que unen empresa y persona por cédula (`cia_accionistas`, `cia_administradores`,
`contact_cias`).

Se usa **únicamente `stg.cia`**: registro societario público, con contacto
institucional de la empresa (`telefono`, `correo_electronico`). Es suficiente
para todo lo anterior y no toca datos personales de terceros.

Esta línea no es negociable por conveniencia: el negocio que se está
construyendo vende seguridad y cumplimiento.

---

**Última actualización:** 2026-08-04 (America/Guayaquil)
