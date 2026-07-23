import { useAuth } from '../auth'

type Section = 'overview' | 'parties' | 'products' | 'invoices' | 'receivables' | 'organization' | 'crm'

const sections: Array<{ id: Section; label: string }> = [
  { id: 'overview', label: 'Resumen' },
  { id: 'parties', label: 'Contactos' },
  { id: 'products', label: 'Productos' },
  { id: 'invoices', label: 'Facturas' },
  { id: 'organization', label: 'Empresa' },
  { id: 'receivables', label: 'Cartera' },
  { id: 'crm', label: 'CRM' },
]

export function Sidebar({
  currentSection,
  onNavigate,
  organizationName,
  ruc,
}: {
  currentSection: Section
  onNavigate: (section: Section) => void
  organizationName: string
  ruc: string
}) {
  const auth = useAuth()

  return (
    <header className="app-header">
      <div className="app-header-inner">
        <strong className="app-brand">IAERP</strong>
        <nav className="app-nav" aria-label="Navegación principal">
          {sections.map((item) => (
            <button
              key={item.id}
              className={currentSection === item.id ? 'active' : ''}
              aria-current={currentSection === item.id ? 'page' : undefined}
              onClick={() => onNavigate(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="app-session">
          <span title={auth.displayName}>{organizationName} · RUC {ruc}</span>
          <button onClick={() => void auth.logout()}>Cerrar sesión</button>
        </div>
      </div>
    </header>
  )
}
