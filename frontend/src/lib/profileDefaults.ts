// Shared "fresh account" profile defaults + normalization — used by
// Profile.tsx, Dashboard.tsx, and the onboarding wizard so nulls from a brand
// new GET /profile response never reach a page that assumes arrays/objects.

import { EMPTY_EXPOSURES, type Profile as ProfileType } from '../types'

export function emptyProfile(): ProfileType {
  return {
    service_periods: [],
    combat_service: false,
    receives_military_retired_pay: null,
    combat_related_disability: null,
    medically_retired: null,
    medically_separated: null,
    exposures: { ...EMPTY_EXPOSURES, locations: [] },
    current_combined_rating: null,
    state: null,
    notes: null,
    dependents: [],
  }
}

/** Normalize a (possibly null-riddled, freshly-created-row) profile response
 * against the empty defaults so nothing downstream reads null.length. */
export function normalizeProfile(data: ProfileType): ProfileType {
  const base = emptyProfile()
  return {
    ...base,
    ...data,
    service_periods: data.service_periods ?? base.service_periods,
    exposures: {
      ...base.exposures,
      ...(data.exposures ?? {}),
      locations: data.exposures?.locations ?? [],
    },
    combat_service: data.combat_service ?? false,
    dependents: data.dependents ?? base.dependents,
  }
}

/** True when a profile has nothing filled in yet — the signal the dashboard
 * uses to show the "Set up your claim" onboarding hero instead of the normal
 * summary tiles.
 *
 * Identity (name / DOB / phone) counts as progress: veterans who only confirmed
 * record-suggested identity were stuck with "profile incomplete" forever because
 * the old check ignored identity entirely.
 */
export function isEmptyProfile(data: ProfileType | null | undefined): boolean {
  if (!data) return true
  const p = normalizeProfile(data)
  const id = p.identity
  const hasIdentity = !!(
    (id?.full_name && id.full_name.trim()) ||
    id?.date_of_birth ||
    (id?.phone && id.phone.trim()) ||
    (id?.email && id.email.trim()) ||
    (id?.address?.street && id.address.street.trim()) ||
    (id?.address?.city && id.address.city.trim())
  )
  if (hasIdentity) return false

  const noExposures =
    !p.exposures.burn_pits &&
    !p.exposures.agent_orange &&
    !p.exposures.gulf_war &&
    !p.exposures.radiation &&
    !p.exposures.camp_lejeune &&
    !p.exposures.mustard_gas &&
    !p.exposures.pow &&
    !(p.exposures.other || '').trim() &&
    (p.exposures.locations?.length ?? 0) === 0
  return (
    (p.service_periods?.length ?? 0) === 0 &&
    !p.combat_service &&
    noExposures &&
    p.current_combined_rating === null &&
    !p.state
  )
}
