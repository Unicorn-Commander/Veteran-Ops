import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Request, type Route } from '@playwright/test'

const userId = '00000000-0000-0000-0000-0000000000a1'
const workspaceId = '00000000-0000-0000-0000-0000000000c3'
const runId = '00000000-0000-0000-0000-0000000000d4'

const steps = [
  { key: 'assemble', label: 'Assemble case', status: 'pending', seconds: null, detail: null },
  { key: 'briefing', label: 'Plain-language briefing', status: 'pending', seconds: null, detail: null },
  { key: 'firm', label: 'Specialist review', status: 'pending', seconds: null, detail: null },
  { key: 'deep_dive', label: 'Rating deep dive', status: 'pending', seconds: null, detail: null },
  { key: 'comprehension', label: 'Whole-case comprehension', status: 'pending', seconds: null, detail: null },
]

function run(status: 'queued' | 'cancelled') {
  return {
    id: runId,
    status,
    steps,
    ran: null,
    summary: null,
    error: status === 'cancelled' ? 'Analysis cancelled at your request.' : null,
    started_at: null,
    finished_at: status === 'cancelled' ? '2026-07-20T12:00:00Z' : null,
    total_seconds: null,
    attempt_count: 0,
    max_attempts: 3,
    next_attempt_at: null,
    lease_expires_at: null,
    cancel_requested: status === 'cancelled',
    created_at: '2026-07-20T11:59:00Z',
  }
}

async function json(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    sessionStorage.setItem('vo_token', 'synthetic-auth-token')
    localStorage.setItem('vo_disclaimer_ack', '1')
    localStorage.setItem('vo_disclaimer_footer_dismissed', '1')
    localStorage.setItem('vo_theme', 'dark')
  })

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (path === '/api/auth/me') {
      return json(route, {
        id: userId,
        email: 'synthetic@example.test',
        full_name: 'Synthetic Veteran',
        email_verified: true,
        avatar_url: null,
        platform_admin: false,
        created_at: '2026-07-20T00:00:00Z',
      })
    }
    if (path === '/api/workspaces') {
      return json(route, {
        workspaces: [{ id: workspaceId, name: 'Personal', kind: 'personal', plan_tier: 'free', status: 'active', role: 'owner' }],
        current_workspace_id: workspaceId,
      })
    }
    if (path === '/api/entitlements') {
      return json(route, { workspace_id: workspaceId, kind: 'personal', tier: 'free', role: 'owner', features: [], seat_limit: 1 })
    }
    if (path === '/api/meta') {
      return json(route, {
        name: 'Rating Raider', version: 'synthetic', disclaimer: '', va_enabled: false,
        billing_self_serve: false, kb_stale: false, kb_verified_as_of: '2026-07-20', kb_status: 'current',
      })
    }
    if (path === '/api/analysis/case-picture') return json(route, null)
    if (path === '/api/analysis/automation-status') {
      return json(route, {
        deep_dive: { last_run: null, has_new_findings: false, auto_on_intake: false },
        comprehension: { available: false, generated_at: null, auto_on_intake: false },
        verification: { flagged_docs: 0, enabled: true },
        cross_read: { disagreement_pages: 0 },
        review_queue: { pending: 0 },
        automations: [],
      })
    }
    if (path === '/api/analysis/intake-benchmark') {
      return json(route, {
        documents: 1, ready: 1, failed: 0, processing: 0, duplicates: 0, total_bytes: 1024,
        total_processing_seconds: 2, wall_clock_seconds: 2, avg_seconds_per_doc: 2,
        first_uploaded_at: '2026-07-20T00:00:00Z', last_ready_at: '2026-07-20T00:00:02Z',
      })
    }
    if (path === '/api/analysis/comprehensive/prerequisites') {
      return json(route, { ready: true, conditions: 1, ready_documents: 1, processing_documents: 0, failed_documents: 0, missing: [] })
    }
    if (path === '/api/analysis/comprehensive/latest') return json(route, null)
    if (path === '/api/analysis/comprehensive/runs' && request.method() === 'GET') return json(route, [])
    if (path === '/api/analysis/comprehensive/start') return json(route, run('queued'))
    if (path === `/api/analysis/comprehensive/runs/${runId}/cancel`) return json(route, run('cancelled'))
    if (path === `/api/analysis/comprehensive/runs/${runId}`) return json(route, run('queued'))
    await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"synthetic route missing"}' })
  })
})

test('authenticated veteran can enqueue and cancel a durable full review', async ({ page }) => {
  let startRequest: Request | null = null
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/analysis/comprehensive/start') startRequest = request
  })

  await page.goto('/analysis')
  await expect(page.getByRole('heading', { name: 'Analysis Center' })).toBeVisible()
  await page.locator('#comprehensive').getByRole('button', { name: 'Run full case review' }).click()
  await expect(page.getByText('Queued durably — waiting for a worker…')).toBeVisible()
  expect(startRequest?.headers()['authorization']).toBe('Bearer synthetic-auth-token')
  expect(startRequest?.headers()['idempotency-key']).toMatch(/^[0-9a-f-]{36}$/)

  await page.getByRole('button', { name: 'Cancel analysis' }).click()
  await expect(page.getByText('The analysis was cancelled.')).toBeVisible()

  const layout = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth > window.innerWidth,
    main: document.querySelector('main')?.getBoundingClientRect().width ?? 0,
  }))
  expect(layout.overflow).toBe(false)
  expect(layout.main).toBeGreaterThan(0)

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  expect(results.violations).toEqual([])
})
