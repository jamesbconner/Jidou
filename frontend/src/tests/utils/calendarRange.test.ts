import { describe, test, expect } from 'vitest'
import {
  GRID_COLS_CLASS,
  addDays,
  computeRangeStart,
  dayLabel,
  resolveAnchorMode,
  startOfWeek,
  toISODate,
  type CalendarRangeSettings,
  type RangeLength,
} from '@/utils/calendarRange'

// 2024-01-01 is a known Monday, giving one fixed date per weekday to test against.
const MON = new Date(2024, 0, 1)
const TUE = new Date(2024, 0, 2)
const WED = new Date(2024, 0, 3)
const THU = new Date(2024, 0, 4)
const FRI = new Date(2024, 0, 5)
const SAT = new Date(2024, 0, 6)
const SUN = new Date(2024, 0, 7)

describe('toISODate', () => {
  test('formats a date as YYYY-MM-DD with zero-padding', () => {
    expect(toISODate(new Date(2024, 0, 5))).toBe('2024-01-05')
  })
})

describe('addDays', () => {
  test('adds positive days, rolling into the next month', () => {
    expect(toISODate(addDays(new Date(2024, 0, 30), 3))).toBe('2024-02-02')
  })

  test('subtracts days, rolling into the previous year', () => {
    expect(toISODate(addDays(new Date(2024, 0, 1), -1))).toBe('2023-12-31')
  })
})

describe('startOfWeek', () => {
  test.each([
    [MON, '2024-01-01'],
    [TUE, '2024-01-01'],
    [WED, '2024-01-01'],
    [THU, '2024-01-01'],
    [FRI, '2024-01-01'],
    [SAT, '2024-01-01'],
    [SUN, '2024-01-01'],
  ])('monday-start: %s -> %s', (input, expected) => {
    expect(toISODate(startOfWeek(input, 'monday'))).toBe(expected)
  })

  test.each([
    [MON, '2023-12-31'],
    [TUE, '2023-12-31'],
    [WED, '2023-12-31'],
    [THU, '2023-12-31'],
    [FRI, '2023-12-31'],
    [SAT, '2023-12-31'],
    [SUN, '2024-01-07'],
  ])('sunday-start: %s -> %s', (input, expected) => {
    expect(toISODate(startOfWeek(input, 'sunday'))).toBe(expected)
  })

  test('zeroes the time of day', () => {
    const withTime = new Date(2024, 0, 3, 15, 30)
    expect(startOfWeek(withTime, 'monday').getHours()).toBe(0)
  })
})

describe('dayLabel', () => {
  test.each([
    [SUN, 'Sun'],
    [MON, 'Mon'],
    [TUE, 'Tue'],
    [WED, 'Wed'],
    [THU, 'Thu'],
    [FRI, 'Fri'],
    [SAT, 'Sat'],
  ])('%s -> %s', (input, expected) => {
    expect(dayLabel(input)).toBe(expected)
  })
})

describe('resolveAnchorMode', () => {
  test('week-start stays week-start when range length is 7', () => {
    expect(resolveAnchorMode('week-start', 7)).toBe('week-start')
  })

  test.each([1, 3, 5] as RangeLength[])(
    'week-start falls back to today-start when range length is %i',
    (rangeLength) => {
      expect(resolveAnchorMode('week-start', rangeLength)).toBe('today-start')
    },
  )

  test.each([1, 3, 5, 7] as RangeLength[])(
    'today-start is unaffected by range length %i',
    (rangeLength) => {
      expect(resolveAnchorMode('today-start', rangeLength)).toBe('today-start')
    },
  )

  test.each([1, 3, 5, 7] as RangeLength[])(
    'today-centered is unaffected by range length %i',
    (rangeLength) => {
      expect(resolveAnchorMode('today-centered', rangeLength)).toBe('today-centered')
    },
  )
})

describe('computeRangeStart', () => {
  test('today-start returns midnight of today, regardless of time of day', () => {
    const settings: CalendarRangeSettings = {
      rangeLength: 5,
      anchorMode: 'today-start',
      weekStartDay: 'monday',
    }
    const result = computeRangeStart(new Date(2024, 0, 3, 18, 45), settings)
    expect(toISODate(result)).toBe('2024-01-03')
    expect(result.getHours()).toBe(0)
  })

  test.each([
    [1, 0],
    [3, 1],
    [5, 2],
    [7, 3],
  ] as [RangeLength, number][])(
    'today-centered offsets range length %i by %i day(s) before today',
    (rangeLength, expectedOffset) => {
      const today = new Date(2024, 0, 10)
      const settings: CalendarRangeSettings = {
        rangeLength,
        anchorMode: 'today-centered',
        weekStartDay: 'monday',
      }
      expect(toISODate(computeRangeStart(today, settings))).toBe(
        toISODate(addDays(today, -expectedOffset)),
      )
    },
  )

  test('week-start with monday weekStartDay matches startOfWeek', () => {
    const settings: CalendarRangeSettings = {
      rangeLength: 7,
      anchorMode: 'week-start',
      weekStartDay: 'monday',
    }
    expect(toISODate(computeRangeStart(WED, settings))).toBe('2024-01-01')
  })

  test('week-start with sunday weekStartDay matches startOfWeek', () => {
    const settings: CalendarRangeSettings = {
      rangeLength: 7,
      anchorMode: 'week-start',
      weekStartDay: 'sunday',
    }
    expect(toISODate(computeRangeStart(WED, settings))).toBe('2023-12-31')
  })

  test('week-start falls back to today-start when range length is not 7', () => {
    const settings: CalendarRangeSettings = {
      rangeLength: 3,
      anchorMode: 'week-start',
      weekStartDay: 'monday',
    }
    expect(toISODate(computeRangeStart(WED, settings))).toBe(toISODate(WED))
  })
})

describe('GRID_COLS_CLASS', () => {
  test.each([1, 3, 5, 7] as RangeLength[])('has a non-empty class string for length %i', (n) => {
    expect(GRID_COLS_CLASS[n]).toBeTruthy()
  })
})
