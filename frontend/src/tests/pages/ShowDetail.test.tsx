import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import ShowDetail from '@/pages/ShowDetail'
import type { ShowRead } from '@/types/api'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(
      QueryClientProvider,
      { client: qc },
      createElement(
        MemoryRouter,
        { initialEntries: ['/shows/1'] },
        createElement(Routes, null, createElement(Route, { path: '/shows/:id', element: children })),
      ),
    )
}

// vi.spyOn(globalThis, 'fetch') triggers a worker crash on Node >=22.1.x
// (https://github.com/nodejs/node/issues/54735); plain assignment avoids it.
const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function mockResponse(body: unknown = null, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    headers: { get: () => null } as unknown as Headers,
    json: async () => body,
  } as unknown as Response
}

function baseShow(overrides: Partial<ShowRead> = {}): ShowRead {
  return {
    id: 1,
    tmdb_id: 100,
    title: 'Test Show',
    media_type: 'tv',
    overview: null,
    poster_path: null,
    backdrop_path: null,
    vote_average: null,
    vote_count: 0,
    release_date: null,
    original_language: null,
    cached: false,
    content_type: null,
    sys_name: null,
    aliases: null,
    aliases_sources: null,
    genres: null,
    origin_country: null,
    last_air_date: null,
    last_episode_to_air: null,
    next_episode_to_air: null,
    homepage: null,
    external_ids: null,
    episode_groups: null,
    episode_group_map: null,
    status: null,
    in_production: null,
    number_of_seasons: null,
    number_of_episodes: null,
    networks: null,
    show_type: null,
    runtime: null,
    tagline: null,
    local_path: null,
    adult: null,
    list_poster_path: null,
    detail_poster_path: null,
    track_missing_episodes: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function mockShowDetail(
  initial: ShowRead,
  opts: { files?: unknown[]; watchlist?: unknown[] } = {},
) {
  let show = initial
  vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (method === 'PATCH' && url.includes('/shows/1')) {
      const patch = JSON.parse(String(init?.body)) as Partial<ShowRead>
      show = { ...show, ...patch }
      return mockResponse(show)
    }
    if (url.includes('/shows/1/episodes')) return mockResponse([])
    if (url.includes('/shows/1/similar')) return mockResponse([])
    if (url.includes('/shows/1/scan-local-movie-file')) return mockResponse([])
    if (url.includes('/files?show_id=1')) return mockResponse(opts.files ?? [])
    if (url.includes('/shows/1')) return mockResponse(show)
    if (url.includes('/config')) return mockResponse({ today: '2026-08-04' })
    if (url.includes('/rss/subscriptions')) return mockResponse([])
    if (url.includes('/rss/feeds')) return mockResponse([])
    if (url.includes('/watchlist')) {
      // Honour the by-show filter the way the API does (DF-18).
      const all = (opts.watchlist ?? []) as { show_id: number }[]
      const byShow = /[?&]show_id=(\d+)/.exec(url)
      return mockResponse(byShow ? all.filter((e) => e.show_id === Number(byShow[1])) : all)
    }
    return mockResponse([])
  })
}

/** The sidebar's less common actions live in an "Action" menu; open it and pick one. */
async function chooseFromMoreMenu(name: string) {
  fireEvent.click(await screen.findByRole('button', { name: /^Action/ }))
  fireEvent.click(await screen.findByRole('menuitem', { name }))
}

describe('ShowDetail — Ignore Missing Eps toggle', () => {
  test('shows "Ignore Missing Eps" for a tracked show and toggles it off on click', async () => {
    mockShowDetail(baseShow({ track_missing_episodes: true }))
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    const button = await screen.findByRole('button', { name: 'Ignore Missing Eps' })
    fireEvent.click(button)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Track Missing Eps' })).toBeInTheDocument()
    })

    const patchCall = vi
      .mocked(fetch)
      .mock.calls.find(([, init]) => init?.method === 'PATCH')
    expect(patchCall).toBeDefined()
    expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ track_missing_episodes: false })
  })

  test('shows "Track Missing Eps" for an ignored show', async () => {
    mockShowDetail(baseShow({ track_missing_episodes: false }))
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    expect(await screen.findByRole('button', { name: 'Track Missing Eps' })).toBeInTheDocument()
  })
})

describe('ShowDetail — Change Images modal', () => {
  test('clicking "Change Images" opens the image picker modal', async () => {
    mockShowDetail(baseShow())
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    await chooseFromMoreMenu('Change Images')

    expect(await screen.findByText('Change Images — Test Show')).toBeInTheDocument()
  })
})

describe('ShowDetail — files fetch', () => {
  test('requests show_ignored=true so ignored files linked to the show still appear', async () => {
    // useFilesByShow only fires for movie-type shows (see isMovie in ShowDetail.tsx).
    mockShowDetail(baseShow({ content_type: 'movie', media_type: 'movie' }))
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    await waitFor(() => {
      const call = vi.mocked(fetch).mock.calls.find(([input]) => String(input).includes('/files?show_id=1'))
      expect(call).toBeDefined()
      expect(String(call?.[0])).toContain('show_ignored=true')
    })
  })
})

describe('ShowDetail — Movie file actions', () => {
  test('renders Fix Match button for a matched movie file', async () => {
    mockShowDetail(baseShow({ content_type: 'movie', media_type: 'movie' }), {
      files: [{ id: 5, original_filename: 'Movie.2020.mkv', status: 'matched', show_id: 1 }],
    })
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    const filenameEl = await screen.findByText('Movie.2020.mkv')
    const row = within(filenameEl.parentElement as HTMLElement)
    expect(row.getByRole('button', { name: 'Fix Match' })).toBeInTheDocument()
  })

  test('does not render Fix Match button while the movie file is still downloading', async () => {
    mockShowDetail(baseShow({ content_type: 'movie', media_type: 'movie' }), {
      files: [{ id: 5, original_filename: 'Movie.2020.mkv', status: 'downloading', show_id: 1 }],
    })
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    const filenameEl = await screen.findByText('Movie.2020.mkv')
    const row = within(filenameEl.parentElement as HTMLElement)
    expect(row.queryByRole('button', { name: 'Fix Match' })).not.toBeInTheDocument()
  })

  test('clicking Fix Match opens the movie file-path modal, not the show-rematch modal', async () => {
    mockShowDetail(baseShow({ content_type: 'movie', media_type: 'movie' }), {
      files: [{ id: 5, original_filename: 'Movie.2020.mkv', status: 'matched', show_id: 1 }],
    })
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    const filenameEl = await screen.findByText('Movie.2020.mkv')
    const row = within(filenameEl.parentElement as HTMLElement)
    fireEvent.click(row.getByRole('button', { name: 'Fix Match' }))

    // The replace-mode ScanLocalMovieFileModal — lets the user type a path
    // directly or pick from a scan of the local path — not RematchModal
    // (which reassigns the file to a different show/movie entirely).
    expect(await screen.findByText('Fix movie file')).toBeInTheDocument()
    expect(screen.getByLabelText('Enter the file path directly')).toBeInTheDocument()
    expect(screen.queryByText('Fix show assignment')).not.toBeInTheDocument()

    const scanCall = vi
      .mocked(fetch)
      .mock.calls.find(([input]) => String(input).includes('/scan-local-movie-file'))
    expect(String(scanCall?.[0])).toContain('replace=true')
  })
})

describe('ShowDetail — banner style (Settings → Appearance)', () => {
  afterEach(() => {
    try {
      localStorage.clear()
    } catch {
      /* jsdom localStorage always available; guard anyway */
    }
  })

  test('renders the w1280 backdrop for the default (hero) style', async () => {
    mockShowDetail(baseShow({ backdrop_path: '/bd.jpg' }))
    const { container } = render(createElement(ShowDetail), { wrapper: makeWrapper() })

    await screen.findByRole('heading', { name: 'Test Show' })
    expect(container.querySelector('img[src="/api/images/w1280/bd.jpg"]')).toBeInTheDocument()
  })

  test('style "none" renders the plain header with no backdrop', async () => {
    localStorage.setItem('jidou.bannerStyle', JSON.stringify('none'))
    mockShowDetail(baseShow({ backdrop_path: '/bd.jpg' }))
    const { container } = render(createElement(ShowDetail), { wrapper: makeWrapper() })

    await screen.findByRole('heading', { name: 'Test Show' })
    expect(container.querySelector('img[src*="/api/images/w1280/"]')).not.toBeInTheDocument()
  })

  test('a show with no backdrop_path never renders a banner, whatever the style', async () => {
    localStorage.setItem('jidou.bannerStyle', JSON.stringify('hero'))
    mockShowDetail(baseShow({ backdrop_path: null }))
    const { container } = render(createElement(ShowDetail), { wrapper: makeWrapper() })

    await screen.findByRole('heading', { name: 'Test Show' })
    expect(container.querySelector('img[src*="/api/images/w1280/"]')).not.toBeInTheDocument()
  })
})

describe('ShowDetail — Queue position select (watchlisted show)', () => {
  test('the editing <select> pairs an explicit background with an explicit text colour in both themes', async () => {
    // Regression: the queue-position <select> had no explicit bg/text classes
    // at all, so it inherited whatever ambient colour surrounded it. That
    // rendered invisible (background-on-background) text — black-on-black in
    // light mode when overlaid on a dark banner, white-on-white in the native
    // dropdown popup in dark mode.
    mockShowDetail(baseShow({ backdrop_path: null }), {
      watchlist: [
        { id: 9, show_id: 1, status: 'planned', position: 0 },
        { id: 10, show_id: 2, status: 'planned', position: 1 },
      ],
    })
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    const queueButton = await screen.findByRole('button', { name: 'Queue #1' })
    fireEvent.click(queueButton)

    const select = screen.getByRole('combobox')
    expect(select.className).toMatch(/\bbg-white\b/)
    expect(select.className).toMatch(/\btext-gray-900\b/)
    expect(select.className).toMatch(/\bdark:bg-gray-800\b/)
    expect(select.className).toMatch(/\bdark:text-gray-100\b/)

    const options = select.querySelectorAll('option')
    expect(options.length).toBe(2)
    options.forEach((opt) => {
      expect(opt.className).toMatch(/\bbg-white\b/)
      expect(opt.className).toMatch(/\bdark:bg-gray-800\b/)
    })
  })
})

function makeEpisode(overrides: Record<string, unknown>) {
  return {
    id: 1,
    show_id: 1,
    season_number: 1,
    episode_number: 1,
    name: 'Pilot',
    overview: null,
    air_date: null,
    file_tracked: false,
    tracked_source: null,
    watched: false,
    backing_files: [],
    ...overrides,
  }
}

describe('ShowDetail — modal state machine', () => {
  test('opening a second modal replaces the first', async () => {
    mockShowDetail(baseShow())
    const base = vi.mocked(fetch).getMockImplementation()!
    // Episode A is untracked ("Match File"); episode B is an imported, tracked
    // episode with no backing file ("Fix Eps" -> Assign Import, no begin-rematch call).
    const episodes = [
      makeEpisode({ id: 11, episode_number: 1, name: 'Episode A' }),
      makeEpisode({
        id: 12,
        episode_number: 2,
        name: 'Episode B',
        file_tracked: true,
        tracked_source: 'import',
      }),
    ]
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (String(input).endsWith('/shows/1/episodes')) return mockResponse(episodes)
      return base(input, init)
    })
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    fireEvent.click(await screen.findByRole('button', { name: 'Match File' }))
    expect(await screen.findByText(/Match file — S01E01/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }))
    await waitFor(() => {
      expect(screen.queryByText(/Match file — S01E01/)).not.toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Fix Eps' }))
    expect(await screen.findByText(/Assign imported file — S01E02/)).toBeInTheDocument()
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
    expect(screen.queryByText(/Match file — S01E01/)).not.toBeInTheDocument()
  })

  test('fires the page-level queries in the original order on mount', async () => {
    mockShowDetail(baseShow())
    render(createElement(ShowDetail), { wrapper: makeWrapper() })
    await screen.findByRole('button', { name: /^Action/ })

    const urls = vi.mocked(fetch).mock.calls.map(([input]) => String(input))
    const firstIndex = (needle: string) => urls.findIndex((u) => u.includes(needle))
    const order = [
      firstIndex('/shows/1'),
      firstIndex('/config'),
      firstIndex('/shows/1/episodes'),
      firstIndex('/rss/subscriptions'),
      firstIndex('/rss/feeds'),
      firstIndex('/watchlist'),
    ]
    expect(order.every((i) => i >= 0)).toBe(true)
    expect([...order].sort((a, b) => a - b)).toEqual(order)
  })

  test('a failed content-type save keeps the modal open with the error, and closing clears it', async () => {
    mockShowDetail(baseShow())
    const base = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (init?.method === 'PATCH') return mockResponse({ detail: 'nope' }, 500)
      return base(input, init)
    })
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    await chooseFromMoreMenu('Set Type')
    fireEvent.click(await screen.findByRole('button', { name: 'Save' }))
    expect(await screen.findByText('nope')).toBeInTheDocument()
    expect(screen.getByText('Set Content Type')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => {
      expect(screen.queryByText('Set Content Type')).not.toBeInTheDocument()
    })
    await chooseFromMoreMenu('Set Type')
    expect(await screen.findByText('Set Content Type')).toBeInTheDocument()
    expect(screen.queryByText('nope')).not.toBeInTheDocument()
  })

  describe('late async modal requests', () => {
    // Holds one matching request open until the test resolves it.
    function deferRequest(matches: (url: string, init?: RequestInit) => boolean, body: unknown) {
      let resolve!: () => void
      const gate = new Promise<void>((r) => {
        resolve = r
      })
      const base = vi.mocked(fetch).getMockImplementation()!
      vi.mocked(fetch).mockImplementation(async (input, init) => {
        if (matches(String(input), init)) {
          await gate
          return mockResponse(body)
        }
        return base(input, init)
      })
      return resolve
    }

    function withEpisodes(episodes: unknown[]) {
      const base = vi.mocked(fetch).getMockImplementation()!
      vi.mocked(fetch).mockImplementation(async (input, init) =>
        String(input).endsWith('/shows/1/episodes') ? mockResponse(episodes) : base(input, init),
      )
    }

    const REMATCH_FILE = { id: 3, show_id: 1, filename: 'a.mkv', file_path: '/x/a.mkv' }
    const backedEpisode = () =>
      makeEpisode({
        id: 11,
        name: 'Episode A',
        file_tracked: true,
        tracked_source: 'download',
        backing_files: [{ id: 3, filename: 'a.mkv' }],
      })

    async function openAliasesAndType(text: string) {
      await chooseFromMoreMenu('Manage Aliases')
      const input = await screen.findByPlaceholderText('Add alias…')
      fireEvent.change(input, { target: { value: text } })
      return input
    }

    test('a late RSS stub does not replace an open modal or its typed input', async () => {
      mockShowDetail(baseShow())
      const release = deferRequest((u, i) => u.includes('/rss-stub') && i?.method === 'POST', {
        id: 5, show_id: 1, feed_id: null,
      })
      render(createElement(ShowDetail), { wrapper: makeWrapper() })

      fireEvent.click(await screen.findByRole('button', { name: 'Add RSS' }))
      const input = await openAliasesAndType('typed alias')
      release()
      await waitFor(() => expect(screen.getByRole('button', { name: 'Add RSS' })).toBeEnabled())

      expect(screen.getByPlaceholderText('Add alias…')).toBe(input)
      expect(input).toHaveValue('typed alias')
      expect(screen.getAllByRole('dialog')).toHaveLength(1)
    })

    test('a late begin-rematch does not replace an open modal', async () => {
      mockShowDetail(baseShow())
      withEpisodes([backedEpisode()])
      const release = deferRequest((u) => u.includes('/begin-rematch'), REMATCH_FILE)
      render(createElement(ShowDetail), { wrapper: makeWrapper() })

      const fixMatch = await screen.findAllByRole('button', { name: 'Fix Match' })
      fireEvent.click(fixMatch[fixMatch.length - 1])
      const input = await openAliasesAndType('typed alias')
      release()
      await waitFor(() => {
        expect(vi.mocked(fetch).mock.calls.some(([u]) => String(u).includes('/begin-rematch'))).toBe(true)
      })
      await new Promise((r) => setTimeout(r, 50))

      expect(input).toHaveValue('typed alias')
      expect(screen.getAllByRole('dialog')).toHaveLength(1)
      expect(screen.queryByText('Fix show assignment')).not.toBeInTheDocument()
    })

    test('a late begin-rematch for Fix Eps does not replace an open modal', async () => {
      mockShowDetail(baseShow())
      withEpisodes([backedEpisode()])
      const release = deferRequest((u) => u.includes('/begin-rematch'), REMATCH_FILE)
      render(createElement(ShowDetail), { wrapper: makeWrapper() })

      fireEvent.click(await screen.findByRole('button', { name: 'Fix Eps' }))
      const input = await openAliasesAndType('typed alias')
      release()
      await waitFor(() => {
        expect(vi.mocked(fetch).mock.calls.some(([u]) => String(u).includes('/begin-rematch'))).toBe(true)
      })
      await new Promise((r) => setTimeout(r, 50))

      expect(input).toHaveValue('typed alias')
      expect(screen.queryByText('Fix episode assignment')).not.toBeInTheDocument()
      expect(screen.getAllByRole('dialog')).toHaveLength(1)
    })

    test('a request resolving with no modal open still opens its modal', async () => {
      mockShowDetail(baseShow())
      withEpisodes([backedEpisode()])
      const release = deferRequest((u) => u.includes('/begin-rematch'), REMATCH_FILE)
      render(createElement(ShowDetail), { wrapper: makeWrapper() })

      const fixMatch = await screen.findAllByRole('button', { name: 'Fix Match' })
      fireEvent.click(fixMatch[fixMatch.length - 1])
      release()
      expect(await screen.findByText('Fix show assignment')).toBeInTheDocument()
    })
  })
})

describe('ShowDetail — Action menu and Refresh Metadata', () => {
  test('keeps Remove, RSS and Refresh Metadata visible and folds the rest into a collapsed Action menu', async () => {
    mockShowDetail(baseShow())
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    expect(await screen.findByRole('button', { name: 'Remove Show' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add RSS' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh Metadata' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Action/ })).toHaveAttribute('aria-expanded', 'false')
    for (const name of ['Fix Match', 'Set Type', 'Manage Aliases', 'Change Images']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
      expect(screen.queryByRole('menuitem', { name })).not.toBeInTheDocument()
    }
  })

  test('the Action menu lists the four less common actions in order', async () => {
    mockShowDetail(baseShow())
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    fireEvent.click(await screen.findByRole('button', { name: /^Action/ }))

    const items = within(await screen.findByRole('menu')).getAllByRole('menuitem')
    expect(items.map((i) => i.textContent)).toEqual([
      'Fix Match',
      'Set Type',
      'Manage Aliases',
      'Change Images',
    ])
  })

  test('the Set Type item shows the current content type', async () => {
    mockShowDetail(baseShow({ content_type: 'anime' }))
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    fireEvent.click(await screen.findByRole('button', { name: /^Action/ }))

    expect(await screen.findByRole('menuitem', { name: 'Type: anime' })).toBeInTheDocument()
  })

  test.each([
    ['Fix Match', 'Change TMDB Match'],
    ['Set Type', 'Set Content Type'],
    ['Change Images', 'Change Images — Test Show'],
  ])('choosing %s opens its modal', async (item, heading) => {
    mockShowDetail(baseShow())
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    await chooseFromMoreMenu(item)

    expect(await screen.findByText(heading)).toBeInTheDocument()
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  test('Refresh Metadata POSTs for this show', async () => {
    mockShowDetail(baseShow())
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    fireEvent.click(await screen.findByRole('button', { name: 'Refresh Metadata' }))

    await waitFor(() => {
      const call = vi
        .mocked(fetch)
        .mock.calls.find(
          ([input, init]) =>
            String(input).includes('/shows/1/refresh-metadata') && init?.method === 'POST',
        )
      expect(call).toBeDefined()
    })
  })

  test('Refresh Metadata is disabled and relabelled while the request is in flight', async () => {
    mockShowDetail(baseShow())
    let release!: () => void
    const gate = new Promise<void>((r) => {
      release = r
    })
    const base = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (String(input).includes('/refresh-metadata')) {
        await gate
        return mockResponse(baseShow())
      }
      return base(input, init)
    })
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    fireEvent.click(await screen.findByRole('button', { name: 'Refresh Metadata' }))

    const pending = await screen.findByRole('button', { name: 'Refreshing…' })
    expect(pending).toBeDisabled()
    release()
    expect(await screen.findByRole('button', { name: 'Refresh Metadata' })).toBeEnabled()
  })

  test('a failed refresh shows the error next to the button', async () => {
    mockShowDetail(baseShow())
    const base = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation(async (input, init) =>
      String(input).includes('/refresh-metadata')
        ? mockResponse({ detail: 'Failed to refresh show metadata from TMDB' }, 502)
        : base(input, init),
    )
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    fireEvent.click(await screen.findByRole('button', { name: 'Refresh Metadata' }))

    expect(await screen.findByText('Failed to refresh show metadata from TMDB')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh Metadata' })).toBeEnabled()
  })
})
