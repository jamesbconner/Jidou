import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { AddShowFromFeedPane, matchSummary } from '@/components/AddShowFromFeedPane'
import type {
  FeedAddShowResult,
  FeedEntryGroupRead,
  RegexMatchReportRead,
  RssFeedRead,
} from '@/types/api'

// See Watchlist.test.tsx for why fetch is a plain assignment rather than
// vi.spyOn, and why Response is duck-typed rather than constructed for real.
const originalFetch = globalThis.fetch

type Handler = { status?: number; body: unknown } | ((init?: RequestInit) => { status?: number; body: unknown })

let handlers: Record<string, Handler> = {}
let calls: { url: string; init?: RequestInit }[] = []

function respond(url: string, init?: RequestInit): Response {
  calls.push({ url, init })
  // Most specific paths first: '/shows/tmdb/search' and '/shows/search' both
  // contain '/shows', and the library index list is '/shows?...'.
  const keys = Object.keys(handlers).sort((a, b) => b.length - a.length)
  const key = keys.find((k) => url.includes(k))
  const h = key ? handlers[key] : { body: [] }
  const { status = 200, body } = typeof h === 'function' ? h(init) : h
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => body,
  } as Response
}

beforeEach(() => {
  calls = []
  handlers = {
    '/shows?': { body: [] },
    '/shows/search': { body: [] },
    '/shows/tmdb/search': { body: { results: [], total_results: 0, total_pages: 1, page: 1 } },
  }
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
    respond(String(input), init),
  ) as typeof fetch
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

const feed = { id: 7, name: 'Example Tracker', url: 'https://t.example/rss', active: true } as RssFeedRead

function group(overrides: Partial<FeedEntryGroupRead> = {}): FeedEntryGroupRead {
  return {
    parsed_name: 'Brand New Show',
    entry_count: 3,
    season_min: 1,
    season_max: 1,
    episode_min: 5,
    episode_max: 6,
    sample_titles: ['[G] Brand New Show - 05 (1080p).mkv'],
    library_show: null,
    existing_subscription_id: null,
    ...overrides,
  }
}

const report: RegexMatchReportRead = {
  matched_titles: ['[G] Brand New Show - 05 (1080p).mkv', '[G] Brand New Show - 06 (1080p).mkv'],
  unmatched_titles: ['[G] Brand New Show - 06 (720p).mkv'],
  total: 3,
}

const suggestion = {
  regex_include: 'Brand.New.Show.*1080p',
  regex_exclude: 'FRENCH',
  model: 'm',
  cached: false,
  match: report,
}

const addResult: FeedAddShowResult = {
  show: { id: 42, title: 'Brand New Show', status: null, poster_path: null },
  show_created: false,
  subscription: null,
  subscription_created: true,
  adopted_stub: false,
  alias_added: true,
  dry_run: false,
}

function bodyOf(urlPart: string): Record<string, unknown> {
  const call = calls.find((c) => c.url.includes(urlPart))
  expect(call, `no request to ${urlPart}`).toBeDefined()
  return JSON.parse(call!.init!.body as string)
}

function renderPane(g: FeedEntryGroupRead = group(), onDone?: () => void) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AddShowFromFeedPane feed={feed} group={g} onDone={onDone} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const libraryGroup = () =>
  group({ library_show: { id: 42, title: 'Brand New Show', status: null, poster_path: null } })

describe('matchSummary', () => {
  test('empty include explains YaRSS2 selects nothing', () => {
    expect(matchSummary(report, true)).toMatch(/will not select any release/)
  })
  test('counts matched over total', () => {
    expect(matchSummary(report, false)).toBe('2 of 3 current titles selected')
  })
  test('singular title', () => {
    expect(matchSummary({ matched_titles: ['a'], unmatched_titles: [], total: 1 }, false)).toBe(
      '1 of 1 current title selected',
    )
  })
  test('before the first report arrives', () => {
    expect(matchSummary(null, false)).toMatch(/Checking/)
  })
})

describe('AddShowFromFeedPane', () => {
  test('a library show is preselected and the filter is suggested from real titles', async () => {
    handlers['/suggest-regex'] = { body: suggestion }

    renderPane(libraryGroup())

    expect(screen.getByText('Brand New Show', { selector: 'strong' })).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByLabelText('Include regex')).toHaveValue('Brand.New.Show.*1080p'),
    )
    expect(screen.getByLabelText('Exclude regex')).toHaveValue('FRENCH')
    expect(screen.getByText('2 of 3 current titles selected')).toBeInTheDocument()
    expect(bodyOf('/suggest-regex')).toEqual({
      parsed_name: 'Brand New Show',
      show_title: 'Brand New Show',
      previous: [],
    })
    // It suggests once on its own, not on every render.
    expect(calls.filter((c) => c.url.includes('/suggest-regex'))).toHaveLength(1)
  })

  test('submits show_id with the edited filter and shows the outcome', async () => {
    handlers['/suggest-regex'] = { body: suggestion }
    handlers['/add-show'] = { body: addResult }
    const onDone = vi.fn()
    renderPane(libraryGroup(), onDone)
    await waitFor(() => expect(screen.getByLabelText('Include regex')).toHaveValue(suggestion.regex_include))

    fireEvent.change(screen.getByLabelText('Subscription name'), { target: { value: 'My Sub' } })
    fireEvent.click(screen.getByLabelText(/Enable now/))
    fireEvent.click(screen.getByRole('button', { name: 'Add show + subscription' }))

    expect(await screen.findByRole('status')).toHaveTextContent(/Using “Brand New Show” from your library/)
    expect(screen.getByRole('status')).toHaveTextContent(/created its subscription/)
    expect(screen.getByRole('status')).toHaveTextContent(/included the next time you publish/)
    expect(screen.getByRole('status')).toHaveTextContent(/added as an alias/)
    expect(screen.getByRole('link', { name: 'Open show' })).toHaveAttribute('href', '/shows/42')
    expect(bodyOf('/add-show')).toEqual({
      parsed_name: 'Brand New Show',
      show_id: 42,
      name: 'My Sub',
      regex_include: 'Brand.New.Show.*1080p',
      regex_exclude: 'FRENCH',
      regex_include_ignorecase: true,
      regex_exclude_ignorecase: true,
      enabled: true,
    })
  })

  test('a TMDB pick sends a show payload, not show_id, and warns it will be added', async () => {
    handlers['/suggest-regex'] = { body: suggestion }
    handlers['/add-show'] = { body: { ...addResult, show_created: true } }
    handlers['/shows/tmdb/search'] = {
      body: {
        results: [
          {
            id: 555,
            name: 'Brand New Show',
            media_type: 'tv',
            first_air_date: '2024-03-01',
            overview: '',
            poster_path: null,
            backdrop_path: null,
            vote_average: 7,
            vote_count: 1,
            original_language: 'en',
          },
        ],
        total_results: 1,
        total_pages: 1,
        page: 1,
      },
    }
    renderPane(group())

    const option = await screen.findByRole('option', { name: /Brand New Show.*TMDB · TV · 2024/ })
    fireEvent.click(option)

    expect(await screen.findByText(/will be added to your library/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('Include regex')).toHaveValue(suggestion.regex_include))
    fireEvent.click(screen.getByRole('button', { name: 'Add show + subscription' }))

    expect(await screen.findByRole('status')).toHaveTextContent(/Added “Brand New Show” to your library/)
    const sent = bodyOf('/add-show')
    expect(sent.show_id).toBeUndefined()
    expect(sent.show).toMatchObject({ tmdb_id: 555, title: 'Brand New Show', media_type: 'tv' })
    expect(bodyOf('/suggest-regex').show_title).toBe('Brand New Show')
  })

  test('a TMDB result already in the library is offered as the library show', async () => {
    handlers['/shows?'] = {
      body: [{ id: 9, tmdb_id: 555, media_type: 'tv', title: 'Brand New Show (Library)' }],
    }
    handlers['/shows/tmdb/search'] = {
      body: {
        results: [
          { id: 555, name: 'Brand New Show', media_type: 'tv', overview: '', poster_path: null,
            backdrop_path: null, vote_average: 1, vote_count: 1, original_language: 'en' },
        ],
        total_results: 1, total_pages: 1, page: 1,
      },
    }
    renderPane(group())

    const option = await screen.findByRole('option', { name: /Brand New Show \(Library\).*In your library/ })
    expect(option).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /TMDB/ })).not.toBeInTheDocument()
  })

  test('hand edits are previewed against the feed with the group key', async () => {
    handlers['/suggest-regex'] = { body: suggestion }
    handlers['/test-regex'] = {
      body: { matched_titles: ['[G] Brand New Show - 05 (1080p).mkv'], unmatched_titles: [], total: 1 },
    }
    renderPane(libraryGroup())
    await waitFor(() => expect(screen.getByLabelText('Include regex')).toHaveValue(suggestion.regex_include))

    fireEvent.change(screen.getByLabelText('Include regex'), { target: { value: 'Brand.*05' } })

    await waitFor(() => expect(screen.getByText('1 of 1 current title selected')).toBeInTheDocument(), {
      timeout: 2000,
    })
    const testCalls = calls.filter((c) => c.url.includes('/test-regex'))
    const testCall = testCalls[testCalls.length - 1]
    expect(JSON.parse(testCall.init!.body as string)).toMatchObject({
      parsed_name: 'Brand New Show',
      regex_include: 'Brand.*05',
      regex_exclude: 'FRENCH',
    })
  })

  test('an empty include shows the YaRSS2 caveat and does not call the preview', async () => {
    handlers['/suggest-regex'] = { status: 422, body: { detail: 'LLM provider is not configured' } }
    renderPane(libraryGroup())

    expect(await screen.findByRole('alert')).toHaveTextContent('LLM provider is not configured')
    expect(screen.getByText(/will not select any release/)).toBeInTheDocument()
    expect(calls.some((c) => c.url.includes('/test-regex'))).toBe(false)
  })

  test('when the LLM is unavailable the user can still add with a hand-written filter', async () => {
    handlers['/suggest-regex'] = { status: 422, body: { detail: 'LLM provider is not configured' } }
    handlers['/test-regex'] = { body: { matched_titles: [], unmatched_titles: [], total: 0 } }
    handlers['/add-show'] = { body: addResult }
    renderPane(libraryGroup())
    await screen.findByRole('alert')

    fireEvent.change(screen.getByLabelText('Include regex'), { target: { value: 'Brand.New' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add show + subscription' }))

    expect(await screen.findByRole('status')).toBeInTheDocument()
    expect(bodyOf('/add-show').regex_include).toBe('Brand.New')
  })

  test('re-suggest sends earlier suggestions so the model must differ', async () => {
    handlers['/suggest-regex'] = { body: suggestion }
    renderPane(libraryGroup())
    await waitFor(() => expect(screen.getByLabelText('Include regex')).toHaveValue(suggestion.regex_include))

    fireEvent.click(await screen.findByRole('button', { name: 'Re-suggest' }))

    await waitFor(() => expect(calls.filter((c) => c.url.includes('/suggest-regex'))).toHaveLength(2))
    const second = JSON.parse(
      calls.filter((c) => c.url.includes('/suggest-regex'))[1].init!.body as string,
    )
    expect(second.previous).toEqual(['Brand.New.Show.*1080p'])
  })

  test('shows the server error when adding fails and keeps the form', async () => {
    handlers['/suggest-regex'] = { body: suggestion }
    handlers['/add-show'] = { status: 404, body: { detail: 'Show not found' } }
    renderPane(libraryGroup())
    await waitFor(() => expect(screen.getByLabelText('Include regex')).toHaveValue(suggestion.regex_include))

    fireEvent.click(screen.getByRole('button', { name: 'Add show + subscription' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Show not found')
    expect(screen.getByLabelText('Include regex')).toBeInTheDocument()
  })

  test('reports an already-subscribed outcome without claiming it changed anything', async () => {
    handlers['/suggest-regex'] = { body: suggestion }
    handlers['/add-show'] = {
      body: { ...addResult, subscription_created: false, alias_added: false },
    }
    renderPane(libraryGroup())
    await waitFor(() => expect(screen.getByLabelText('Include regex')).toHaveValue(suggestion.regex_include))

    fireEvent.click(screen.getByRole('button', { name: 'Add show + subscription' }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/already subscribed to this feed/)
    expect(status).toHaveTextContent(/Nothing was changed/)
  })

  test('the submit button is disabled until a show is picked', () => {
    renderPane(group())

    expect(screen.getByRole('button', { name: 'Add show + subscription' })).toBeDisabled()
    expect(screen.queryByLabelText('Include regex')).not.toBeInTheDocument()
  })

  test('a movie and a TV result sharing a TMDB id are distinct options', async () => {
    const base = {
      overview: '',
      poster_path: null,
      backdrop_path: null,
      vote_average: 1,
      vote_count: 1,
      original_language: 'en',
    }
    handlers['/suggest-regex'] = { body: suggestion }
    handlers['/shows/tmdb/search'] = {
      body: {
        results: [
          { ...base, id: 555, name: 'Same Id Show', media_type: 'tv' },
          { ...base, id: 555, title: 'Same Id Movie', media_type: 'movie' },
        ],
        total_results: 2,
        total_pages: 1,
        page: 1,
      },
    }
    renderPane(group())

    const tv = await screen.findByRole('option', { name: /Same Id Show/ })
    const movie = await screen.findByRole('option', { name: /Same Id Movie/ })
    fireEvent.click(movie)

    expect(movie).toHaveAttribute('aria-selected', 'true')
    expect(tv).toHaveAttribute('aria-selected', 'false')
    fireEvent.click(tv)
    expect(tv).toHaveAttribute('aria-selected', 'true')
    expect(movie).toHaveAttribute('aria-selected', 'false')
  })

  test('onAdded is called once the add succeeds', async () => {
    handlers['/suggest-regex'] = { body: suggestion }
    handlers['/add-show'] = { body: addResult }
    const onAdded = vi.fn()
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <AddShowFromFeedPane feed={feed} group={libraryGroup()} onAdded={onAdded} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await waitFor(() =>
      expect(screen.getByLabelText('Include regex')).toHaveValue(suggestion.regex_include),
    )

    expect(onAdded).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Add show + subscription' }))

    await screen.findByRole('status')
    expect(onAdded).toHaveBeenCalledTimes(1)
  })
})
