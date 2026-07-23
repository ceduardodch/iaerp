import { useAuth } from '../auth'

type Section = 'overview' | 'parties' | 'products' | 'invoices' | 'receivables' | 'organization' | 'crm'

const sections: Array<{
  id: Section
  label: string
  eyebrow: string
}> = [
  { id: 'overview', label: 'Resumen', eyebrow: '01' },
  { id: 'parties', label: 'Contactos', eyebrow: '02' },
  { id: 'products', label: 'Productos', eyebrow: '03' },
  { id: 'invoices', label: 'Facturas', eyebrow: '04' },
  { id: 'organization', label: 'Empresa', eyebrow: '05' },
  { id: 'receivables', label: 'Cartera', eyebrow: '06' },
  { id: 'crm', label: 'CRM', eyebrow: '07' },
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
        {sections.map((item) => {
          return (
            <button
              key={item.id}
              className={currentSection === item.id ? 'active' : ''}
              aria-current={currentSection === item.id ? 'page' : undefined}
              aria-label={`${item.eyebrow} ${item.label}`}
              onClick={() => onNavigate(item.id)}
            >
              {item.label}
            </button>
          )
        })}
        </nav>
        <div className="app-session">
          <span title={auth.displayName}>{organizationName} · RUC {ruc}</span>
          <button onClick={() => void auth.logout()}>Cerrar sesión</button>
        </div>
      </div>
    </header>
  )
}
