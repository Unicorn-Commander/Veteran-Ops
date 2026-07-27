import { Plus, Trash2 } from 'lucide-react'
import { Checkbox } from './ui'
import type { ServicePeriod } from '../types'

// Shared by Profile.tsx and the onboarding wizard (WAVE2-SPEC §1) — one
// service-period editor, not two copies drifting apart.

export const BRANCHES = ['Army', 'Navy', 'Air Force', 'Marine Corps', 'Space Force', 'Coast Guard']
export const COMPONENTS = ['Active Duty', 'Reserve', 'National Guard']
export const DISCHARGES = [
  'Honorable',
  'General (Under Honorable Conditions)',
  'Other Than Honorable',
  'Bad Conduct',
  'Dishonorable',
  'Uncharacterized',
]

export function emptyServicePeriod(): ServicePeriod {
  return { branch: BRANCHES[0], component: COMPONENTS[0], start_date: null, end_date: null, discharge_character: DISCHARGES[0] }
}

export function ServicePeriodsEditor({
  periods,
  combatService,
  onAdd,
  onUpdate,
  onRemove,
  onCombatServiceChange,
}: {
  periods: ServicePeriod[]
  combatService: boolean
  onAdd: () => void
  onUpdate: (idx: number, patch: Partial<ServicePeriod>) => void
  onRemove: (idx: number) => void
  onCombatServiceChange: (value: boolean) => void
}) {
  return (
    <div className="space-y-3">
      {periods.length === 0 && <p className="text-sm text-muted">No service periods added yet.</p>}
      {periods.map((period, idx) => (
        <div key={idx} className="rounded-control border border-line bg-surface2 p-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-sm">
              <span className="vo-label">Branch</span>
              <select className="vo-input" value={period.branch} onChange={(e) => onUpdate(idx, { branch: e.target.value })}>
                {BRANCHES.map((b) => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="vo-label">Component</span>
              <select className="vo-input" value={period.component} onChange={(e) => onUpdate(idx, { component: e.target.value })}>
                {COMPONENTS.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="vo-label">Start date</span>
              <input
                type="date"
                className="vo-input"
                value={period.start_date ?? ''}
                onChange={(e) => onUpdate(idx, { start_date: e.target.value || null })}
              />
            </label>
            <label className="text-sm">
              <span className="vo-label">End date</span>
              <input
                type="date"
                className="vo-input"
                value={period.end_date ?? ''}
                onChange={(e) => onUpdate(idx, { end_date: e.target.value || null })}
              />
            </label>
          </div>
          <div className="mt-3 flex items-end justify-between gap-3">
            <label className="flex-1 text-sm">
              <span className="vo-label">Discharge character</span>
              <select
                className="vo-input"
                value={period.discharge_character}
                onChange={(e) => onUpdate(idx, { discharge_character: e.target.value })}
              >
                {DISCHARGES.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </label>
            <button
              onClick={() => onRemove(idx)}
              className="vo-icon-btn vo-btn-ghost shrink-0 text-danger hover:bg-danger-soft"
              aria-label="Remove service period"
              type="button"
            >
              <Trash2 size={16} />
            </button>
          </div>
        </div>
      ))}

      <div className="flex items-center justify-between gap-3 pt-1">
        <Checkbox
          checked={combatService}
          onChange={(e) => onCombatServiceChange(e.target.checked)}
          label="I had combat service"
          className="flex-1"
        />
        <button onClick={onAdd} className="vo-btn-secondary text-xs" type="button">
          <Plus size={14} /> Add period
        </button>
      </div>
    </div>
  )
}
