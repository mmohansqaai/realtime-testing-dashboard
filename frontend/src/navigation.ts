export type DashboardTab = 'testing' | 'triage'

export function readLocation(): { tab: DashboardTab; runId: number | null } {
  const path = window.location.pathname.replace(/\/+$/, '') || '/'
  const tab: DashboardTab = path === '/triage' ? 'triage' : 'testing'
  const raw = new URLSearchParams(window.location.search).get('runId')
  if (!raw || !/^\d+$/.test(raw)) {
    return { tab, runId: null }
  }
  const runId = Number(raw)
  return { tab, runId: runId > 0 ? runId : null }
}

export function locationHref(tab: DashboardTab, runId: number | null): string {
  const path = tab === 'triage' ? '/triage' : '/'
  return runId ? `${path}?runId=${runId}` : path
}

export function writeLocation(tab: DashboardTab, runId: number | null, replace = false): void {
  const url = locationHref(tab, runId)
  const method = replace ? 'replaceState' : 'pushState'
  window.history[method]({ tab, runId }, '', url)
}
