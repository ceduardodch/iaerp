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
}: {
  tabs: ReadonlyArray<{ value: T; label: string }>
  value: T
  onChange: (value: T) => void
  ariaLabel: string
}) {
  function move(event: React.KeyboardEvent<HTMLDivElement>) {
    const paso = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (!paso) return
    event.preventDefault()
    const actual = tabs.findIndex((tab) => tab.value === value)
    // Circular: desde la última la flecha derecha vuelve a la primera.
    const destino = tabs[(actual + paso + tabs.length) % tabs.length]
    if (!destino) return
    onChange(destino.value)
    document.getElementById(`tab-${destino.value}`)?.focus()
  }

  return (
    <div className="erp-tabs" role="tablist" aria-label={ariaLabel} onKeyDown={move}>
      {tabs.map((tab) => (
        <button
          key={tab.value}
          id={`tab-${tab.value}`}
          type="button"
          role="tab"
          aria-selected={tab.value === value}
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
