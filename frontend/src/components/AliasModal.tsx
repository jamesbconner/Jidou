import { useState, useEffect, KeyboardEvent } from 'react'
import { useFocusTrap } from '@/hooks/useFocusTrap'
import { useUpdateShowAliases, useRegenerateShowAliases } from '@/hooks/useShows'
import type { ShowRead } from '@/types/api'

interface Props {
  show: ShowRead
  onClose: () => void
}

export function AliasModal({ show, onClose }: Props) {
  const dialogRef = useFocusTrap<HTMLDivElement>(onClose)
  const sources = show.aliases_sources ?? { tmdb: [], llm: [], user: [] }

  const [userAliases, setUserAliases] = useState<string[]>(sources.user)
  const [newAlias, setNewAlias] = useState('')

  const updateAliases = useUpdateShowAliases(show.id)
  const regenerate = useRegenerateShowAliases(show.id)

  // Sync user aliases from show data when regeneration completes.
  useEffect(() => {
    setUserAliases(show.aliases_sources?.user ?? [])
  }, [show.aliases_sources])

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

  function handleSave() {
    updateAliases.mutate(userAliases, { onSuccess: onClose })
  }

  const tmdbAliases = show.aliases_sources?.tmdb ?? []
  const llmAliases = show.aliases_sources?.llm ?? []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={dialogRef}
        className="w-full max-w-lg bg-white rounded-lg shadow-xl flex flex-col max-h-[90vh]"
        role="dialog"
        aria-modal="true"
        aria-label={`Manage aliases for ${show.title}`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <h2 className="font-semibold text-gray-900 truncate">
            Manage Aliases — {show.title}
          </h2>
          <button
            onClick={onClose}
            className="ml-2 text-gray-400 hover:text-gray-600"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-5">
          {/* TMDB source */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-gray-700">TMDB</h3>
              <span className="text-xs text-gray-400">Read-only</span>
            </div>
            {tmdbAliases.length > 0 ? (
              <ul className="flex flex-wrap gap-1.5">
                {tmdbAliases.map((a) => (
                  <li
                    key={a}
                    className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-xs"
                  >
                    {a}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-gray-400 italic">None</p>
            )}
          </section>

          {/* LLM source */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-gray-700">LLM</h3>
              <span className="text-xs text-gray-400">Read-only</span>
            </div>
            {llmAliases.length > 0 ? (
              <ul className="flex flex-wrap gap-1.5">
                {llmAliases.map((a) => (
                  <li
                    key={a}
                    className="px-2 py-0.5 bg-purple-50 text-purple-700 rounded text-xs"
                  >
                    {a}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-gray-400 italic">None</p>
            )}
          </section>

          {/* Regenerate button */}
          <div>
            <button
              onClick={() => regenerate.mutate()}
              disabled={regenerate.isPending}
              className="px-3 py-1.5 text-sm border rounded hover:bg-gray-50 disabled:opacity-50"
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
            <h3 className="text-sm font-medium text-gray-700 mb-2">
              User-defined
              <span className="ml-1 text-xs font-normal text-gray-400">
                (persisted, never overwritten by regeneration)
              </span>
            </h3>
            {userAliases.length > 0 ? (
              <ul className="flex flex-wrap gap-1.5 mb-2">
                {userAliases.map((a) => (
                  <li
                    key={a}
                    className="flex items-center gap-1 px-2 py-0.5 bg-green-50 text-green-700 rounded text-xs"
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
              <p className="text-xs text-gray-400 italic mb-2">None yet</p>
            )}
            <div className="flex gap-2">
              <input
                type="text"
                value={newAlias}
                onChange={(e) => setNewAlias(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Add alias…"
                className="flex-1 text-sm border rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-300"
              />
              <button
                onClick={addAlias}
                className="px-3 py-1 text-sm border rounded hover:bg-gray-50"
              >
                Add
              </button>
            </div>
          </section>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-5 py-3 border-t">
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-sm border rounded hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={updateAliases.isPending}
            className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {updateAliases.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
