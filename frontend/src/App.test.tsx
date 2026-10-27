import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

describe('App', () => {
  afterEach(() => vi.restoreAllMocks())

  it('shows healthy platform dependencies', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          status: 'healthy',
          api: { status: 'healthy' },
          database: { status: 'healthy' },
          redis: { status: 'healthy' },
        }),
      }),
    )

    render(<App />)

    expect(await screen.findByText('PostgreSQL')).toBeInTheDocument()
    expect(screen.getByText('Redis')).toBeInTheDocument()
    expect(screen.getAllByText('healthy')).toHaveLength(4)
  })
})

