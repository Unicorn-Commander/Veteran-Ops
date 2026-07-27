/** The Aurora identity-hue system: nav sections, claim types, evidence status,
 * and exposure programs each carry one of 12 hues (CSS vars themed for dark
 * AND light in index.css). Dynamic hues are applied via inline `--hue` /
 * `--hue-soft` custom properties (see .vo-chip-hue / .vo-accent) because
 * Tailwind can't generate them at runtime. */

export const HUES = [
  'rose', 'orange', 'amber', 'lime', 'emerald', 'teal',
  'cyan', 'sky', 'indigo', 'violet', 'fuchsia', 'pink',
] as const

export type Hue = (typeof HUES)[number]

export const hueVar = (h: Hue) => `var(--hue-${h})`
export const hueSoftVar = (h: Hue) => `var(--hue-${h}-soft)`

/** A hue blended toward the theme's muted text — for tinted-but-quiet accents
 * like sidebar section labels (full hue would shout; this whispers). */
export const hueMix = (h: Hue, pct = 55) =>
  `color-mix(in srgb, ${hueVar(h)} ${pct}%, var(--muted))`

/** CONTRAST-SAFE hue text. Both helpers route through theme-tuned mix vars
 * (index.css §section-contract) so every hue passes WCAG 4.5:1 in BOTH themes
 * (dark brightens barely; light inks the hue toward --txt/--muted).
 * - hueInk: hue-colored TEXT on soft/tinted grounds (active nav, stat text).
 * - hueLabel: quiet tinted LABELS on the app bg (group labels, breadcrumbs).
 * Verified 2026-07-05 across all 12 hues; worst case light-amber 4.71:1. */
export const hueInk = (h: Hue) =>
  `color-mix(in srgb, ${hueVar(h)} var(--mix-ink, 92%), var(--txt))`
export const hueLabel = (h: Hue) =>
  `color-mix(in srgb, ${hueVar(h)} var(--mix-label, 62%), var(--muted))`

/** Inline style that lights up .vo-chip-hue / .vo-accent with a hue. */
export function hueStyle(h: Hue): Record<string, string> {
  return { '--hue': hueVar(h), '--hue-soft': hueSoftVar(h) }
}

/** Stable identity hue for any id/string — same input, same color, forever. */
export function hueFor(id: string): Hue {
  let acc = 0
  for (let i = 0; i < id.length; i++) acc = (acc * 31 + id.charCodeAt(i)) | 0
  return HUES[Math.abs(acc) % HUES.length]
}

/* =====================  SECTION IDENTITY (wave 3)  =====================
 * The app is organized into 7 color-coded sections. Every page root carries
 * `data-section="<Section>"` + `.vo-page`; index.css turns that into
 * --section-hue/--section-soft/--section-glow, the section aurora tint, and
 * default panel accents. Full contract: comment block at top of index.css. */

export type Section = 'home' | 'claim' | 'math' | 'insight' | 'records' | 'guide' | 'settings'

/** Section → primary hue token. `settings` is deliberately a MUTED violet in
 * CSS (see index.css [data-section='settings']); use sectionHueCss()/
 * sectionSoftCss() — not hueVar(SECTION_HUES.settings) — when styling section
 * chrome outside a [data-section] scope (e.g. the Shell topbar/rail). */
export const SECTION_HUES: Record<Section, Hue> = {
  home: 'violet',
  claim: 'emerald',
  math: 'sky',
  insight: 'fuchsia',
  records: 'amber',
  guide: 'indigo',
  settings: 'violet',
}

export const SECTION_LABELS: Record<Section, string> = {
  home: 'Home',
  claim: 'Claim tools',
  math: 'Rating math',
  insight: 'Insights',
  records: 'Records',
  guide: 'Guides',
  settings: 'You',
}

/** view key (VIEW_HUES key) → its section. */
export const VIEW_SECTIONS: Record<string, Section> = {
  dashboard: 'home',
  raider: 'home',
  workflows: 'home',
  journey: 'home',
  conditions: 'claim',
  buildcase: 'claim',
  evidence: 'claim',
  actions: 'claim',
  claims: 'claim',
  calculator: 'math',
  scenarios: 'math',
  backpay: 'math',
  analysis: 'insight',
  strategy: 'insight',
  secondaries: 'insight',
  presumptives: 'insight',
  decode: 'insight',
  appeals: 'insight',
  benefits: 'insight',
  whatschanged: 'insight',
  readiness: 'claim',
  itf: 'claim',
  symptomlog: 'claim',
  records: 'records',
  reviewqueue: 'records',
  corrections: 'records',
  rank: 'records',
  documents: 'records',
  vaimport: 'records',
  buddy: 'records',
  form526: 'records',
  nexus: 'records',
  statement: 'records',
  tdiu: 'records',
  dependency: 'records',
  filing: 'guide',
  cp: 'guide',
  help: 'guide',
  profile: 'settings',
  settings: 'settings',
  onboarding: 'settings',
  vasync: 'records',
}

/** Section hue as CSS, usable OUTSIDE a [data-section] scope. Mirrors the
 * [data-section='settings'] muted-violet mix in index.css — keep in sync. */
export const sectionHueCss = (s: Section) =>
  s === 'settings'
    ? `color-mix(in srgb, ${hueVar('violet')} 62%, var(--muted))`
    : hueVar(SECTION_HUES[s])
export const sectionSoftCss = (s: Section) =>
  s === 'settings'
    ? `color-mix(in srgb, ${hueVar('violet')} 9%, transparent)`
    : hueSoftVar(SECTION_HUES[s])

/** Per-nav-item identity (sidebar rows, panel accents). Wave 3: items stay
 * inside their section's hue FAMILY (claim=emerald/teal, math=sky/cyan,
 * insight=fuchsia/pink, records=amber/orange, guide=indigo) so the nav reads
 * as color-banded groups. */
export const VIEW_HUES: Record<string, Hue> = {
  dashboard: 'violet',
  raider: 'violet',
  workflows: 'violet',
  journey: 'violet',
  onboarding: 'violet',
  profile: 'violet',
  conditions: 'emerald',
  buildcase: 'emerald',
  evidence: 'teal',
  actions: 'violet',
  claims: 'emerald',
  calculator: 'sky',
  scenarios: 'cyan',
  backpay: 'sky',
  analysis: 'fuchsia',
  strategy: 'fuchsia',
  secondaries: 'fuchsia',
  presumptives: 'pink',
  decode: 'fuchsia',
  appeals: 'pink',
  benefits: 'pink',
  whatschanged: 'teal',
  readiness: 'emerald',
  itf: 'teal',
  symptomlog: 'teal',
  filing: 'indigo',
  cp: 'indigo',
  help: 'indigo',
  records: 'amber',
  reviewqueue: 'amber',
  corrections: 'orange',
  rank: 'orange',
  documents: 'amber',
  vaimport: 'orange',
  buddy: 'orange',
  form526: 'amber',
  nexus: 'orange',
  statement: 'amber',
  tdiu: 'emerald',
  dependency: 'violet',
  settings: 'violet',
  vasync: 'violet',
}

/** Document status identity (Documents.tsx). */
export const DOC_STATUS_HUES: Record<string, Hue> = {
  uploaded: 'sky',
  processing: 'amber',
  ready: 'emerald',
  failed: 'rose',
}

/** Claim-type identity (badges on the conditions list/detail). */
export const CLAIM_TYPE_HUES: Record<string, Hue> = {
  direct: 'violet',
  secondary: 'fuchsia',
  presumptive: 'cyan',
  increase: 'orange',
}

/** Condition-status identity. */
export const STATUS_HUES: Record<string, Hue> = {
  considering: 'sky',
  gathering_evidence: 'amber',
  ready_to_file: 'emerald',
  filed: 'violet',
  decided: 'teal',
}

/** VA-disposition identity (badges on the conditions list + Game Plan). */
export const VA_STATUS_HUES: Record<string, Hue> = {
  service_connected: 'emerald',
  denied: 'rose',
  pending: 'amber',
  unknown: 'sky',
}

/** Short badge label per VA disposition. Only `denied` / `service_connected`
 * are badged in the UI (unknown = "not yet claimed" needs no chip). */
export const VA_STATUS_BADGES: Record<string, string> = {
  service_connected: 'Service-connected',
  denied: 'Denied — Supplemental Claim',
  pending: 'Claim pending',
}

/** Evidence-status identity. */
export const EVIDENCE_STATUS_HUES: Record<string, Hue> = {
  have: 'emerald',
  need: 'rose',
  requested: 'amber',
  not_applicable: 'indigo',
}

/** Presumptive-program identity (PACT/AO/Gulf War/radiation/Camp Lejeune). */
export const PROGRAM_HUES: Record<string, Hue> = {
  pact: 'emerald',
  agent_orange: 'lime',
  gulf_war: 'amber',
  radiation: 'fuchsia',
  camp_lejeune: 'cyan',
}

export function hueForKey(map: Record<string, Hue>, key: string): Hue {
  return map[key] ?? hueFor(key)
}
