import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { getWorkspace, setWorkspace, workspacesApi } from '../lib/api'
import { errorMessage } from '../hooks/useAsync'
import type { Workspace } from '../types'
import { useAuth } from './AuthContext'

interface WorkspaceContextValue {
  workspaces: Workspace[]
  current: Workspace | null
  loading: boolean
  error: string | null
  switchTo: (id: string) => void
  refresh: () => Promise<void>
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null)

/** Resolve the active workspace from a fetched list: prefer the locally stored
 * selection when it's still a workspace the user belongs to, else the server's
 * current, else the personal workspace, else the first entry. */
function resolveCurrent(list: Workspace[], serverCurrentId: string | null): Workspace | null {
  if (list.length === 0) return null
  const stored = getWorkspace()
  return (
    (stored && list.find((w) => w.id === stored)) ||
    (serverCurrentId && list.find((w) => w.id === serverCurrentId)) ||
    list.find((w) => w.kind === 'personal') ||
    list[0]
  )
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [current, setCurrent] = useState<Workspace | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setError(null)
      const res = await workspacesApi.list()
      const list = res.workspaces ?? []
      const active = resolveCurrent(list, res.current_workspace_id ?? null)
      setWorkspaces(list)
      setCurrent(active)
      // Keep the header in sync with what we resolved (may differ from storage).
      setWorkspace(active ? active.id : null)
    } catch (err) {
      setError(errorMessage(err))
      // Preserve the last known workspace during a transient outage. On the first
      // load these remain empty; on refresh, downstream requests keep their scope.
    }
  }, [])

  // Load once a user is present; clear everything on logout.
  useEffect(() => {
    let cancelled = false
    if (!user) {
      setWorkspaces([])
      setCurrent(null)
      setWorkspace(null)
      setError(null)
      setLoading(false)
      return
    }
    setLoading(true)
    const boot = async () => {
      await load()
      if (!cancelled) setLoading(false)
    }
    void boot()
    return () => {
      cancelled = true
    }
  }, [user, load])

  // Switching tenants re-scopes every page's data. Persist the choice, then do
  // a full reload — all page data is workspace-scoped and re-fetches on load,
  // so this is the simplest correct way to swap the whole app's context.
  const switchTo = useCallback(
    (id: string) => {
      if (id === current?.id) return
      setWorkspace(id)
      setCurrent(workspaces.find((w) => w.id === id) ?? current)
      window.location.reload()
    },
    [current, workspaces]
  )

  const refresh = useCallback(async () => {
    await load()
  }, [load])

  const value = useMemo<WorkspaceContextValue>(
    () => ({ workspaces, current, loading, error, switchTo, refresh }),
    [workspaces, current, loading, error, switchTo, refresh]
  )

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext)
  if (!ctx) throw new Error('useWorkspace must be used within a WorkspaceProvider')
  return ctx
}
