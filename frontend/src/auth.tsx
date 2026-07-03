import Keycloak from 'keycloak-js'
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type PropsWithChildren,
} from 'react'

type AuthState = {
  loading: boolean
  authenticated: boolean
  displayName: string
  getToken: () => Promise<string>
  loginDev: (email: string, tenantId: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)
const authMode = import.meta.env.VITE_AUTH_MODE ?? 'dev'
const apiUrl = import.meta.env.VITE_API_URL ?? '/api/v1'
const storageKey = 'iaerp.auth.v1'

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

    void keycloak
      .init({
        onLoad: 'login-required',
        pkceMethod: 'S256',
        scope: 'openid organization',
        checkLoginIframe: false,
      })
      .then((authenticated) => {
        setKeycloakReady(authenticated)
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
    const next = { token: body.accessToken, displayName: email.split('@')[0] }
    sessionStorage.setItem(storageKey, JSON.stringify(next))
    setStored(next)
  }

  async function getToken() {
    if (authMode === 'dev') {
      if (!stored?.token) throw new Error('Sesión no disponible')
      return stored.token
    }
    await keycloak.updateToken(30)
    if (!keycloak.token) throw new Error('Sesión no disponible')
    return keycloak.token
  }

  async function logout() {
    if (authMode === 'dev') {
      sessionStorage.removeItem(storageKey)
      setStored(null)
      return
    }
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
        loading,
        authenticated: authMode === 'dev' ? Boolean(stored) : keycloakReady,
        displayName,
        getToken,
        loginDev,
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
