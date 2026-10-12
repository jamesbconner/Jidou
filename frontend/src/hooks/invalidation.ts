import type { QueryClient } from '@tanstack/react-query'
import { fileKeys } from '@/hooks/useFiles'
import { showKeys } from '@/hooks/useShows'

/**
 * Refetch every show and file query after a mutation that re-links files.
 *
 * Linking, fixing or reassigning a file changes both the Files table and the
 * per-show episode/progress data, and six mutations used to repeat these two
 * calls by hand. One helper keeps the pair from drifting apart.
 */
export function invalidateShowsAndFiles(qc: QueryClient): Promise<void> {
  return Promise.all([
    qc.invalidateQueries({ queryKey: fileKeys.all }),
    qc.invalidateQueries({ queryKey: showKeys.all }),
  ]).then(() => undefined)
}
