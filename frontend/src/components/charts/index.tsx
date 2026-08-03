import { useId, type ReactNode } from 'react'

import { formatAmount } from '../../utils/format'

/**
 * Gráficos en SVG propio, sin librería.
 *
 * No se usa una librería por dos razones concretas: el CI corre auditorías WCAG
 * y las librerías de gráficos obligan a parchear accesibilidad a mano, y el
 * bundle ya está en un tamaño que conviene no engordar. Las formas que necesita
 * un ERP —línea, columnas, barra apilada, minigráfica— son geometría simple.
 *
 * Reglas fijas en todos los gráficos de este archivo:
 * - Marcas finas: columnas ≤ 24px, líneas de 2px, marcadores ≥ 8px de diámetro.
 * - Extremo de dato redondeado 4px, cuadrado contra la línea base.
 * - Cuadrícula y ejes en línea sólida de 1px, recesivos (nunca punteados).
 * - Separación por hueco de 2px del color de la superficie, nunca por borde:
 *   un borde agrega tinta que no es dato.
 * - Etiquetas SELECTIVAS: el extremo, el máximo, el que cuenta la historia.
 *   Un número sobre cada punto no se lee.
 * - El texto nunca lleva el color de la serie; va en tokens de texto. La
 *   identidad la da la marca de color que está al lado.
 * - Todo gráfico trae su tabla equivalente para lector de pantalla, así ningún
 *   valor queda accesible solo por color o solo por el tooltip.
 */

const CURRENCY = (value: number | string) => `$${formatAmount(value)}`

/**
 * Marca del eje, abreviada sin perder exactitud.
 *
 * Redondear a entero mentía: con techo 3.000 la marca de la mitad cae en 1.500
 * y `Math.round(1.5)` la rotulaba "2k" sobre la línea de 1.500. Un eje que
 * declara un valor distinto del que dibuja es peor que no tener eje.
 */
const formatTick = (value: number): string => {
  if (value >= 1000) {
    const thousands = value / 1000
    return `${thousands.toFixed(Number.isInteger(thousands) ? 0 : 1).replace('.', ',')}k`
  }
  return String(Math.round(value))
}

/** Tabla equivalente, visible solo para lectores de pantalla. */
function ChartTable({
  caption,
  columns,
  rows,
}: {
  caption: string
  columns: string[]
  rows: Array<{ key: string; cells: string[] }>
}) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead>
        <tr>{columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key}>
            {row.cells.map((cell, index) =>
              index === 0 ? <th key={cell} scope="row">{cell}</th> : <td key={`${row.key}-${index}`}>{cell}</td>,
            )}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export type LinePoint = { label: string; value: number }

/**
 * Tendencia en el tiempo: una sola serie, así que no lleva caja de leyenda —
 * el título ya dice qué se grafica y una leyenda de un solo color lo repetiría.
 *
 * El tiempo se lee de izquierda a derecha; por eso esto es una línea y no la
 * pila de barras horizontales que había antes, que gastaba media pantalla en
 * doce filas y escondía la pendiente.
 */
export function ErpLineChart({
  points,
  label,
  height = 200,
}: {
  points: LinePoint[]
  label: string
  height?: number
}) {
  const gradientId = useId()
  if (points.length === 0) return null

  const width = 900
  const padLeft = 56
  const padRight = 24
  const padTop = 20
  const baseline = height - 42
  const plotWidth = width - padLeft - padRight

  const maximum = Math.max(...points.map((point) => point.value), 1)
  // Techo redondeado hacia arriba: los ticks caen en números limpios.
  const magnitude = 10 ** Math.floor(Math.log10(maximum))
  const ceiling = Math.ceil(maximum / magnitude) * magnitude
  const step = points.length > 1 ? plotWidth / (points.length - 1) : 0
  const x = (index: number) => padLeft + index * step
  const y = (value: number) => baseline - (value / ceiling) * (baseline - padTop)

  const line = points.map((point, index) => `${x(index)},${y(point.value)}`).join(' ')
  const last = points[points.length - 1]!
  const ticks = [ceiling, ceiling * 0.5, 0]

  // Con muchos meses se rotula uno de cada dos para que las etiquetas no choquen.
  const labelStride = points.length > 8 ? 2 : 1

  return (
    <div className="erp-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} className="erp-chart-svg">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--chart-1)" stopOpacity="var(--chart-area-opacity)" />
            <stop offset="100%" stopColor="var(--chart-1)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={padLeft}
              y1={y(tick)}
              x2={width - padRight}
              y2={y(tick)}
              stroke={tick === 0 ? 'var(--chart-axis)' : 'var(--chart-grid)'}
              strokeWidth="1"
            />
            <text x={padLeft - 8} y={y(tick) + 4} className="erp-chart-tick">
              {formatTick(tick)}
            </text>
          </g>
        ))}
        <polygon
          points={`${line} ${x(points.length - 1)},${baseline} ${padLeft},${baseline}`}
          fill={`url(#${gradientId})`}
        />
        <polyline
          points={line}
          fill="none"
          stroke="var(--chart-1)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {/* Anillo de 2px del color de la superficie: mantiene el punto legible
            donde cruza la línea. */}
        <circle cx={x(points.length - 1)} cy={y(last.value)} r="5" fill="var(--chart-1)" stroke="var(--surface-card)" strokeWidth="2" />
        {/* Etiqueta directa solo en el extremo: el resto lo lleva el eje. */}
        <text x={x(points.length - 1)} y={y(last.value) - 12} className="erp-chart-value" textAnchor="end">
          {CURRENCY(last.value)}
        </text>
        {points.map((point, index) =>
          index % labelStride === 0 || index === points.length - 1 ? (
            <text key={point.label} x={x(index)} y={height - 14} className="erp-chart-cat" textAnchor="middle">
              {point.label}
            </text>
          ) : null,
        )}
      </svg>
      <ChartTable
        caption={label}
        columns={['Periodo', 'Total']}
        rows={points.map((point) => ({ key: point.label, cells: [point.label, CURRENCY(point.value)] }))}
      />
    </div>
  )
}

export type OrdinalBar = { label: string; value: number; description?: string }

/**
 * Columnas sobre una escala CON orden propio (antigüedad, etapas de embudo).
 *
 * Usa la rampa ordinal de un solo tono: el color muestra el orden. No se colorea
 * cada columna por su valor —eso volvería a codificar lo que la altura ya dice—
 * ni se usa rojo, que está reservado para estado.
 */
export function ErpOrdinalColumns({
  bars,
  label,
  emphasizeLast = false,
}: {
  bars: OrdinalBar[]
  label: string
  emphasizeLast?: boolean
}) {
  if (bars.length === 0) return null

  const width = 460
  const height = 190
  const padLeft = 46
  const baseline = 146
  const padTop = 20
  const plotWidth = width - padLeft - 12
  const band = plotWidth / bars.length
  const barWidth = Math.min(24, band * 0.5)

  const maximum = Math.max(...bars.map((bar) => bar.value), 1)
  const magnitude = 10 ** Math.floor(Math.log10(maximum))
  const ceiling = Math.ceil(maximum / magnitude) * magnitude
  const heightOf = (value: number) => (value / ceiling) * (baseline - padTop)

  // Solo se rotulan el mayor y el último: etiquetar todo vuelve ilegible el gráfico.
  const peakIndex = bars.reduce((best, bar, index) => (bar.value > (bars[best]?.value ?? 0) ? index : best), 0)

  return (
    <div className="erp-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} className="erp-chart-svg">
        {[ceiling, ceiling * 0.5, 0].map((tick) => {
          const ty = baseline - heightOf(tick)
          return (
            <g key={tick}>
              <line x1={padLeft} y1={ty} x2={width - 10} y2={ty} stroke={tick === 0 ? 'var(--chart-axis)' : 'var(--chart-grid)'} strokeWidth="1" />
              <text x={padLeft - 6} y={ty + 4} className="erp-chart-tick">
                {formatTick(tick)}
              </text>
            </g>
          )
        })}
        {bars.map((bar, index) => {
          const barHeight = Math.max(heightOf(bar.value), bar.value > 0 ? 3 : 0)
          const bx = padLeft + band * index + (band - barWidth) / 2
          const by = baseline - barHeight
          const tone = `var(--chart-ordinal-${Math.min(index + 1, 6)})`
          const labelled = index === peakIndex || (emphasizeLast && index === bars.length - 1)
          return (
            <g key={bar.label}>
              {barHeight > 0 ? (
                <>
                  <rect x={bx} y={by} width={barWidth} height={barHeight} rx="4" fill={tone} />
                  {/* Recorte del redondeo contra la base: la marca crece desde
                      una línea base recta, solo el extremo del dato va curvo. */}
                  <rect x={bx} y={baseline - 4} width={barWidth} height="4" fill={tone} />
                </>
              ) : null}
              {labelled ? (
                <text x={bx + barWidth / 2} y={by - 7} className="erp-chart-value" textAnchor="middle">
                  {CURRENCY(bar.value)}
                </text>
              ) : null}
              <text x={bx + barWidth / 2} y={height - 26} className="erp-chart-cat" textAnchor="middle">
                {bar.label}
              </text>
            </g>
          )
        })}
      </svg>
      <ChartTable
        caption={label}
        columns={['Tramo', 'Saldo']}
        rows={bars.map((bar) => ({ key: bar.label, cells: [bar.label, CURRENCY(bar.value)] }))}
      />
    </div>
  )
}

export type StackedRow = { label: string; parts: number[] }

/**
 * Barras horizontales apiladas para parte-y-todo con nombres largos.
 *
 * Los segmentos se separan por un hueco de 2px del color de la superficie, no
 * por un borde. Lleva leyenda porque son dos o más series: la identidad nunca
 * puede depender solo del color.
 */
export function ErpStackedBars({
  rows,
  seriesNames,
  label,
}: {
  rows: StackedRow[]
  seriesNames: string[]
  label: string
}) {
  if (rows.length === 0) return null

  const width = 460
  const rowHeight = 42
  const height = rows.length * rowHeight
  const padLeft = 58
  const padRight = 62
  const plotWidth = width - padLeft - padRight
  const barHeight = 20
  const GAP = 2

  const maximum = Math.max(...rows.map((row) => row.parts.reduce((sum, part) => sum + part, 0)), 1)

  return (
    <div className="erp-chart">
      <ul className="erp-chart-legend">
        {seriesNames.map((name, index) => (
          <li key={name}>
            <span className="erp-chart-swatch" style={{ background: `var(--chart-${index + 1})` }} aria-hidden="true" />
            {name}
          </li>
        ))}
      </ul>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} className="erp-chart-svg">
        {rows.map((row, rowIndex) => {
          const top = rowIndex * rowHeight + (rowHeight - barHeight) / 2
          const total = row.parts.reduce((sum, part) => sum + part, 0)
          let cursor = padLeft
          return (
            <g key={row.label}>
              <text x={0} y={top + 14} className="erp-chart-cat2">{row.label}</text>
              {row.parts.map((part, partIndex) => {
                const partWidth = total > 0 ? (part / maximum) * plotWidth : 0
                const x = cursor
                cursor += partWidth + (partWidth > 0 ? GAP : 0)
                if (partWidth <= 0) return null
                return (
                  <rect
                    key={seriesNames[partIndex]}
                    x={x}
                    y={top}
                    width={partWidth}
                    height={barHeight}
                    rx="4"
                    fill={`var(--chart-${partIndex + 1})`}
                  />
                )
              })}
              {/* Total al final de la barra: cabe siempre porque el área está
                  reservada, así que nunca se recorta ni pisa un segmento. */}
              <text x={cursor + 6} y={top + 14} className="erp-chart-value">{CURRENCY(total)}</text>
            </g>
          )
        })}
      </svg>
      <ChartTable
        caption={label}
        columns={['Periodo', ...seriesNames, 'Total']}
        rows={rows.map((row) => ({
          key: row.label,
          cells: [
            row.label,
            ...row.parts.map((part) => CURRENCY(part)),
            CURRENCY(row.parts.reduce((sum, part) => sum + part, 0)),
          ],
        }))}
      />
    </div>
  )
}

/**
 * Comparación de magnitudes entre categorías SIN orden propio (ventas contra
 * compras, cliente contra cliente).
 *
 * Todas las barras van en el MISMO tono y no hay leyenda: son una sola serie
 * medida en la misma unidad, y la categoría ya la dice su etiqueta. Colorear
 * cada barra distinto gastaría el canal de identidad en repetir lo que el
 * largo de la barra ya muestra.
 */
export function ErpCompareBars({
  bars,
  label,
  unitLabel = 'Monto',
}: {
  bars: OrdinalBar[]
  label: string
  unitLabel?: string
}) {
  if (bars.length === 0) return null

  const width = 460
  const rowHeight = 42
  const height = bars.length * rowHeight
  const padLeft = 74
  const padRight = 74
  const plotWidth = width - padLeft - padRight
  const barHeight = 20
  const maximum = Math.max(...bars.map((bar) => bar.value), 1)

  return (
    <div className="erp-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} className="erp-chart-svg">
        {bars.map((bar, index) => {
          const top = index * rowHeight + (rowHeight - barHeight) / 2
          const barWidth = (bar.value / maximum) * plotWidth
          return (
            <g key={bar.label}>
              <text x={0} y={top + 14} className="erp-chart-cat2">{bar.label}</text>
              {barWidth > 0 ? (
                <rect x={padLeft} y={top} width={barWidth} height={barHeight} rx="4" fill="var(--chart-1)" />
              ) : null}
              {/* El valor va fuera del extremo, sobre área reservada: nunca se
                  recorta ni se monta encima de la barra. */}
              <text x={padLeft + barWidth + 6} y={top + 14} className="erp-chart-value">
                {CURRENCY(bar.value)}
              </text>
            </g>
          )
        })}
      </svg>
      <ChartTable
        caption={label}
        columns={['Categoría', unitLabel]}
        rows={bars.map((bar) => ({ key: bar.label, cells: [bar.label, CURRENCY(bar.value)] }))}
      />
    </div>
  )
}

/**
 * Minigráfica de la tarjeta: contexto, no lectura precisa.
 *
 * Va en gris de de-énfasis con el punto actual en el color de la serie; sin
 * ejes ni etiquetas, porque su trabajo es responder "¿viene subiendo?" de un
 * vistazo. El valor exacto siempre está en la cifra grande de la tarjeta.
 */
export function ErpSparkline({ values, tone = 'var(--chart-1)' }: { values: number[]; tone?: string }) {
  if (values.length < 2) return null

  const width = 120
  const height = 28
  // El punto final mide 4 de radio más 2 de anillo: sin este margen quedaría
  // recortado contra el borde del viewBox.
  const margin = 6
  const maximum = Math.max(...values, 1)
  const step = (width - margin * 2) / (values.length - 1)
  const y = (value: number) => height - margin - (value / maximum) * (height - margin * 2)
  const points = values.map((value, index) => `${margin + index * step},${y(value)}`).join(' ')

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="erp-sparkline" aria-hidden="true" focusable="false">
      <polyline points={points} fill="none" stroke="var(--chart-muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={width - margin} cy={y(values[values.length - 1] ?? 0)} r="4" fill={tone} stroke="var(--surface-card)" strokeWidth="2" />
    </svg>
  )
}

/**
 * Tarjeta de indicador: etiqueta, cifra y —cuando hay con qué compararla— la
 * variación y su minigráfica.
 *
 * ``delta`` es opcional a propósito: una variación que no se puede calcular con
 * datos reales no se inventa. Sin comparación la tarjeta muestra contexto en
 * texto y ya.
 */
export function ErpStatTile({
  label,
  value,
  tone,
  delta,
  spark,
  footnote,
}: {
  label: string
  value: string
  tone?: 'danger' | 'success'
  delta?: { value: number; goodWhen: 'up' | 'down' }
  spark?: number[]
  footnote?: ReactNode
}) {
  const isGood = delta ? (delta.value >= 0 ? delta.goodWhen === 'up' : delta.goodWhen === 'down') : undefined

  return (
    <article className="erp-stat-tile">
      <span className="erp-stat-label">{label}</span>
      <strong className={tone ? `erp-stat-value is-${tone}` : 'erp-stat-value'}>{value}</strong>
      {delta ? (
        <span className={`erp-stat-delta ${isGood ? 'is-good' : 'is-bad'}`}>
          <span aria-hidden="true">{delta.value >= 0 ? '▲' : '▼'}</span>{' '}
          {formatAmount(Math.abs(delta.value))} % vs. mes anterior
        </span>
      ) : null}
      {spark && spark.length > 1 ? <ErpSparkline values={spark} /> : null}
      {footnote ? <p className="erp-stat-foot">{footnote}</p> : null}
    </article>
  )
}
