import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AuthLayout } from '../auth-layout'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))
vi.mock('@/hooks/use-system-config', () => ({
  useSystemConfig: () => ({
    systemName: 'New API',
    logo: '/logo.png',
    loading: false,
  }),
}))

describe('ModelPort account layout', () => {
  it('renders the account form inside the shared product identity without losing upstream attribution', () => {
    render(
      <AuthLayout>
        <h2>Sign in</h2>
      </AuthLayout>
    )
    expect(screen.getByText('模港 ModelPort')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeVisible()
    expect(screen.getByText('Powered by New API')).toBeVisible()
    expect(
      screen.getByText(
        'Frontend design and development by New API contributors.'
      )
    ).toBeVisible()
  })

  it('uses same-origin document links for the product homepage, guide and chat workspace', () => {
    render(
      <AuthLayout>
        <h2>Create an account</h2>
      </AuthLayout>
    )
    expect(screen.getByRole('link', { name: 'Go to home' })).toHaveAttribute(
      'href',
      '/h5/'
    )
    expect(screen.getByRole('link', { name: 'Docs' })).toHaveAttribute(
      'href',
      '/h5/#guide'
    )
    expect(screen.getByRole('link', { name: 'Chat' })).toHaveAttribute(
      'href',
      '/h5/#chat'
    )
    expect(screen.getByRole('link', { name: /Source code/ })).toHaveAttribute(
      'href',
      '/console-assets/modelport-source.tar.gz'
    )
  })
})
