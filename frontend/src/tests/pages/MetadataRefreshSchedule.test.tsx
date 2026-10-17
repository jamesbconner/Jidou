import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import { MetadataRefreshSchedule } from '@/pages/settings/MetadataRefreshSchedule'
import type { AppSettings } from '@/types/api'

function settings(overrides: Partial<AppSettings> = {}): AppSettings {
  return {
    show_adult_content: false,
    calendar_enabled: true,
    discover_enabled: true,
    dashboard_page_enabled: true,
    recent_episodes_enabled: true,
    recent_movies_enabled: true,
    recent_episodes_prefer_posters: false,
    similar_titles_enabled: true,
    similar_titles_count: 12,
    similar_titles_include_external: true,
    metadata_refresh_schedule_enabled: true,
    metadata_refresh_schedule_hours: '4',
    metadata_refresh_limit_per_run: 10,
    ...overrides,
  }
}

function mutation(over: Record<string, unknown> = {}) {
  return { mutate: vi.fn(), isPending: false, isError: false, isSuccess: false, error: null, ...over }
}

function setup(appSettings: AppSettings | undefined = settings(), over: Record<string, unknown> = {}) {
  const update = mutation(over)
  const view = render(
    <MetadataRefreshSchedule
      appSettings={appSettings}
      update={update as unknown as Parameters<typeof MetadataRefreshSchedule>[0]['update']}
    />,
  )
  return { update, user: userEvent.setup(), ...view }
}

const hours = () => screen.getByRole('textbox', { name: /run at/i })
const limit = () => screen.getByRole('spinbutton', { name: /shows per run/i })
const enabled = () => screen.getByRole('switch', { name: /enabled/i })
const save = () => screen.getByRole('button', { name: 'Save' })

describe('MetadataRefreshSchedule', () => {
  test('renders nothing until the settings have loaded', () => {
    const { container } = setup(null as unknown as undefined)
    expect(container).toBeEmptyDOMElement()
  })

  test('shows the saved schedule in the same row format as the other schedules', () => {
    setup(settings({ metadata_refresh_schedule_hours: '4,16' }))
    expect(screen.getByText('Metadata Refresh')).toBeInTheDocument()
    // "Enabled" is both the row's status badge and the switch's label; find the badge.
    expect(screen.getAllByText('Enabled').some((el) => el.className.includes('rounded-full'))).toBe(true)
    expect(screen.getByText(/Daily at 04:00, 16:00 UTC/)).toBeInTheDocument()
  })

  test('a disabled schedule reads "not scheduled"', () => {
    setup(settings({ metadata_refresh_schedule_enabled: false }))
    expect(screen.getByText('not scheduled')).toBeInTheDocument()
    expect(enabled()).not.toBeChecked()
  })

  test('the controls start with the saved values and Save is disabled until something changes', () => {
    setup(settings({ metadata_refresh_schedule_hours: '4,16', metadata_refresh_limit_per_run: 25 }))
    expect(enabled()).toBeChecked()
    expect(hours()).toHaveValue('4,16')
    expect(limit()).toHaveValue(25)
    expect(save()).toBeDisabled()
  })

  test('saves only the fields that changed', async () => {
    const { user, update } = setup()
    await user.clear(limit())
    await user.type(limit(), '30')
    await user.click(save())
    expect(update.mutate).toHaveBeenCalledExactlyOnceWith({ metadata_refresh_limit_per_run: 30 })
  })

  test('hours are saved in canonical form', async () => {
    const { user, update } = setup()
    await user.clear(hours())
    await user.type(hours(), '16, 04')
    await user.click(save())
    expect(update.mutate).toHaveBeenCalledExactlyOnceWith({ metadata_refresh_schedule_hours: '4,16' })
  })

  test('typing the saved hours in a different format is not a change', async () => {
    const { user } = setup(settings({ metadata_refresh_schedule_hours: '4,16' }))
    await user.clear(hours())
    await user.type(hours(), '16, 4')
    expect(save()).toBeDisabled()
  })

  test('toggling Enabled saves the new flag', async () => {
    const { user, update } = setup()
    await user.click(enabled())
    await user.click(save())
    expect(update.mutate).toHaveBeenCalledExactlyOnceWith({ metadata_refresh_schedule_enabled: false })
  })

  test('several changes are sent together', async () => {
    const { user, update } = setup()
    await user.click(enabled())
    await user.clear(hours())
    await user.type(hours(), '6')
    await user.clear(limit())
    await user.type(limit(), '5')
    await user.click(save())
    expect(update.mutate).toHaveBeenCalledExactlyOnceWith({
      metadata_refresh_schedule_enabled: false,
      metadata_refresh_schedule_hours: '6',
      metadata_refresh_limit_per_run: 5,
    })
  })

  test.each(['', '25', 'a', '4;16'])('invalid hours %j show an error and block Save', async (bad) => {
    const { user, update } = setup()
    await user.clear(hours())
    if (bad) await user.type(hours(), bad)
    expect(screen.getByRole('alert')).toHaveTextContent(/hours/i)
    expect(hours()).toHaveAttribute('aria-invalid', 'true')
    expect(save()).toBeDisabled()
    expect(update.mutate).not.toHaveBeenCalled()
  })

  test.each(['0', '501', '-3', ''])('an invalid limit %j shows an error and blocks Save', async (bad) => {
    const { user } = setup()
    await user.clear(limit())
    if (bad) await user.type(limit(), bad)
    expect(screen.getByRole('alert')).toHaveTextContent(/1.+500/)
    expect(save()).toBeDisabled()
  })

  test('the limit bounds themselves are valid', async () => {
    const { user } = setup()
    await user.clear(limit())
    await user.type(limit(), '500')
    expect(save()).toBeEnabled()
    await user.clear(limit())
    await user.type(limit(), '1')
    expect(save()).toBeEnabled()
  })

  test('while saving, the controls and Save are disabled and Save reads "Saving…"', () => {
    setup(settings(), { isPending: true })
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled()
    expect(hours()).toBeDisabled()
    expect(limit()).toBeDisabled()
    expect(enabled()).toBeDisabled()
  })

  test('a failed save shows the server message', () => {
    setup(settings(), { isError: true, error: new Error('Invalid hour 25') })
    expect(screen.getByRole('alert')).toHaveTextContent('Invalid hour 25')
  })

  test('a successful save with nothing pending shows a confirmation', () => {
    setup(settings(), { isSuccess: true })
    expect(screen.getByText('Saved.')).toBeInTheDocument()
  })

  test('the confirmation goes away once the form is edited again', async () => {
    const { user } = setup(settings(), { isSuccess: true })
    await user.click(enabled())
    expect(screen.queryByText('Saved.')).not.toBeInTheDocument()
  })

  test('explains that the limit is per run, not per day', () => {
    setup()
    expect(screen.getByText(/per run, not per day/i)).toBeInTheDocument()
  })
})
