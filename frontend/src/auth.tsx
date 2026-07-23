import Keycloak from 'keycloak-js'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type PropsWithChildren,
} from 'react'

import { configureApiTokenProvider } from './api'

type AuthState = {
  mode: 'dev' | 'oidc'
  loading: boolean
  authenticated: boolean
  displayName: string
  getToken: () => Promise<string>
  loginDev: (email: string, tenantId: string) => Promise<void>
  loginOidc: (organizationAlias: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)
const authMode: 'dev' | 'oidc' =
  import.meta.env.VITE_AUTH_MODE === 'oidc' ? 'oidc' : 'dev'
const apiUrl = import.meta.env.VITE_API_URL ?? '/api/v1'
const storageKey = 'iaerp.auth.v1'
// Alias de organización elegido en el login OIDC. El backend exige que el token
// traiga EXACTAMENTE una organización (scope `organization:<alias>`). Un usuario
// puede pertenecer a varias, así que hay que recordar cuál eligió y re-pedir ese
// scope en cada carga; si no, `check-sso` genera un token sin (o con varias)
// organización y el backend responde "Token must contain exactly one organization".
const orgAliasKey = 'iaerp.auth.org'

const keycloak = new Keycloak({
  url: import.meta.env.VITE_KEYCLOAK_URL ?? 'http://localhost:8080',
  realm: import.meta.env.VITE_KEYCLOAK_REALM ?? 'iaerp',
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? 'iaerp-web',
})

type StoredAuth = {
  token: string
  displayName: string
}

function readStoredAuth(): StoredAuth | null {
  try {
    const value = sessionStorage.getItem(storageKey)
    return value ? (JSON.parse(value) as StoredAuth) : null
  } catch {
    sessionStorage.removeItem(storageKey)
    return null
  }
}

export function AuthProvider({ children }: PropsWithChildren) {
  const [stored, setStored] = useState<StoredAuth | null>(() =>
    authMode === 'dev' ? readStoredAuth() : null,
  )
  const [loading, setLoading] = useState(authMode !== 'dev')
  const [keycloakReady, setKeycloakReady] = useState(false)

  useEffect(() => {
    if (authMode === 'dev') return

    const savedAlias = localStorage.getItem(orgAliasKey)
    void keycloak
      .init({
        onLoad: 'check-sso',
        pkceMethod: 'S256',
        checkLoginIframe: false,
        // Re-pide la organización elegida para que el token de `check-sso`
        // (recarga) traiga exactamente esa una; si no, el backend lo rechaza.
        scope: savedAlias ? `organization:${savedAlias}` : undefined,
      })
      .then((authenticated) => {
        // Red de seguridad: si hay sesión pero el token NO trae exactamente una
        // organización (sesión previa sin alias guardado, o usuario miembro de
        // varias), se trata como "no autenticado" para mostrar la pantalla de
        // elegir empresa, en vez de dejar que el backend responda 403
        // "Token must contain exactly one organization".
        const org = keycloak.tokenParsed?.organization as
          | Record<string, unknown>
          | undefined
        const hasExactlyOneOrg =
          !!org && typeof org === 'object' && Object.keys(org).length === 1
        setKeycloakReady(authenticated && hasExactlyOneOrg)
        setLoading(false)
      })
  }, [])

  async function loginDev(email: string, tenantId: string) {
    const response = await fetch(`${apiUrl}/dev/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, tenantId, scopes: [] }),
    })
    if (!response.ok) throw new Error('Usuario o empresa de desarrollo no válidos')
    const body = (await response.json()) as { accessToken: string }
    const displayName = email.split('@')[0] || 'Usuario'
    const next = { token: body.accessToken, displayName }
    sessionStorage.setItem(storageKey, JSON.stringify(next))
    setStored(next)
  }

  const getToken = useCallback(async (forceRefresh = false) => {
    if (authMode === 'dev') {
      if (!stored?.token) throw new Error('Sesión no disponible')
      return stored.token
    }
    await keycloak.updateToken(forceRefresh ? -1 : 30)
    if (!keycloak.token) throw new Error('Sesión no disponible')
    return keycloak.token
  }, [stored])

  useEffect(() => {
    configureApiTokenProvider(getToken)
    return () => configureApiTokenProvider(null)
  }, [getToken])

  async function loginOidc(organizationAlias: string) {
    const alias = organizationAlias.trim().toLowerCase()
    if (!/^[a-z0-9][a-z0-9-]{1,62}$/.test(alias)) {
      throw new Error('El alias de empresa no es válido')
    }
    // Se recuerda el alias para re-pedir el scope en cada `init`/refresh.
    localStorage.setItem(orgAliasKey, alias)
    await keycloak.login({
      redirectUri: window.location.origin,
      scope: `openid organization:${alias}`,
    })
  }

  async function logout() {
    if (authMode === 'dev') {
      sessionStorage.removeItem(storageKey)
      setStored(null)
      return
    }
    localStorage.removeItem(orgAliasKey)
    await keycloak.logout({ redirectUri: window.location.origin })
  }

  const displayName =
    stored?.displayName ??
    keycloak.tokenParsed?.name ??
    keycloak.tokenParsed?.preferred_username ??
    'Usuario'

  return (
    <AuthContext.Provider
      value={{
        mode: authMode,
        loading,
        authenticated: authMode === 'dev' ? Boolean(stored) : keycloakReady,
        displayName,
        getToken,
        loginDev,
        loginOidc,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

// oxlint-disable-next-line react/only-export-components
export function useAuth(): AuthState {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
