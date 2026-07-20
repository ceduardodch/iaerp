import { useState, useEffect } from 'react'
import {
  LayoutDashboard,
  Users,
  Package,
  FileText,
  Building2,
  DollarSign,
  TrendingUp,
} from 'lucide-react'
import { useAuth } from '../auth'

type Section = 'overview' | 'parties' | 'products' | 'invoices' | 'receivables' | 'organization' | 'crm'

const sections: Array<{
  id: Section
  label: string
  eyebrow: string
  icon: typeof LayoutDashboard
}> = [
  { id: 'overview', label: 'Resumen', eyebrow: '01', icon: LayoutDashboard },
  { id: 'parties', label: 'Contactos', eyebrow: '02', icon: Users },
  { id: 'products', label: 'Productos', eyebrow: '03', icon: Package },
  { id: 'invoices', label: 'Facturas', eyebrow: '04', icon: FileText },
  { id: 'organization', label: 'Empresa', eyebrow: '05', icon: Building2 },
  { id: 'receivables', label: 'Cartera', eyebrow: '06', icon: DollarSign },
  { id: 'crm', label: 'CRM', eyebrow: '07', icon: TrendingUp },
]

const STORAGE_KEY = 'sidebar-collapsed'

export function Sidebar({
  currentSection,
  onNavigate,
}: {
  currentSection: Section
  onNavigate: (section: Section) => void
}) {
  const auth = useAuth()
  const [collapsed, setCollapsed] = useState(() => {
    // Initialize from localStorage
    try {
      return localStorage.getItem(STORAGE_KEY) === 'true'
    } catch {
      return false
    }
  })

  // Sync to localStorage on change
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(collapsed))
    } catch {
      // Ignore localStorage errors
    }
  }, [collapsed])

  // Add/remove collapsed class from app-shell
  useEffect(() => {
    const appShell = document.querySelector('.app-shell')
    if (appShell) {
      if (collapsed) {
        appShell.classList.add('sidebar-collapsed')
      } else {
        appShell.classList.remove('sidebar-collapsed')
      }
    }
  }, [collapsed])

  function toggleCollapse() {
    setCollapsed((current) => !current)
  }

  return (
    <aside className={`sidebar ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <div className="sidebar-header">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            IA
          </span>
          {!collapsed ? (
            <div>
              <strong>IAERP</strong>
              <small>Finanzas aumentadas</small>
            </div>
          ) : null}
        </div>
        <button
          className="sidebar-toggle"
          onClick={toggleCollapse}
          aria-label={collapsed ? 'Expandir menú' : 'Contraer menú'}
          aria-pressed={collapsed}
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 20 20"
            fill="none"
            aria-hidden="true"
          >
            {collapsed ? (
              <path
                d="M12.5 15L8 10L12.5 5"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ) : (
              <path
                d="M7.5 5L12 10L7.5 15"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            )}
          </svg>
        </button>
      </div>

      <nav aria-label="Navegación principal">
        {sections.map((item) => {
          const Icon = item.icon
          return (
            <button
              key={item.id}
              className={currentSection === item.id ? 'active' : ''}
              aria-current={currentSection === item.id ? 'page' : undefined}
              onClick={() => onNavigate(item.id)}
              title={collapsed ? item.label : undefined}
            >
              {collapsed ? (
                <Icon size={20} strokeWidth={2} />
              ) : (
                <>
                  <span>{item.eyebrow}</span>
                  {item.label}
                </>
              )}
            </button>
          )
        })}
      </nav>

      {!collapsed ? (
        <div className="sidebar-footer">
          <span
            className="avatar"
            aria-hidden="true"
          >
            {auth.displayName.slice(0, 2).toUpperCase()}
          </span>
          <div>
            <strong>{auth.displayName}</strong>
            <button onClick={() => void auth.logout()}>Cerrar sesión</button>
          </div>
        </div>
      ) : null}
    </aside>
  )
}
