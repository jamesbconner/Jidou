import { describe, expect, test } from 'vitest'
import { taskTypeLabel } from '@/utils/taskTypeLabel'

describe('taskTypeLabel', () => {
  test.each([
    ['sync', 'Sync'],
    ['refresh_show_metadata', 'Refresh Show Metadata'],
    ['backfill_show_metadata', 'Backfill Show Metadata'],
    ['rss_import', 'RSS Import'],
    ['db_import', 'DB Import'],
  ])('%s -> %s', (type, label) => {
    expect(taskTypeLabel(type)).toBe(label)
  })
})
