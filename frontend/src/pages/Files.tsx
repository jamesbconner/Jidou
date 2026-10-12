import { useState, useRef, useEffect } from 'react'
import { useFiles } from '@/hooks/useFiles'
import { FilesModals, FilesSummary, FilesTable } from '@/pages/files/FilesTable'
import { FilesToolbar } from '@/pages/files/FilesToolbar'
import { useLocalStorageState } from '@/hooks/useLocalStorage'
import type { FileRead, FileStatus } from '@/types/api'

interface FilesFilterState {
  status: FileStatus | ''
  pageSize: number
  maxRecords: number | null
  showIgnored: boolean
  duplicatesOnly: boolean
}

const DEFAULT_FILES_FILTERS: FilesFilterState = {
  status: '',
  pageSize: 50,
  maxRecords: null,
  showIgnored: false,
  duplicatesOnly: false,
}

/**
 * Rows to fetch for one page. Caps the fetched page at maxRecords total across
 * all pages combined — the last page under the cap is truncated rather than
 * showing a full pageSize.
 */
function pageLimit(pageSize: number, maxRecords: number | null, offset: number): number {
  return maxRecords !== null ? Math.max(0, Math.min(pageSize, maxRecords - offset)) : pageSize
}

export default function Files() {
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [page, setPage] = useState(0)
  const [resolveFile, setResolveFile] = useState<FileRead | null>(null)
  const [rematchFile, setRematchFile] = useState<FileRead | null>(null)
  const [fixEpsFile, setFixEpsFile] = useState<FileRead | null>(null)

  // Persisted so filter/pagination choices survive navigating away and back,
  // not just page reloads — mirrors the Shows page's filter persistence.
  const [filters, setFilters] = useLocalStorageState<FilesFilterState>(
    'jidou:files-filters',
    DEFAULT_FILES_FILTERS,
  )
  const { status: statusFilter, pageSize, maxRecords, showIgnored, duplicatesOnly } = filters
  const setStatusFilter = (v: FileStatus | '') => setFilters({ ...filters, status: v })
  const setPageSize = (v: number) => setFilters({ ...filters, pageSize: v })
  const setMaxRecords = (v: number | null) => setFilters({ ...filters, maxRecords: v })
  const setShowIgnored = (v: boolean) => setFilters({ ...filters, showIgnored: v })
  const setDuplicatesOnly = (v: boolean) => setFilters({ ...filters, duplicatesOnly: v })

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setDebouncedSearch(search), 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [search])

  // Reset to page 0 when a filter changes — adjusted directly during render
  // rather than in an effect, per React's guidance for syncing state to a
  // prop/input change. `effectivePage` (rather than the stale `page` local)
  // is used below so this render's own offset/limit reflect the reset
  // immediately, instead of momentarily computing against the old page.
  const [prevFilterKey, setPrevFilterKey] = useState(
    [statusFilter, debouncedSearch, pageSize, maxRecords, showIgnored, duplicatesOnly] as const,
  )
  const filterKey = [statusFilter, debouncedSearch, pageSize, maxRecords, showIgnored, duplicatesOnly] as const
  let effectivePage = page
  if (filterKey.some((value, i) => value !== prevFilterKey[i])) {
    setPrevFilterKey(filterKey)
    setPage(0)
    effectivePage = 0
  }

  const offset = effectivePage * pageSize
  const filesQuery = useFiles({
    status: statusFilter || undefined,
    limit: pageLimit(pageSize, maxRecords, offset),
    offset,
    search: debouncedSearch || undefined,
    showIgnored,
    duplicatesOnly,
  })
  const files = filesQuery.data?.data ?? []
  const total = filesQuery.data?.total ?? 0
  const effectiveTotal = maxRecords !== null ? Math.min(total, maxRecords) : total
  const totalPages = Math.max(1, Math.ceil(effectiveTotal / pageSize))
  const isLoading = filesQuery.isLoading

  // Snap back to the last valid page when total shrinks (e.g. after a
  // mutation). Self-correcting: once page is clamped, the condition is
  // false on the next render, so this converges without needing an effect.
  if (effectiveTotal > 0 && page >= totalPages) {
    setPage(totalPages - 1)
  }

  return (
    <div className="space-y-4">
      <FilesToolbar
        search={search}
        onSearchChange={setSearch}
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        pageSize={pageSize}
        onPageSizeChange={setPageSize}
        maxRecords={maxRecords}
        onMaxRecordsChange={setMaxRecords}
        showIgnored={showIgnored}
        onShowIgnoredChange={setShowIgnored}
        duplicatesOnly={duplicatesOnly}
        onDuplicatesOnlyChange={setDuplicatesOnly}
      />

      {isLoading ? (
        <p className="text-gray-400 dark:text-gray-500 text-sm">Loading…</p>
      ) : files.length === 0 ? (
        <p className="text-gray-500 dark:text-gray-400 text-sm">No files found.</p>
      ) : (
        <FilesTable files={files} onResolve={setResolveFile} onRematch={setRematchFile} onFixEps={setFixEpsFile} />
      )}

      {!isLoading && total > 0 && (
        <FilesSummary
          total={total}
          maxRecords={maxRecords}
          filtered={Boolean(debouncedSearch || statusFilter || duplicatesOnly)}
          page={page}
          totalPages={totalPages}
          onPageChange={setPage}
        />
      )}

      <FilesModals
        resolveFile={resolveFile}
        rematchFile={rematchFile}
        fixEpsFile={fixEpsFile}
        onCloseResolve={() => setResolveFile(null)}
        onCloseRematch={() => setRematchFile(null)}
        onCloseFixEps={() => setFixEpsFile(null)}
      />
    </div>
  )
}
