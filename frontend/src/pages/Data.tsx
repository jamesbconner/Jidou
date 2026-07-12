import { useRef, useState } from 'react'
import { useImportText, useExportDatabase, useImportDatabase } from '@/hooks/useData'
import { useTask } from '@/hooks/useTasks'
import { useTaskProgress } from '@/hooks/useTaskProgress'
import { TaskProgressBar } from '@/components/TaskProgressBar'
import type { TaskRead } from '@/types/api'

// ---------------------------------------------------------------------------
// Live task tracker — subscribes to WS progress for a single task
// ---------------------------------------------------------------------------

function LiveImportTask({ task }: { task: TaskRead }) {
  const { data: live } = useTask(task.id)
  useTaskProgress(task.celery_task_id)
  const t = live ?? task
  return (
    <div className="mt-4 space-y-2">
      <TaskProgressBar task={t} />
      {t.status === 'completed' && t.result_summary && (
        <pre className="text-xs bg-gray-50 border rounded p-2 overflow-x-auto">
          {JSON.stringify(t.result_summary, null, 2)}
        </pre>
      )}
      {t.status === 'failed' && (
        <p className="text-sm text-red-600">{t.progress_message}</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Text File Import section
// ---------------------------------------------------------------------------

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
    <section className="bg-white rounded-lg shadow p-6 space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Text File Import</h2>
        <p className="text-sm text-gray-500 mt-1">
          Upload a plain-text file of episode paths (one per line) to batch-import shows and mark
          episodes as tracked. Accepts Windows and Linux paths.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <fieldset className="space-y-2">
          <legend className="text-xs text-gray-500 mb-1">Import mode</legend>
          {IMPORT_MODE_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex items-start gap-2 text-sm cursor-pointer">
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
                <span className="text-gray-500"> — {opt.description}</span>
              </span>
            </label>
          ))}
        </fieldset>

        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Path file (.txt)</label>
            <input
              ref={fileRef}
              type="file"
              accept=".txt,text/plain"
              required
              className="text-sm"
            />
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">Content type</label>
            <select
              value={contentType}
              onChange={(e) => setContentType(e.target.value)}
              title="Selects which library root anchors path parsing — required in every mode, not just for newly created shows"
              className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="anime">Anime</option>
              <option value="tv">TV</option>
              <option value="movie">Movie</option>
            </select>
          </div>

          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              className="rounded"
            />
            Dry run
          </label>

          <button
            type="submit"
            disabled={isPending}
            className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {isPending ? 'Submitting…' : 'Import'}
          </button>
        </div>

        {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}
        {task && <LiveImportTask task={task} />}
      </form>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Database Export section
// ---------------------------------------------------------------------------

function DatabaseExportSection() {
  const { mutate, isPending, error, isSuccess } = useExportDatabase()

  return (
    <section className="bg-white rounded-lg shadow p-6 space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Database Export</h2>
        <p className="text-sm text-gray-500 mt-1">
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
        <p className="text-sm text-green-700">Download started.</p>
      )}
      {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}
    </section>
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
    <section className="bg-white rounded-lg shadow p-6 space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Database Import</h2>
        <p className="text-sm text-gray-500 mt-1">
          Restore from a Jidou backup JSON file. Shows and episodes are upserted by TMDB ID;
          existing local paths are preserved when absent in the backup.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Backup file (.json)</label>
            <input
              ref={fileRef}
              type="file"
              accept=".json,application/json"
              required
              className="text-sm"
            />
          </div>

          <button
            type="submit"
            disabled={isPending}
            className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {isPending ? 'Submitting…' : 'Restore'}
          </button>
        </div>

        {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}
        {task && <LiveImportTask task={task} />}
      </form>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Data() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Data</h1>
      <TextImportSection />
      <DatabaseExportSection />
      <DatabaseImportSection />
    </div>
  )
}
