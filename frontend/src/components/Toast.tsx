import { CheckCircle2, Info, X, XCircle } from 'lucide-react'
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

type ToastTone = 'success' | 'error' | 'info'
interface Toast {
  id: number
  message: string
  tone: ToastTone
  leaving?: boolean
}

interface ToastContextValue {
  toast: (message: string, tone?: ToastTone) => void
  success: (message: string) => void
  error: (message: string) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

let counter = 0
const SHOW_MS = 4000
const EXIT_MS = 220

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timers = useRef(new Map<number, number>())

  const remove = useCallback((id: number) => {
    const t = timers.current.get(id)
    if (t) window.clearTimeout(t)
    timers.current.delete(id)
    // Two-phase exit: mark leaving (CSS animates out), then unmount.
    setToasts((list) => list.map((x) => (x.id === id ? { ...x, leaving: true } : x)))
    window.setTimeout(() => {
      setToasts((list) => list.filter((x) => x.id !== id))
    }, EXIT_MS)
  }, [])

  const toast = useCallback(
    (message: string, tone: ToastTone = 'info') => {
      const id = ++counter
      setToasts((t) => [...t, { id, message, tone }])
      timers.current.set(id, window.setTimeout(() => remove(id), SHOW_MS))
    },
    [remove]
  )

  const value = useMemo<ToastContextValue>(
    () => ({
      toast,
      success: (m: string) => toast(m, 'success'),
      error: (m: string) => toast(m, 'error'),
    }),
    [toast]
  )

  // Split by urgency so errors land in an assertive region (interrupt, never
  // dropped) and success/info in a polite one. Both regions are mounted from
  // first render — only their children change — so screen readers reliably
  // announce every toast (many mutations report ONLY via toast).
  const politeToasts = toasts.filter((t) => t.tone !== 'error')
  const errorToasts = toasts.filter((t) => t.tone === 'error')

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="vo-no-print pointer-events-none fixed inset-x-0 bottom-[max(1rem,env(safe-area-inset-bottom))] z-[60] flex flex-col items-center gap-2 px-4">
        <div aria-live="polite" aria-atomic="false" className="flex w-full flex-col items-center gap-2">
          {politeToasts.map((t) => (
            <ToastItem key={t.id} toast={t} onClose={() => remove(t.id)} />
          ))}
        </div>
        <div aria-live="assertive" aria-atomic="false" className="flex w-full flex-col items-center gap-2">
          {errorToasts.map((t) => (
            <ToastItem key={t.id} toast={t} onClose={() => remove(t.id)} />
          ))}
        </div>
      </div>
    </ToastContext.Provider>
  )
}

function ToastItem({ toast, onClose }: { toast: Toast; onClose: () => void }) {
  const tones: Record<ToastTone, { ring: string; icon: ReactNode }> = {
    success: { ring: 'border-success/40', icon: <CheckCircle2 size={18} className="text-success" /> },
    error: { ring: 'border-[color-mix(in_oklab,var(--danger)_50%,transparent)]', icon: <XCircle size={18} className="text-danger" /> },
    info: { ring: 'border-brand/40', icon: <Info size={18} className="text-brand" /> },
  }
  const cfg = tones[toast.tone]
  // No per-item live role: the permanent regions in ToastProvider own the
  // announcement, so a nested role here would double-announce.
  return (
    <div
      className={`pointer-events-auto flex w-full max-w-sm items-start gap-2.5 rounded-xl border ${cfg.ring} vo-card px-4 py-3 shadow-pop transition-all duration-200 ease-out ${
        toast.leaving ? 'translate-y-2 opacity-0' : 'animate-pop-in'
      }`}
    >
      <span className="mt-0.5 shrink-0">{cfg.icon}</span>
      <p className="flex-1 text-sm text-txt">{toast.message}</p>
      <button
        onClick={onClose}
        aria-label="Dismiss"
        className="-m-1.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-faint transition-colors hover:bg-surface2 hover:text-txt"
      >
        <X size={15} />
      </button>
    </div>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within a ToastProvider')
  return ctx
}
