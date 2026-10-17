import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import { ServicesTab, type ServicesTabProps } from '@/pages/settings/ServicesTab'
import type { AppSettings } from '@/types/api'

/** The Metadata Refresh schedule sits in the Services tab's Schedules card, next to the env-only ones. */

function appSettings(overrides: Partial<AppSettings> = {}): AppSettings {
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

function setup(settings: AppSettings | undefined) {
  const mutate = vi.fn()
  const idle = { mutate, isPending: false, isError: false, isSuccess: false, error: null }
  const stub = { mutate: vi.fn(), isPending: false }
  const props = {
    config: {
      llm_provider: 'none',
      sync_schedule_enabled: true,
      sync_schedule_hours: '2',
      rss_import_schedule_enabled: false,
      rss_import_schedule_hours: '6',
    },
    cache: { data: undefined, refetch: vi.fn(), isFetching: false },
    flushCache: stub,
    health: { data: undefined, refetch: vi.fn(), isFetching: false },
    tests: { tmdb: stub, sftp: stub, redis: stub, llm: stub },
    appSettings: settings,
    updateAppSettings: idle,
  } as unknown as ServicesTabProps
  render(<ServicesTab {...props} />)
  return { mutate, user: userEvent.setup() }
}

describe('ServicesTab: Metadata Refresh schedule', () => {
  test('is listed with the other schedules in the Schedules card', () => {
    setup(appSettings())
    const card = screen.getByRole('heading', { name: 'Schedules' }).closest('.card') as HTMLElement
    expect(card).toHaveTextContent('Full Sync')
    expect(card).toHaveTextContent('RSS Import')
    expect(card).toHaveTextContent('Metadata Refresh')
  })

  test('is editable, unlike the environment-configured schedules', async () => {
    const { user, mutate } = setup(appSettings())
    const hours = screen.getByRole('textbox', { name: /run at/i })
    await user.clear(hours)
    await user.type(hours, '4,16')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(mutate).toHaveBeenCalledExactlyOnceWith({ metadata_refresh_schedule_hours: '4,16' })
  })

  test('the card note no longer claims every schedule needs an environment variable and a restart', () => {
    setup(appSettings())
    const note = screen.getByText(/environment variables/i)
    expect(note).toHaveTextContent(/Full Sync and RSS Import/)
    expect(note).toHaveTextContent(/restart/i)
    expect(note).toHaveTextContent(/Metadata Refresh/)
    expect(note).toHaveTextContent(/no restart/i)
  })

  test('shows no editor, and no Metadata Refresh row, until the settings have loaded', () => {
    setup(undefined)
    expect(screen.queryByText('Metadata Refresh')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
    expect(screen.getByText('Full Sync')).toBeInTheDocument()
  })
})
