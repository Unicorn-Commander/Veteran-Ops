import { Checkbox } from './ui'
import { LocationsTypeahead } from './LocationsTypeahead'
import type { Exposures } from '../types'

// Shared by Profile.tsx and the onboarding wizard (WAVE2-SPEC §1).

function ExposureCheckbox({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return <Checkbox checked={checked} onChange={(e) => onChange(e.target.checked)} label={label} description={hint} />
}

export function ExposuresEditor({
  exposures,
  locationsText,
  onExposureChange,
  onLocationsTextChange,
  locations,
  onLocationsChange,
  suggestedLocationsFromRecords = [],
  compact = false,
}: {
  exposures: Exposures
  /** @deprecated Prefer locations + onLocationsChange chips; kept for onboarding. */
  locationsText?: string
  onExposureChange: <K extends keyof Exposures>(key: K, value: Exposures[K]) => void
  onLocationsTextChange?: (text: string) => void
  locations?: string[]
  onLocationsChange?: (next: string[]) => void
  suggestedLocationsFromRecords?: string[]
  /** Onboarding shows a one-line "why" per program; Profile keeps it terser. */
  compact?: boolean
}) {
  const useChips = typeof onLocationsChange === 'function' && Array.isArray(locations)

  return (
    <div className="space-y-3">
      <ExposureCheckbox
        label="Burn pits / airborne hazards (PACT Act)"
        hint={compact ? undefined : 'Burn pits, sand/dust, oil-well fires — 2022 PACT Act presumptive list.'}
        checked={exposures.burn_pits}
        onChange={(v) => onExposureChange('burn_pits', v)}
      />
      <ExposureCheckbox
        label="Agent Orange"
        hint={compact ? undefined : 'Herbicide exposure — Vietnam, Korean DMZ, and other listed locations/dates.'}
        checked={exposures.agent_orange}
        onChange={(v) => onExposureChange('agent_orange', v)}
      />
      <ExposureCheckbox
        label="Gulf War service"
        hint={compact ? undefined : 'Southwest Asia theater service — undiagnosed illness / chronic multisymptom presumptions.'}
        checked={exposures.gulf_war}
        onChange={(v) => onExposureChange('gulf_war', v)}
      />
      <ExposureCheckbox
        label="Radiation exposure"
        hint={compact ? undefined : 'Nuclear testing, occupation forces, certain nuclear-facility duty.'}
        checked={exposures.radiation}
        onChange={(v) => onExposureChange('radiation', v)}
      />
      <ExposureCheckbox
        label="Camp Lejeune water contamination"
        hint={compact ? undefined : 'Stationed at Camp Lejeune, NC, Aug 1953–Dec 1987 (30+ days).'}
        checked={exposures.camp_lejeune}
        onChange={(v) => onExposureChange('camp_lejeune', v)}
      />
      <ExposureCheckbox
        label="Former prisoner of war (POW)"
        hint={compact ? undefined : 'POW status — presumptive conditions under 38 CFR §3.309(c).'}
        checked={exposures.pow}
        onChange={(v) => {
          onExposureChange('pow', v)
          if (!v) onExposureChange('pow_internment_days', null)
        }}
      />
      {exposures.pow ? (
        <label className="block text-sm">
          <span className="vo-label">Approx. total internment days (optional)</span>
          <input
            className="vo-input"
            type="number"
            min={0}
            max={20000}
            inputMode="numeric"
            placeholder="e.g. 14 or 45"
            value={exposures.pow_internment_days ?? ''}
            onChange={(e) => {
              const raw = e.target.value.trim()
              if (raw === '') {
                onExposureChange('pow_internment_days', null)
                return
              }
              const n = Number.parseInt(raw, 10)
              if (Number.isFinite(n) && n >= 0) {
                onExposureChange('pow_internment_days', n)
              }
            }}
          />
          <span className="mt-1 block text-xs text-faint">
            §3.309(c) splits any-period vs 30+ day presumptive lists. Leave blank if unsure —
            we only show the any-period list until you add a number.
          </span>
        </label>
      ) : null}
      <ExposureCheckbox
        label="Mustard gas / Lewisite exposure"
        hint={compact ? undefined : 'Full-body exposure to mustard gas or Lewisite — presumptive under 38 CFR §3.316.'}
        checked={exposures.mustard_gas}
        onChange={(v) => onExposureChange('mustard_gas', v)}
      />
      {useChips ? (
        <LocationsTypeahead
          locations={locations}
          onChange={onLocationsChange}
          suggestedFromRecords={suggestedLocationsFromRecords}
        />
      ) : (
        <label className="block text-sm">
          <span className="vo-label">Locations (comma-separated)</span>
          <input
            className="vo-input"
            placeholder="e.g. Vietnam, Da Nang AB, Camp Lejeune"
            value={locationsText ?? ''}
            onChange={(e) => onLocationsTextChange?.(e.target.value)}
          />
        </label>
      )}
      <label className="block text-sm">
        <span className="vo-label">Other exposures</span>
        <textarea
          className="vo-input min-h-[80px]"
          value={exposures.other}
          onChange={(e) => onExposureChange('other', e.target.value)}
          placeholder="Anything else worth noting for your provider or VSO"
        />
      </label>
    </div>
  )
}
