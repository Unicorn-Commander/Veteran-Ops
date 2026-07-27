import { Plus, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { filterLocationSuggestions } from '../lib/exposureLocations'

/**
 * Chip list + typeahead for exposure / deployment locations.
 * Free-text allowed; curated suggestions appear as you type (or on empty focus).
 */
export function LocationsTypeahead({
  locations,
  onChange,
  suggestedFromRecords = [],
}: {
  locations: string[]
  onChange: (next: string[]) => void
  /** Optional matches found in the veteran's records (shown first). */
  suggestedFromRecords?: string[]
}) {
  const [draft, setDraft] = useState('')
  const [open, setOpen] = useState(false)

  const suggestions = useMemo(() => {
    const curated = filterLocationSuggestions(draft, locations, 10)
    const fromRec = suggestedFromRecords.filter(
      (s) =>
        !locations.some((l) => l.toLowerCase() === s.toLowerCase()) &&
        (!draft.trim() || s.toLowerCase().includes(draft.trim().toLowerCase())),
    )
    // Records first, then curated (dedupe)
    const seen = new Set<string>()
    const out: { label: string; fromRecords: boolean }[] = []
    for (const s of fromRec) {
      const k = s.toLowerCase()
      if (seen.has(k)) continue
      seen.add(k)
      out.push({ label: s, fromRecords: true })
    }
    for (const s of curated) {
      const k = s.toLowerCase()
      if (seen.has(k)) continue
      seen.add(k)
      out.push({ label: s, fromRecords: false })
    }
    return out.slice(0, 12)
  }, [draft, locations, suggestedFromRecords])

  const add = (raw: string) => {
    const name = raw.trim()
    if (!name) return
    if (locations.some((l) => l.toLowerCase() === name.toLowerCase())) {
      setDraft('')
      return
    }
    onChange([...locations, name])
    setDraft('')
    setOpen(false)
  }

  const remove = (idx: number) => {
    onChange(locations.filter((_, i) => i !== idx))
  }

  return (
    <div className="space-y-2">
      <span className="vo-label">Locations</span>
      <p className="text-xs text-muted">
        Bases, countries, or theaters (e.g. Vietnam, Camp Lejeune, Iraq). Suggestions appear as you
        type; pick a chip or press Enter to add your own.
      </p>

      {locations.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {locations.map((loc, i) => (
            <span
              key={`${loc}-${i}`}
              className="inline-flex items-center gap-1 rounded-full border border-line bg-surface2 px-2.5 py-1 text-xs font-medium text-txt"
            >
              {loc}
              <button
                type="button"
                className="rounded-full p-0.5 text-muted hover:bg-surface hover:text-txt"
                aria-label={`Remove ${loc}`}
                onClick={() => remove(i)}
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="relative">
        <div className="flex gap-2">
          <input
            className="vo-input min-w-0 flex-1"
            placeholder="Start typing a place…"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value)
              setOpen(true)
            }}
            onFocus={() => setOpen(true)}
            onBlur={() => {
              // Delay so click on suggestion registers
              window.setTimeout(() => setOpen(false), 150)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                if (suggestions[0] && draft.trim()) {
                  // Prefer first match if typing a prefix; else free text
                  const exact = suggestions.find(
                    (s) => s.label.toLowerCase() === draft.trim().toLowerCase(),
                  )
                  add(exact?.label ?? (draft.includes(',') ? draft.split(',')[0] : draft))
                } else if (draft.trim()) {
                  add(draft)
                }
              } else if (e.key === 'Escape') {
                setOpen(false)
              }
            }}
            autoComplete="off"
          />
          <button
            type="button"
            className="vo-btn-secondary shrink-0"
            onClick={() => add(draft)}
            disabled={!draft.trim()}
          >
            <Plus size={15} /> Add
          </button>
        </div>

        {open && suggestions.length > 0 && (
          <ul
            className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-control border border-line bg-surface py-1 shadow-lg"
            role="listbox"
          >
            {suggestions.map((s) => (
              <li key={s.label}>
                <button
                  type="button"
                  role="option"
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm text-txt hover:bg-surface2"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => add(s.label)}
                >
                  <span>{s.label}</span>
                  {s.fromRecords && (
                    <span className="text-micro font-medium text-brand">In your records</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {suggestedFromRecords.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
          <span className="text-micro text-faint">From records:</span>
          {suggestedFromRecords
            .filter((s) => !locations.some((l) => l.toLowerCase() === s.toLowerCase()))
            .slice(0, 8)
            .map((s) => (
              <button
                key={s}
                type="button"
                className="vo-chip text-micro hover:ring-1 hover:ring-brand/40"
                onClick={() => add(s)}
              >
                <Plus size={10} /> {s}
              </button>
            ))}
        </div>
      )}
    </div>
  )
}
