import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchJson, fetchJsonPost } from './apiClient'

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

type Props = {
  onPipelineFinished?: () => void
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

function stepClass(step: CiStep): string {
  if (step.status === 'in_progress') return 'ci-step in-progress'
  if (step.conclusion === 'success') return 'ci-step success'
  if (step.conclusion === 'failure') return 'ci-step failure'
  if (step.conclusion === 'skipped') return 'ci-step skipped'
  return 'ci-step'
}

export default function CiPipelinePanel({ onPipelineFinished }: Props) {
  const [config, setConfig] = useState<CiConfig | null>(null)
  const [workflows, setWorkflows] = useState<CiWorkflow[]>([])
  const [workflowFile, setWorkflowFile] = useState('')
  const [ref, setRef] = useState('main')
  const [flow, setFlow] = useState<CiRunFlow | null>(null)
  const [activeRunId, setActiveRunId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [triggering, setTriggering] = useState(false)
  const finishedRef = useRef(false)

  const loadConfig = useCallback(async () => {
    try {
      const data = await fetchJson<CiConfig>('/api/ci/config')
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
      const data = await fetchJson<{ workflows: CiWorkflow[] }>('/api/ci/workflows')
      setWorkflows(data.workflows)
      if (data.workflows.length > 0) {
        setWorkflowFile((prev) => {
          if (prev) return prev
          const path = data.workflows[0].path || ''
          return path.replace(/^\.github\/workflows\//, '')
        })
      }
    } catch {
      setWorkflows([])
    }
  }, [])

  const refreshFlow = useCallback(async (runId: number) => {
    const data = await fetchJson<CiRunFlow>(`/api/ci/runs/${runId}`)
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
          setError(e instanceof Error ? e.message : String(e))
          window.setTimeout(poll, 6000)
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
        setActiveRunId(result.run_id)
      } else {
        const recent = await fetchJson<{ runs: Array<{ id: number }> }>('/api/ci/runs?limit=1')
        if (recent.runs[0]?.id) {
          setActiveRunId(recent.runs[0].id)
        } else {
          setError('Pipeline started on GitHub; open the Actions tab to track the run.')
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setTriggering(false)
    }
  }

  if (!config) {
    return (
      <section className="card ci-panel">
        <div className="card-title">CI pipeline control</div>
        <p className="meta">Loading CI configuration…</p>
      </section>
    )
  }

  if (!config.enabled) {
    return (
      <section className="card ci-panel">
        <div className="card-title">CI pipeline control</div>
        <p className="meta">
          Not configured. Set <code>GITHUB_CI_TOKEN</code> and <code>GITHUB_CI_REPO</code> on the API (Render), then
          redeploy. The workflow must include <code>workflow_dispatch</code>.
        </p>
      </section>
    )
  }

  return (
    <section className="card ci-panel">
      <div className="card-title">CI pipeline control</div>
      <p className="meta" style={{ marginTop: 0 }}>
        Trigger <strong>{config.repo}</strong> on GitHub Actions and watch job/step progress here.
      </p>

      <div className="ci-controls">
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
          <input
            className="html-report-select"
            value={ref}
            onChange={(e) => setRef(e.target.value)}
            placeholder="main"
          />
        </label>
        <button type="button" disabled={triggering} onClick={() => void triggerPipeline()}>
          {triggering ? 'Starting pipeline…' : 'Run pipeline'}
        </button>
      </div>

      {error ? (
        <pre className="ci-error" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {error}
        </pre>
      ) : null}

      {flow ? (
        <div className="ci-flow">
          <div className="ci-flow-header">
            <div>
              <strong>{flow.name}</strong>{' '}
              <span className={`ci-run-badge status-${flow.status}`}>{flow.status}</span>
              {flow.conclusion ? (
                <span className={`ci-run-badge conclusion-${flow.conclusion}`}> {flow.conclusion}</span>
              ) : null}
            </div>
            <div className="meta">
              {flow.head_branch ? `branch ${flow.head_branch}` : null}
              {flow.head_sha ? ` · ${flow.head_sha}` : null}
            </div>
            {flow.html_url ? (
              <a className="html-report-open" href={flow.html_url} target="_blank" rel="noreferrer">
                Open on GitHub
              </a>
            ) : null}
          </div>

          {flow.jobs.map((job) => (
            <div className="ci-job" key={job.id}>
              <div className="ci-job-title">
                <span>{job.name}</span>
                <span className={`ci-run-badge status-${job.status}`}>{job.status}</span>
              </div>
              <ol className="ci-steps">
                {job.steps.map((step) => (
                  <li key={`${job.id}-${step.number}`} className={stepClass(step)}>
                    <span className="ci-step-icon">{stepIcon(step)}</span>
                    <span className="ci-step-name">{step.name}</span>
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      ) : activeRunId ? (
        <p className="meta">Waiting for workflow run #{activeRunId}…</p>
      ) : null}
    </section>
  )
}
