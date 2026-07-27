import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearToken, getToken, setToken } from './api'

const TOKEN_KEY = 'vo_token'

function memoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    get length() {
      return values.size
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, String(value)),
  }
}

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  vi.stubGlobal('sessionStorage', memoryStorage())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('bearer token storage', () => {
  it('stores new sessions only for the current tab', () => {
    setToken('fresh-token')
    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBe('fresh-token')
    expect(window.localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(getToken()).toBe('fresh-token')
  })

  it('migrates and removes a legacy persistent token once', () => {
    window.localStorage.setItem(TOKEN_KEY, 'legacy-token')
    expect(getToken()).toBe('legacy-token')
    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBe('legacy-token')
    expect(window.localStorage.getItem(TOKEN_KEY)).toBeNull()

    clearToken()
    expect(getToken()).toBeNull()
  })
})
