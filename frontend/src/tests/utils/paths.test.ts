import { describe, test, expect } from 'vitest'
import { sanitizeFolderName } from '@/utils/paths'

describe('sanitizeFolderName', () => {
  test('replaces a colon touching both neighbors with a single space', () => {
    expect(sanitizeFolderName('Re:Zero')).toBe('Re Zero')
  })

  test('does not double a space when the colon is already followed by one', () => {
    expect(sanitizeFolderName('Attack on Titan: Final Season')).toBe(
      'Attack on Titan Final Season',
    )
  })

  test('replaces every invalid character and collapses runs of whitespace', () => {
    expect(sanitizeFolderName('Show: "Special" <Edition>')).toBe('Show Special Edition')
  })

  test('leaves a title with nothing to sanitize unchanged', () => {
    expect(sanitizeFolderName('Cowboy Bebop')).toBe('Cowboy Bebop')
  })

  test('strips whitespace introduced at the start/end of the title', () => {
    expect(sanitizeFolderName(':Show:')).toBe('Show')
  })

  test('handles every character in the invalid set, not just colon', () => {
    expect(sanitizeFolderName('A\\B/C:D*E?F"G<H>I|J')).toBe('A B C D E F G H I J')
  })

  test('falls back to "Untitled" when the title is entirely invalid characters', () => {
    expect(sanitizeFolderName(':::')).not.toBe('')
    expect(sanitizeFolderName(':::')).toBe('Untitled')
  })

  test('falls back to "Untitled" for an empty title', () => {
    expect(sanitizeFolderName('')).toBe('Untitled')
  })
})
