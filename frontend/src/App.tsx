import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

type Summary = {
  totals: {
    runs: number
    cases: number
    pass_rate: number
    open_defects: number
  }
  status_counts: Record<string, number>
  environment_counts: Record<string, number>
  module_quality: Array<{
    module: string
    passed: number
    failed: number
    total: number
    pass_rate: number
  }>
  latest_runs: Array<{
    id: number
    suite_name: string
    environment: string
    build_version: string
    status: string
    started_at: string
    completed_at: string | null
    passed: number
    failed: number
    total: number
    html_report_url?: string | null
    has_html_report_inline?: boolean
    has_html_report_zip?: boolean
    html_report_index_path?: string | null
  }>
  generated_at: string
}

const pct = (value: number, total: number): number => {
  if (!total) return 0
  return Math.round((value / total) * 100)
}

/** Deployed Render API — must match the URL shown in Render (may include a suffix like `-abc1`). */
const DEFAULT_PROD_API = 'https://realtime-testing-dashboard-api-ld7t.onrender.com'
const FETCH_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 20000)
const RENDER_FALLBACK_TIMEOUT_MS = Number(import.meta.env.VITE_RENDER_FALLBACK_TIMEOUT_MS || 45000)
const ENABLE_WS =
  import.meta.env.MODE === 'development'
    ? true
    : String(import.meta.env.VITE_ENABLE_WS || '').toLowerCase() === '1'

/**
 * Empty base ⇒ relative `/api/...` ⇒ hits the deploy host (vercel.app), not Render.
 *
 * Do NOT use `import.meta.env.PROD`: Vite sets PROD only when `mode === 'production'`.
 * `vite build --mode staging` (and similar) leaves PROD false while still being a production
 * build — same bug as DEV true → empty `trimmed` → vercel.app/api/summary.
 *
 * Only `vite` dev server uses `MODE === 'development'` + empty base for the local proxy.
 */
function getApiBaseUrl(): string {
  const trimmed = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
  if (import.meta.env.MODE === 'development') {
    return trimmed
  }
  // Hard rule for deployed UI: always use same-origin /api via Vercel rewrite.
  // This avoids cross-origin CORS failures even if VITE_API_BASE_URL is set in Vercel.
  return ''
}

function getWsBaseUrl(): string {
  const trimmed = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
  if (import.meta.env.MODE === 'development') {
    return trimmed
  }
  if (typeof window !== 'undefined' && trimmed && trimmed === window.location.origin.replace(/\/$/, '')) {
    return DEFAULT_PROD_API
  }
  return trimmed || DEFAULT_PROD_API
}

const apiUrl = (path: string): string => {
  const base = getApiBaseUrl()
  if (!base) return path
  return `${base}${path}`
}

const renderApiUrl = (path: string): string => `${DEFAULT_PROD_API}${path}`

/** Primary URL for viewing a run's HTML report (ZIP bundle, single-file, or external link). */
function reportViewerUrl(run: {
  id: number
  html_report_url?: string | null
  has_html_report_inline?: boolean
  has_html_report_zip?: boolean
  html_report_index_path?: string | null
}): string | null {
  if (run.has_html_report_zip && run.html_report_index_path) {
    const path = run.html_report_index_path
      .split('/')
      .map((seg) => encodeURIComponent(seg))
      .join('/')
    return apiUrl(`/api/runs/${run.id}/report/${path}`)
  }
  if (run.has_html_report_inline) {
    return apiUrl(`/api/runs/${run.id}/html-report`)
  }
  const u = (run.html_report_url ?? '').trim()
  return u.length > 0 ? u : null
}

async function fetchJson<T>(path: string): Promise<T> {
  const primary = apiUrl(path)
  const shouldTryRenderFallback =
    import.meta.env.MODE !== 'development' && !primary.startsWith('http')
  const candidates: Array<{ url: string; timeoutMs: number }> = [{ url: primary, timeoutMs: FETCH_TIMEOUT_MS }]
  if (shouldTryRenderFallback) {
    candidates.push({ url: renderApiUrl(path), timeoutMs: RENDER_FALLBACK_TIMEOUT_MS })
  }

  let lastError = ''
  for (const candidate of candidates) {
    const url = candidate.url
    const sep = url.includes('?') ? '&' : '?'
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), candidate.timeoutMs)
    try {
      const response = await fetch(`${url}${sep}_=${Date.now()}`, {
        cache: 'no-store',
        signal: controller.signal,
        headers: {
          Accept: 'application/json',
        },
      })
      if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText} ${url}`)
      }
      const ct = response.headers.get('content-type') || ''
      if (!ct.includes('application/json')) {
        throw new Error(`Expected JSON from API, got ${ct || 'unknown type'} from ${url}`)
      }
      const data = (await response.json()) as T
      if (path.includes('summary') && data && typeof data === 'object') {
        const s = data as unknown as Summary
        if (!s.totals || typeof s.totals.runs !== 'number') {
          throw new Error(`Invalid /api/summary JSON from ${url}`)
        }
      }
      return data
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      if ((e instanceof Error && e.name === 'AbortError') || msg.includes('aborted')) {
        lastError = `Timed out after ${candidate.timeoutMs}ms while loading ${url}.`
      } else {
        lastError = `Network/API error while loading ${url}: ${msg}`
      }
    } finally {
      clearTimeout(timeoutId)
    }
  }

  throw new Error(
    `${lastError} Render may still be waking up; click Retry.`,
  )
}

const createDemoPayload = () => {
  const timestamp = Date.now()
  return {
    suite_name: `Checkout Regression ${timestamp.toString().slice(-4)}`,
    environment: ['QA', 'UAT', 'STAGING'][Math.floor(Math.random() * 3)],
    build_version: `v2.${Math.floor(Math.random() * 9)}.${Math.floor(Math.random() * 20)}`,
    test_cases: [
      { name: 'Login with MFA', module: 'Auth', status: 'RUNNING', duration_ms: 0 },
      { name: 'Create new order', module: 'Checkout', status: 'RUNNING', duration_ms: 0 },
      { name: 'Apply coupon', module: 'Pricing', status: 'RUNNING', duration_ms: 0 },
      { name: 'Card payment flow', module: 'Payments', status: 'RUNNING', duration_ms: 0 },
      { name: 'Order history sync', module: 'Orders', status: 'RUNNING', duration_ms: 0 },
    ],
  }
}

function App() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [wsError, setWsError] = useState<string | null>(null)
  const [connectionStatus, setConnectionStatus] = useState('Connecting...')
  const reconnectTimerRef = useRef<number | null>(null)
  const [dataSource, setDataSource] = useState<string>('unknown')
  const [selectedReportRunId, setSelectedReportRunId] = useState<number | null>(null)

  const loadSummary = useCallback(async (): Promise<boolean> => {
    try {
      const data = await fetchJson<Summary>('/api/summary')
      setSummary(data)
      setFetchError(null)
      return true
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setFetchError(msg)
      console.error('[dashboard] /api/summary failed', msg)
      return false
    }
  }, [])

  const loadConfig = useCallback(async () => {
    try {
      const data = await fetchJson<{ data_source?: string }>('/api/config')
      setDataSource(data.data_source ?? 'unknown')
    } catch {
      setDataSource('unknown')
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      // Render free tier can cold-start; backoff avoids a permanent "Loading..." state.
      const delays = [0, 1500, 3000, 6000, 12000]
      for (let i = 0; i < delays.length; i += 1) {
        if (cancelled) return
        if (delays[i] > 0) {
          await new Promise((resolve) => window.setTimeout(resolve, delays[i]))
          if (cancelled) return
        }
        const ok = await loadSummary()
        if (ok) return
      }
    }
    void run()
    void loadConfig()
    return () => {
      cancelled = true
    }
  }, [loadSummary, loadConfig])

  // If WebSocket cannot stay connected (common on free Render), still refresh summary periodically.
  useEffect(() => {
    const id = window.setInterval(() => {
      void loadSummary()
    }, 15000)
    return () => window.clearInterval(id)
  }, [loadSummary])

  useEffect(() => {
    if (!ENABLE_WS) {
      setConnectionStatus('Polling (WS disabled)')
      setWsError(null)
      return
    }
    let socket: WebSocket | null = null

    const connect = () => {
      const base = getWsBaseUrl()
      if (base) {
        const wsUrl = base.replace(/^http/, 'ws')
        socket = new WebSocket(`${wsUrl}/ws`)
      } else {
        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
        socket = new WebSocket(`${protocol}://${window.location.host}/ws`)
      }

      socket.onopen = () => {
        setConnectionStatus('Live')
        setWsError(null)
        // Re-fetch so the UI matches GET /api/summary; do not trust WS `initial` alone (can race / disagree with REST).
        void loadSummary()
      }

      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data) as { event?: string; summary?: Summary }
        // `initial` duplicates GET /api/summary and has been observed to overwrite a correct REST response with stale data.
        if (payload.event === 'initial' || !payload.summary) {
          return
        }
        setSummary(payload.summary)
      }

      socket.onerror = () => {
        setWsError('Live WebSocket is unavailable (500/timeout). The dashboard continues with 15s polling.')
      }

      socket.onclose = () => {
        setConnectionStatus('Reconnecting…')
        reconnectTimerRef.current = window.setTimeout(connect, 2000)
      }
    }

    connect()

    return () => {
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current)
      }
      socket?.close()
    }
  }, [loadSummary])

  const createDemoRun = useCallback(async () => {
    await fetch(apiUrl('/api/runs'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(createDemoPayload()),
    })
  }, [])

  const totalStatuses = useMemo(
    () => Object.values(summary?.status_counts ?? {}).reduce((a, b) => a + b, 0),
    [summary],
  )
  const totalEnvironments = useMemo(
    () => Object.values(summary?.environment_counts ?? {}).reduce((a, b) => a + b, 0),
    [summary],
  )

  const runsWithReport = useMemo(() => {
    if (!summary) return []
    return summary.latest_runs.filter((r) => {
      return reportViewerUrl(r) !== null
    })
  }, [summary])

  const selectedReportRun = useMemo(() => {
    if (runsWithReport.length === 0) return null
    const picked =
      selectedReportRunId !== null
        ? runsWithReport.find((r) => r.id === selectedReportRunId)
        : undefined
    return picked ?? runsWithReport[0]
  }, [runsWithReport, selectedReportRunId])

  useEffect(() => {
    if (runsWithReport.length === 0) {
      setSelectedReportRunId(null)
      return
    }
    setSelectedReportRunId((prev) => {
      if (prev !== null && runsWithReport.some((r) => r.id === prev)) return prev
      return runsWithReport[0].id
    })
  }, [runsWithReport])

  const reportFrameSrc = selectedReportRun ? reportViewerUrl(selectedReportRun) : null

  const reportOpenHref = selectedReportRun ? reportViewerUrl(selectedReportRun) : null

  if (!summary && fetchError) {
    return (
      <div className="container">
        <header>
          <h1>Real-Time Testing Dashboard</h1>
          <p>Could not load summary from the API.</p>
        </header>
        <section className="card" style={{ borderColor: 'var(--danger, #c44)' }}>
          <div className="card-title">Connection error</div>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{fetchError}</pre>
          <p className="meta">
            API base in use: <strong>{getApiBaseUrl() || 'same-origin'}</strong>. Without{' '}
            <code>VITE_API_BASE_URL</code>, production uses <code>same-origin /api</code> for REST (Vercel rewrite),
            and <code>{DEFAULT_PROD_API}</code> for WebSocket.
          </p>
          <button type="button" onClick={() => void loadSummary()}>
            Retry
          </button>
        </section>
      </div>
    )
  }

  if (!summary) {
    return <div className="container">Loading dashboard...</div>
  }

  return (
    <div className="container">
      {fetchError ? (
        <section className="card" style={{ marginBottom: 16, borderColor: 'var(--warning, #a83)' }}>
          <div className="card-title">Refresh failed (showing last loaded data)</div>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12 }}>{fetchError}</pre>
          <button type="button" onClick={() => void loadSummary()}>
            Retry now
          </button>
        </section>
      ) : null}
      {wsError ? (
        <section className="card" style={{ marginBottom: 16, borderColor: 'var(--warning, #a83)' }}>
          <div className="card-title">Live channel degraded</div>
          <p className="meta" style={{ marginBottom: 0 }}>{wsError}</p>
        </section>
      ) : null}
      <header>
        <div>
          <h1>Real-Time Testing Dashboard</h1>
          <p>Open-source QA observability dashboard for live execution monitoring</p>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <div className="pill">Data: {dataSource}</div>
          <div className="pill" title="REST + WS target">API: {getApiBaseUrl() || 'same-origin'}</div>
          <div className={`pill ${connectionStatus === 'Live' ? 'status-live' : ''}`}>{connectionStatus}</div>
        </div>
      </header>

      <section className="kpi-grid">
        <div className="kpi"><div className="label">Total Runs</div><div className="value">{summary.totals.runs}</div></div>
        <div className="kpi"><div className="label">Total Test Cases</div><div className="value">{summary.totals.cases}</div></div>
        <div className="kpi"><div className="label">Pass Rate</div><div className="value">{summary.totals.pass_rate}%</div></div>
        <div className="kpi"><div className="label">Open Defects</div><div className="value">{summary.totals.open_defects}</div></div>
      </section>

      {selectedReportRun && reportFrameSrc ? (
        <section className="card html-report-card">
          <div className="card-title">Latest CI Run View</div>
          <div className="html-report-toolbar">
            {runsWithReport.length > 1 ? (
              <label className="html-report-select-label">
                <span className="meta">Run</span>
                <select
                  className="html-report-select"
                  value={selectedReportRun.id}
                  onChange={(e) => setSelectedReportRunId(Number(e.target.value))}
                >
                  {runsWithReport.map((r) => (
                    <option key={r.id} value={r.id}>
                      #{r.id} · {r.suite_name} · {r.build_version.slice(0, 7)}
                      {r.has_html_report_zip ? ' (zip)' : r.has_html_report_inline ? ' (stored)' : ''}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <div className="meta">
                Run #{selectedReportRun.id} · {selectedReportRun.suite_name} · {selectedReportRun.build_version}
                {selectedReportRun.has_html_report_zip
                  ? ' · HTML report (zip) on API'
                  : selectedReportRun.has_html_report_inline
                    ? ' · stored on API'
                    : ''}
              </div>
            )}
            {reportOpenHref ? (
              <a className="html-report-open" href={reportOpenHref} target="_blank" rel="noreferrer">
                Open in new tab
              </a>
            ) : null}
          </div>
          <p className="meta" style={{ marginTop: 0 }}>
            Embedded view may be blocked for some external URLs (X-Frame-Options). Use “Open in new tab” if the frame is
            blank.
          </p>
          <div className="html-report-frame-wrap">
            <iframe
              title="CI HTML test report"
              className="html-report-frame"
              src={reportFrameSrc}
              sandbox="allow-scripts allow-same-origin allow-popups allow-downloads"
            />
          </div>
        </section>
      ) : null}

      <section className="grid two">
        <article className="card">
          <div className="card-title">Execution Status</div>
          {Object.entries(summary.status_counts)
            .sort((a, b) => b[1] - a[1])
            .map(([label, value]) => {
              const cssClass = label === 'PASSED' ? 'success' : label === 'RUNNING' ? 'info' : label === 'SKIPPED' ? 'warning' : 'danger'
              return (
                <div className="breakdown-row" key={label}>
                  <div className="breakdown-label"><span>{label}</span><span>{value}</span></div>
                  <div className="bar"><div className={`fill ${cssClass}`} style={{ width: `${pct(value, totalStatuses)}%` }} /></div>
                </div>
              )
            })}
        </article>
        <article className="card">
          <div className="card-title">Environment Distribution</div>
          {Object.entries(summary.environment_counts)
            .sort((a, b) => b[1] - a[1])
            .map(([label, value]) => (
              <div className="breakdown-row" key={label}>
                <div className="breakdown-label"><span>{label}</span><span>{value}</span></div>
                <div className="bar"><div className="fill info" style={{ width: `${pct(value, totalEnvironments)}%` }} /></div>
              </div>
            ))}
        </article>
      </section>

      <section className="grid two">
        <article className="card">
          <div className="card-title">Module Quality Trend</div>
          {[...summary.module_quality]
            .sort((a, b) => a.pass_rate - b.pass_rate)
            .map((item) => {
              const cssClass = item.pass_rate >= 85 ? 'success' : item.pass_rate >= 70 ? 'warning' : 'danger'
              return (
                <div className="module-row" key={item.module}>
                  <div className="module-title">
                    <span>{item.module}</span>
                    <span>{item.pass_rate}% ({item.passed}/{item.total})</span>
                  </div>
                  <div className="bar"><div className={`fill ${cssClass}`} style={{ width: `${item.pass_rate}%` }} /></div>
                </div>
              )
            })}
        </article>
        <article className="card">
          <div className="card-title">Live Execution Feed</div>
          <div className="meta">Last refreshed: {new Date(summary.generated_at).toLocaleString()}</div>
          <div className="meta" style={{ marginTop: 6, lineHeight: 1.4 }}>
            Numbers match <code>GET {getApiBaseUrl()}/api/summary</code> (Network → Preview). Rows in Preview = rows in
            the API database; truncate Postgres on Render or use <code>DATA_SOURCE=github</code> to turn off demo
            writes.
          </div>
          <table>
            <thead>
              <tr>
                <th>Suite</th>
                <th>Build</th>
                <th>Env</th>
                <th>Status</th>
                <th>Progress</th>
                <th>HTML report</th>
              </tr>
            </thead>
            <tbody>
              {summary.latest_runs.map((run) => {
                const progress = pct(run.passed + run.failed, run.total)
                const cssClass = run.status === 'FAILED' || run.status === 'BLOCKED' ? 'danger' : run.status === 'PASSED' ? 'success' : 'info'
                const reportHref = reportViewerUrl(run)
                return (
                  <tr key={run.id}>
                    <td>{run.suite_name}</td>
                    <td>{run.build_version}</td>
                    <td>{run.environment}</td>
                    <td><span className={`status ${run.status}`}>{run.status}</span></td>
                    <td><div className="bar"><div className={`fill ${cssClass}`} style={{ width: `${progress}%` }} /></div></td>
                    <td>
                      {reportHref ? (
                        <a href={reportHref} target="_blank" rel="noreferrer" className="html-report-link">
                          Open
                        </a>
                      ) : (
                        <span className="meta">—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {dataSource === 'github' &&
          summary.latest_runs.length > 0 &&
          summary.latest_runs.every((r) => !reportViewerUrl(r)) ? (
            <p className="meta" style={{ marginTop: 14, lineHeight: 1.5 }}>
              HTML stays empty until your <strong>Playwright / CI workflow</strong> uploads the report: use{' '}
              <code>POST {getApiBaseUrl()}/api/ingest/github-actions/run-with-report</code> with a{' '}
              <code>report_zip</code> part (folder zipped as in the README). Pushing this dashboard repo does not send
              GitHub artifacts to the API.
            </p>
          ) : null}
        </article>
      </section>

      {dataSource !== 'github' ? (
        <section className="card control-panel">
          <div className="card-title">Demo Controls</div>
          <p>Inject a sample run to demonstrate real-time streaming to the dashboard.</p>
          <button onClick={() => void createDemoRun()}>Create Demo Test Run</button>
        </section>
      ) : null}
    </div>
  )
}

export default App
