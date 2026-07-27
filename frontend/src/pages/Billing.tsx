import {
  Building2,
  Check,
  CircleDollarSign,
  CreditCard,
  ExternalLink,
  Heart,
  Infinity as InfinityIcon,
  ArrowRight,
  Sparkles,
  Users,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { Badge, ErrorBlock, LoadingBlock, Panel } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage } from '../hooks/useAsync'
import { useAsync } from '../hooks/useAsync'
import { billingApi, creditsApi } from '../lib/api'
import { humanize } from '../lib/format'
import type { BillingStatus, CreditProduct, CreditsResponse, Plan, PlansResponse } from '../types'

/** Turn a backend feature key into a plain-English capability. Falls back to a
 * title-cased version of the key so an unknown feature still reads. */
const FEATURE_LABELS: Record<string, string> = {
  org_invites: 'Invite teammates',
  staff_caseload: 'Shared caseload',
  org_admin_console: 'Admin console',
  org_audit: 'Activity trail',
  white_label: 'White-label branding',
  sso_byoidp: 'Bring-your-own SSO',
  priority_support: 'Priority support',
}

function featureLabel(key: string): string {
  return FEATURE_LABELS[key] ?? humanize(key)
}

const CREDIT_ACTIVITY_LABELS: Record<string, string> = {
  'document.process': 'Document processed',
  'document.decode': 'Decision decoded',
  'analysis.map_conditions': 'Conditions mapped',
  'analysis.secondaries': 'Secondaries suggested',
  'analysis.case_candidates': 'Case candidates built',
  'grant.approved': 'Grant awarded',
}

function creditActivityLabel(operation: string): string {
  return CREDIT_ACTIVITY_LABELS[operation] ?? humanize(operation.replace(/\./g, ' '))
}

/** Price line for a plan card: "Free", "$49/mo", or "Contact us". */
function priceLabel(price: number | null): string {
  if (price === null) return 'Contact us'
  if (price === 0) return 'Free'
  return `$${price}/mo`
}

function seatLabel(seatLimit: number): string {
  if (seatLimit === -1) return 'Unlimited seats'
  return `${seatLimit} seat${seatLimit === 1 ? '' : 's'}`
}

interface BillingData {
  status: BillingStatus
  plans: PlansResponse
  credits: CreditsResponse
}

async function loadBilling(): Promise<BillingData> {
  const [status, plans, credits] = await Promise.all([billingApi.status(), billingApi.plans(), creditsApi.get()])
  return { status, plans, credits }
}

export function Billing() {
  const { toast } = useToast()
  const { data, loading, error, reload } = useAsync(loadBilling)
  const [sponsorEmail, setSponsorEmail] = useState('')
  const [pending, setPending] = useState<CreditProduct | null>(null)

  if (loading)
    return (
      <div className="vo-page mx-auto w-full max-w-5xl space-y-6 p-4 sm:p-6" data-section="settings">
        <LoadingBlock label="Loading plans…" />
      </div>
    )
  if (error || !data)
    return (
      <div className="vo-page mx-auto w-full max-w-5xl space-y-6 p-4 sm:p-6" data-section="settings">
        <ErrorBlock message={error ?? 'Could not load billing.'} onRetry={reload} />
      </div>
    )

  const { status, plans, credits } = data

  const startCheckout = async (product: CreditProduct) => {
    if (pending) return
    setPending(product)
    try {
      const body =
        product === 'sponsor' && sponsorEmail.trim()
          ? { product, beneficiary_email: sponsorEmail.trim() }
          : { product }
      const session = await billingApi.checkoutSession(body)
      window.location.assign(session.url)
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setPending(null)
    }
  }

  return (
    <div className="vo-page mx-auto w-full max-w-5xl space-y-6 p-4 sm:p-6" data-section="settings">
      <div className="vo-page-head vo-section-band">
        <h1 className="vo-page-title">Plans &amp; billing</h1>
        <p className="vo-page-sub">
          Individual veteran self-help is free, always. Full Access purchases, top-ups, and sponsorships use a hosted
          Stripe checkout; team plans remain separate.
        </p>
      </div>

      {/* The consumer credit + grant surface only appears once self-serve billing is
          live (Stripe wired + flag on). While it's dormant, individual use is simply
          free and these cards would be non-functional, so they stay hidden. */}
      {status.self_serve && (
        <>
          <CreditWalletCard credits={credits} />
          <SelfServeActions sponsorEmail={sponsorEmail} setSponsorEmail={setSponsorEmail} pending={pending} onStart={startCheckout} />
        </>
      )}
      <CurrentPlanCard status={status} />
      <ManageBilling status={status} />
      <PlansGrid plans={plans.plans} />
      {status.self_serve && (
        <Panel hue="teal" title="Grant support" subtitle="Need-based help and sponsor-backed claims">
          <div className="flex flex-wrap items-center justify-between gap-3 p-5">
            <div className="space-y-1 text-sm text-muted">
              <p className="text-txt">If you need a grant, apply and a person on our team will review it.</p>
              <p>Sponsored claims go into the grant pool, then we award the next eligible applicant.</p>
            </div>
            <Link to="/grants" className="vo-btn-primary text-sm">
              Request a grant <ArrowRight size={15} />
            </Link>
          </div>
        </Panel>
      )}
    </div>
  )
}

function CreditWalletCard({ credits }: { credits: CreditsResponse }) {
  const latest = credits.recent[0]
  return (
    <Panel hue="emerald">
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-success/10 text-success">
              <CircleDollarSign size={22} />
            </span>
            <div>
              <p className="text-micro font-semibold uppercase tracking-wider text-faint">Credit wallet</p>
              <h2 className="text-heading text-txt">{credits.balance.toLocaleString()} credits</h2>
            </div>
          </div>
          <Badge tone="primary">Live balance</Badge>
        </div>
        {latest ? (
          <div className="rounded-control border border-line bg-surface2 px-4 py-3 text-sm text-muted">
            <p className="font-medium text-txt">{creditActivityLabel(latest.operation)}</p>
            <p className="mt-1">
              {latest.delta >= 0 ? '+' : ''}
              {latest.delta} credits · balance now {latest.balance_after}
            </p>
            <p className="mt-3 border-t border-line pt-3 text-xs leading-relaxed text-muted">
              <strong className="text-txt">What you get</strong>
              <span className="mt-1 block">
                One-time access, not a subscription. Credits are spent when you ask Rating Raider to read or analyze
                your own records or decode a VA letter. Anything you already created stays in your account if you
                run out, and you can add a top-up whenever you need more.
              </span>
            </p>
          </div>
        ) : (
          <div className="rounded-control border border-line bg-surface2 px-4 py-3 text-sm text-muted">
            <p>No credit activity yet. Your first purchase, sponsorship, or grant will appear here.</p>
            <p className="mt-3 border-t border-line pt-3 text-xs leading-relaxed text-muted">
              <strong className="text-txt">What you get</strong>
              <span className="mt-1 block">
                One-time access, not a subscription. Credits are spent when you ask Rating Raider to read or analyze
                your own records or decode a VA letter. Anything you already created stays in your account if you
                run out, and you can add a top-up whenever you need more.
              </span>
            </p>
          </div>
        )}
      </div>
    </Panel>
  )
}

function SelfServeActions({
  sponsorEmail,
  setSponsorEmail,
  pending,
  onStart,
}: {
  sponsorEmail: string
  setSponsorEmail: (value: string) => void
  pending: CreditProduct | null
  onStart: (product: CreditProduct) => Promise<void>
}) {
  return (
    <Panel hue="amber" title="Self-serve checkout" subtitle="Hosted by Stripe; no card data touches this app">
      <div className="grid gap-4 p-5 md:grid-cols-3">
        <ActionCard
          title="Full Access"
          price="$100"
          blurb="One-time, not a subscription. Includes 1,000 credits — enough to work a whole claim."
          actionLabel={pending === 'full_claim' ? 'Starting…' : 'Get Full Access'}
          onClick={() => void onStart('full_claim')}
        />
        <ActionCard
          title="Add credits"
          price="$25"
          blurb="A top-up adds 300 credits for an unusually large records file."
          actionLabel={pending === 'topup' ? 'Starting…' : 'Add a top-up'}
          onClick={() => void onStart('topup')}
        />
        <div className="rounded-control border border-line bg-surface2 p-4">
          <p className="text-sm font-semibold text-txt">Sponsor a veteran</p>
          <p className="mt-1 text-sm text-muted">Cover Full Access for a veteran who's struggling — name them by email, or leave it blank to fund the next veteran in the grant pool.</p>
          <input
            className="vo-input mt-3"
            placeholder="beneficiary@example.com"
            value={sponsorEmail}
            onChange={(e) => setSponsorEmail(e.target.value)}
          />
          <button
            className="vo-btn-primary mt-3 text-sm"
            onClick={() => void onStart('sponsor')}
            disabled={pending === 'sponsor'}
            type="button"
          >
            {pending === 'sponsor' ? 'Starting…' : 'Sponsor a veteran'}
          </button>
        </div>
      </div>
      <p className="border-t border-line px-5 py-3 text-xs leading-relaxed text-muted">
        Veteran-Ops is self-help software. Paying does not file your claim, represent you, or
        change any VA decision — it unlocks the tools you use yourself. A free VA-accredited VSO can
        always help you file.
      </p>
    </Panel>
  )
}

function ActionCard({
  title,
  price,
  blurb,
  actionLabel,
  onClick,
}: {
  title: string
  price: string
  blurb: string
  actionLabel: string
  onClick: () => void
}) {
  return (
    <div className="rounded-control border border-line bg-surface2 p-4">
      <p className="text-sm font-semibold text-txt">{title}</p>
      <p className="mt-1 text-2xl font-bold text-txt">{price}</p>
      <p className="mt-2 text-sm text-muted">{blurb}</p>
      <button className="vo-btn-primary mt-3 text-sm" type="button" onClick={onClick}>
        {actionLabel}
      </button>
    </div>
  )
}

function CurrentPlanCard({ status }: { status: BillingStatus }) {
  const isPersonal = status.kind === 'personal'
  const unlimited = status.seat_limit === -1
  const features = status.features.filter(Boolean)

  return (
    <Panel hue="violet">
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-brand-soft text-brand">
              {isPersonal ? <Heart size={22} /> : <Building2 size={22} />}
            </span>
            <div className="min-w-0">
              <p className="text-micro font-semibold uppercase tracking-wider text-faint">Current plan</p>
              <h2 className="truncate text-heading text-txt">{status.plan_name}</h2>
              <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted">
                <span className="inline-flex items-center gap-1">
                  <Users size={13} className="text-faint" />
                  {status.seats_used} of {unlimited ? 'unlimited' : status.seat_limit} seat
                  {status.seat_limit === 1 ? '' : 's'} used
                </span>
              </p>
            </div>
          </div>
          <Badge tone={isPersonal ? 'neutral' : 'primary'}>{humanize(status.tier)}</Badge>
        </div>

        {isPersonal ? (
          <p className="flex items-start gap-2 rounded-control border border-line bg-surface2 px-4 py-3 text-sm leading-relaxed text-muted">
            <Heart size={16} className="mt-0.5 shrink-0 text-brand" />
            <span>
              You're on the free Individual plan — every self-help tool is yours, always free. The plans below
              are for teams and organizations.
            </span>
          </p>
        ) : features.length > 0 ? (
          <div>
            <p className="mb-2 text-micro font-semibold uppercase tracking-wider text-faint">Included</p>
            <ul className="grid gap-2 sm:grid-cols-2">
              {features.map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm text-txt">
                  <Check size={15} className="shrink-0 text-success" />
                  {featureLabel(f)}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </Panel>
  )
}

/** The upgrade / manage-billing affordance, gated by manageability + how the
 * suite operates billing for this workspace. Never a checkout button. */
function ManageBilling({ status }: { status: BillingStatus }) {
  if (!status.manageable) {
    return (
      <div className="animate-pop-in flex items-start gap-2.5 rounded-control border border-line bg-surface2 px-4 py-3 text-sm">
        <Sparkles size={16} className="mt-0.5 shrink-0 text-faint" />
        <span className="text-muted">
          Billing for this team is managed by an owner or admin. Ask them if you need to change your plan.
        </span>
      </div>
    )
  }

  if (status.portal_url) {
    const label = status.self_serve ? 'Upgrade or manage billing' : 'Manage billing'
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-brand/40 bg-brand-soft px-4 py-3.5">
        <span className="flex items-start gap-2 text-sm text-txt">
          <CreditCard size={16} className="mt-0.5 shrink-0 text-brand" />
          {status.self_serve
            ? 'Change your plan or update payment details in the billing portal.'
            : 'View invoices and payment details in the billing portal.'}
        </span>
        <a
          href={status.portal_url}
          target="_blank"
          rel="noopener noreferrer"
          className="vo-btn-primary shrink-0 text-sm"
        >
          {label}
          <ExternalLink size={15} />
        </a>
      </div>
    )
  }

  return (
    <div className="animate-pop-in flex items-start gap-2.5 rounded-control border border-line bg-surface2 px-4 py-3 text-sm">
      <Sparkles size={16} className="mt-0.5 shrink-0 text-h-amber" />
      <span className="text-muted">
        Plan changes are managed by your account team — contact your Unicorn Commander representative to
        upgrade or adjust seats.
      </span>
    </div>
  )
}

function PlansGrid({ plans }: { plans: Plan[] }) {
  if (plans.length === 0) return null
  return (
    <div className="space-y-3">
      <h2 className="text-heading text-txt">Plans</h2>
      <div className="grid gap-4 md:grid-cols-3">
        {plans.map((plan) => (
          <PlanCard key={plan.tier} plan={plan} />
        ))}
      </div>
    </div>
  )
}

function PlanCard({ plan }: { plan: Plan }) {
  const unlimited = plan.seat_limit === -1
  return (
    <section
      className={cxRing(plan.current)}
      aria-label={`${plan.name} plan${plan.current ? ' (current plan)' : ''}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-heading text-txt">{plan.name}</h3>
          <p className="mt-0.5 text-xs text-muted">{plan.audience}</p>
        </div>
        {plan.current && <Badge tone="primary">Current plan</Badge>}
      </div>

      <div className="mt-3 flex items-baseline gap-1">
        <span className="text-2xl font-bold text-txt">{priceLabel(plan.price_monthly)}</span>
      </div>

      <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
        {unlimited ? (
          <InfinityIcon size={14} className="shrink-0 text-faint" />
        ) : (
          <Users size={13} className="shrink-0 text-faint" />
        )}
        {seatLabel(plan.seat_limit)}
      </p>

      {plan.highlights.length > 0 && (
        <ul className="mt-4 space-y-2 border-t border-line pt-4">
          {plan.highlights.map((h, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-txt">
              <Check size={15} className="mt-0.5 shrink-0 text-success" />
              <span className="leading-relaxed">{h}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** Plan card shell — the current plan gets a brand ring; others a plain panel. */
function cxRing(current: boolean): string {
  const base = 'vo-panel flex flex-col p-5'
  return current
    ? `${base} border-brand/60 shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--brand)_45%,transparent)]`
    : base
}
