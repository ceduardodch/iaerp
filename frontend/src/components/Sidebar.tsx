import { ChevronDown, Menu } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { useAuth } from '../auth'
import { ErpModal } from './erp/ErpModal'

export type Section = 'overview' | 'parties' | 'catalogs' | 'invoices' | 'purchases' | 'receivables' | 'organization' | 'contracts' | 'crm' | 'tax'

type NavigationItem = { id: Section; label: string }
type NavigationGroup = { id: string; label: string; items: NavigationItem[] }

const overviewItem: NavigationItem = { id: 'overview', label: 'Resumen' }

const navigationGroups: NavigationGroup[] = [
  {
    id: 'commercial',
    label: 'Comercial',
    items: [
      { id: 'crm', label: 'CRM' },
      { id: 'parties', label: 'Contactos' },
      { id: 'contracts', label: 'Contratos' },
    ],
  },
  {
    id: 'operations',
    label: 'Operaciones',
    items: [
      { id: 'invoices', label: 'Facturas' },
      { id: 'receivables', label: 'Cartera' },
      { id: 'purchases', label: 'Compras' },
      { id: 'tax', label: 'Tributario' },
    ],
  },
  {
    id: 'administration',
    label: 'Administración',
    items: [
      { id: 'catalogs', label: 'Catálogos' },
      { id: 'organization', label: 'Empresa' },
    ],
  },
]

const allItems = [overviewItem, ...navigationGroups.flatMap((group) => group.items)]

function NavigationButton({
  item,
  currentSection,
  onSelect,
}: {
  item: NavigationItem
  currentSection: Section
  onSelect: (section: Section) => void
}) {
  const active = currentSection === item.id
  return (
    <button
      type="button"
      className={active ? 'active' : ''}
      aria-current={active ? 'page' : undefined}
      onClick={() => onSelect(item.id)}
    >
      {item.label}
    </button>
  )
}

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
  const navigationRef = useRef<HTMLElement>(null)
  const groupTriggerRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  const [openGroup, setOpenGroup] = useState<string | null>(null)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const currentItem = allItems.find((item) => item.id === currentSection) ?? overviewItem

  useEffect(() => {
    function closeDesktopMenus(event: MouseEvent) {
      if (!navigationRef.current?.contains(event.target as Node)) setOpenGroup(null)
    }

    function closeWithEscape(event: KeyboardEvent) {
      if (event.key !== 'Escape' || !openGroup) return
      event.preventDefault()
      const trigger = groupTriggerRefs.current[openGroup]
      setOpenGroup(null)
      window.requestAnimationFrame(() => trigger?.focus())
    }

    document.addEventListener('mousedown', closeDesktopMenus)
    document.addEventListener('keydown', closeWithEscape)
    return () => {
      document.removeEventListener('mousedown', closeDesktopMenus)
      document.removeEventListener('keydown', closeWithEscape)
    }
  }, [openGroup])

  function selectSection(section: Section) {
    setOpenGroup(null)
    setMobileMenuOpen(false)
    onNavigate(section)
  }

  return (
    <header className="app-header">
      <div className="app-header-inner">
        <strong className="app-brand">IAERP</strong>
        <span className="app-current-section" aria-hidden="true">{currentItem.label}</span>

        <nav ref={navigationRef} className="app-nav" aria-label="Navegación principal">
          <NavigationButton item={overviewItem} currentSection={currentSection} onSelect={selectSection} />
          {navigationGroups.map((group) => {
            const groupActive = group.items.some((item) => item.id === currentSection)
            const expanded = openGroup === group.id
            return (
              <div className="app-nav-group" key={group.id}>
                <button
                  ref={(element) => { groupTriggerRefs.current[group.id] = element }}
                  type="button"
                  className={groupActive ? 'group-active' : ''}
                  aria-expanded={expanded}
                  aria-controls={`nav-group-${group.id}`}
                  onClick={() => setOpenGroup(expanded ? null : group.id)}
                >
                  {group.label}
                  <ChevronDown aria-hidden="true" size={16} />
                </button>
                {expanded ? (
                  <div id={`nav-group-${group.id}`} className="app-nav-group-menu" aria-label={group.label}>
                    {group.items.map((item) => (
                      <NavigationButton key={item.id} item={item} currentSection={currentSection} onSelect={selectSection} />
                    ))}
                  </div>
                ) : null}
              </div>
            )
          })}
        </nav>

        <div className="app-session">
          <span title={auth.displayName}>{organizationName} · RUC {ruc}</span>
          <button type="button" onClick={() => void auth.logout()}>Cerrar sesión</button>
        </div>

        <button
          type="button"
          className="app-menu-button"
          aria-haspopup="dialog"
          aria-expanded={mobileMenuOpen}
          onClick={() => setMobileMenuOpen(true)}
        >
          <Menu aria-hidden="true" size={20} />
          Menú
        </button>
      </div>

      {mobileMenuOpen ? (
        <ErpModal title="Menú principal" onClose={() => setMobileMenuOpen(false)} variant="drawer" closeLabel="Cerrar menú">
          <nav className="mobile-navigation" aria-label="Navegación principal móvil">
            <section aria-labelledby="mobile-nav-overview">
              <h3 id="mobile-nav-overview">Inicio</h3>
              <NavigationButton item={overviewItem} currentSection={currentSection} onSelect={selectSection} />
            </section>
            {navigationGroups.map((group) => (
              <section key={group.id} aria-labelledby={`mobile-nav-${group.id}`}>
                <h3 id={`mobile-nav-${group.id}`}>{group.label}</h3>
                {group.items.map((item) => (
                  <NavigationButton key={item.id} item={item} currentSection={currentSection} onSelect={selectSection} />
                ))}
              </section>
            ))}
          </nav>
          <div className="mobile-navigation-session">
            <strong>{organizationName}</strong>
            <span>RUC {ruc}</span>
            <button type="button" onClick={() => void auth.logout()}>Cerrar sesión</button>
          </div>
        </ErpModal>
      ) : null}
    </header>
  )
}
