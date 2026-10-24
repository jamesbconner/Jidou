import { useState, KeyboardEvent } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { ModalCloseButton } from '@/components/ui/ModalCloseButton'
import {
  useUpdateShowAliases,
  useRegenerateShowAliases,
  useUpdateSeasonAliases,
} from '@/hooks/useShows'
import type { ShowRead } from '@/types/api'

interface Props {
  show: ShowRead
  onClose: () => void
}

export function AliasModal({ show, onClose }: Props) {
  const sources = show.aliases_sources ?? { tmdb: [], llm: [], user: [] }

  const [userAliases, setUserAliases] = useState<string[]>(sources.user)
  const [newAlias, setNewAlias] = useState('')
  const [prevAliasesSources, setPrevAliasesSources] = useState(show.aliases_sources)
  const [seasonAliases, setSeasonAliases] = useState<Record<string, number>>(
    show.season_aliases ?? {},
  )
  const [prevSeasonAliases, setPrevSeasonAliases] = useState(show.season_aliases)
  const [newSeasonName, setNewSeasonName] = useState('')
  const [newSeasonNumber, setNewSeasonNumber] = useState('')

  const updateAliases = useUpdateShowAliases(show.id)
  const updateSeasonAliases = useUpdateSeasonAliases(show.id)
  const regenerate = useRegenerateShowAliases(show.id)
  const saving = updateAliases.isPending || updateSeasonAliases.isPending

  // Sync user aliases from show data when regeneration completes — adjusted
  // directly during render rather than in an effect, per React's guidance
  // for syncing state to a prop change.
  if (show.aliases_sources !== prevAliasesSources) {
    setPrevAliasesSources(show.aliases_sources)
    setUserAliases(show.aliases_sources?.user ?? [])
  }
  if (show.season_aliases !== prevSeasonAliases) {
    setPrevSeasonAliases(show.season_aliases)
    setSeasonAliases(show.season_aliases ?? {})
  }

  function addAlias() {
    const trimmed = newAlias.trim().toLowerCase()
    if (!trimmed || userAliases.includes(trimmed)) {
      setNewAlias('')
      return
    }
    setUserAliases((prev) => [...prev, trimmed])
    setNewAlias('')
  }

  function removeAlias(alias: string) {
    setUserAliases((prev) => prev.filter((a) => a !== alias))
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      addAlias()
    }
  }

  function addSeasonAlias() {
    const name = newSeasonName.trim().toLowerCase()
    const season = Number(newSeasonNumber)
    if (!name || newSeasonNumber.trim() === '' || !Number.isInteger(season) || season < 0 || season > 999) {
      return
    }
    setSeasonAliases((prev) => ({ ...prev, [name]: season }))
    setNewSeasonName('')
    setNewSeasonNumber('')
  }

  function removeSeasonAlias(name: string) {
    setSeasonAliases((prev) => Object.fromEntries(Object.entries(prev).filter(([n]) => n !== name)))
  }

  function handleSeasonKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      addSeasonAlias()
    }
  }

  async function handleSave() {
    try {
      await Promise.all([
        updateAliases.mutateAsync(userAliases),
        updateSeasonAliases.mutateAsync(seasonAliases),
      ])
      onClose()
    } catch {
      // The failed mutation's isError drives the message below.
    }
  }

  const tmdbAliases = show.aliases_sources?.tmdb ?? []
  const llmAliases = show.aliases_sources?.llm ?? []

  return (
    <Modal onClose={onClose} tone="light" ariaLabel={`Manage aliases for ${show.title}`} className="flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <h2 className="font-semibold text-gray-900 dark:text-gray-100 truncate">
            Manage Aliases — {show.title}
          </h2>
          <ModalCloseButton onClose={onClose} leftGap />
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-5">
          {/* TMDB source */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">TMDB</h3>
              <span className="text-xs text-gray-400 dark:text-gray-500">Read-only</span>
            </div>
            {tmdbAliases.length > 0 ? (
              <ul className="flex flex-wrap gap-1.5">
                {tmdbAliases.map((a) => (
                  <li
                    key={a}
                    className="px-2 py-0.5 bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 rounded text-xs"
                  >
                    {a}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-gray-400 dark:text-gray-500 italic">None</p>
            )}
          </section>

          {/* LLM source */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">LLM</h3>
              <span className="text-xs text-gray-400 dark:text-gray-500">Read-only</span>
            </div>
            {llmAliases.length > 0 ? (
              <ul className="flex flex-wrap gap-1.5">
                {llmAliases.map((a) => (
                  <li
                    key={a}
                    className="px-2 py-0.5 bg-purple-50 text-purple-700 dark:bg-purple-950/40 dark:text-purple-300 rounded text-xs"
                  >
                    {a}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-gray-400 dark:text-gray-500 italic">None</p>
            )}
          </section>

          {/* Regenerate button */}
          <div>
            <button
              onClick={() => regenerate.mutate()}
              disabled={regenerate.isPending}
              className="px-3 py-1.5 text-sm border rounded hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
            >
              {regenerate.isPending ? 'Regenerating…' : 'Regenerate TMDB + LLM'}
            </button>
            {regenerate.isError && (
              <p className="text-xs text-red-600 mt-1">
                Regeneration failed — check server logs.
              </p>
            )}
          </div>

          {/* User source */}
          <section>
            <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              User-defined
              <span className="ml-1 text-xs font-normal text-gray-400 dark:text-gray-500">
                (persisted, never overwritten by regeneration)
              </span>
            </h3>
            {userAliases.length > 0 ? (
              <ul className="flex flex-wrap gap-1.5 mb-2">
                {userAliases.map((a) => (
                  <li
                    key={a}
                    className="flex items-center gap-1 px-2 py-0.5 bg-green-50 text-green-700 dark:bg-green-950/40 dark:text-green-300 rounded text-xs"
                  >
                    {a}
                    <button
                      onClick={() => removeAlias(a)}
                      className="hover:text-red-500"
                      aria-label={`Remove alias ${a}`}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-gray-400 dark:text-gray-500 italic mb-2">None yet</p>
            )}
            <div className="flex gap-2">
              <input
                type="text"
                value={newAlias}
                onChange={(e) => setNewAlias(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Add alias…"
                className="flex-1 text-sm border rounded px-2 py-1 dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-300"
              />
              <button
                onClick={addAlias}
                className="px-3 py-1 text-sm border rounded hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                Add
              </button>
            </div>
          </section>

          {/* Season names */}
          <section>
            <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Season names</h3>
            <p className="text-xs text-gray-400 dark:text-gray-500 mb-2">
              Release names that mean one season, such as an arc title. Files named
              &ldquo;{show.title} - &lt;name&gt; - 01&rdquo; go to that season.
            </p>
            {Object.keys(seasonAliases).length > 0 ? (
              <ul className="flex flex-col gap-1 mb-2">
                {Object.entries(seasonAliases).map(([name, season]) => (
                  <li
                    key={name}
                    className="flex items-center gap-2 px-2 py-0.5 bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300 rounded text-xs"
                  >
                    <span className="flex-1 truncate">{name}</span>
                    <span className="tabular-nums">Season {season}</span>
                    <button
                      onClick={() => removeSeasonAlias(name)}
                      className="hover:text-red-500"
                      aria-label={`Remove season name ${name}`}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-gray-400 dark:text-gray-500 italic mb-2">None yet</p>
            )}
            <div className="flex gap-2">
              <input
                type="text"
                value={newSeasonName}
                onChange={(e) => setNewSeasonName(e.target.value)}
                onKeyDown={handleSeasonKeyDown}
                placeholder="Add season name…"
                className="flex-1 min-w-0 text-sm border rounded px-2 py-1 dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-300"
              />
              <input
                type="number"
                min={0}
                max={999}
                value={newSeasonNumber}
                onChange={(e) => setNewSeasonNumber(e.target.value)}
                onKeyDown={handleSeasonKeyDown}
                placeholder="Season"
                aria-label="Season number"
                className="w-20 text-sm border rounded px-2 py-1 dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-300"
              />
              <button
                onClick={addSeasonAlias}
                aria-label="Add season name"
                className="px-3 py-1 text-sm border rounded hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                Add
              </button>
            </div>
          </section>
          {(updateAliases.isError || updateSeasonAliases.isError) && (
            <p className="text-xs text-red-600">Saving failed — check server logs.</p>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-5 py-3 border-t">
          <Button onClick={onClose} variant="secondary" tone="light" size="md">
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving} variant="primary" tone="light" size="md">
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </div>
    </Modal>
  )
}
