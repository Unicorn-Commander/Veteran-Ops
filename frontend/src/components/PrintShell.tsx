import { ArrowLeft, Printer } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

/** Standalone print-view chrome shared by Packet.tsx-style pages (no Shell
 * nav/header — just a back link + print button, then the printable page). */
export function PrintShell({
  backTo,
  backLabel,
  children,
}: {
  backTo: string
  backLabel: string
  children: ReactNode
}) {
  return (
    <div className="min-h-screen bg-bg">
      <div className="vo-no-print flex items-center justify-between border-b border-line px-4 py-3 sm:px-6">
        <Link to={backTo} className="inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-txt">
          <ArrowLeft size={14} /> {backLabel}
        </Link>
        <button onClick={() => window.print()} className="vo-btn-primary text-sm">
          <Printer size={14} /> Print
        </button>
      </div>
      <div className="vo-print-page mx-auto max-w-3xl px-6 py-10">{children}</div>
    </div>
  )
}
