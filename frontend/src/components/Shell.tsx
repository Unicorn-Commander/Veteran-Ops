import {
  AlarmClock,
  CalendarClock,
  Banknote,
  Briefcase,
  Building2,
  Calculator,
  ChevronDown,
  Compass,
  ClipboardCheck,
  ClipboardList,
  CreditCard,
  FileStack,
  FileText,
  Folder,
  FolderOpen,
  Gauge,
  Gavel,
  Gift,
  Hourglass,
  FileCheck2,
  Home,
  Landmark,
  LifeBuoy,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  MessageSquareQuote,
  MessagesSquare,
  Moon,
  MoreHorizontal,
  NotebookPen,
  PenLine,
  PhoneCall,
  Scale,
  ScanText,
  ScanSearch,
  Cpu,
  Settings as SettingsIcon,
  Shield,
  Sparkles,
  Stethoscope,
  Sun,
  Target,
  Upload,
  User as UserIcon,
  UserPlus,
  Users,
  Waypoints,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useWorkspace } from '../context/WorkspaceContext'
import { useAsync } from '../hooks/useAsync'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { useRouteFocus } from '../hooks/useRouteFocus'
import { subscribeCaseCandidates } from '../lib/caseCandidatesStore'
import { resumeDeferredAnalysisIfNeeded, subscribeDeferredAnalysis } from '../lib/deferredAnalysisStore'
import { entitlementsApi, metaApi, setPaymentRequiredHandler } from '../lib/api'
import {
  hueInk,
  hueLabel,
  hueVar,
  sectionHueCss,
  SECTION_HUES,
  SECTION_LABELS,
  VIEW_HUES,
  VIEW_SECTIONS,
  type Hue,
  type Section,
} from '../lib/hues'
import { useToast } from './Toast'
import { DisclaimerFooter, DisclaimerModal, hasAcknowledgedDisclaimer } from './Disclaimer'
import { ErrorBoundary } from './ErrorBoundary'
import { Wordmark } from './Brand'
import { UserAvatar } from './Avatar'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'

interface NavEntry {
  to: string
  label: string
  icon: typeof LayoutDashboard
  view: string
  /** A short hover/focus tooltip (title) clarifying what the page is for. */
  hint?: string
  /** Secondary tools are tucked under a per-group "More" toggle so the default
   * sidebar stays calm; the route is unchanged, only its default visibility. */
  secondary?: boolean
}

interface NavGroupDef {
  section: Section
  /** Group heading in the sidebar; omitted for the ungrouped home row. */
  label?: string
  items: NavEntry[]
}

/* The nav is organized by JOURNEY PHASE, not tool category — it reads top-to-bottom
 * as the veteran's arc (start → build → understand → file → after), so the sidebar
 * answers "where am I and what's next," not "what kinds of tools exist." Each item
 * keeps its own `view` (which drives its individual hue AND its canonical section via
 * VIEW_SECTIONS — see currentContext), so regrouping items across phases NEVER
 * desyncs a page's theme or breadcrumb from where it lives here. Placement is a plain
 * declarative list: to move a tool between phases, move its line. The `section` on a
 * group only tints that group's rail/heading.
 *
 * Primary nav stays lean. Everything not listed as primary is tucked under
 * "More tools" via secondary: true — routes unchanged. */
const NAV_GROUPS: NavGroupDef[] = [
  {
    section: 'home',
    label: 'Home',
    items: [
      { to: '/raider', label: 'Ask Raider', icon: MessagesSquare, view: 'raider', hint: 'Ask anything about your claim in plain words.' },
      { to: '/', label: 'Home', icon: LayoutDashboard, view: 'dashboard', hint: 'Your next step and where you stand.' },
      { to: '/journey', label: 'Rings & journey', icon: Compass, view: 'journey', hint: 'Open rings to close and the full VA path.' },
      { to: '/workflows', label: 'Guided workflows', icon: Waypoints, view: 'workflows', hint: 'Step-by-step guided flows for common tasks.', secondary: true },
    ],
  },
  {
    section: 'claim',
    label: 'Build',
    items: [
      { to: '/documents', label: 'Upload records', icon: FolderOpen, view: 'documents', hint: 'Upload service and medical records — read privately.' },
      { to: '/build-case', label: 'From records → case', icon: Sparkles, view: 'buildcase', hint: 'Suggest conditions from your records; you confirm what to add.' },
      { to: '/review-queue', label: 'Confirm findings', icon: ClipboardCheck, view: 'reviewqueue', hint: 'Values flagged for you to confirm before they become facts.' },
      { to: '/conditions', label: 'Your conditions', icon: Folder, view: 'conditions', hint: 'The conditions you’re claiming — the backbone of your case.' },
      { to: '/evidence', label: 'Evidence map', icon: ClipboardList, view: 'evidence', hint: 'What each condition has and still needs.', secondary: true },
      { to: '/symptom-log', label: 'Symptom log', icon: NotebookPen, view: 'symptomlog', hint: 'Log symptoms over time to show severity and continuity.', secondary: true },
      { to: '/va-sync', label: 'Connect VA data', icon: Landmark, view: 'vasync', hint: 'Pull records and claim status from VA.', secondary: true },
      { to: '/records', label: 'Request records', icon: FileStack, view: 'records', hint: 'Request military and medical records you don’t have yet.', secondary: true },
    ],
  },
  {
    section: 'insight',
    label: 'Analyze',
    items: [
      { to: '/analysis', label: 'Run analysis', icon: ScanSearch, view: 'analysis', hint: 'Full pass over your file with live progress.' },
      { to: '/strategy', label: 'Claim plan', icon: Target, view: 'strategy', hint: 'Prioritized plan of what to do next and why.' },
      { to: '/calculator', label: 'Rating calculator', icon: Calculator, view: 'calculator', hint: 'Combine ratings the VA way.', secondary: true },
      { to: '/actions', label: 'Suggested actions', icon: Sparkles, view: 'actions', hint: 'Actions drawn from your case.', secondary: true },
      { to: '/readiness', label: 'File readiness', icon: Gauge, view: 'readiness', hint: 'How ready each condition is to file.', secondary: true },
      { to: '/secondaries', label: 'Secondaries', icon: Sparkles, view: 'secondaries', hint: 'Conditions that often develop from ones you’ve claimed.', secondary: true },
      { to: '/presumptives', label: 'Presumptives', icon: Shield, view: 'presumptives', hint: 'Screen service and exposures against VA lists.', secondary: true },
      { to: '/scenarios', label: 'Scenarios', icon: ListChecks, view: 'scenarios', hint: 'Compare “what if” rating outcomes.', secondary: true },
      { to: '/backpay', label: 'Back pay', icon: Banknote, view: 'backpay', hint: 'Estimate retroactive pay you may be owed.', secondary: true },
    ],
  },
  {
    section: 'records',
    label: 'File',
    items: [
      { to: '/itf', label: 'Intent to File', icon: AlarmClock, view: 'itf', hint: 'Lock in a possible earlier effective date while you build.' },
      { to: '/application', label: 'Application (526EZ)', icon: FileCheck2, view: 'form526', hint: 'Main disability-compensation application draft.' },
      { to: '/cp-companion', label: 'C&P exam prep', icon: Stethoscope, view: 'cp', hint: 'VA exam companion — how examiners assess conditions; prepare honestly.' },
      { to: '/filing', label: 'How to submit', icon: FileText, view: 'filing', hint: 'How and where to submit — you or a free VSO file.' },
      { to: '/nexus', label: 'Nexus letter', icon: Stethoscope, view: 'nexus', hint: 'Medical opinion linking a condition to service — often from your treating clinician.', secondary: true },
      { to: '/statement', label: 'Personal statement', icon: PenLine, view: 'statement', hint: 'Your account in your words.', secondary: true },
      { to: '/buddy', label: 'Buddy statement', icon: MessageSquareQuote, view: 'buddy', hint: 'Statement from someone who witnessed symptoms.', secondary: true },
      { to: '/dependency', label: 'Dependents', icon: UserPlus, view: 'dependency', hint: 'Add dependents (21-686c).', secondary: true },
      { to: '/tdiu', label: 'TDIU', icon: Briefcase, view: 'tdiu', hint: 'Unemployability worksheet.', secondary: true },
    ],
  },
  {
    section: 'claim',
    label: 'After filing',
    items: [
      { to: '/claims', label: 'Claims status', icon: Hourglass, view: 'claims', hint: 'Track where filed claims stand.' },
      { to: '/decode', label: 'Decision decoder', icon: ScanText, view: 'decode', hint: 'Plain English + next steps from a decision letter.' },
      { to: '/appeals', label: 'Appeal a denial', icon: Gavel, view: 'appeals', hint: 'Options when a decision doesn’t go your way.' },
      { to: '/whats-changed', label: "What's changed", icon: CalendarClock, view: 'whatschanged', hint: 'New evidence or rules since your last rating.', secondary: true },
      { to: '/benefits', label: 'Benefits', icon: Gift, view: 'benefits', hint: 'Benefits your rating may unlock.', secondary: true },
      { to: '/corrections', label: 'Records corrections', icon: Scale, view: 'corrections', hint: 'Fix errors in military records.', secondary: true },
    ],
  },
  {
    section: 'guide',
    label: 'Help',
    items: [
      { to: '/help', label: 'Help', icon: LifeBuoy, view: 'help', hint: 'How Rating Raider works and common questions.' },
    ],
  },
]

/* Org-only tools — the caseload + admin console. Shown only when the active
 * workspace is a team (see Shell()); a personal workspace never sees these. */
const ORG_GROUP: NavGroupDef = {
  section: 'settings',
  label: 'Team',
  items: [
    { to: '/caseload', label: 'Caseload', icon: Briefcase, view: 'caseload' },
    { to: '/console', label: 'Org console', icon: Building2, view: 'console' },
  ],
}

/** Pinned to the sidebar bottom: the veteran's own stuff (settings section). */
const YOU_GROUP: NavGroupDef = {
  section: 'settings',
  label: 'You',
  items: [
    { to: '/profile', label: 'Profile', icon: UserIcon, view: 'profile', hint: 'Service history, identity, and exposures — confirm suggestions from records.' },
    { to: '/teams', label: 'Teams', icon: Users, view: 'teams' },
    { to: '/billing', label: 'Plans & billing', icon: CreditCard, view: 'billing' },
    { to: '/settings', label: 'Settings', icon: SettingsIcon, view: 'settings' },
    { to: '/admin/services', label: 'Service settings', icon: Cpu, view: 'settings', secondary: true },
  ],
}

/** Resolve the current route to its section + page title (topbar breadcrumb,
 * sidebar rail highlight). Longest path prefix wins so /conditions/:id maps
 * to Conditions. */
// Routes reachable from inside a parent page (not shown as their own nav item),
// so the topbar breadcrumb + rail still resolve to the right section.
const SECONDARY_ROUTES: { to: string; section: Section; title: string }[] = [
  { to: '/rank', section: 'records', title: 'Rank correction' },
  { to: '/va-import', section: 'records', title: 'Import from VA' },
  { to: '/grants', section: 'settings', title: 'Grant request' },
  { to: '/admin/services', section: 'settings', title: 'Service settings' },
  // Reached from the "Ongoing" and "Survivors" journey stages, not the primary nav.
  { to: '/concurrent-pay', section: 'insight', title: 'Concurrent pay' },
  { to: '/survivors', section: 'guide', title: 'Survivors benefits' },
]

function currentContext(pathname: string): { section: Section; title: string; view: string | null } {
  if (pathname === '/') return { section: 'home', title: 'Dashboard', view: 'dashboard' }
  if (pathname.startsWith('/onboarding')) return { section: 'settings', title: 'Guided setup', view: null }
  const secondary = SECONDARY_ROUTES.find((r) => pathname.startsWith(r.to))
  if (secondary) return { section: secondary.section, title: secondary.title, view: null }
  // Resolve section from the item's VIEW (its canonical section), NOT its nav group —
  // items are now grouped by journey phase, so a page keeps its own theme/breadcrumb
  // section wherever it sits in the sidebar.
  const hit = [...NAV_GROUPS, ORG_GROUP, YOU_GROUP]
    .flatMap((g) => g.items.map((i) => ({ ...i, section: VIEW_SECTIONS[i.view] ?? g.section })))
    .filter((i) => i.to !== '/' && pathname.startsWith(i.to))
    .sort((a, b) => b.to.length - a.to.length)[0]
  return hit
    ? { section: hit.section, title: hit.label, view: hit.view }
    : { section: 'home', title: 'Dashboard', view: 'dashboard' }
}

export function Shell({ children }: { children?: ReactNode } = {}) {
  const { user, logout } = useAuth()
  const { current, error: workspaceError, refresh: refreshWorkspaces } = useWorkspace()
  const { toast } = useToast()
  const isOrg = current?.kind === 'org'
  const { data: meta } = useAsync(() => metaApi.get())
  const { data: entitlements } = useAsync(() => entitlementsApi.get(), [current?.id])
  const location = useLocation()
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [caseBuildBusy, setCaseBuildBusy] = useState(false)
  const [showDisclaimer, setShowDisclaimer] = useState(() => !hasAcknowledgedDisclaimer())

  // Background "populate case from records" continues if the user leaves /build-case.
  useEffect(() => {
    return subscribeCaseCandidates((snap) => setCaseBuildBusy(snap.status === 'loading'))
  }, [])

  // "Analyze after upload" continues even if the user leaves Documents mid-batch.
  useEffect(() => {
    resumeDeferredAnalysisIfNeeded()
    return subscribeDeferredAnalysis(() => {
      /* Documents page owns the banner; Shell only keeps the poller alive. */
    })
  }, [])
  const [creditNotice, setCreditNotice] = useState<string | null>(null)
  const creditNoticeTimer = useRef<number | null>(null)
  const { section, title, view: activeView } = currentContext(location.pathname)
  const drawerRef = useRef<HTMLDivElement>(null)
  const currentEntitlements = entitlements && entitlements.workspace_id === current?.id ? entitlements : null
  const role = currentEntitlements?.role ?? current?.role
  const features = currentEntitlements?.features ?? []
  const isManager = role === 'owner' || role === 'admin'
  const navGroups = NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => item.to !== '/va-sync' || meta?.va_enabled),
  }))
  const orgGroup = {
    ...ORG_GROUP,
    items: ORG_GROUP.items.filter((item) => {
      if (item.to === '/caseload') return role !== 'member' && features.includes('staff_caseload')
      if (item.to === '/console') return isManager && features.includes('org_admin_console')
      return false
    }),
  }
  const youGroup = {
    ...YOU_GROUP,
    items: YOU_GROUP.items.filter((item) => {
      if (item.to === '/billing') return isOrg ? isManager : !!meta?.billing_self_serve
      if (item.to === '/admin/services') return !!user?.platform_admin
      return true
    }),
  }

  // On route change: update the document title and move focus to <main> so
  // screen-reader / keyboard users are told the page changed.
  useRouteFocus(title)

  // Trap focus in the mobile nav drawer + lock body scroll while it's open.
  useFocusTrap(drawerRef, mobileNavOpen)
  useEffect(() => {
    if (!mobileNavOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [mobileNavOpen])

  useEffect(() => {
    const saved = (localStorage.getItem('vo_theme') as 'dark' | 'light' | null) ?? 'dark'
    setTheme(saved)
  }, [])
  useEffect(() => {
    document.documentElement.dataset.theme = theme === 'light' ? 'light' : ''
    localStorage.setItem('vo_theme', theme)
  }, [theme])

  // Allow Settings to re-trigger the first-run modal via a custom event.
  useEffect(() => {
    const onShow = () => setShowDisclaimer(true)
    window.addEventListener('vo:show-disclaimer', onShow)
    return () => window.removeEventListener('vo:show-disclaimer', onShow)
  }, [])

  useEffect(() => {
    setPaymentRequiredHandler(() => {
      const message = "You're out of credits — add a top-up."
      setCreditNotice(message)
      toast(message, 'error')
      if (creditNoticeTimer.current) window.clearTimeout(creditNoticeTimer.current)
      creditNoticeTimer.current = window.setTimeout(() => {
        setCreditNotice((current) => (current === message ? null : current))
        creditNoticeTimer.current = null
      }, 10000)
    })
    return () => {
      if (creditNoticeTimer.current) window.clearTimeout(creditNoticeTimer.current)
      creditNoticeTimer.current = null
      setPaymentRequiredHandler(null)
    }
  }, [toast])

  // Escape closes the mobile drawer.
  useEffect(() => {
    if (!mobileNavOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMobileNavOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mobileNavOpen])

  return (
    <div className="flex h-dvh flex-col text-txt">
      {showDisclaimer && <DisclaimerModal onAccept={() => setShowDisclaimer(false)} />}

      {/* Skip link: first focusable element, jumps keyboard/AT users past the
          nav straight to the routed content. */}
      <a
        href="#main-content"
        className="sr-only left-4 top-4 z-[110] rounded-control bg-brand px-4 py-2 text-sm font-semibold text-white shadow-pop focus:not-sr-only focus:absolute"
      >
        Skip to content
      </a>

      {/* Background is hidden from assistive tech while the first-run gate is up. */}
      <div className="flex min-h-0 flex-1" aria-hidden={showDisclaimer || undefined}>
        {/* Nav rail (desktop) */}
        <nav className="vo-no-print relative hidden w-60 shrink-0 flex-col border-r border-line md:flex" aria-label="Primary">
          {/* Slim section-colored rail on the sidebar's spine — tracks the
              section you're in. */}
          <span
            aria-hidden
            className="absolute inset-y-3 left-0 w-[3px] rounded-full transition-[background] duration-300"
            style={{
              background: `linear-gradient(180deg, ${sectionHueCss(section)} 0%, transparent 85%)`,
              opacity: 0.75,
            }}
          />
          <div className="flex h-16 shrink-0 items-center px-4">
            <Link
              to="/"
              aria-label="Rating Raider — go to your dashboard"
              className="rounded-control transition-opacity hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
            >
              <Wordmark size={32} />
            </Link>
          </div>
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 pt-1">
            <NavGroups groups={navGroups} activeSection={section} activeView={activeView} />
            <div className="mt-auto pt-3">
              <CrisisLink />
              {isOrg && orgGroup.items.length > 0 && <NavGroup group={orgGroup} activeSection={section} />}
              <NavGroup group={youGroup} activeSection={section} />
            </div>
          </div>
        </nav>

        {/* Main column: scrolling content with the glass topbar stuck inside
            it, so pages genuinely slide beneath the blur. Bottom padding on
            mobile clears the fixed bottom tab bar + safe-area inset. */}
        <div className="flex min-w-0 flex-1 flex-col pb-[calc(4rem+env(safe-area-inset-bottom))] md:pb-0">
          <main
            id="main-content"
            tabIndex={-1}
            className="min-h-0 flex-1 overflow-y-auto focus:outline-none"
          >
            <header className="vo-topbar vo-no-print flex h-16 items-center justify-between px-3 sm:px-6">
              <div className="flex min-w-0 items-center gap-2">
                <button
                  onClick={() => setMobileNavOpen((v) => !v)}
                  className="vo-icon-btn vo-btn-ghost md:hidden"
                  aria-label="Toggle navigation"
                  aria-expanded={mobileNavOpen}
                >
                  {mobileNavOpen ? <X size={18} /> : <Menu size={18} />}
                </button>
                <Link to="/" aria-label="Rating Raider — go to your dashboard" className="md:hidden rounded-control focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
                  <Wordmark size={28} />
                </Link>
                {/* Section breadcrumb: where you are, in that section's color. */}
                <div className="hidden min-w-0 items-center gap-2 md:flex" aria-label={`Current section: ${SECTION_LABELS[section]}`}>
                  <span
                    aria-hidden
                    className="h-2 w-2 shrink-0 rounded-full transition-[background,box-shadow] duration-300"
                    style={{ background: sectionHueCss(section), boxShadow: `0 0 8px ${sectionHueCss(section)}` }}
                  />
                  <span
                    className="text-micro font-semibold uppercase tracking-wider transition-colors duration-300"
                    style={{ color: sectionLabelColor(section) }}
                  >
                    {SECTION_LABELS[section]}
                  </span>
                  <span aria-hidden className="text-faint">/</span>
                  <span className="truncate text-sm font-semibold text-txt">{title}</span>
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                {/* Crisis chip — always visible on mobile (not only in the drawer). */}
                <a
                  href="tel:988"
                  className="inline-flex min-h-11 items-center gap-1.5 rounded-control border border-line px-2.5 text-xs font-semibold text-muted transition-colors hover:bg-surface2 hover:text-txt focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand md:hidden"
                  aria-label="Veterans Crisis Line: call 988, then press 1"
                  title="Veterans Crisis Line — 988, then 1"
                >
                  <PhoneCall size={14} className="shrink-0" aria-hidden />
                  <span>988</span>
                </a>
                <WorkspaceSwitcher />
                <button
                  onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
                  className="vo-icon-btn vo-btn-ghost"
                  aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
                  title="Toggle theme"
                >
                  {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
                </button>
                <div className="flex items-center gap-1.5 pl-1">
                  <UserAvatar
                    name={user?.full_name}
                    email={user?.email}
                    src={user?.avatar_url}
                    size={36}
                  />
                  <button onClick={logout} className="vo-icon-btn vo-btn-ghost" aria-label="Sign out" title="Sign out">
                    <LogOut size={17} />
                  </button>
                </div>
              </div>
            </header>
            {workspaceError && (
              <div className="px-3 pb-3 pt-0 sm:px-6" role="alert">
                <div className="flex flex-col items-start justify-between gap-3 border-l-[3px] border-warning bg-surface px-4 py-3 text-sm sm:flex-row sm:items-center">
                  <p className="text-txt">
                    Your workspace list could not be loaded. We are not treating it as empty. {workspaceError}
                  </p>
                  <button type="button" onClick={() => void refreshWorkspaces()} className="vo-btn-secondary min-h-11 shrink-0 text-xs">
                    Try again
                  </button>
                </div>
              </div>
            )}
            {creditNotice && (
              <div className="px-3 pb-3 pt-0 sm:px-6">
                <div className="flex items-center justify-between gap-3 rounded-control border border-warn/35 bg-h-amber-soft px-4 py-3 text-sm">
                  <p className="min-w-0 text-txt">{creditNotice}</p>
                  <div className="flex items-center gap-2">
                    <Link to="/billing" className="vo-btn-primary text-xs">
                      Add a top-up
                    </Link>
                    <button
                      type="button"
                      onClick={() => {
                        if (creditNoticeTimer.current) window.clearTimeout(creditNoticeTimer.current)
                        creditNoticeTimer.current = null
                        setCreditNotice(null)
                      }}
                      className="vo-btn-ghost text-xs text-muted hover:text-txt"
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              </div>
            )}
            {caseBuildBusy && !location.pathname.startsWith('/build-case') && (
              <div className="px-3 pb-3 pt-0 sm:px-6" role="status" aria-live="polite">
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-brand/30 bg-h-emerald-soft/40 px-4 py-3 text-sm">
                  <p className="min-w-0 text-txt">
                    <span className="font-semibold">Still reading your records…</span>{' '}
                    <span className="text-muted">Suggestions keep preparing in the background. You can keep working elsewhere.</span>
                  </p>
                  <Link to="/build-case" className="vo-btn-secondary min-h-11 shrink-0 text-xs">
                    View progress
                  </Link>
                </div>
              </div>
            )}
            <ErrorBoundary resetKey={location.pathname}>{children ?? <Outlet />}</ErrorBoundary>
          </main>
          <DisclaimerFooter />
        </div>
      </div>

      {/* Mobile bottom tab bar — five primary destinations, always reachable. */}
      <nav
        className="vo-no-print fixed inset-x-0 bottom-0 z-40 flex border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden"
        aria-label="Primary mobile"
      >
        <MobileTab to="/raider" label="Raider" icon={MessagesSquare} active={location.pathname.startsWith('/raider')} />
        <MobileTab to="/" label="Home" icon={Home} active={location.pathname === '/'} end />
        <MobileTab to="/documents" label="Upload" icon={Upload} active={location.pathname.startsWith('/documents')} />
        <MobileTab
          to="/conditions"
          label="Case"
          icon={Folder}
          active={
            location.pathname.startsWith('/conditions') ||
            location.pathname.startsWith('/build-case') ||
            location.pathname.startsWith('/review-queue') ||
            location.pathname.startsWith('/evidence') ||
            location.pathname.startsWith('/analysis') ||
            location.pathname.startsWith('/strategy') ||
            location.pathname.startsWith('/application') ||
            location.pathname.startsWith('/readiness')
          }
        />
        <button
          type="button"
          onClick={() => setMobileNavOpen(true)}
          className="flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-micro font-medium text-muted transition-colors hover:text-txt focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand"
          aria-label="Open more navigation"
          aria-expanded={mobileNavOpen}
        >
          <MoreHorizontal size={20} aria-hidden />
          <span>More</span>
        </button>
      </nav>

      {/* Nav drawer (mobile) — same color-banded groups as the desktop rail. */}
      {mobileNavOpen && (
        <div ref={drawerRef} className="vo-no-print fixed inset-0 z-50 flex md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div
            className="animate-fade-in absolute inset-0 bg-black/55 backdrop-blur-sm"
            onClick={() => setMobileNavOpen(false)}
          />
          <nav
            className="animate-drawer-in relative flex w-72 max-w-[85vw] flex-col overflow-y-auto border-r border-line bg-surface p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pl-[max(0.75rem,env(safe-area-inset-left))] shadow-pop"
            aria-label="Primary"
          >
            <div className="mb-2 flex h-12 items-center justify-between px-1">
              <Link
                to="/"
                onClick={() => setMobileNavOpen(false)}
                aria-label="Rating Raider — go to your dashboard"
                className="rounded-control focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              >
                <Wordmark size={28} />
              </Link>
              <button onClick={() => setMobileNavOpen(false)} className="vo-icon-btn vo-btn-ghost" aria-label="Close navigation">
                <X size={17} />
              </button>
            </div>
            <NavGroups groups={navGroups} activeSection={section} activeView={activeView} onNavigate={() => setMobileNavOpen(false)} />
            <div className="mt-auto pt-3">
              <CrisisLink onNavigate={() => setMobileNavOpen(false)} />
              {isOrg && orgGroup.items.length > 0 && <NavGroup group={orgGroup} activeSection={section} onNavigate={() => setMobileNavOpen(false)} />}
              <NavGroup group={youGroup} activeSection={section} onNavigate={() => setMobileNavOpen(false)} />
            </div>
          </nav>
        </div>
      )}
    </div>
  )
}

/** One item in the mobile bottom tab bar. */
function MobileTab({
  to,
  label,
  icon: Icon,
  active,
  end,
}: {
  to: string
  label: string
  icon: typeof LayoutDashboard
  active: boolean
  end?: boolean
}) {
  return (
    <NavLink
      to={to}
      end={end}
      aria-current={active ? 'page' : undefined}
      className={`flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-micro font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand ${
        active ? 'font-semibold text-brand' : 'text-muted hover:text-txt'
      }`}
      aria-label={label}
    >
      <Icon size={20} aria-hidden />
      <span>{label}</span>
    </NavLink>
  )
}

function CrisisLink({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <a
      href="tel:988"
      onClick={onNavigate}
      className="mx-2 mb-2 flex min-h-11 items-center gap-2.5 rounded-control border border-line px-3 py-2 text-sm font-semibold text-muted transition-colors hover:bg-surface2 hover:text-txt focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      aria-label="Veterans Crisis Line: call 988, then press 1"
    >
      <PhoneCall size={17} className="shrink-0" />
      <span className="min-w-0">Crisis support</span>
      <span className="ml-auto text-xs font-medium text-faint">988, then 1</span>
    </a>
  )
}

/** Section label color, contrast-safe in both themes via hueLabel();
 * settings stays a quiet muted-violet by design. */
function sectionLabelColor(section: Section): string {
  if (section === 'settings') return 'color-mix(in srgb, var(--hue-violet) 40%, var(--muted))'
  return hueLabel(SECTION_HUES[section])
}

function NavGroups({
  groups,
  activeSection,
  activeView,
  onNavigate,
}: {
  groups: NavGroupDef[]
  activeSection: Section
  activeView?: string | null
  onNavigate?: () => void
}) {
  return (
    <div className="flex flex-col">
      {groups.map((g) => (
        <NavGroup
          key={g.label ?? g.section}
          group={g}
          activeSection={activeSection}
          activeView={activeView}
          onNavigate={onNavigate}
        />
      ))}
    </div>
  )
}

/** One section group: hue-tinted heading with its dot, a slim hue rail down
 * the group's left edge (brightens when you're inside the section), and the
 * hue-dotted items. */
function NavGroup({
  group,
  activeSection,
  activeView,
  onNavigate,
}: {
  group: NavGroupDef
  activeSection: Section
  activeView?: string | null
  onNavigate?: () => void
}) {
  // A phase group's rail lights when the page you're on lives in THIS group. Match by
  // the active VIEW (precise — exactly one group owns each page); fall back to section
  // match for the single-section ORG/YOU groups that don't pass activeView.
  const active =
    activeView != null
      ? group.items.some((i) => i.view === activeView)
      : group.items.some((i) => (VIEW_SECTIONS[i.view] ?? group.section) === activeSection)
  const railHue = sectionHueCss(group.section)

  // Keep the default sidebar calm: only the core per-phase items show; the rest
  // hide behind a "More" toggle. Routes are unchanged — this is visibility only.
  const primary = group.items.filter((i) => !i.secondary)
  const secondary = group.items.filter((i) => i.secondary)
  // If the page you're on is a tucked-away tool, expand its group so you can see
  // where you are (and keep it expanded once opened).
  const activeIsSecondary = activeView != null && secondary.some((i) => i.view === activeView)
  const [expanded, setExpanded] = useState(activeIsSecondary)
  useEffect(() => {
    if (activeIsSecondary) setExpanded(true)
  }, [activeIsSecondary])

  return (
    <div className="relative mt-3 first:mt-0">
      <span
        aria-hidden
        className="absolute bottom-1 left-0 top-1 w-[2px] rounded-full transition-opacity duration-300"
        style={{
          background: `linear-gradient(180deg, ${railHue} 0%, color-mix(in srgb, ${railHue} 25%, transparent) 100%)`,
          opacity: active ? 0.9 : 0.25,
        }}
      />
      {group.label && (
        <div
          className="mb-1 flex items-center gap-1.5 pl-4 pr-3 pt-1 text-micro font-semibold uppercase tracking-wider"
          style={{
            color:
              group.section === 'settings'
                ? 'color-mix(in srgb, var(--hue-violet) 40%, var(--muted))'
                : hueLabel(VIEW_HUES[group.items[0].view] ?? 'violet'),
          }}
        >
          {group.label}
        </div>
      )}
      <div className="flex flex-col gap-0.5 pl-2">
        {primary.map((n) => (
          <NavItem key={n.to} to={n.to} label={n.label} icon={n.icon} view={n.view} hint={n.hint} onNavigate={onNavigate} />
        ))}
        {expanded &&
          secondary.map((n) => (
            <NavItem key={n.to} to={n.to} label={n.label} icon={n.icon} view={n.view} hint={n.hint} onNavigate={onNavigate} />
          ))}
        {secondary.length > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="group mt-0.5 flex min-h-[2rem] items-center gap-2.5 rounded-control px-3 py-1.5 text-xs font-medium text-faint transition-colors hover:bg-surface2 hover:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            <ChevronDown
              size={15}
              className={`shrink-0 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
            />
            <span>{expanded ? 'Show less' : `More in this section (${secondary.length})`}</span>
          </button>
        )}
      </div>
    </div>
  )
}

/** One nav row: a hue dot that lives in front of the icon, hue-soft active
 * fill with an inset hue ring, a glow indicator bar that scales in, and an
 * icon that adopts the section hue on hover/active. Active text runs through
 * hueInk() so it clears WCAG in both themes. */
function NavItem({
  to,
  label,
  icon: Icon,
  view,
  hint,
  onNavigate,
}: {
  to: string
  label: string
  icon: typeof LayoutDashboard
  view: string
  hint?: string
  onNavigate?: () => void
}) {
  const hue = (VIEW_HUES[view] ?? 'violet') as Hue
  return (
    <NavLink
      to={to}
      end={to === '/'}
      title={hint}
      onClick={onNavigate}
      className={({ isActive }) =>
        `group relative flex min-h-[2.5rem] items-center gap-2.5 rounded-control px-3 py-2.5 text-sm font-medium transition-colors duration-150 ${
          isActive ? 'font-semibold' : 'text-muted hover:bg-surface2 hover:text-txt'
        }`
      }
      style={({ isActive }) =>
        isActive
          ? {
              color: hueInk(hue),
              background: `linear-gradient(90deg, var(--hue-${hue}-soft), color-mix(in srgb, ${hueVar(hue)} 4%, transparent))`,
              boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${hueVar(hue)} 35%, transparent)`,
            }
          : undefined
      }
    >
      {({ isActive }) => (
        <>
          <span
            aria-hidden
            className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full transition-transform duration-200 ease-out"
            style={{
              background: hueVar(hue),
              transform: `translateY(-50%) scaleY(${isActive ? 1 : 0})`,
              boxShadow: isActive ? `0 0 8px ${hueVar(hue)}` : undefined,
            }}
          />
          <Icon
            size={17}
            className="shrink-0 transition-transform duration-200 ease-out group-hover:scale-110"
            style={{ color: isActive ? hueVar(hue) : hueLabel(hue) }}
          />
          <span className="min-w-0 flex-1 truncate">{label}</span>
          <span
            aria-hidden
            className="h-1.5 w-1.5 shrink-0 rounded-full transition-all duration-200"
            style={{
              background: hueVar(hue),
              opacity: isActive ? 1 : 0.4,
              boxShadow: isActive ? `0 0 6px ${hueVar(hue)}` : undefined,
            }}
          />
        </>
      )}
    </NavLink>
  )
}
