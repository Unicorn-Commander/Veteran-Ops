import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../lib/api'

interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

interface UseAsyncResult<T> extends AsyncState<T> {
  reload: () => void
  setData: (updater: T | null | ((prev: T | null) => T | null)) => void
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return 'Something went wrong. Please try again.'
}

/**
 * Run an async loader on mount (and on dependency change), exposing loading,
 * error and data states plus a manual reload. The loader is wrapped so a stale
 * response from a superseded call is discarded.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []): UseAsyncResult<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, loading: true, error: null })
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  const setData = useCallback((updater: T | null | ((prev: T | null) => T | null)) => {
    setState((s) => ({
      ...s,
      data: typeof updater === 'function' ? (updater as (prev: T | null) => T | null)(s.data) : updater,
    }))
  }, [])

  useEffect(() => {
    let active = true
    setState((s) => ({ ...s, loading: true, error: null }))
    loader()
      .then((data) => {
        if (active) setState({ data, loading: false, error: null })
      })
      .catch((err) => {
        if (active) setState((s) => ({ ...s, loading: false, error: errorMessage(err) }))
      })
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { ...state, reload, setData }
}
