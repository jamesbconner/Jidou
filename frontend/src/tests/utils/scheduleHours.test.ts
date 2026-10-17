import { describe, expect, test } from 'vitest'
import { normalizeScheduleHours, parseScheduleHours } from '@/utils/scheduleHours'

describe('parseScheduleHours', () => {
  test.each([
    ['4', [4]],
    ['2,14', [2, 14]],
    ['14, 2', [2, 14]],
    [' 4 , 16 ', [4, 16]],
    ['4,4,16', [4, 16]],
    ['0,23', [0, 23]],
    ['04', [4]],
    ['4,,16', [4, 16]],
  ])('accepts %j', (raw, expected) => {
    expect(parseScheduleHours(raw)).toEqual(expected)
  })

  test.each(['', '   ', ',', '24', '-1', '4,25', 'a', '4;16', '4.5', '4,16x', '１２'])(
    'rejects %j',
    (raw) => {
      expect(parseScheduleHours(raw)).toBeNull()
    },
  )
})

describe('normalizeScheduleHours', () => {
  test('returns the canonical comma-separated form', () => {
    expect(normalizeScheduleHours(' 16, 04 ,4')).toBe('4,16')
  })

  test('returns null for an invalid list', () => {
    expect(normalizeScheduleHours('25')).toBeNull()
  })
})
