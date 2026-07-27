/**
 * README screenshot gallery — captured from the REAL React app.
 *
 * Every capture here drives the actual product UI. Only the API responses
 * behind it are mocked, and every one of them is synthetic (see synthetic.ts):
 * no real veteran, no real record, no real decision letter, no PII, no secrets.
 *
 * These tests are inert during a normal run. To refresh the gallery:
 *
 *   README_SCREENSHOTS=1 npm run test:e2e -- --project=desktop-chromium
 *
 * Desktop captures are 1440 wide; the mobile capture is 390 wide and runs under
 * the same project so one command refreshes the whole gallery. A few screens
 * raise the viewport HEIGHT: the app Shell scrolls <main> internally, so
 * `fullPage` stops at the viewport and a taller window is how a long screen fits
 * in one honest image rather than three stitched crops.
 */
import { expect, test } from '@playwright/test'
import { installSyntheticApi, seedSession } from './synthetic'

test.skip(!process.env.README_SCREENSHOTS, 'README gallery capture only')

const SHOTS = '../docs/screenshots'

test.describe('README gallery (synthetic demo data)', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test('front door', async ({ page }) => {
    await installSyntheticApi(page)
    await page.goto('/login')
    await expect(page.getByLabel('Email')).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/login-front-door.png`, fullPage: true })
  })

  test('onboarding first run', async ({ page }) => {
    await seedSession(page)
    await installSyntheticApi(page)
    await page.goto('/onboarding')
    await expect(page.getByRole('button', { name: /continue|next|start/i }).first()).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/veteran-ops-onboarding-synthetic.png`, fullPage: true })
  })

  test('analysis center', async ({ page }) => {
    await seedSession(page)
    await installSyntheticApi(page)
    await page.goto('/analysis')
    await expect(page.getByRole('heading', { name: 'Analysis Center' })).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/analysis-center-synthetic.png`, fullPage: true })
  })

  test('rating raider gap interview', async ({ page }) => {
    await seedSession(page, { pastChats: true })
    await installSyntheticApi(page)
    await page.goto('/raider?mode=post_analysis')
    await expect(page.getByText('Optional but recommended')).toBeVisible()
    await expect(page.getByText('Saved on this device')).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/rating-raider-synthetic.png`, fullPage: true })
  })

  // Taller than 900 so the whole thread — agent identity, past chats, the streamed
  // turn, and the Claim Plan hand-off — reads in one image instead of three.
  test('rating raider conversation, past chats, and claim plan handoff', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1330 })
    await seedSession(page, { pastChats: true })
    await installSyntheticApi(page)
    await page.goto('/raider?mode=post_analysis')

    // Drive the real interview flow: this streams a turn through the app's own
    // SSE client, so the thread below is rendered exactly as it is in production.
    await page.getByRole('button', { name: /start gap interview/i }).click()
    await expect(page.getByText(/keep you from working a full day/i)).toBeVisible()
    await expect(page.getByText('Ready for the ordered plan?')).toBeVisible()

    // Open the browser-local history so "Past chats" and "New chat" are both visible.
    await page.getByRole('button', { name: /past chats/i }).click()
    await expect(page.getByText('What does "nexus" actually mean?')).toBeVisible()

    await page.screenshot({ path: `${SHOTS}/rating-raider-chat-synthetic.png`, fullPage: true })
  })

  // The Shell scrolls <main> internally, so fullPage stops at the viewport. Use a
  // tall viewport here to show the whole coach spine: Do this first → Then →
  // Parked → Outstanding, with the standing disclaimer above it.
  test('claim plan', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1830 })
    await seedSession(page)
    await installSyntheticApi(page)
    await page.goto('/strategy')
    await expect(page.getByRole('heading', { name: 'Your Claim Plan' })).toBeVisible()
    await expect(page.getByText('Do this first').first()).toBeVisible()
    await expect(page.getByText('Outstanding').first()).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/veteran-ops-claim-plan-synthetic.png`, fullPage: true })
  })

  test('conditions and evidence workspace', async ({ page }) => {
    await seedSession(page)
    await installSyntheticApi(page)
    await page.goto('/evidence')
    await expect(page.getByText('Lumbosacral strain').first()).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/veteran-ops-evidence-synthetic.png`, fullPage: true })
  })

  test('printable case brief', async ({ page }) => {
    await seedSession(page)
    await installSyntheticApi(page)
    await page.goto('/case-brief')
    await expect(page.getByRole('heading', { name: /case brief/i })).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/veteran-ops-case-brief-synthetic.png`, fullPage: true })
  })
})

test.describe('README gallery — mobile (synthetic demo data)', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  test('claim plan on a phone', async ({ page }) => {
    // 390 wide is the phone; the extra height carries the shot past the intro to
    // the "Do this first" card, which is the point of the screen.
    await page.setViewportSize({ width: 390, height: 1500 })
    await seedSession(page)
    await installSyntheticApi(page)
    await page.goto('/strategy')
    await expect(page.getByRole('heading', { name: 'Your Claim Plan' })).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/veteran-ops-mobile-synthetic.png`, fullPage: true })
  })
})
