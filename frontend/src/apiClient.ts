const FETCH_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 60000)

export function getApiBaseUrl(): string {
  const trimmed = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
  if (import.meta.env.MODE === 'development') {
    return trimmed
  }
  // Production: same-origin /api via Vercel serverless proxy (never cross-origin to Render).
  return ''
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
    return (await response.json()) as T
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    if ((e instanceof Error && e.name === 'AbortError') || msg.includes('aborted')) {
      throw new Error(`Timed out after ${timeoutMs}ms while loading ${url}.`)
    }
    throw new Error(`Network/API error while loading ${url}: ${msg}`)
  } finally {
    window.clearTimeout(timeoutId)
  }
}

export async function fetchJson<T>(path: string): Promise<T> {
  return fetchOnce<T>(apiUrl(path), { headers: { Accept: 'application/json' } }, FETCH_TIMEOUT_MS)
}

export async function fetchJsonPost<T>(path: string, body: unknown): Promise<T> {
  return fetchOnce<T>(
    apiUrl(path),
    {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    FETCH_TIMEOUT_MS,
  )
}
