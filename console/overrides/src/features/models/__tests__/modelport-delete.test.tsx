import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth-store'

import { DataTableRowActions } from '../components/data-table-row-actions'
import { ModelsProvider } from '../components/models-provider'
import type { Model } from '../types'

function Actions() {
  const model: Model = {
    id: 0,
    model_name: 'channel-only',
    name_rule: 0,
    status: 0,
    sync_official: 0,
    has_metadata: false,
    configured_channel_count: 1,
    created_time: 0,
    updated_time: 0,
  }
  const table = useReactTable({
    data: [model],
    columns: [],
    getCoreRowModel: getCoreRowModel(),
  })
  return <DataTableRowActions row={table.getRowModel().rows[0]} />
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it('offers explicit channel removal for a model without metadata and keeps errors visible', async () => {
  useAuthStore.getState().auth.setUser({ id: 1, username: 'admin', role: 100 })
  const post = vi.spyOn(api, 'post').mockResolvedValue({
    data: { success: false, message: 'fixture deletion rejected' },
  })
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <ModelsProvider>
        <Actions />
      </ModelsProvider>
    </QueryClientProvider>
  )
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Delete' }))
  const dialog = screen.getByRole('alertdialog')
  expect(
    within(dialog).getByRole('checkbox', {
      name: 'Also remove from all channels',
    })
  ).toBeChecked()
  expect(
    within(dialog).getByRole('checkbox', {
      name: 'Also remove from all channels',
    })
  ).toHaveAttribute('aria-disabled', 'true')
  expect(post).not.toHaveBeenCalled()
  await user.click(within(dialog).getByRole('button', { name: 'Delete' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'fixture deletion rejected'
  )
  expect(post).toHaveBeenCalledWith('/api/models/channel-only/delete', {
    model_name: 'channel-only',
  })
  client.clear()
})
