import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchJsonOr404 } from './apiClient'

export type TriageState =
  | 'NOT_STARTED'
  | 'ANALYZING'
  | 'COMPLETED'
  | 'REVIEW_REQUIRED'
  | 'FAILED_TO_ANALYZE'

export type TriageResult = {
  id: number
  provider: string
  repository: string
  runId: string
  triageState: TriageState
  pipelineName?: string | null
  pipelineStatus?: string | null
  failedJob?: string | null
  failedStep?: string | null
  classification?: string | null
  subtype?: string | null
  confidence?: number | null
  probableCause?: string | null
  evidence?: unknown
  recommendedAction?: string | null
  humanReviewRequired?: boolean | null
  analysisMode?: string | null
  relatedFailures?: string[] | null
  createdAt: string
  updatedAt: string
}

type Props = {
  provider: string
  repository: string
  runId: string
  pipelineComplete: boolean
  pipelineConclusion?: string | null
  githubFailedJob?: string | null
  githubFailedStep?: string | null
  githubRunUrl?: string | null
}

function evidenceItems(evidence: unknown): string[] {
  if (evidence == null || evidence === '') return []
  if (Array.isArray(evidence)) {
    return evidence.map((item) => (typeof item === 'string' ? item : JSON.stringify(item))).filter(Boolean)
  }
  if (typeof evidence === 'string') return [evidence]
  return [JSON.stringify(evidence)]
}

function stateClass(state: TriageState): string {
  if (state === 'ANALYZING') return 'triage-state analyzing'
  if (state === 'COMPLETED') return 'triage-state completed'
  if (state === 'REVIEW_REQUIRED') return 'triage-state review'
  if (state === 'FAILED_TO_ANALYZE') return 'triage-state failed'
  return 'triage-state'
}

function shouldPoll(state: TriageState, pipelineComplete: boolean, missCount: number): boolean {
  if (state === 'ANALYZING') return true
  if (state === 'NOT_STARTED' && pipelineComplete && missCount < 4) return true
  return false
}

function notStartedCopy(
  pipelineComplete: boolean,
  pipelineConclusion?: string | null,
  failedJob?: string | null,
  failedStep?: string | null,
): string {
  if (!pipelineComplete) {
    return 'Waiting for the GitHub Actions run to finish. Triage is ingested after the pipeline completes.'
  }
  if (pipelineConclusion === 'success') {
    return 'This GitHub run succeeded, so there is no failure classification to show.'
  }
  const where = [failedJob, failedStep].filter(Boolean).join(' / ')
  if (where) {
    return `Failed at ${where}. No classification is stored for this run ID yet.`
  }
  return 'This GitHub run failed, but no classification is stored for this run ID yet.'
}

export default function TriagePanel({
  provider,
  repository,
  runId,
  pipelineComplete,
  pipelineConclusion = null,
  githubFailedJob = null,
  githubFailedStep = null,
  githubRunUrl = null,
}: Props) {
  const [result, setResult] = useState<TriageResult | null>(null)
  const [state, setState] = useState<TriageState>('NOT_STARTED')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [missCount, setMissCount] = useState(0)
  const generationRef = useRef(0)

  const load = useCallback(async () => {
    const generation = generationRef.current
    setLoading(true)
    try {
      const params = new URLSearchParams({ provider, repository, runId })
      const data = await fetchJsonOr404<TriageResult>(`/api/triage/result?${params.toString()}`, 90000)
      if (generation !== generationRef.current) return
      setError(null)
      if (!data) {
        setResult(null)
        setState('NOT_STARTED')
        setMissCount((count) => count + 1)
        return
      }
      setResult(data)
      setState(data.triageState)
      setMissCount(0)
    } catch (e) {
      if (generation !== generationRef.current) return
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (generation === generationRef.current) {
        setLoading(false)
      }
    }
  }, [provider, repository, runId])

  useEffect(() => {
    generationRef.current += 1
    setResult(null)
    setState('NOT_STARTED')
    setError(null)
    setMissCount(0)
    void load()
  }, [provider, repository, runId, load])

  useEffect(() => {
    if (error) return
    if (!shouldPoll(state, pipelineComplete, missCount)) return
    const id = window.setTimeout(() => {
      void load()
    }, 4000)
    return () => window.clearTimeout(id)
  }, [state, pipelineComplete, error, load, result?.updatedAt, missCount])

  const showFullResult = state === 'COMPLETED' || state === 'REVIEW_REQUIRED'
  const evidence = evidenceItems(result?.evidence)

  return (
    <div className="triage-panel">
      <div className="triage-header">
        <strong>Classification</strong>
        <span className={stateClass(state)}>{state.replaceAll('_', ' ')}</span>
      </div>
      {githubRunUrl ? (
        <p className="meta">
          <a href={githubRunUrl} target="_blank" rel="noreferrer" className="html-report-link">
            Open this run on GitHub
          </a>
        </p>
      ) : null}

      {error ? (
        <div className="triage-error">
          <p className="meta" style={{ color: 'var(--warning)', marginBottom: 8 }}>
            Could not refresh triage. The CI pipeline view is unchanged.
          </p>
          <p className="meta" style={{ marginBottom: 10 }}>{error}</p>
          <button type="button" onClick={() => void load()}>
            Retry
          </button>
        </div>
      ) : null}

      {!error && state === 'NOT_STARTED' ? (
        <p className="meta">
          {notStartedCopy(pipelineComplete, pipelineConclusion, githubFailedJob, githubFailedStep)}
          {loading && missCount < 4 ? ' Checking again…' : ''}
        </p>
      ) : null}

      {!error && state === 'ANALYZING' ? (
        <p className="meta triage-analyzing">Analyzing this CI execution… checking for an updated result every 4s.</p>
      ) : null}

      {state === 'FAILED_TO_ANALYZE' ? (
        <div className="triage-failed">
          <p className="meta" style={{ color: 'var(--danger)' }}>
            Triage failed to analyze this execution.
          </p>
          {result?.probableCause ? <p className="meta">{result.probableCause}</p> : null}
          {result?.recommendedAction ? <p className="meta">{result.recommendedAction}</p> : null}
          {!error ? (
            <button type="button" onClick={() => void load()}>
              Retry
            </button>
          ) : null}
        </div>
      ) : null}

      {showFullResult && result ? (
        <div className="triage-result">
          {state === 'REVIEW_REQUIRED' || result.humanReviewRequired ? (
            <div className="triage-review">Human review required</div>
          ) : null}
          <div className="triage-grid">
            <div className="triage-field">
              <div className="label">Classification</div>
              <div>{result.classification || '—'}</div>
            </div>
            <div className="triage-field">
              <div className="label">Subtype</div>
              <div>{result.subtype || '—'}</div>
            </div>
            <div className="triage-field">
              <div className="label">Confidence</div>
              <div>{result.confidence == null ? '—' : `${result.confidence}%`}</div>
            </div>
            <div className="triage-field">
              <div className="label">Analysis mode</div>
              <div>{result.analysisMode || '—'}</div>
            </div>
            <div className="triage-field">
              <div>Human Review Required: {result.humanReviewRequired ? 'Yes' : 'No'}</div>
            </div>
            <div className="triage-field">
              <div className="label">Pipeline</div>
              <div>
                {result.pipelineName || '—'}
                {result.pipelineStatus ? ` · ${result.pipelineStatus}` : ''}
              </div>
            </div>
            <div className="triage-field">
              <div className="label">Failed job / step</div>
              <div>
                {result.failedJob || '—'}
                {result.failedStep ? ` / ${result.failedStep}` : ''}
              </div>
            </div>
          </div>
          <div className="triage-block">
            <div className="label">Probable cause</div>
            <p>{result.probableCause || '—'}</p>
          </div>
          {result.relatedFailures && result.relatedFailures.length > 0 ? (
            <div className="triage-block">
              <div className="label">Related failures</div>
              <ul className="triage-evidence">
                {result.relatedFailures.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="triage-block">
            <div className="label">Evidence</div>
            {evidence.length > 0 ? (
              <ul className="triage-evidence">
                {evidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p className="meta">—</p>
            )}
          </div>
          <div className="triage-block">
            <div className="label">Recommended action</div>
            <p>{result.recommendedAction || '—'}</p>
          </div>
        </div>
      ) : null}
    </div>
  )
}
