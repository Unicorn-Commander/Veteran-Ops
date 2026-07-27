import { Building2, Check, ChevronDown, Plus, User as UserIcon } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useWorkspace } from '../context/WorkspaceContext'
import type { OrgRole, Workspace } from '../types'
import { cx } from './ui'

const ROLE_LABELS: Record<OrgRole, string> = {
  owner: 'Owner',
  admin: 'Admin',
  staff: 'Staff',
  member: 'Member',
}

/** Personal workspaces get a person; teams get a building. */
function WorkspaceIcon({ kind, size = 16 }: { kind: Workspace['kind']; size?: number }) {
  const Icon = kind === 'personal' ? UserIcon : Building2
  return <Icon size={size} className="shrink-0" aria-hidden />
}

export function WorkspaceSwitcher() {
  const { workspaces, current, switchTo } = useWorkspace()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuId = useId()

  const close = useCallback(() => setOpen(false), [])

  // Close on outside-click and Escape while open; return focus to the trigger.
  useEffect(() => {
    if (!open) return
    const onPointer = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        setOpen(false)
        rootRef.current?.querySelector<HTMLButtonElement>('[data-ws-trigger]')?.focus()
      }
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [open])

  // Move focus into the menu when it opens (to the active row, else the first).
  useEffect(() => {
    if (!open) return
    const menu = menuRef.current
    if (!menu) return
    const target =
      menu.querySelector<HTMLElement>('[data-ws-item][aria-checked="true"]') ??
      menu.querySelector<HTMLElement>('[data-ws-item]')
    target?.focus()
  }, [open])

  // Roving arrow-key navigation across the menu's items.
  const onMenuKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[data-ws-item]') ?? []
    )
    if (items.length === 0) return
    e.preventDefault()
    const idx = items.indexOf(document.activeElement as HTMLElement)
    let next = 0
    if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = items.length - 1
    else if (e.key === 'ArrowDown') next = idx < 0 ? 0 : (idx + 1) % items.length
    else next = idx <= 0 ? items.length - 1 : idx - 1
    items[next]?.focus()
  }

  // Nothing to render if we have no workspaces at all (single-tenant/older backend).
  if (workspaces.length === 0) return null

  // Only one workspace: a static, non-interactive label — nothing to switch to.
  if (workspaces.length < 2) {
    const only = current ?? workspaces[0]
    return (
      <div
        className="hidden items-center gap-2 rounded-control border border-line bg-surface2 px-2.5 py-1.5 text-sm text-muted sm:flex"
        title={only.name}
      >
        <WorkspaceIcon kind={only.kind} />
        <span className="max-w-[10rem] truncate font-medium text-txt">{only.name}</span>
      </div>
    )
  }

  const active = current ?? workspaces[0]

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        data-ws-trigger
        onClick={() => setOpen((v) => !v)}
        className={cx(
          'flex items-center gap-2 rounded-control border border-line bg-surface2 px-2.5 py-1.5 text-sm font-medium text-txt transition-colors duration-150 hover:border-line2 hover:bg-surface',
          open && 'border-line2 bg-surface'
        )}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`Current workspace: ${active.name}. Switch workspace`}
      >
        <WorkspaceIcon kind={active.kind} />
        <span className="max-w-[8rem] truncate sm:max-w-[12rem]">{active.name}</span>
        <ChevronDown
          size={15}
          className={cx('shrink-0 text-muted transition-transform duration-200', open && 'rotate-180')}
          aria-hidden
        />
      </button>

      {open && (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label="Switch workspace"
          onKeyDown={onMenuKeyDown}
          className="animate-pop-in absolute right-0 z-50 mt-2 w-72 origin-top-right overflow-hidden rounded-2xl border border-line bg-surface shadow-pop"
        >
          <div className="px-3 pb-1.5 pt-3">
            <p className="text-micro font-semibold uppercase tracking-wider text-faint">Workspaces</p>
          </div>
          <ul className="max-h-[min(60vh,22rem)] overflow-y-auto px-1.5 pb-1.5">
            {workspaces.map((ws) => {
              const isActive = ws.id === active.id
              return (
                <li key={ws.id}>
                  <button
                    type="button"
                    role="menuitemradio"
                    aria-checked={isActive}
                    data-ws-item
                    onClick={() => {
                      close()
                      switchTo(ws.id)
                    }}
                    className={cx(
                      'group flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-left text-sm transition-colors duration-150',
                      isActive ? 'bg-surface2 text-txt' : 'text-muted hover:bg-surface2 hover:text-txt'
                    )}
                  >
                    <WorkspaceIcon kind={ws.kind} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-txt">{ws.name}</span>
                      <span className="block truncate text-xs text-muted">
                        {ws.kind === 'personal' ? 'Personal' : ROLE_LABELS[ws.role]}
                      </span>
                    </span>
                    {ws.kind === 'org' && (
                      <span className="vo-chip shrink-0 !px-2 !py-0.5 text-micro capitalize">
                        {ROLE_LABELS[ws.role]}
                      </span>
                    )}
                    <Check
                      size={16}
                      className={cx('shrink-0 text-brand', isActive ? 'opacity-100' : 'opacity-0')}
                      aria-hidden
                    />
                  </button>
                </li>
              )
            })}
          </ul>
          <div className="border-t border-line p-1.5">
            <Link
              to="/teams"
              role="menuitem"
              data-ws-item
              onClick={close}
              className="flex items-center gap-2.5 rounded-control px-2.5 py-2 text-sm font-medium text-muted transition-colors duration-150 hover:bg-surface2 hover:text-txt"
            >
              <Plus size={16} className="shrink-0" aria-hidden />
              Manage teams
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
