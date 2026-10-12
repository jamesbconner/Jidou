import { useRef, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { useImportText, useExportDatabase, useImportDatabase } from '@/hooks/useData'
import { useTriggerWithDryRun } from '@/hooks/useSettingsActions'
import type { TaskRead } from '@/types/api'
import { LiveImportTask } from './LiveImportTask'

type ImportMode = 'full' | 'shows_only' | 'episodes_only'

const IMPORT_MODE_OPTIONS: { value: ImportMode; label: string; description: string }[] = [
  {
    value: 'full',
    label: 'Full',
    description: 'Create/find shows and match episodes in one pass (default). Each line' +
      'should represent the full path of an episode file.',
  },
  {
    value: 'shows_only',
    label: 'Shows only',
    description:
      'Create/find shows and sync their episodes, but skip episode matching. Useful as a ' +
      'first pass to populate or verify the show catalog before touching episode-level data. ' +
      'Each line can be the path to a bare show directory instead of a full episode file path.',
  },
  {
    value: 'episodes_only',
    label: 'Episodes only',
    description:
      'Match episodes only against shows already in the database. Never searches TMDB or ' +
      'creates a new show. Files under a show not already in the database are reported ' +
      'unmatched.',
  },
]

function TextImportSection() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [contentType, setContentType] = useState('anime')
  const [dryRun, setDryRun] = useState(false)
  const [mode, setMode] = useState<ImportMode>('full')
  const [task, setTask] = useState<TaskRead | null>(null)
  const { mutate, isPending, error } = useImportText()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const file = fileRef.current?.files?.[0]
    if (!file) return
    setTask(null)
    mutate(
      { file, contentType, dryRun, mode },
      {
        onSuccess: (t) => setTask(t),
      },
    )
  }

  return (
    <Card as="section" padding="lg" className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold dark:text-gray-100">Text File Import</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Upload a plain-text file of episode paths (one per line) to batch-import shows and mark
          episodes as tracked. Accepts Windows and Linux paths.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <fieldset className="space-y-2">
          <legend className="text-xs text-gray-500 dark:text-gray-400 mb-1">Import mode</legend>
          {IMPORT_MODE_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex items-start gap-2 text-sm cursor-pointer dark:text-gray-200">
              <input
                type="radio"
                name="import-mode"
                value={opt.value}
                checked={mode === opt.value}
                onChange={() => setMode(opt.value)}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium">{opt.label}</span>
                <span className="text-gray-500 dark:text-gray-400"> — {opt.description}</span>
              </span>
            </label>
          ))}
        </fieldset>

        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="text-xs text-gray-500 dark:text-gray-400 block mb-1">Path file (.txt)</label>
            <input
              ref={fileRef}
              type="file"
              accept=".txt,text/plain"
              required
              className="text-sm dark:text-gray-300"
            />
          </div>

          <div>
            <label className="text-xs text-gray-500 dark:text-gray-400 block mb-1">Content type</label>
            <select
              value={contentType}
              onChange={(e) => setContentType(e.target.value)}
              title="Selects which library root anchors path parsing — required in every mode, not just for newly created shows"
              className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:text-gray-100"
            >
              <option value="anime">Anime</option>
              <option value="tv">TV</option>
              <option value="movie">Movie</option>
            </select>
          </div>

          <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              className="rounded"
            />
            Dry run
          </label>

          <Button type="submit" disabled={isPending} variant="primary" tone="light" size="md">
            {isPending ? 'Submitting…' : 'Import'}
          </Button>
        </div>

        {error && <p className="text-sm text-red-600 dark:text-red-400">{(error as Error).message}</p>}
        {task && <LiveImportTask task={task} />}
      </form>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Database Export section
// ---------------------------------------------------------------------------

function DatabaseExportSection() {
  const { mutate, isPending, error, isSuccess } = useExportDatabase()

  return (
    <Card as="section" padding="lg" className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold dark:text-gray-100">Database Export</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Download all shows, episodes, and watchlist entries as a JSON backup file.
        </p>
      </div>

      <button
        onClick={() => mutate()}
        disabled={isPending}
        className="px-4 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50"
      >
        {isPending ? 'Preparing…' : 'Download backup'}
      </button>

      {isSuccess && (
        <p className="text-sm text-green-700 dark:text-green-400">Download started.</p>
      )}
      {error && <p className="text-sm text-red-600 dark:text-red-400">{(error as Error).message}</p>}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Database Import section
// ---------------------------------------------------------------------------

function DatabaseImportSection() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [task, setTask] = useState<TaskRead | null>(null)
  const { mutate, isPending, error } = useImportDatabase()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const file = fileRef.current?.files?.[0]
    if (!file) return
    setTask(null)
    mutate(file, { onSuccess: (t) => setTask(t) })
  }

  return (
    <Card as="section" padding="lg" className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold dark:text-gray-100">Database Import</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Restore from a Jidou backup JSON file. Shows and episodes are upserted by TMDB ID;
          existing local paths are preserved when absent in the backup.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="text-xs text-gray-500 dark:text-gray-400 block mb-1">Backup file (.json)</label>
            <input
              ref={fileRef}
              type="file"
              accept=".json,application/json"
              required
              className="text-sm dark:text-gray-300"
            />
          </div>

          <Button type="submit" disabled={isPending} variant="primary" tone="light" size="md">
            {isPending ? 'Submitting…' : 'Restore'}
          </Button>
        </div>

        {error && <p className="text-sm text-red-600 dark:text-red-400">{(error as Error).message}</p>}
        {task && <LiveImportTask task={task} />}
      </form>
    </Card>
  )
}
/** Import/export and maintenance triggers (the Settings "Data" tab). */
export function DataTab() {
  const seed = useTriggerWithDryRun('seed')
  const backfill = useTriggerWithDryRun('backfill_show_metadata')

  return (
    <div className="space-y-6">
      <TextImportSection />
      <DatabaseExportSection />
      <DatabaseImportSection />

      <Card padding="md" className="space-y-3">
        <h2 className="font-semibold dark:text-gray-100">SFTP Baseline Files</h2>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          Inventories all existing files on the SFTP server and marks them as{' '}
          <span className="font-mono text-xs bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300 px-1 rounded">seeded</span>{' '}
          so Jidou will never re-download them. The operation is idempotent — safe to re-run.
        </p>
        <div className="flex gap-3 flex-wrap">
          <Button onClick={() => seed.dryRun.mutate()} disabled={seed.dryRun.isPending || seed.live.isPending} variant="secondary" tone="light" size="md">
            {seed.dryRun.isPending ? 'Running dry run…' : 'Dry Run'}
          </Button>
          <button
            onClick={() => {
              if (window.confirm('Mark all current SFTP files as seeded? This cannot be undone without deleting seeded records from the database.')) {
                seed.live.mutate()
              }
            }}
            disabled={seed.dryRun.isPending || seed.live.isPending}
            className="px-3 py-1.5 text-sm rounded bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50"
          >
            {seed.live.isPending ? 'Running…' : 'Run Baseline'}
          </button>
        </div>
        {(seed.dryRun.isError || seed.live.isError) && (
          <p className="text-xs text-red-600 dark:text-red-400">
            {String((seed.dryRun.error ?? seed.live.error) || 'Unknown error')}
          </p>
        )}
      </Card>

      <Card padding="md" className="space-y-3">
        <h2 className="font-semibold dark:text-gray-100">Show Metadata Backfill</h2>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          Refetches full TMDB details for shows with no genre data (e.g. added by searching TMDB
          directly rather than resolving a matched file) and reapplies genres, external IDs, and
          other TMDB fields. Local path, content type, aliases, and folder naming are never
          touched. Safe to re-run.
        </p>
        <div className="flex gap-3 flex-wrap">
          <Button onClick={() => backfill.dryRun.mutate()} disabled={backfill.dryRun.isPending || backfill.live.isPending} variant="secondary" tone="light" size="md">
            {backfill.dryRun.isPending ? 'Running dry run…' : 'Dry Run'}
          </Button>
          <button
            onClick={() => {
              if (window.confirm('Backfill missing TMDB metadata for all affected shows?')) {
                backfill.live.mutate()
              }
            }}
            disabled={backfill.dryRun.isPending || backfill.live.isPending}
            className="px-3 py-1.5 text-sm rounded bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50"
          >
            {backfill.live.isPending ? 'Running…' : 'Run Backfill'}
          </button>
        </div>
        {(backfill.dryRun.isError || backfill.live.isError) && (
          <p className="text-xs text-red-600 dark:text-red-400">
            {String((backfill.dryRun.error ?? backfill.live.error) || 'Unknown error')}
          </p>
        )}
      </Card>
    </div>
  )
}
