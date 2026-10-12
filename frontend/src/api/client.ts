const BASE = '/api'
const API_KEY = import.meta.env.VITE_API_KEY as string | undefined

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function apiHeaders(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = API_KEY ? { 'X-API-Key': API_KEY } : {}
  return extra ? { ...h, ...extra } : h
}

/**
 * Single error path for every request helper: turns a non-2xx response into an
 * ApiError carrying the status and the backend's `detail` (or statusText when
 * the body is not JSON), so the four call sites cannot drift apart.
 */
async function ensureOk(res: Response): Promise<Response> {
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, detail.detail ?? res.statusText)
  }
  return res
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await ensureOk(
    await fetch(`${BASE}${path}`, {
      method,
      headers: apiHeaders(body !== undefined ? { 'Content-Type': 'application/json' } : undefined),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  )
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

async function requestForm<T>(path: string, form: FormData): Promise<T> {
  const res = await ensureOk(
    await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: apiHeaders(),
      body: form,
    }),
  )
  return res.json() as Promise<T>
}

async function requestWithTotal<T>(path: string): Promise<{ data: T; total: number }> {
  const res = await ensureOk(
    await fetch(`${BASE}${path}`, { method: 'GET', headers: apiHeaders() }),
  )
  const total = parseInt(res.headers.get('X-Total-Count') ?? '0', 10)
  const data = (await res.json()) as T
  return { data, total }
}

async function downloadBlob(path: string): Promise<{ blob: Blob; filename: string }> {
  const res = await ensureOk(
    await fetch(`${BASE}${path}`, { method: 'GET', headers: apiHeaders() }),
  )
  const cd = res.headers.get('Content-Disposition') ?? ''
  const match = cd.match(/filename="([^"]+)"/)
  const filename = match ? match[1] : 'download'
  const blob = await res.blob()
  return { blob, filename }
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  getWithTotal: <T>(path: string) => requestWithTotal<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  delete: <T>(path: string, body?: unknown) => request<T>('DELETE', path, body),
  postForm: <T>(path: string, form: FormData) => requestForm<T>(path, form),
  downloadBlob: (path: string) => downloadBlob(path),
}

export { ApiError }
