import { describe, expect, test } from 'vitest'
import { year } from '@/components/resolveFile/year'

describe('year', () => {
  test.each([
    ['2020-01-01', '2020'],
    ['2020-12-31', '2020'],
    ['2020-06-15T12:00:00Z', '2020'],
  ])('reads the calendar year of %s regardless of the local timezone', (date, expected) => {
    expect(year(date)).toBe(expected)
  })

  test.each([null, undefined, ''])('returns null for %p', (date) => {
    expect(year(date)).toBeNull()
  })
})
