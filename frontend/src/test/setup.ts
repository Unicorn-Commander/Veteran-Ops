import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'

afterEach(() => {
  document.documentElement.removeAttribute('data-theme')
  window.localStorage?.clear()
  window.sessionStorage?.clear()
})
