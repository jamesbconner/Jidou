import { QueryClient } from '@tanstack/react-query'
import { describe, test, expect } from 'vitest'
import { invalidateShowsAndFiles } from '@/hooks/invalidation'
import { fileKeys } from '@/hooks/useFiles'
import { showKeys } from '@/hooks/useShows'
import { dashboardKeys } from '@/hooks/useDashboard'

describe('invalidateShowsAndFiles', () => {
  test('marks show and file queries stale but leaves other namespaces alone', async () => {
    const qc = new QueryClient()
    const seeded = {
      show: showKeys.detail(1),
      episodes: showKeys.episodes(1),
      file: fileKeys.list({ limit: 10, offset: 0 }),
      dashboard: dashboardKeys.genres(),
    }
    for (const key of Object.values(seeded)) qc.setQueryData(key, [])

    await invalidateShowsAndFiles(qc)

    expect(Object.keys(seeded)).toHaveLength(4)
    expect(qc.getQueryState(seeded.show)?.isInvalidated).toBe(true)
    expect(qc.getQueryState(seeded.episodes)?.isInvalidated).toBe(true)
    expect(qc.getQueryState(seeded.file)?.isInvalidated).toBe(true)
    expect(qc.getQueryState(seeded.dashboard)?.isInvalidated).toBe(false)
  })
})
