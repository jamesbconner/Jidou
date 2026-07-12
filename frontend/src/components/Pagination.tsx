import { useEffect, useState, type KeyboardEvent } from 'react'

interface PaginationProps {
  /** Zero-indexed current page. */
  page: number
  totalPages: number
  onPageChange: (page: number) => void
}

/**
 * First/Prev/Next/Last controls plus a numeric "go to page" input so a large
 * result set (e.g. hundreds of pages) doesn't require clicking through every
 * intermediate page. Renders nothing when there's only one page.
 */
export function Pagination({ page, totalPages, onPageChange }: PaginationProps) {
  const [jumpValue, setJumpValue] = useState(String(page + 1))

  // Keep the input in sync when the page changes from elsewhere (Prev/Next
  // buttons, filters resetting to page 0, the "snap back" clamp effect, etc.)
  useEffect(() => {
    setJumpValue(String(page + 1))
  }, [page])

  if (totalPages <= 1) return null

  function commitJump() {
    const parsed = parseInt(jumpValue, 10)
    if (Number.isNaN(parsed)) {
      setJumpValue(String(page + 1))
      return
    }
    const clamped = Math.min(Math.max(parsed, 1), totalPages)
    setJumpValue(String(clamped))
    if (clamped - 1 !== page) onPageChange(clamped - 1)
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') e.currentTarget.blur()
  }

  return (
    <div className="flex items-center gap-2 text-sm">
      <button
        onClick={() => onPageChange(0)}
        disabled={page === 0}
        className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50"
        title="First page"
      >
        «
      </button>
      <button
        onClick={() => onPageChange(Math.max(0, page - 1))}
        disabled={page === 0}
        className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50"
        title="Previous page"
      >
        ‹
      </button>
      <span className="flex items-center gap-1 text-gray-600">
        Page
        <input
          type="number"
          min={1}
          max={totalPages}
          value={jumpValue}
          onChange={(e) => setJumpValue(e.target.value)}
          onBlur={commitJump}
          onKeyDown={handleKeyDown}
          aria-label="Go to page"
          className="w-14 border rounded px-1 py-0.5 text-center focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        of {totalPages}
      </span>
      <button
        onClick={() => onPageChange(Math.min(totalPages - 1, page + 1))}
        disabled={page >= totalPages - 1}
        className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50"
        title="Next page"
      >
        ›
      </button>
      <button
        onClick={() => onPageChange(totalPages - 1)}
        disabled={page >= totalPages - 1}
        className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50"
        title="Last page"
      >
        »
      </button>
    </div>
  )
}
