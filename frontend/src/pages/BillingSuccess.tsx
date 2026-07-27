import { CheckCircle2, CreditCard, RefreshCw } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { Badge, EmptyState, ErrorBlock, LoadingBlock, Panel } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { creditsApi } from '../lib/api'
import { formatDateTime, humanize } from '../lib/format'

async function loadCredits() {
  return creditsApi.get()
}

export function BillingSuccess() {
  const [params] = useSearchParams()
  const { data, loading, error, reload } = useAsync(loadCredits)
  const product = params.get('product') ?? 'purchase'

  if (loading) {
    return (
      <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6">
        <LoadingBlock label="Refreshing your balance…" />
      </div>
    )
  }
  if (error || !data) {
    return (
      <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6">
        <ErrorBlock message={error ?? 'Could not load your credit balance.'} onRetry={reload} />
      </div>
    )
  }

  const recent = data.recent[0]
  const sponsorCheckout = product === 'sponsor'
  const headline = sponsorCheckout ? 'Sponsor recorded' : 'Payment complete'
  const body = sponsorCheckout
    ? 'Your sponsored claim has been recorded. The grant pool changed, but your own balance stays the same.'
    : 'Your hosted Stripe checkout completed. The balance below is the live wallet now tied to your account.'
  return (
    <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="settings">
      <div className="vo-page-head vo-section-band">
        <h1 className="vo-page-title">{headline}</h1>
        <p className="vo-page-sub">{body}</p>
      </div>

      <Panel hue="emerald">
        <div className="space-y-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-success/10 text-success">
                <CheckCircle2 size={22} />
              </span>
              <div>
                <p className="text-micro font-semibold uppercase tracking-wider text-faint">
                  {sponsorCheckout ? 'Your wallet balance' : 'Current balance'}
                </p>
                <h2 className="text-display text-txt">{data.balance.toLocaleString()} credits</h2>
              </div>
            </div>
            <Badge tone="primary">{humanize(product)}</Badge>
          </div>

          <div className="rounded-control border border-line bg-surface2 px-4 py-3 text-sm text-muted">
            <div className="flex items-center gap-2 text-txt">
              <CreditCard size={15} className="text-brand" />
              <span>{sponsorCheckout ? 'Sponsor credit check' : 'Wallet update'}</span>
            </div>
            <p className="mt-1 text-sm text-muted">
              {sponsorCheckout
                ? 'Your sponsor purchase added claims to the grant pool. Your personal balance is unchanged.'
                : 'Your wallet is being refreshed so the latest balance shows in the app.'}
            </p>
            {recent ? (
              <p className="mt-2 text-xs text-faint">
                Most recent activity: {humanize(recent.operation.replace(/\./g, ' '))} at {formatDateTime(recent.created_at)}
              </p>
            ) : null}
          </div>

          <div className="flex flex-wrap gap-3">
            <Link to="/billing" className="vo-btn-primary text-sm">
              <RefreshCw size={15} /> Refresh billing
            </Link>
            <Link to="/" className="vo-btn-secondary text-sm">
              Back to dashboard
            </Link>
          </div>
        </div>
      </Panel>

      <EmptyState
        hue="emerald"
        title={sponsorCheckout ? 'The grant pool is funded' : 'Your wallet is ready'}
        description={
          sponsorCheckout
            ? 'The sponsored claim is available for review in the grant flow. Your own balance did not change.'
            : 'If you bought Full Access or a top-up, the credits are now available in your wallet.'
        }
      />
    </div>
  )
}
