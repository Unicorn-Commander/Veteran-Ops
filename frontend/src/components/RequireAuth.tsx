import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Wordmark } from './Brand'
import { Spinner } from './ui'

/** Full-screen brand splash while the session is resolving. */
function BootSplash() {
  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-4">
      <Wordmark size={48} />
      <span className="flex items-center gap-2 text-sm text-muted">
        <Spinner />
        Loading Rating Raider…
      </span>
    </div>
  )
}

/** Gates the authenticated app: waits for boot, redirects unauthenticated users to /login. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <BootSplash />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />

  return <>{children}</>
}
