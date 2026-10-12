/**
 * Serialises the rendered document one element per line so a characterization
 * snapshot diffs readably when markup, element order or wrappers drift.
 */
export function domSnapshot(root: ParentNode = document.body): string {
  const html = (root as HTMLElement).innerHTML ?? ''
  return html.replace(/></g, '>\n<')
}

export const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

/** Minimal fetch Response stand-in used by the characterization suites. */
export function mockResponse(body: unknown = null, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    headers: { get: () => null } as unknown as Headers,
    json: async () => body,
  } as unknown as Response
}
