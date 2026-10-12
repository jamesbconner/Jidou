import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '@/api/client'

/** Stubs the global fetch to resolve with the given Response. */
function stubFetch(res: Response): void {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res))
}

const jsonRes = (status: number, body: unknown, statusText = ''): Response =>
  new Response(JSON.stringify(body), {
    status,
    statusText,
    headers: { 'Content-Type': 'application/json' },
  })

const textRes = (status: number, statusText: string): Response =>
  new Response('<html>boom</html>', { status, statusText })

const calls: Array<[string, () => Promise<unknown>]> = [
  ['get', () => api.get('/x')],
  ['postForm', () => api.postForm('/x', new FormData())],
  ['getWithTotal', () => api.getWithTotal('/x')],
  ['downloadBlob', () => api.downloadBlob('/x')],
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api client error handling', () => {
  describe.each(calls)('%s', (_name, call) => {
    it('throws ApiError with the parsed detail', async () => {
      stubFetch(jsonRes(404, { detail: 'nope' }))
      const err = await call().catch((e: unknown) => e)
      expect(err).toBeInstanceOf(ApiError)
      expect(err).toMatchObject({ status: 404, message: 'nope' })
    })

    it('falls back to statusText when the body is not JSON', async () => {
      stubFetch(textRes(500, 'Server Error'))
      const err = await call().catch((e: unknown) => e)
      expect(err).toBeInstanceOf(ApiError)
      expect(err).toMatchObject({ status: 500, message: 'Server Error' })
    })
  })
})

describe('api client success paths', () => {
  it('getWithTotal reads X-Total-Count', async () => {
    stubFetch(
      new Response(JSON.stringify([1, 2]), {
        status: 200,
        headers: { 'X-Total-Count': '42' },
      }),
    )
    await expect(api.getWithTotal<number[]>('/x')).resolves.toEqual({
      data: [1, 2],
      total: 42,
    })
  })

  it('getWithTotal defaults the total to 0 without the header', async () => {
    stubFetch(jsonRes(200, []))
    await expect(api.getWithTotal('/x')).resolves.toEqual({
      data: [],
      total: 0,
    })
  })

  it('downloadBlob parses the filename from Content-Disposition', async () => {
    stubFetch(
      new Response('abc', {
        status: 200,
        headers: { 'Content-Disposition': 'attachment; filename="report.csv"' },
      }),
    )
    const { filename, blob } = await api.downloadBlob('/x')
    expect(filename).toBe('report.csv')
    expect(blob.size).toBe(3)
  })

  it('downloadBlob falls back to "download"', async () => {
    stubFetch(new Response('abc', { status: 200 }))
    expect((await api.downloadBlob('/x')).filename).toBe('download')
  })

  it('delete resolves to undefined on 204', async () => {
    stubFetch(new Response(null, { status: 204 }))
    await expect(api.delete('/x')).resolves.toBeUndefined()
  })
})
