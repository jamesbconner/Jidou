import { Link } from 'react-router'
import { FileStatusBadge } from '@/components/FileStatusBadge'
import { Pagination } from '@/components/Pagination'
import { ResolveFileModal } from '@/components/ResolveFileModal'
import { RematchModal } from '@/components/RematchModal'
import { FixEpisodeModal } from '@/components/FixEpisodeModal'
import { Card } from '@/components/ui/Card'
import { InlineEpisodePicker, InlineShowId, pad2 } from '@/pages/files/InlineEditors'
import type { FileRead } from '@/types/api'

/** Statuses during which a file is still moving, so it cannot be re-matched yet. */
const IN_FLIGHT_STATUSES = ['downloading', 'routing', 'pending', 'discovered']

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}

function FilenameCell({ file: f }: { file: FileRead }) {
  return (
    <td className="px-4 py-2 font-mono text-xs max-w-xs">
      <div className="truncate dark:text-gray-200" title={f.original_filename}>{f.original_filename}</div>
      {f.parsed_show_name && f.status === 'unmatched' && (
        <div className="text-zinc-400 truncate text-xs mt-0.5">
          Parsed: {f.parsed_show_name}
        </div>
      )}
      {f.error_message && (
        <div className="text-red-500 dark:text-red-400 truncate mt-0.5" title={f.error_message}>
          {f.error_message}
        </div>
      )}
    </td>
  )
}

function ShowCell({ file: f }: { file: FileRead }) {
  if (!f.show) {
    return (
      <td className="px-4 py-2">
        <InlineShowId fileId={f.id} showId={f.show_id} />
      </td>
    )
  }
  return (
    <td className="px-4 py-2">
      <div className="space-y-0.5">
        <Link
          to={`/shows/${f.show.id}`}
          className="text-sm font-medium text-[var(--color-ocean-400)] hover:underline"
        >
          {f.show.title}
        </Link>
        {(f.status === 'unmatched' || f.status === 'error') ? (
          <InlineEpisodePicker
            fileId={f.id}
            showId={f.show.id}
            episodeId={f.episode_id}
            episode={f.episode}
          />
        ) : f.episode && (
          <div className="text-xs text-gray-500 dark:text-gray-400">
            {`S${pad2(f.episode.season_number)}E${pad2(f.episode.episode_number)} · ${f.episode.name}`}
          </div>
        )}
      </div>
    </td>
  )
}

function ActionsCell({
  file: f,
  onResolve,
  onRematch,
  onFixEps,
}: {
  file: FileRead
  onResolve: (f: FileRead) => void
  onRematch: (f: FileRead) => void
  onFixEps: (f: FileRead) => void
}) {
  return (
    <td className="px-4 py-2 text-right whitespace-nowrap space-x-3">
      {f.status === 'unmatched' && f.show_id == null && (
        <button
          onClick={() => onResolve(f)}
          className="text-xs text-[var(--color-ocean-600)] hover:underline"
        >
          Resolve
        </button>
      )}
      {f.show_id != null && !IN_FLIGHT_STATUSES.includes(f.status) && (
        <button
          onClick={() => onRematch(f)}
          className="text-xs text-[var(--color-ocean-600)] dark:text-[var(--color-ocean-400)] hover:underline"
        >
          Fix Show
        </button>
      )}
      {f.show_id != null && ['matched', 'routed'].includes(f.status) && (
        <button
          onClick={() => onFixEps(f)}
          className="text-xs text-[var(--color-ocean-600)] dark:text-[var(--color-ocean-400)] hover:underline"
        >
          Fix Eps
        </button>
      )}
    </td>
  )
}

/** The files table; row actions are reported upward, modal state lives in Files. */
export function FilesTable({
  files,
  onResolve,
  onRematch,
  onFixEps,
}: {
  files: FileRead[]
  onResolve: (f: FileRead) => void
  onRematch: (f: FileRead) => void
  onFixEps: (f: FileRead) => void
}) {
  return (
    <Card className="overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 dark:bg-gray-900 text-gray-500 dark:text-gray-400 text-xs uppercase">
          <tr>
            <th className="px-4 py-2 text-left">Filename</th>
            <th className="px-4 py-2 text-left">Size</th>
            <th className="px-4 py-2 text-left">Status</th>
            <th className="px-4 py-2 text-left">Downloaded</th>
            <th className="px-4 py-2 text-left">Show</th>
            <th className="px-4 py-2" />
          </tr>
        </thead>
        <tbody className="divide-y">
          {files.map((f) => (
            <tr key={f.id} className="hover:bg-gray-50 dark:hover:bg-gray-800">
              <FilenameCell file={f} />
              <td className="px-4 py-2 text-gray-500 dark:text-gray-400">{formatBytes(f.file_size)}</td>
              <td className="px-4 py-2">
                <FileStatusBadge status={f.status} />
              </td>
              <td className="px-4 py-2 text-gray-500 dark:text-gray-400 whitespace-nowrap">
                {new Date(f.created_at).toLocaleString()}
              </td>
              <ShowCell file={f} />
              <ActionsCell file={f} onResolve={onResolve} onRematch={onRematch} onFixEps={onFixEps} />
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

/** "N files" footer line with the pager. */
export function FilesSummary({
  total,
  maxRecords,
  filtered,
  page,
  totalPages,
  onPageChange,
}: {
  total: number
  maxRecords: number | null
  filtered: boolean
  page: number
  totalPages: number
  onPageChange: (page: number) => void
}) {
  const plural = total !== 1 ? 's' : ''
  return (
    <div className="flex items-center justify-between text-sm text-gray-500 dark:text-gray-400">
      <span>
        {maxRecords !== null && total > maxRecords
          ? `${maxRecords} of ${total} file${plural}`
          : `${total} file${plural}`}
        {filtered ? ' matching filters' : ''}
      </span>
      <Pagination page={page} totalPages={totalPages} onPageChange={onPageChange} />
    </div>
  )
}

/** The three row-action modals; which one is open is state owned by Files. */
export function FilesModals({
  resolveFile,
  rematchFile,
  fixEpsFile,
  onCloseResolve,
  onCloseRematch,
  onCloseFixEps,
}: {
  resolveFile: FileRead | null
  rematchFile: FileRead | null
  fixEpsFile: FileRead | null
  onCloseResolve: () => void
  onCloseRematch: () => void
  onCloseFixEps: () => void
}) {
  return (
    <>
      {resolveFile && <ResolveFileModal file={resolveFile} onClose={onCloseResolve} />}
      {rematchFile && <RematchModal file={rematchFile} onClose={onCloseRematch} />}
      {fixEpsFile && <FixEpisodeModal file={fixEpsFile} onClose={onCloseFixEps} />}
    </>
  )
}
