import { Suspense, lazy, useEffect } from 'react'
import type { ComponentType } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { RequireAuth } from './components/RequireAuth'
import { Shell } from './components/Shell'
import { useAuth } from './context/AuthContext'
import { useAsync } from './hooks/useAsync'
import { documentsApi, profileApi } from './lib/api'
import { emptyProfile, isEmptyProfile } from './lib/profileDefaults'
import { Login } from './pages/Login'

/* Route-level code-splitting (Wave 7): every page below is its own async chunk, so
 * the initial bundle is just the shell + auth + router. Pages are NAMED exports, so
 * each lazy() maps the export onto the default React.lazy expects. Login, Shell, and
 * RequireAuth stay eager — they're the always-present chrome/auth gate. */
const named = <M, K extends keyof M>(loader: () => Promise<M>, key: K) =>
  lazy(() => loader().then((m) => ({ default: m[key] as unknown as ComponentType })))

const AnalysisCenter = named(() => import('./pages/AnalysisCenter'), 'AnalysisCenter')
const Backpay = named(() => import('./pages/Backpay'), 'Backpay')
const Benefits = named(() => import('./pages/Benefits'), 'Benefits')
const Billing = named(() => import('./pages/Billing'), 'Billing')
const BillingSuccess = named(() => import('./pages/BillingSuccess'), 'BillingSuccess')
const Buddy = named(() => import('./pages/Buddy'), 'Buddy')
const BuddyPrint = named(() => import('./pages/BuddyPrint'), 'BuddyPrint')
const Calculator = named(() => import('./pages/Calculator'), 'Calculator')
const Caseload = named(() => import('./pages/Caseload'), 'Caseload')
const CaseDetail = named(() => import('./pages/CaseDetail'), 'CaseDetail')
const Claims = named(() => import('./pages/Claims'), 'Claims')
const ConditionDetail = named(() => import('./pages/ConditionDetail'), 'ConditionDetail')
const Conditions = named(() => import('./pages/Conditions'), 'Conditions')
const ConcurrentPay = named(() => import('./pages/ConcurrentPay'), 'ConcurrentPay')
const Corrections = named(() => import('./pages/Corrections'), 'Corrections')
const CorrectionsPrint = named(() => import('./pages/CorrectionsPrint'), 'CorrectionsPrint')
const CpCompanion = named(() => import('./pages/CpCompanion'), 'CpCompanion')
const BuildCase = named(() => import('./pages/BuildCase'), 'BuildCase')
const Dashboard = named(() => import('./pages/Dashboard'), 'Dashboard')
const Decode = named(() => import('./pages/Decode'), 'Decode')
const Documents = named(() => import('./pages/Documents'), 'Documents')
const Evidence = named(() => import('./pages/Evidence'), 'Evidence')
const Actions = named(() => import('./pages/Actions'), 'Actions')
const Filing = named(() => import('./pages/Filing'), 'Filing')
const Help = named(() => import('./pages/Help'), 'Help')
const ForgotPassword = named(() => import('./pages/ForgotPassword'), 'ForgotPassword')
const Form526 = named(() => import('./pages/Form526'), 'Form526')
const Form526Print = named(() => import('./pages/Form526Print'), 'Form526Print')
const AdminServices = named(() => import('./pages/AdminServices'), 'AdminServices')
const Appeals = named(() => import('./pages/Appeals'), 'Appeals')
const AppealsPrint = named(() => import('./pages/AppealsPrint'), 'AppealsPrint')
const Itf = named(() => import('./pages/Itf'), 'Itf')
const Journey = named(() => import('./pages/Journey'), 'Journey')
const Legal = named(() => import('./pages/Legal'), 'Legal')
const Nexus = named(() => import('./pages/Nexus'), 'Nexus')
const NexusPrint = named(() => import('./pages/NexusPrint'), 'NexusPrint')
const Onboarding = named(() => import('./pages/Onboarding'), 'Onboarding')
const OrgConsole = named(() => import('./pages/OrgConsole'), 'OrgConsole')
const Packet = named(() => import('./pages/Packet'), 'Packet')
const Presumptives = named(() => import('./pages/Presumptives'), 'Presumptives')
const WhatsChanged = named(() => import('./pages/WhatsChanged'), 'WhatsChanged')
const Raider = named(() => import('./pages/Raider'), 'Raider')
const Rank = named(() => import('./pages/Rank'), 'Rank')
const Profile = named(() => import('./pages/Profile'), 'Profile')
const Readiness = named(() => import('./pages/Readiness'), 'Readiness')
const Records = named(() => import('./pages/Records'), 'Records')
const ReviewQueue = named(() => import('./pages/ReviewQueue'), 'ReviewQueue')
const RequestLetterPrint = named(() => import('./pages/RecordsPrintViews'), 'RequestLetterPrint')
const Sf180Print = named(() => import('./pages/RecordsPrintViews'), 'Sf180Print')
const Va2010206Print = named(() => import('./pages/RecordsPrintViews'), 'Va2010206Print')
const Scenarios = named(() => import('./pages/Scenarios'), 'Scenarios')
const Secondaries = named(() => import('./pages/Secondaries'), 'Secondaries')
const Settings = named(() => import('./pages/Settings'), 'Settings')
const Grants = named(() => import('./pages/Grants'), 'Grants')
const SsoCallback = named(() => import('./pages/SsoCallback'), 'SsoCallback')
const ResetPassword = named(() => import('./pages/ResetPassword'), 'ResetPassword')
const VerifyEmail = named(() => import('./pages/VerifyEmail'), 'VerifyEmail')
const InviteAccept = named(() => import('./pages/InviteAccept'), 'InviteAccept')
const Teams = named(() => import('./pages/Teams'), 'Teams')
const Statement = named(() => import('./pages/Statement'), 'Statement')
const StatementPrint = named(() => import('./pages/StatementPrint'), 'StatementPrint')
const Survivors = named(() => import('./pages/Survivors'), 'Survivors')
const Tdiu = named(() => import('./pages/Tdiu'), 'Tdiu')
const TdiuPrint = named(() => import('./pages/TdiuPrint'), 'TdiuPrint')
const Dependency = named(() => import('./pages/Dependency'), 'Dependency')
const DependencyPrint = named(() => import('./pages/DependencyPrint'), 'DependencyPrint')
const Strategy = named(() => import('./pages/Strategy'), 'Strategy')
const VaImport = named(() => import('./pages/VaImport'), 'VaImport')
const StrategyPrint = named(() => import('./pages/StrategyPrint'), 'StrategyPrint')
const CaseBrief = named(() => import('./pages/CaseBrief'), 'CaseBrief')
const SymptomLog = named(() => import('./pages/SymptomLog'), 'SymptomLog')
const VaSync = named(() => import('./pages/VaSync'), 'VaSync')
const Workflows = named(() => import('./pages/Workflows'), 'Workflows')
const NotFound = named(() => import('./pages/NotFound'), 'NotFound')

/** Lightweight fallback while a route chunk loads — a quiet centered pulse, no
 * layout shift (fills the routed area). */
function RouteFallback() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center" role="status" aria-live="polite">
      <span className="sr-only">Loading…</span>
      <span className="h-6 w-6 animate-pulse rounded-full bg-line" aria-hidden />
    </div>
  )
}

// Canonical first-run (P0): a brand-new veteran lands on guided setup
// (`/onboarding`), not a blank dashboard or profile. We route them there exactly
// once (a localStorage flag), so returning veterans and anyone who's already set
// things up land on the dashboard as usual and are never nagged. If the profile
// is empty but they already have documents (e.g. dropped files first), send them
// to documents instead so they can keep building the case.
const FIRST_RUN_KEY = 'vo_profile_first_routed'

function hasRoutedFirstRun(): boolean {
  try {
    return localStorage.getItem(FIRST_RUN_KEY) === '1'
  } catch {
    return true // storage unavailable — never force the redirect
  }
}

/** The index element: for a returning veteran render the Dashboard immediately
 * (no extra fetch); for a first-run veteran, decide once whether to steer them to
 * the canonical onboarding start. */
function HomeRoute() {
  if (hasRoutedFirstRun()) return <Dashboard />
  return <FirstRunDecider />
}

/** One-shot: read profile + documents summary (best-effort). Empty profile with
 * no docs → `/onboarding?start=1`. Empty profile with docs already present →
 * `/documents` so they keep building. Otherwise fall through to the Dashboard.
 * Marks the flag so this only ever happens once. */
function FirstRunDecider() {
  const { data, loading } = useAsync(async () => {
    const [profile, docs] = await Promise.all([
      profileApi.get().catch(() => emptyProfile()),
      documentsApi.summary().catch(() => null),
    ])
    return { profile, docs }
  })

  // Mark first-run as consumed once we have a decision (empty or not).
  useEffect(() => {
    if (loading || data == null) return
    try {
      localStorage.setItem(FIRST_RUN_KEY, '1')
    } catch {
      /* storage unavailable — non-fatal */
    }
  }, [loading, data])

  if (loading || data == null) return <RouteFallback />
  if (!isEmptyProfile(data.profile)) return <Dashboard />
  // Profile empty but records already uploaded → keep them in the documents path.
  if ((data.docs?.total ?? 0) > 0) return <Navigate to="/documents" replace />
  return <Navigate to="/onboarding?start=1" replace />
}

/** Redirect already-authenticated veterans away from the login screen. */
function LoginRoute() {
  const { user, loading } = useAuth()
  if (loading) return null
  if (user) return <Navigate to="/" replace />
  return <Login />
}

export default function App() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route path="/login" element={<LoginRoute />} />
        <Route path="/auth/sso-callback" element={<SsoCallback />} />
        {/* Self-service auth flows — public (the signed token in the URL is the proof;
            they work from a fresh browser with no session). */}
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        {/* Org invitation accept — handles its own auth state (prompts sign-in with the
            invited email if needed). */}
        <Route path="/invite" element={<InviteAccept />} />
        <Route
          path="/billing/success"
          element={
            <RequireAuth>
              <Shell>
                <BillingSuccess />
              </Shell>
            </RequireAuth>
          }
        />
        {/* Terms + privacy — public (GET /api/legal is unauthenticated; shown
            pre-signup, and a VA Lighthouse production-access prerequisite). */}
        <Route path="/legal" element={<Legal />} />
        {/* Packet and the records worksheets are standalone print views — no
            shell chrome, own routes (Packet.tsx pattern, WAVE2-SPEC §2). */}
        <Route
          path="/conditions/:id/packet"
          element={
            <RequireAuth>
              <Packet />
            </RequireAuth>
          }
        />
        <Route
          path="/records/sf180"
          element={
            <RequireAuth>
              <Sf180Print />
            </RequireAuth>
          }
        />
        <Route
          path="/records/va20-10206"
          element={
            <RequireAuth>
              <Va2010206Print />
            </RequireAuth>
          }
        />
        <Route
          path="/records/request-letter/print"
          element={
            <RequireAuth>
              <RequestLetterPrint />
            </RequireAuth>
          }
        />
        <Route
          path="/buddy/print"
          element={
            <RequireAuth>
              <BuddyPrint />
            </RequireAuth>
          }
        />
        <Route
          path="/application/print"
          element={
            <RequireAuth>
              <Form526Print />
            </RequireAuth>
          }
        />
        <Route
          path="/nexus/print"
          element={
            <RequireAuth>
              <NexusPrint />
            </RequireAuth>
          }
        />
        <Route
          path="/statement/print"
          element={
            <RequireAuth>
              <StatementPrint />
            </RequireAuth>
          }
        />
        <Route
          path="/tdiu/print"
          element={
            <RequireAuth>
              <TdiuPrint />
            </RequireAuth>
          }
        />
        <Route
          path="/dependency/print"
          element={
            <RequireAuth>
              <DependencyPrint />
            </RequireAuth>
          }
        />
        <Route
          path="/appeals/print"
          element={
            <RequireAuth>
              <AppealsPrint />
            </RequireAuth>
          }
        />
        <Route
          path="/strategy/print"
          element={
            <RequireAuth>
              <StrategyPrint />
            </RequireAuth>
          }
        />
        <Route
          path="/strategy/case-brief"
          element={
            <RequireAuth>
              <CaseBrief />
            </RequireAuth>
          }
        />
        <Route
          path="/case-brief"
          element={
            <RequireAuth>
              <CaseBrief />
            </RequireAuth>
          }
        />
        <Route
          path="/corrections/print"
          element={
            <RequireAuth>
              <CorrectionsPrint />
            </RequireAuth>
          }
        />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Shell />
            </RequireAuth>
          }
        >
          <Route index element={<HomeRoute />} />
          <Route path="raider" element={<Raider />} />
          <Route path="workflows" element={<Workflows />} />
          <Route path="journey" element={<Journey />} />
          <Route path="onboarding" element={<Onboarding />} />
          <Route path="profile" element={<Profile />} />
          <Route path="conditions" element={<Conditions />} />
          <Route path="build-case" element={<BuildCase />} />
          <Route path="conditions/:id" element={<ConditionDetail />} />
          <Route path="claims" element={<Claims />} />
          <Route path="calculator" element={<Calculator />} />
          <Route path="scenarios" element={<Scenarios />} />
          <Route path="backpay" element={<Backpay />} />
          <Route path="benefits" element={<Benefits />} />
          <Route path="readiness" element={<Readiness />} />
          <Route path="itf" element={<Itf />} />
          <Route path="symptom-log" element={<SymptomLog />} />
          <Route path="buddy" element={<Buddy />} />
          <Route path="cp-companion" element={<CpCompanion />} />
          <Route path="va-sync" element={<VaSync />} />
          <Route path="va-import" element={<VaImport />} />
          <Route path="secondaries" element={<Secondaries />} />
          <Route path="presumptives" element={<Presumptives />} />
          <Route path="whats-changed" element={<WhatsChanged />} />
          <Route path="analysis" element={<AnalysisCenter />} />
          <Route path="strategy" element={<Strategy />} />
          <Route path="decode" element={<Decode />} />
          <Route path="appeals" element={<Appeals />} />
          <Route path="evidence" element={<Evidence />} />
          <Route path="actions" element={<Actions />} />
          <Route path="filing" element={<Filing />} />
          <Route path="help" element={<Help />} />
          <Route path="records" element={<Records />} />
          <Route path="review-queue" element={<ReviewQueue />} />
          <Route path="application" element={<Form526 />} />
          <Route path="nexus" element={<Nexus />} />
          <Route path="statement" element={<Statement />} />
          <Route path="tdiu" element={<Tdiu />} />
          <Route path="concurrent-pay" element={<ConcurrentPay />} />
          <Route path="survivors" element={<Survivors />} />
          <Route path="dependency" element={<Dependency />} />
          <Route path="corrections" element={<Corrections />} />
          <Route path="rank" element={<Rank />} />
          <Route path="documents" element={<Documents />} />
          <Route path="teams" element={<Teams />} />
          <Route path="caseload" element={<Caseload />} />
          <Route path="caseload/:id" element={<CaseDetail />} />
          <Route path="console" element={<OrgConsole />} />
          <Route path="billing" element={<Billing />} />
          <Route path="grants" element={<Grants />} />
          <Route path="settings" element={<Settings />} />
          <Route path="admin/services" element={<AdminServices />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  )
}
