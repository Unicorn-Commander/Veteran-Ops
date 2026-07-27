import { defineConfig, devices } from '@playwright/test'

const localBrowser = process.env.CI ? {} : { channel: 'chrome' as const }

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:4178',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop-chromium', use: { ...devices['Desktop Chrome'], ...localBrowser } },
    { name: 'mobile-chromium', use: { ...devices['Pixel 7'], ...localBrowser } },
  ],
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4178 --strictPort',
    url: 'http://127.0.0.1:4178/login',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
