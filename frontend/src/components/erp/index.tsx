import type {
  ButtonHTMLAttributes,
  FormEventHandler,
  PropsWithChildren,
  ReactNode,
} from 'react'

/** `icon` es un botón cuadrado que solo lleva un icono; exige `aria-label`. */
type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success' | 'icon'

type ErpButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
}

export function ErpButton({
  variant = 'secondary',
  className = '',
  type = 'button',
  ...props
}: ErpButtonProps) {
  return (
    <button
      {...props}
      type={type}
      className={`erp-button erp-button-${variant} ${className}`.trim()}
    />
  )
}

export function ErpPageHeader({
  eyebrow,
  title,
  subtitle,
  meta,
  actions,
}: {
  eyebrow: string
  title: string
  subtitle?: string
  meta?: ReactNode
  actions?: ReactNode
}) {
  return (
    <header className="erp-page-header">
      <div className="erp-page-heading">
        <p className="kicker">{eyebrow}</p>
        <h1>{title}</h1>
        {subtitle ? <p className="erp-page-subtitle">{subtitle}</p> : null}
      </div>
      {meta || actions ? (
        <div className="erp-page-header-side">
          {meta ? <div className="erp-page-meta">{meta}</div> : null}
          {actions ? <div className="erp-page-actions">{actions}</div> : null}
        </div>
      ) : null}
    </header>
  )
}

export function ErpToolbar({
  children,
  ariaLabel = 'Herramientas del listado',
}: PropsWithChildren<{ ariaLabel?: string }>) {
  return (
    <section className="erp-toolbar" aria-label={ariaLabel}>
      {children}
    </section>
  )
}

/**
 * Listado tabular estándar.
 *
 * El mismo armado —`table-wrap` con `tabIndex` para poder desplazar la tabla
 * con el teclado, `erp-responsive-table`, cabecera y cuerpo— estaba copiado en
 * 17 lugares. Cada copia podía olvidarse el `aria-label`, el `scope` de las
 * cabeceras o el estado vacío, y de hecho varias lo hacían.
 */
export function ErpDataTable<T>({
  ariaLabel,
  columns,
  rows,
  rowKey,
  emptyState,
  className = '',
}: {
  ariaLabel: string
  columns: ReadonlyArray<{
    header: ReactNode
    cell: (row: T) => ReactNode
    className?: string
    mobileLabel?: string
  }>
  rows: readonly T[]
  /** Recibe el índice porque hay listados sin identificador estable. */
  rowKey: (row: T, index: number) => string
  emptyState?: ReactNode
  className?: string
}) {
  if (!rows.length && emptyState) return <>{emptyState}</>
  return (
    <div className="table-wrap" tabIndex={0} aria-label={ariaLabel}>
      <table className={`erp-responsive-table ${className}`.trim()}>
        <thead>
          <tr>
            {columns.map((column, index) => (
              <th key={index} scope="col" className={column.className}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey(row, index)}>
              {columns.map((column, index) => (
                <td
                  key={index}
                  className={column.className}
                  data-label={column.mobileLabel}
                >
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * Pestañas con la semántica que espera un lector de pantalla.
 *
 * Las pantallas venían pintando botones sueltos: se anunciaban como "botón" en
 * vez de "pestaña 2 de 3", no decían cuál estaba activa y obligaban a tabular
 * por cada una. Un `tablist` real navega con flechas y solo la activa entra en
 * el orden de tabulación (patrón ARIA de pestañas).
 */
export function ErpTabs<T extends string>({
  tabs,
  value,
  onChange,
  ariaLabel,
  idPrefix = 'tab',
  panelIdPrefix,
}: {
  tabs: ReadonlyArray<{ value: T; label: string }>
  value: T
  onChange: (value: T) => void
  ariaLabel: string
  idPrefix?: string
  panelIdPrefix?: string
}) {
  function move(event: React.KeyboardEvent<HTMLDivElement>) {
    const actual = tabs.findIndex((tab) => tab.value === value)
    let destinationIndex: number | null = null
    if (event.key === 'ArrowRight') destinationIndex = (actual + 1) % tabs.length
    if (event.key === 'ArrowLeft') destinationIndex = (actual - 1 + tabs.length) % tabs.length
    if (event.key === 'Home') destinationIndex = 0
    if (event.key === 'End') destinationIndex = tabs.length - 1
    if (destinationIndex === null) return
    event.preventDefault()
    const destino = tabs[destinationIndex]
    if (!destino) return
    onChange(destino.value)
    document.getElementById(`${idPrefix}-${destino.value}`)?.focus()
  }

  return (
    <div className="erp-tabs" role="tablist" aria-label={ariaLabel} onKeyDown={move}>
      {tabs.map((tab) => (
        <button
          key={tab.value}
          id={`${idPrefix}-${tab.value}`}
          type="button"
          role="tab"
          aria-selected={tab.value === value}
          aria-controls={panelIdPrefix ? `${panelIdPrefix}-${tab.value}` : undefined}
          tabIndex={tab.value === value ? 0 : -1}
          className={`erp-tab${tab.value === value ? ' erp-tab-active' : ''}`}
          onClick={() => onChange(tab.value)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

export function ErpPanel({
  title,
  count,
  actions,
  children,
  className = '',
}: PropsWithChildren<{
  title: string
  count?: number | string
  actions?: ReactNode
  className?: string
}>) {
  return (
    <section className={`data-panel erp-panel ${className}`.trim()}>
      <div className="panel-heading">
        <h2>{title}</h2>
        <div className="erp-panel-heading-side">
          {count !== undefined ? <span>{count} registros</span> : null}
          {actions}
        </div>
      </div>
      {children}
    </section>
  )
}

export function ErpMetricGrid({
  children,
  ariaLabel = 'Indicadores',
}: PropsWithChildren<{ ariaLabel?: string }>) {
  return <section className="metric-grid" aria-label={ariaLabel}>{children}</section>
}

export function ErpFormPanel({
  eyebrow,
  title,
  submitLabel = 'Guardar',
  pendingLabel = 'Guardando…',
  pending = false,
  submitDisabled = false,
  error,
  onSubmit,
  onCancel,
  children,
}: PropsWithChildren<{
  eyebrow: string
  title: string
  submitLabel?: string
  pendingLabel?: string
  pending?: boolean
  submitDisabled?: boolean
  error?: string
  onSubmit: FormEventHandler<HTMLFormElement>
  onCancel: () => void
}>) {
  return (
    <section className="form-panel erp-form-panel erp-full-page-form" aria-labelledby="erp-form-title">
      <p className="section-number">{eyebrow}</p>
      <h2 id="erp-form-title">{title}</h2>
      <form onSubmit={onSubmit}>
        <div className="erp-form-fields">{children}</div>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <div className="erp-form-actions">
          <ErpButton variant="secondary" onClick={onCancel} disabled={pending}>
            Cancelar
          </ErpButton>
          <ErpButton variant="primary" type="submit" disabled={pending || submitDisabled}>
            {pending ? pendingLabel : submitLabel}
          </ErpButton>
        </div>
      </form>
    </section>
  )
}

export function ErpStatusBadge({
  children,
  tone = 'neutral',
}: PropsWithChildren<{ tone?: 'neutral' | 'success' | 'warning' | 'danger' }>) {
  return <span className={`erp-status erp-status-${tone}`}>{children}</span>
}

export function ErpEmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="erp-empty-state">
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  )
}

export function ErpActionCell({ children }: PropsWithChildren) {
  return <div className="erp-action-cell">{children}</div>
}
