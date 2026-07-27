import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  auth as authApi,
  clearToken,
  getToken,
  setToken,
  setUnauthorizedHandler,
} from '../lib/api'
import type { User } from '../types'

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  loginWithToken: (token: string) => Promise<void>
  register: (email: string, password: string, fullName: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const logout = useCallback(() => {
    clearToken()
    setUser(null)
  }, [])

  // Wire the api layer's 401 handler so an expired token logs the user out.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearToken()
      setUser(null)
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  // On mount, if we have a token, resolve the current user.
  useEffect(() => {
    let cancelled = false
    const boot = async () => {
      if (!getToken()) {
        setLoading(false)
        return
      }
      try {
        const me = await authApi.me()
        if (!cancelled) setUser(me)
      } catch {
        if (!cancelled) {
          clearToken()
          setUser(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void boot()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const res = await authApi.login({ email, password })
    setToken(res.access_token)
    setUser(res.user)
  }, [])

  // SSO: the backend has already validated the identity + entitlement and
  // minted a native session token; store it and resolve the user.
  const loginWithToken = useCallback(async (token: string) => {
    setToken(token)
    const me = await authApi.me()
    setUser(me)
  }, [])

  const register = useCallback(async (email: string, password: string, fullName: string) => {
    const res = await authApi.register({ email, password, full_name: fullName })
    setToken(res.access_token)
    setUser(res.user)
  }, [])

  const refresh = useCallback(async () => {
    const me = await authApi.me()
    setUser(me)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, login, loginWithToken, register, logout, refresh }),
    [user, loading, login, loginWithToken, register, logout, refresh]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
