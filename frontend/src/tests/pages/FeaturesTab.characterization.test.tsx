import { render, screen, fireEvent } from '@testing-library/react'
import { describe, test, expect, vi } from 'vitest'
import { FeaturesTab, type FeaturesTabProps } from '@/pages/settings/FeaturesTab'
import { domSnapshot } from '../helpers/dom'

/**
 * Characterization of the Features settings tab: rendered DOM for the loading,
 * loaded, pending and master-switch-off states, and the exact patch payload each
 * control sends. Written before the SettingToggle extraction; it must pass
 * unchanged afterwards.
 */

const settings = {
  similar_titles_enabled: true,
  similar_titles_include_external: true,
  similar_titles_count: 12,
  show_adult_content: false,
  recent_episodes_enabled: true,
  recent_movies_enabled: true,
  recent_episodes_prefer_posters: false,
  dashboard_page_enabled: true,
  calendar_enabled: true,
  discover_enabled: true,
}

function setup(overrides: Partial<Record<keyof typeof settings, unknown>> | null, pending = false) {
  const mutate = vi.fn()
  const setBannerStyle = vi.fn()
  const props = {
    appSettings: overrides === null ? undefined : { ...settings, ...overrides },
    updateAppSettings: { mutate, isPending: pending },
    bannerStyle: 'hero',
    setBannerStyle,
  } as unknown as FeaturesTabProps
  const view = render(<FeaturesTab {...props} />)
  return { mutate, setBannerStyle, view }
}

describe('FeaturesTab characterization', () => {
  test('settings still loading', () => {
    setup(null)
    expect(domSnapshot()).toMatchSnapshot('loading')
  })

  test('loaded with defaults', () => {
    setup({})
    expect(domSnapshot()).toMatchSnapshot('loaded')
  })

  test('all flipped', () => {
    setup({
      similar_titles_enabled: false,
      show_adult_content: true,
      recent_episodes_prefer_posters: true,
      calendar_enabled: false,
      similar_titles_count: 3,
    })
    expect(domSnapshot()).toMatchSnapshot('flipped')
  })

  test('mutation pending disables every control', () => {
    setup({}, true)
    expect(domSnapshot()).toMatchSnapshot('pending')
  })

  test('each switch sends its own patch', () => {
    const { mutate } = setup({})
    const switches = screen.getAllByRole('switch')
    expect(switches).toHaveLength(9)
    for (const sw of switches) fireEvent.click(sw)
    expect(mutate.mock.calls).toMatchSnapshot('switch patches')
  })

  test('count input clamps, rounds and ignores non-numbers', () => {
    const { mutate } = setup({})
    const input = screen.getByRole('spinbutton')
    fireEvent.change(input, { target: { value: '99' } })
    fireEvent.change(input, { target: { value: '0' } })
    fireEvent.change(input, { target: { value: '7.6' } })
    fireEvent.change(input, { target: { value: '' } })
    expect(mutate.mock.calls).toMatchSnapshot('count patches')
  })

  test('banner style control reports the chosen style', () => {
    const { setBannerStyle } = setup({})
    fireEvent.click(screen.getByRole('radio', { name: 'Full' }))
    expect(setBannerStyle).toHaveBeenCalledWith('full')
  })
})
