import { renderHook } from '@testing-library/react'
import { expect, it } from 'vitest'

import { ROLE } from '@/lib/roles'

import { useSidebarData } from '../use-sidebar-data'

it('defines only API sales navigation and reserves audit for administrators', () => {
  const { result } = renderHook(useSidebarData)
  expect(result.current.navGroups.some((group) => group.id === 'chat')).toBe(
    false
  )
  const general = result.current.navGroups.find(
    (group) => group.id === 'general'
  )
  expect(
    general?.items
      .filter((item) => !item.requiredRole)
      .map((item) => ('url' in item ? item.url : ''))
  ).toEqual([
    '/dashboard/models',
    '/dashboard/overview',
    '/keys',
    '/usage-logs/common',
    '/usage-logs/task',
  ])
  expect(
    general?.items.find(
      (item) => 'url' in item && item.url === '/usage-logs/audit'
    )?.requiredRole
  ).toBe(ROLE.ADMIN)
})
