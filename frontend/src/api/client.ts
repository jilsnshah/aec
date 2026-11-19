/** A small fetch wrapper: same-origin /api, the session cookie, JSON in and
 *  out, and one error type carrying the server's message. */

export const SIGNED_OUT = 'aec:signed-out'

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message)
  }
}

type Query = Record<string, string | number | boolean | null | undefined>

function messageFrom(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item: { loc?: unknown[]; msg?: string }) => {
        const field = item.loc?.filter((part) => part !== 'body').join(' › ')
        return field ? `${field}: ${item.msg}` : item.msg
      })
      .join('\n')
  }
  if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message)
  return status === 0 ? 'The server could not be reached.' : `Request failed (${status}).`
}

export async function request<T>(method: string, path: string, options: { query?: Query; body?: unknown } = {}): Promise<T> {
  const url = new URL(path, window.location.origin)
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value))
  }
  let response: Response
  try {
    response = await fetch(url.pathname + url.search, {
      method,
      credentials: 'include',
      headers: options.body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, 'The server could not be reached.')
  }
  if (response.status === 401 && !path.startsWith('/api/auth/login')) {
    window.dispatchEvent(new Event(SIGNED_OUT))
  }
  if (!response.ok) {
    let detail: unknown
    try {
      const body = await response.json()
      // Validation errors arrive as {detail}; business-rule errors as {code, message, details}.
      detail = body?.detail ?? body
    } catch {
      detail = undefined
    }
    throw new ApiError(response.status, messageFrom(detail, response.status), detail)
  }
  if (response.status === 204) return undefined as T
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const http = {
  get: <T>(path: string, query?: Query) => request<T>('GET', path, { query }),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, { body: body ?? {} }),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, { body }),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, { body }),
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
