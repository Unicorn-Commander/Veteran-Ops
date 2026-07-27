import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

const capabilityResponse = {
  sso_enabled: false,
  sso_label: 'Unicorn Commander',
  password_login_enabled: true,
  registration_open: false,
  registration_mode: 'closed',
  email_enabled: false,
  password_reset_enabled: false,
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/config', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(capabilityResponse) })
  })
  await page.goto('/login')
  await expect(page.getByLabel('Email')).toBeVisible()
})

test('login is responsive, touch-safe, and accessible', async ({ page }) => {
  await expect(page.getByRole('main')).toBeVisible()
  await expect(page.getByText('Create account')).toHaveCount(0)
  await expect(page.getByText('Forgot password?')).toHaveCount(0)

  const layout = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth > window.innerWidth,
    inputFont: Number.parseFloat(getComputedStyle(document.querySelector('input')!).fontSize),
  }))
  expect(layout.overflow).toBe(false)
  expect(layout.inputFont).toBeGreaterThanOrEqual(16)

  const actions = page.locator('button, a[href]')
  for (let index = 0; index < await actions.count(); index += 1) {
    const action = actions.nth(index)
    if (!(await action.isVisible())) continue
    const box = await action.boundingBox()
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
  }

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  expect(results.violations).toEqual([])
})
