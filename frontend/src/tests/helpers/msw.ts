import { setupServer } from 'msw/node'
import { http, HttpResponse, type RequestHandler } from 'msw'
import { afterAll, afterEach, beforeAll } from 'vitest'

/**
 * Starts an MSW server for the calling test file and records every request.
 *
 * `handlers` are tried first; any other `/api/*` GET answers `[]` so pages
 * and hooks with incidental queries still settle. Each recorded entry is
 * `"METHOD /path?query"`, which lets a test assert both what was fetched and
 * what was not (e.g. that no `limit=10000` list was requested).
 */
export function startMswServer(...handlers: RequestHandler[]) {
  const requests: string[] = []
  const server = setupServer(
    ...handlers,
    http.get('/api/*', () => HttpResponse.json([])),
  )

  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url)
    requests.push(`${request.method} ${url.pathname}${url.search}`)
  })

  beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
  afterEach(() => {
    server.resetHandlers()
    requests.length = 0
  })
  afterAll(() => server.close())

  return { server, requests }
}
