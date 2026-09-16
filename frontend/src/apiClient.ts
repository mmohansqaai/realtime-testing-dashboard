export const DEFAULT_PROD_API = 'https://realtime-testing-dashboard.onrender.com'
export const FETCH_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 90000)

export function getApiBaseUrl(): string {
  if (import.meta.env.DEV) {
    return (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
  }
  return DEFAULT_PROD_API
}

export function apiUrl(path: string): string {
  const base = getApiBaseUrl()
  if (!base) return path
  return `${base}${path}`
}

async function fetchOnce<T>(url: string, init: RequestInit, timeoutMs: number): Promise<T> {
  const sep = url.includes('?') ? '&' : '?'
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(`${url}${sep}_=${Date.now()}`, {
      ...init,
      cache: 'no-store',
      signal: controller.signal,
    })
    if (!response.ok) {
      const text = await response.text()
      throw new Error(`${response.status} ${response.statusText}: ${text || url}`)
    }
    const ct = response.headers.get('content-type') || ''
    if (!ct.includes('application/json')) {
      throw new Error(`Expected JSON from API, got ${ct || 'unknown type'} from ${url}`)
    }
    return (await response.json()) as T
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    if ((e instanceof Error && e.name === 'AbortError') || msg.includes('aborted')) {
      throw new Error(
        `Timed out after ${timeoutMs}ms while loading ${url}. Open ${DEFAULT_PROD_API}/api/health then Retry.`,
      )
    }
    throw new Error(`Network/API error while loading ${url}: ${msg}`)
  } finally {
    window.clearTimeout(timeoutId)
  }
}

export async function fetchJson<T>(path: string, timeoutMs = FETCH_TIMEOUT_MS): Promise<T> {
  return fetchOnce<T>(apiUrl(path), { headers: { Accept: 'application/json' } }, timeoutMs)
}

export async function fetchJsonPost<T>(path: string, body: unknown, timeoutMs = FETCH_TIMEOUT_MS): Promise<T> {
  return fetchOnce<T>(
    apiUrl(path),
    {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    timeoutMs,
  )
}
