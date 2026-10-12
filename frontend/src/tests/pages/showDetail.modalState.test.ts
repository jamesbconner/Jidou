import { describe, test, expect } from 'vitest'
import type { ShowDetailModal } from '@/pages/showDetail/modalState'

/**
 * Exhaustive over `ShowDetailModal['kind']`: the `never` default makes `tsc -b`
 * fail when a variant is added to the union without being handled here.
 */
function modalKindLabel(kind: ShowDetailModal['kind']): string {
  switch (kind) {
    case 'rematch':
    case 'path':
    case 'contentType':
    case 'aliases':
    case 'image':
    case 'deleteConfirm':
    case 'scanLocalFiles':
    case 'episodeGroups':
    case 'scanLocalMovieFile':
    case 'fixMovieFile':
    case 'fileRematch':
    case 'fileFixEps':
    case 'assignImport':
    case 'linkFile':
    case 'rssSubscription':
      return kind
    default: {
      const unhandled: never = kind
      return unhandled
    }
  }
}

describe('ShowDetailModal union', () => {
  test('labels every modal kind', () => {
    const kinds: ShowDetailModal['kind'][] = [
      'rematch',
      'path',
      'contentType',
      'aliases',
      'image',
      'deleteConfirm',
      'scanLocalFiles',
      'episodeGroups',
      'scanLocalMovieFile',
      'fixMovieFile',
      'fileRematch',
      'fileFixEps',
      'assignImport',
      'linkFile',
      'rssSubscription',
    ]
    expect(kinds).toHaveLength(15)
    expect(new Set(kinds.map(modalKindLabel)).size).toBe(15)
  })
})
