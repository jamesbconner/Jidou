import { useState, useRef, useMemo } from 'react'
import { useAssignFileShow, useAssignFileEpisode } from '@/hooks/useFiles'
import { useShowEpisodes } from '@/hooks/useShows'
import type { EpisodeBrief } from '@/types/api'
import { buildSeasonMap } from '@/utils/episodeUtils'

/** Click-to-edit show-id cell; owns its own mutation and edit state. */
export function InlineShowId({ fileId, showId }: { fileId: number; showId: number | null }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(showId?.toString() ?? '')
  const cancelRef = useRef(false)
  const patch = useAssignFileShow(fileId)

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
        className="text-gray-500 dark:text-gray-400 hover:text-[var(--color-ocean-600)] dark:hover:text-[var(--color-ocean-400)] hover:underline text-left"
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
      className="border rounded px-1 py-0.5 text-xs w-20 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:bg-gray-800 dark:text-gray-100"
    />
  )
}

export function pad2(n: number) {
  return String(n).padStart(2, '0')
}

/** Click-to-edit episode select for a file already linked to a show. */
export function InlineEpisodePicker({
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
  const { data: episodes = [] } = useShowEpisodes(showId)

  const patch = useAssignFileEpisode(fileId, {
    onSuccess: () => {
      setEditing(false)
      setError(null)
    },
    onError: (err) => {
      setSelectValue(episodeId?.toString() ?? '')
      const msg = err instanceof Error ? err.message : 'Failed to update episode'
      setError(msg)
    },
  })

  const seasonMap = useMemo(() => buildSeasonMap(episodes), [episodes])
  const seasons = useMemo(() => Array.from(seasonMap.keys()).sort((a, b) => a - b), [seasonMap])

  const label = episode
    ? `S${pad2(episode.season_number)}E${pad2(episode.episode_number)} · ${episode.name}`
    : '—'

  if (!editing) {
    return (
      <div className="mt-0.5">
        <button
          onClick={() => { setSelectValue(episodeId?.toString() ?? ''); setError(null); setEditing(true) }}
          disabled={patch.isPending}
          className="text-xs text-gray-500 dark:text-gray-400 hover:text-[var(--color-ocean-600)] dark:hover:text-[var(--color-ocean-400)] hover:underline text-left disabled:opacity-50 disabled:cursor-not-allowed"
          title="Click to assign episode"
        >
          {label}
        </button>
        {error && <p className="text-xs text-red-500 dark:text-red-400 mt-0.5">{error}</p>}
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
        className="border rounded px-1 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500 max-w-xs dark:bg-gray-800 dark:text-gray-100"
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
      {error && <p className="text-xs text-red-500 dark:text-red-400 mt-0.5">{error}</p>}
    </div>
  )
}
