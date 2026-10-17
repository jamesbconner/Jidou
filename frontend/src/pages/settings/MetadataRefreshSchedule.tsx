import { useState } from 'react'
import type { useUpdateAppSettings } from '@/hooks/useSettings'
import { normalizeScheduleHours } from '@/utils/scheduleHours'
import type { AppSettings, AppSettingsPatch } from '@/types/api'
import { ScheduleRow } from './ScheduleRow'

const LIMIT_MIN = 1
const LIMIT_MAX = 500

const HOURS_ERROR = 'Use whole hours from 0 to 23, separated by commas (for example 4 or 4,16).'
const LIMIT_ERROR = `Enter a whole number from ${LIMIT_MIN} to ${LIMIT_MAX}.`

const INPUT_CLS =
  'border rounded px-2 py-1 text-sm border-gray-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 disabled:opacity-50'

export interface MetadataRefreshScheduleProps {
  appSettings: AppSettings | undefined
  /** Settings' shared mutation; owned by Settings so its state survives tab switches. */
  update: ReturnType<typeof useUpdateAppSettings>
}

/**
 * The show-metadata refresh schedule: the same read-only row the other
 * schedules get, plus controls to change it. Unlike Full Sync and RSS Import
 * (environment variables, restart required), these are saved settings that
 * take effect at the next hourly check.
 */
export function MetadataRefreshSchedule({ appSettings, update }: MetadataRefreshScheduleProps) {
  if (!appSettings) return null
  const { metadata_refresh_schedule_enabled: enabled, metadata_refresh_schedule_hours: hours } = appSettings
  const limit = appSettings.metadata_refresh_limit_per_run

  return (
    <div className="space-y-2">
      <ScheduleRow label="Metadata Refresh" enabled={enabled} hours={hours} />
      {/* Re-keyed on the saved values so the drafts reset after every save. */}
      <ScheduleForm key={`${enabled}|${hours}|${limit}`} saved={appSettings} update={update} />
    </div>
  )
}

function ScheduleForm({ saved, update }: { saved: AppSettings; update: MetadataRefreshScheduleProps['update'] }) {
  const [enabled, setEnabled] = useState(saved.metadata_refresh_schedule_enabled)
  const [hoursText, setHoursText] = useState(saved.metadata_refresh_schedule_hours)
  const [limitText, setLimitText] = useState(String(saved.metadata_refresh_limit_per_run))
  const [edited, setEdited] = useState(false)

  const normalizedHours = normalizeScheduleHours(hoursText)
  const limitValue = /^[0-9]+$/.test(limitText.trim()) ? Number(limitText.trim()) : NaN
  const limitValid = Number.isInteger(limitValue) && limitValue >= LIMIT_MIN && limitValue <= LIMIT_MAX

  const patch: AppSettingsPatch = {}
  if (enabled !== saved.metadata_refresh_schedule_enabled) patch.metadata_refresh_schedule_enabled = enabled
  if (normalizedHours !== null && normalizedHours !== saved.metadata_refresh_schedule_hours) {
    patch.metadata_refresh_schedule_hours = normalizedHours
  }
  if (limitValid && limitValue !== saved.metadata_refresh_limit_per_run) {
    patch.metadata_refresh_limit_per_run = limitValue
  }

  const dirty = Object.keys(patch).length > 0
  const valid = normalizedHours !== null && limitValid
  const locked = update.isPending

  function edit<T>(setter: (value: T) => void) {
    return (value: T) => {
      setter(value)
      setEdited(true)
    }
  }

  return (
    <div className="space-y-3 rounded border border-gray-200 dark:border-gray-700 p-3 text-sm">
      <label className="flex items-center justify-between gap-3 cursor-pointer">
        <FieldLabel title="Enabled">Run the metadata refresh on the schedule below.</FieldLabel>
        <input
          type="checkbox"
          role="switch"
          checked={enabled}
          disabled={locked}
          onChange={(e) => edit(setEnabled)(e.target.checked)}
          className="h-4 w-4 shrink-0 accent-[var(--color-ocean-600)]"
        />
      </label>

      <label className="flex items-start justify-between gap-3">
        <FieldLabel title="Run at (UTC hours)">
          Comma-separated hours, 0–23 (for example 4 or 4,16). It is checked every hour, so a change
          applies from the next full hour.
        </FieldLabel>
        <input
          type="text"
          inputMode="numeric"
          value={hoursText}
          disabled={locked}
          aria-invalid={normalizedHours === null}
          onChange={(e) => edit(setHoursText)(e.target.value)}
          className={`w-28 shrink-0 ${INPUT_CLS}`}
        />
      </label>
      {normalizedHours === null && (
        <p role="alert" className="text-xs text-red-600 dark:text-red-400">
          {HOURS_ERROR}
        </p>
      )}

      <label className="flex items-start justify-between gap-3">
        <FieldLabel title="Shows per run">
          Per run, not per day: with two scheduled hours the cap applies twice a day. Each TV show costs
          three TMDB calls.
        </FieldLabel>
        <input
          type="number"
          min={LIMIT_MIN}
          max={LIMIT_MAX}
          value={limitText}
          disabled={locked}
          aria-invalid={!limitValid}
          onChange={(e) => edit(setLimitText)(e.target.value)}
          className={`w-20 shrink-0 ${INPUT_CLS}`}
        />
      </label>
      {!limitValid && (
        <p role="alert" className="text-xs text-red-600 dark:text-red-400">
          {LIMIT_ERROR}
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={locked || !dirty || !valid}
          onClick={() => update.mutate(patch)}
          className="btn px-3 py-1.5 text-xs border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800 disabled:opacity-50"
        >
          {locked ? 'Saving…' : 'Save'}
        </button>
        {update.isError && (
          <p role="alert" className="text-xs text-red-600 dark:text-red-400">
            {(update.error as Error | null)?.message ?? 'Could not save the schedule.'}
          </p>
        )}
        {update.isSuccess && !edited && !locked && (
          <span className="text-xs text-green-600 dark:text-green-400">Saved.</span>
        )}
      </div>
    </div>
  )
}

function FieldLabel({ title, children }: { title: string; children: string }) {
  return (
    <span className="text-gray-700 dark:text-gray-300">
      {title}
      <span className="block text-xs text-gray-400 dark:text-gray-500 font-normal">{children}</span>
    </span>
  )
}
