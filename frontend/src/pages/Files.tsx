import { useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useFiles, fileKeys } from '@/hooks/useFiles'
import { showKeys, useShowEpisodes } from '@/hooks/useShows'
import { FileStatusBadge } from '@/components/FileStatusBadge'
import { ResolveFileModal } from '@/components/ResolveFileModal'
import { RematchModal } from '@/components/RematchModal'
import { api } from '@/api/client'
import { useQueryClient, useMutation } from '@tanstack/react-query'
import type { FileRead, FileStatus, EpisodeBrief } from '@/types/api'

const STATUS_OPTIONS: (FileStatus | '')[] = [
  '',
  'pending',
  'discovered',
  'downloading',
  'downloaded',
  'unmatched',
  'matched',
  'routing',
  'routed',
  'error',
]

function InlineShowId({ fileId, showId }: { fileId: number; showId: number | null }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(showId?.toString() ?? '')
  const cancelRef = useRef(false)
  const qc = useQueryClient()
  const patch = useMutation({
    mutationFn: (newShowId: number | null) =>
      api.patch<FileRead>(`/files/${fileId}`, { show_id: newShowId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: fileKeys.all })
      qc.invalidateQueries({ queryKey: showKeys.all })
    },
  })

  function commit() {
    if (cancelRef.current) { cancelRef.current = false; return }
    setEditing(false)
    if (value === '') {
      if (showId !== null) patch.mutate(null)
      return
    }
    const parsed = parseInt(value, 10)
    if (isNaN(parsed) || parsed <= 0) {
      setValue(showId?.toString() ?? '')
      return
    }
    if (parsed !== showId) patch.mutate(parsed)
  }

  if (!editing) {
    return (
      <button
        onClick={() => { cancelRef.current = false; setValue(showId?.toString() ?? ''); setEditing(true) }}
        className="text-gray-500 hover:text-blue-600 hover:underline text-left"
        title="Click to assign show"
      >
        {showId ?? '—'}
      </button>
    )
  }

  return (
    <input
      type="number"
      autoFocus
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
        if (e.key === 'Escape') { cancelRef.current = true; setValue(showId?.toString() ?? ''); setEditing(false) }
      }}
      className="border rounded px-1 py-0.5 text-xs w-20 focus:outline-none focus:ring-1 focus:ring-blue-500"
    />
  )
}

function pad2(n: number) { return String(n).padStart(2, '0') }

function InlineEpisodePicker({
  fileId,
  showId,
  episodeId,
  episode,
}: {
  fileId: number
  showId: number
  episodeId: number | null
  episode: EpisodeBrief | null
}) {
  const [editing, setEditing] = useState(false)
  const [selectValue, setSelectValue] = useState(episodeId?.toString() ?? '')
  const [error, setError] = useState<string | null>(null)
  const qc = useQueryClient()
  const { data: episodes = [] } = useShowEpisodes(showId)

  const patch = useMutation({
    mutationFn: (newEpisodeId: number | null) =>
      api.patch<FileRead>(`/files/${fileId}`, {
        episode_id: newEpisodeId,
        ...(newEpisodeId !== null ? { status: 'matched' } : {}),
      }),
    onSuccess: () => {
      setEditing(false)
      setError(null)
      qc.invalidateQueries({ queryKey: fileKeys.all })
      qc.invalidateQueries({ queryKey: showKeys.all })
    },
    onError: (err: unknown) => {
      setSelectValue(episodeId?.toString() ?? '')
      const msg = err instanceof Error ? err.message : 'Failed to update episode'
      setError(msg)
    },
  })

  const seasonMap = new Map<number, typeof episodes>()
  for (const ep of episodes) {
    const bucket = seasonMap.get(ep.season_number) ?? []
    bucket.push(ep)
    seasonMap.set(ep.season_number, bucket)
  }
  const seasons = Array.from(seasonMap.keys()).sort((a, b) => a - b)

  const label = episode
    ? `S${pad2(episode.season_number)}E${pad2(episode.episode_number)} · ${episode.name}`
    : '—'

  if (!editing) {
    return (
      <div className="mt-0.5">
        <button
          onClick={() => { setSelectValue(episodeId?.toString() ?? ''); setError(null); setEditing(true) }}
          className="text-xs text-gray-500 hover:text-blue-600 hover:underline text-left"
          title="Click to assign episode"
        >
          {label}
        </button>
        {error && <p className="text-xs text-red-500 mt-0.5">{error}</p>}
      </div>
    )
  }

  return (
    <div className="mt-0.5">
      <select
        autoFocus
        value={selectValue}
        onChange={(e) => {
          const val = e.target.value
          setSelectValue(val)
          patch.mutate(val === '' ? null : Number(val))
        }}
        onBlur={() => setEditing(false)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setEditing(false)
        }}
        disabled={patch.isPending}
        className="border rounded px-1 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500 max-w-xs"
      >
        <option value="">— clear —</option>
        {seasons.map((sn) => (
          <optgroup key={sn} label={`Season ${sn}`}>
            {(seasonMap.get(sn) ?? [])
              .sort((a, b) => a.episode_number - b.episode_number)
              .map((ep) => (
                <option key={ep.id} value={ep.id}>
                  {`S${pad2(ep.season_number)}E${pad2(ep.episode_number)} — ${ep.name}`}
                  {ep.file_tracked && ep.id !== episodeId ? ' (taken)' : ''}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
      {error && <p className="text-xs text-red-500 mt-0.5">{error}</p>}
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}

export default function Files() {
  const [statusFilter, setStatusFilter] = useState<FileStatus | ''>('')
  const [resolveFile, setResolveFile] = useState<FileRead | null>(null)
  const [rematchFile, setRematchFile] = useState<FileRead | null>(null)
  const { data: files = [], isLoading } = useFiles(statusFilter || undefined)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Files</h1>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as FileStatus | '')}
          className="border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s || 'All statuses'}</option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : files.length === 0 ? (
        <p className="text-gray-500 text-sm">No files found.</p>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="px-4 py-2 text-left">Filename</th>
                <th className="px-4 py-2 text-left">Size</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-left">Show</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {files.map((f) => (
                <tr key={f.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-mono text-xs max-w-xs">
                    <div className="truncate">{f.original_filename}</div>
                    {f.parsed_show_name && f.status === 'unmatched' && (
                      <div className="text-zinc-400 truncate text-xs mt-0.5">
                        Parsed: {f.parsed_show_name}
                      </div>
                    )}
                    {f.error_message && (
                      <div className="text-red-500 truncate mt-0.5" title={f.error_message}>
                        {f.error_message}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-2 text-gray-500">{formatBytes(f.file_size)}</td>
                  <td className="px-4 py-2">
                    <FileStatusBadge status={f.status} />
                  </td>
                  <td className="px-4 py-2">
                    {f.show ? (
                      <div className="space-y-0.5">
                        <Link
                          to={`/shows/${f.show.id}`}
                          className="text-sm font-medium text-indigo-400 hover:underline"
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
                          <div className="text-xs text-gray-500">
                            {`S${pad2(f.episode.season_number)}E${pad2(f.episode.episode_number)} · ${f.episode.name}`}
                          </div>
                        )}
                      </div>
                    ) : (
                      <InlineShowId fileId={f.id} showId={f.show_id} />
                    )}
                  </td>
                  <td className="px-4 py-2 text-right whitespace-nowrap">
                    {f.status === 'unmatched' && (
                      <button
                        onClick={() => setResolveFile(f)}
                        className="text-xs text-indigo-600 hover:underline"
                      >
                        Resolve
                      </button>
                    )}
                    {f.show_id != null && f.status !== 'unmatched' && (
                      <button
                        onClick={() => setRematchFile(f)}
                        className="text-xs text-blue-600 hover:underline"
                      >
                        Re-match
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {resolveFile && (
        <ResolveFileModal
          file={resolveFile}
          onClose={() => setResolveFile(null)}
        />
      )}
      {rematchFile && (
        <RematchModal
          file={rematchFile}
          onClose={() => setRematchFile(null)}
        />
      )}
    </div>
  )
}
