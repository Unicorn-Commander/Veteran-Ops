import axe from 'axe-core'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AuthConfig } from '../types'
import { Login } from './Login'

const mocks = vi.hoisted(() => ({
  config: vi.fn<() => Promise<AuthConfig>>(),
  login: vi.fn(),
  register: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  auth: { config: mocks.config },
  ssoLoginUrl: () => '/api/auth/keycloak/login',
}))

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ login: mocks.login, register: mocks.register }),
}))

const closedConfig: AuthConfig = {
  sso_enabled: false,
  sso_label: 'Unicorn Commander',
  password_login_enabled: true,
  registration_open: false,
  registration_mode: 'closed',
  email_enabled: false,
  password_reset_enabled: false,
}

function renderLogin() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Login />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.clearAllMocks()
})

describe('Login capability contract', () => {
  it('shows only actions the instance can complete', async () => {
    mocks.config.mockResolvedValue(closedConfig)
    const { container } = renderLogin()

    expect(screen.getByRole('status')).toHaveTextContent('Checking sign-in options')
    await screen.findByRole('button', { name: 'Sign in' })
    expect(screen.queryByText('Create account')).not.toBeInTheDocument()
    expect(screen.queryByText('Forgot password?')).not.toBeInTheDocument()
    expect(screen.queryByText(/Sign in with Unicorn Commander/)).not.toBeInTheDocument()
    expect(screen.getByRole('main')).toBeInTheDocument()

    const result = await axe.run(container, {
      rules: { 'color-contrast': { enabled: false } },
    })
    expect(result.violations).toEqual([])
  })

  it('supports SSO, registration, and reset only when advertised', async () => {
    mocks.config.mockResolvedValue({
      ...closedConfig,
      sso_enabled: true,
      registration_open: true,
      registration_mode: 'open',
      email_enabled: true,
      password_reset_enabled: true,
    })
    renderLogin()

    expect(await screen.findByRole('link', { name: 'Sign in with Unicorn Commander' })).toHaveAttribute(
      'href',
      '/api/auth/keycloak/login',
    )
    expect(screen.getByRole('link', { name: 'Forgot password?' })).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Create account' })[0])
    expect(await screen.findByLabelText('Full name')).toBeInTheDocument()
  })

  it('fails closed and can retry when capability discovery fails', async () => {
    mocks.config.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(closedConfig)
    renderLogin()

    expect(await screen.findByRole('alert')).toHaveTextContent("couldn't load")
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(screen.getByLabelText('Email')).toBeInTheDocument())
  })

  it('renders an honest closed-access state', async () => {
    mocks.config.mockResolvedValue({
      ...closedConfig,
      password_login_enabled: false,
    })
    renderLogin()
    expect(await screen.findByText(/Access is currently closed/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
  })
})
