import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, fetchJson, fetchJsonPost } from './apiClient'
import TriagePanel from './TriagePanel'

type CiConfig = {
  enabled: boolean
  repo: string | null
  default_workflow_file: string | null
  default_ref: string
}

type CiWorkflow = {
  id: number
  name: string
  path: string
  state: string
}

type CiStep = {
  number: number
  name: string
  status: string
  conclusion: string | null
}

type CiJob = {
  id: number
  name: string
  status: string
  conclusion: string | null
  html_url: string | null
  steps: CiStep[]
}

type CiRunSummary = {
  id: number
  name: string
  status: string
  conclusion: string | null
}

type CiRunFlow = {
  id: number
  name: string
  status: string
  conclusion: string | null
  html_url: string | null
  head_branch?: string | null
  head_sha?: string | null
  jobs: CiJob[]
}

function firstFailedStep(flow: CiRunFlow | null): { job: string; step: string } | null {
  if (!flow) return null
  for (const job of flow.jobs) {
    const step = job.steps.find((item) => item.conclusion === 'failure')
    if (step) {
      return { job: job.name, step: step.name || `Step ${step.number}` }
    }
    if (job.conclusion === 'failure') {
      return { job: job.name, step: '' }
    }
  }
  return null
}

type Props = {
  onPipelineFinished?: () => void
  selectedRunId?: number | null
  onSelectedRunIdChange?: (runId: number) => void
  mode?: 'testing' | 'triage'
}

function stepIcon(step: CiStep): string {
  if (step.status === 'completed') {
    if (step.conclusion === 'success') return '✓'
    if (step.conclusion === 'failure') return '✗'
    if (step.conclusion === 'skipped') return '○'
    return '•'
  }
  if (step.status === 'in_progress') return '…'
  return '○'
}

function formatCiError(message: string): string {
  if (message.toLowerCase().includes('rate limit')) {
    return 'GitHub API rate limit exceeded for this token. Wait until the limit resets, and avoid refreshing this page — retries make it worse.'
  }
  if (message.includes('403') || message.toLowerCase().includes('not accessible by personal access token')) {
    return [
      'GitHub rejected the token (403).',
      'Use a classic PAT with scopes repo + workflow.',
      'If the org uses SSO, authorize the token (Configure SSO).',
      'Update GITHUB_CI_TOKEN on Render and redeploy the API.',
    ].join(' ')
  }
  return message
}

function shouldRetryGithub(error: unknown): boolean {
  if (error instanceof ApiError && (error.status === 401 || error.status === 403)) return false
  const message = error instanceof Error ? error.message : String(error)
  return !message.toLowerCase().includes('rate limit')
}

function stepClass(step: CiStep): string {
  if (step.status === 'in_progress') return 'ci-step ci-running'
  if (step.conclusion === 'success') return 'ci-step ci-ok'
  if (step.conclusion === 'failure') return 'ci-step ci-fail'
  if (step.conclusion === 'skipped') return 'ci-step ci-skip'
  return 'ci-step'
}

function parseGithubRunId(raw: string): number | null {
  const trimmed = raw.trim()
  if (!/^\d+$/.test(trimmed)) return null
  const value = Number(trimmed)
  if (!Number.isInteger(value) || value <= 0) return null
  return value
}

export default function CiPipelinePanel({
  onPipelineFinished,
  selectedRunId = null,
  onSelectedRunIdChange,
  mode = 'testing',
}: Props) {
  const [config, setConfig] = useState<CiConfig | null>(null)
  const [workflows, setWorkflows] = useState<CiWorkflow[]>([])
  const [workflowFile, setWorkflowFile] = useState('')
  const [ref, setRef] = useState('main')
  const [flow, setFlow] = useState<CiRunFlow | null>(null)
  const [activeRunId, setActiveRunId] = useState<number | null>(selectedRunId)
  const [error, setError] = useState<string | null>(null)
  const [triggering, setTriggering] = useState(false)
  const [existingRunId, setExistingRunId] = useState(selectedRunId ? String(selectedRunId) : '32837090794')
  const [loadingExisting, setLoadingExisting] = useState(false)
  const [latestFailedRunId, setLatestFailedRunId] = useState<number | null>(null)
  const finishedRef = useRef(false)

  const selectRun = useCallback((runId: number) => {
    setActiveRunId(runId)
    setExistingRunId(String(runId))
    onSelectedRunIdChange?.(runId)
  }, [onSelectedRunIdChange])

  const loadConfig = useCallback(async () => {
    try {
      const data = await fetchJson<CiConfig>('/api/ci/config', 25000)
      setConfig(data)
      setRef(data.default_ref || 'main')
      if (data.default_workflow_file) {
        setWorkflowFile(data.default_workflow_file)
      }
    } catch {
      setConfig({ enabled: false, repo: null, default_workflow_file: null, default_ref: 'main' })
    }
  }, [])

  const loadWorkflows = useCallback(async () => {
    try {
      const data = await fetchJson<{ workflows: CiWorkflow[] }>('/api/ci/workflows', 25000)
      setWorkflows(data.workflows || [])
      setWorkflowFile((prev) => {
        if (prev) return prev
        const path = data.workflows?.[0]?.path || ''
        return path.replace(/^\.github\/workflows\//, '')
      })
    } catch {
      setWorkflows([])
    }
  }, [])

  const refreshFlow = useCallback(async (runId: number) => {
    const data = await fetchJson<CiRunFlow>(`/api/ci/runs/${runId}`, 25000)
    setFlow(data)
    return data
  }, [])

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  useEffect(() => {
    if (config?.enabled) {
      void loadWorkflows()
    }
  }, [config?.enabled, loadWorkflows])

  useEffect(() => {
    if (mode !== 'triage' || !config?.enabled) return
    let cancelled = false
    void (async () => {
      try {
        const data = await fetchJson<{ runs: CiRunSummary[] }>('/api/ci/runs?limit=20', 25000)
        if (cancelled) return
        const failed = data.runs.find((run) => run.conclusion === 'failure')
        setLatestFailedRunId(failed?.id ?? null)
      } catch {
        if (!cancelled) setLatestFailedRunId(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [mode, config?.enabled])

  useEffect(() => {
    if (!selectedRunId || selectedRunId === activeRunId) return
    finishedRef.current = false
    setFlow(null)
    setActiveRunId(selectedRunId)
    setExistingRunId(String(selectedRunId))
  }, [selectedRunId, activeRunId])

  useEffect(() => {
    if (!activeRunId) return
    finishedRef.current = false
    let cancelled = false

    const poll = async () => {
      try {
        const data = await refreshFlow(activeRunId)
        if (cancelled) return
        setError(null)
        const done = data.status === 'completed' || data.status === 'cancelled'
        if (done && !finishedRef.current) {
          finishedRef.current = true
          onPipelineFinished?.()
        }
        if (!done && !cancelled) {
          window.setTimeout(poll, 4000)
        }
      } catch (e) {
        if (!cancelled) {
          setError(formatCiError(e instanceof Error ? e.message : String(e)))
          if (shouldRetryGithub(e)) {
            window.setTimeout(poll, 6000)
          }
        }
      }
    }

    void poll()
    return () => {
      cancelled = true
    }
  }, [activeRunId, refreshFlow, onPipelineFinished])

  const triggerPipeline = async () => {
    setTriggering(true)
    setError(null)
    setFlow(null)
    try {
      const result = await fetchJsonPost<{
        run_id: number | null
        html_url: string | null
        workflow_file: string
        ref: string
      }>('/api/ci/trigger', {
        ref,
        workflow_file: workflowFile || undefined,
      })
      if (result.run_id) {
        selectRun(result.run_id)
      } else {
        const recent = await fetchJson<{ runs: Array<{ id: number }> }>('/api/ci/runs?limit=1', 25000)
        if (recent.runs[0]?.id) {
          selectRun(recent.runs[0].id)
        } else {
          setError('Pipeline started on GitHub; open the Actions tab to track the run.')
        }
      }
    } catch (e) {
      setError(formatCiError(e instanceof Error ? e.message : String(e)))
    } finally {
      setTriggering(false)
    }
  }

  const loadLatestFailedRun = async () => {
    setLoadingExisting(true)
    setError(null)
    try {
      const data = await fetchJson<{ runs: CiRunSummary[] }>('/api/ci/runs?limit=20', 25000)
      const failed = data.runs.find((run) => run.conclusion === 'failure')
      if (!failed?.id) {
        setError('No failed GitHub Actions run found for this workflow.')
        return
      }
      setLatestFailedRunId(failed.id)
      selectRun(failed.id)
    } catch (e) {
      setError(formatCiError(e instanceof Error ? e.message : String(e)))
    } finally {
      setLoadingExisting(false)
    }
  }

  const loadExistingRun = async () => {
    const runId = parseGithubRunId(existingRunId)
    if (!runId) {
      setError('Enter a positive GitHub Actions run ID.')
      return
    }
    setLoadingExisting(true)
    setError(null)
    finishedRef.current = false
    try {
      if (runId !== activeRunId) {
        setFlow(null)
        selectRun(runId)
      } else {
        await refreshFlow(runId)
      }
    } catch (e) {
      setError(formatCiError(e instanceof Error ? e.message : String(e)))
    } finally {
      setLoadingExisting(false)
    }
  }

  if (!config) {
    return (
      <section className="card ci-panel">
        <div className="card-title">{mode === 'triage' ? 'CI execution' : 'CI pipeline control'}</div>
        <p className="meta">Loading CI configuration…</p>
      </section>
    )
  }

  if (!config.enabled) {
    return (
      <section className="card ci-panel">
        <div className="card-title">CI pipeline control</div>
        <p className="meta" style={{ lineHeight: 1.6 }}>
          Not configured. On Render (API service → Environment) set:
        </p>
        <ol className="meta ci-setup-steps">
          <li>
            GitHub classic PAT with scopes <code>repo</code> and <code>workflow</code>.
          </li>
          <li>
            <code>GITHUB_CI_TOKEN</code> = that token (Secret).
          </li>
          <li>
            <code>GITHUB_CI_REPO</code> = <code>mmohansqaai/SelfHealingPlaywrightFramework</code>
          </li>
          <li>Save and <strong>Redeploy</strong> the API, then refresh this page.</li>
        </ol>
      </section>
    )
  }

  return (
    <section className="card ci-panel">
      <div className="card-title">{mode === 'triage' ? 'CI execution' : 'CI pipeline control'}</div>
      <p className="meta" style={{ marginTop: 0 }}>
        {mode === 'triage' ? (
          <>
            Load a GitHub Actions run for <strong>{config.repo}</strong>, then review the correlated CI Failure Triage
            result.
          </>
        ) : (
          <>
            Trigger <strong>{config.repo}</strong> on GitHub Actions and watch job/step progress here.
          </>
        )}
      </p>

      <div className="ci-controls">
        {mode === 'testing' ? (
          <>
            <label className="ci-field">
              <span className="meta">Workflow file</span>
              <select
                className="html-report-select"
                value={workflowFile}
                onChange={(e) => setWorkflowFile(e.target.value)}
              >
                {workflows.length === 0 ? (
                  <option value={workflowFile}>{workflowFile || 'playwright.yml'}</option>
                ) : (
                  workflows.map((wf) => {
                    const file = (wf.path || '').replace(/^\.github\/workflows\//, '')
                    return (
                      <option key={wf.id} value={file}>
                        {wf.name} ({file})
                      </option>
                    )
                  })
                )}
              </select>
            </label>
            <label className="ci-field">
              <span className="meta">Branch (ref)</span>
              <input className="html-report-select" value={ref} onChange={(e) => setRef(e.target.value)} />
            </label>
            <button type="button" disabled={triggering || !workflowFile} onClick={() => void triggerPipeline()}>
              {triggering ? 'Starting…' : 'Run pipeline'}
            </button>
          </>
        ) : (
          <>
            <label className="ci-field">
              <span className="meta">Existing run ID</span>
              <input
                className="html-report-select"
                inputMode="numeric"
                value={existingRunId}
                onChange={(e) => setExistingRunId(e.target.value)}
                placeholder="32837090794"
              />
            </label>
            <button type="button" disabled={loadingExisting || !existingRunId.trim()} onClick={() => void loadExistingRun()}>
              {loadingExisting ? 'Loading…' : 'Load run'}
            </button>
            <button
              type="button"
              className="app-tab-link"
              disabled={loadingExisting}
              onClick={() => void loadLatestFailedRun()}
            >
              {loadingExisting ? 'Loading…' : 'Load latest failed run'}
            </button>
          </>
        )}
      </div>

      {error ? <p className="meta" style={{ color: 'var(--danger)' }}>{error}</p> : null}

      {mode === 'triage' && latestFailedRunId && latestFailedRunId !== activeRunId ? (
        <p className="meta" style={{ color: 'var(--danger)' }}>
          GitHub has a newer failed Playwright run ({latestFailedRunId}). This page is showing a different run.
          Use <strong>Load latest failed run</strong>.
        </p>
      ) : null}

      {mode === 'triage' && activeRunId && config.repo ? (
        <TriagePanel
          provider="github-actions"
          repository={config.repo}
          runId={String(activeRunId)}
          pipelineComplete={flow?.status === 'completed' || flow?.status === 'cancelled'}
          pipelineConclusion={flow?.conclusion ?? null}
          githubFailedJob={firstFailedStep(flow)?.job ?? null}
          githubFailedStep={firstFailedStep(flow)?.step ?? null}
        />
      ) : null}

      {flow ? (
        <div className="ci-flow">
          <div className="ci-flow-header">
            <strong>{flow.name}</strong>
            <span className="meta">
              {flow.status}
              {flow.conclusion ? ` / ${flow.conclusion}` : ''}
              {flow.head_sha ? ` · ${flow.head_sha}` : ''}
            </span>
            {flow.html_url ? (
              <a href={flow.html_url} target="_blank" rel="noreferrer" className="html-report-link">
                Open on GitHub
              </a>
            ) : null}
          </div>
          {flow.jobs.map((job) => (
            <div key={job.id} className="ci-job">
              <div className="ci-job-title">
                <span>{job.name}</span>
                <span className={`ci-job-status ${job.status === 'in_progress' ? 'running' : ''}`}>
                  {job.status === 'in_progress' ? 'Running…' : job.status}
                </span>
              </div>
              <ul className="ci-steps">
                {job.steps.map((step) => (
                  <li key={`${job.id}-${step.number}`} className={stepClass(step)}>
                    <span>{stepIcon(step)}</span>{' '}
                    {step.name || `Step ${step.number}`}
                    {step.status === 'in_progress' ? ' — running' : ''}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}
