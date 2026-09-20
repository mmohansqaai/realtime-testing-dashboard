import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchJsonOr404 } from './apiClient'

export type TriageState =
  | 'NOT_STARTED'
  | 'ANALYZING'
  | 'COMPLETED'
  | 'REVIEW_REQUIRED'
  | 'FAILED_TO_ANALYZE'

export type FailedTestTriage = {
  title: string
  fullName: string
  file?: string | null
  classification: string
  subtype: string
  confidence: number
  whatHappened: string
  whyItFailed: string
  recommendedAction: string
  owner?: string | null
  evidence?: string[]
  errorExcerpt?: string | null
}

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
  failedTests?: FailedTestTriage[] | null
  executiveSummary?: string | null
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

const CLASS_LABEL: Record<string, string> = {
  AUTOMATION_DEFECT: 'Test script',
  PRODUCT_DEFECT: 'Product',
  ENVIRONMENT: 'Environment',
  CI_INFRASTRUCTURE: 'CI / dashboard',
  AUTH_SECURITY: 'Authentication',
  FLAKY_TEST: 'Flaky test',
  TEST_DATA: 'Test data',
  DEPENDENCY_CONFIG: 'Dependency',
  UNKNOWN: 'Needs review',
}

const SUBTYPE_LABEL: Record<string, string> = {
  LOCATOR_FAILURE: 'Element not found',
  ASSERTION_MISMATCH: 'Value mismatch',
  SERVICE_CONNECTION_REFUSED: 'Connection refused',
  HTTP_5XX_UNAVAILABLE: 'Service unavailable',
  TOKEN_OR_UNAUTHORIZED: 'Unauthorized',
  DOWNSTREAM_SERVICE_UNAVAILABLE: 'Publish timed out',
  DOWNSTREAM_SERVICE: 'Publish failed',
  RUNNER_SETUP: 'Setup failed',
  INSUFFICIENT_EVIDENCE: 'Not enough evidence',
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

function classTone(classification?: string | null): string {
  if (classification === 'ENVIRONMENT' || classification === 'CI_INFRASTRUCTURE') return 'env'
  if (classification === 'AUTOMATION_DEFECT') return 'auto'
  if (classification === 'PRODUCT_DEFECT') return 'product'
  if (classification === 'AUTH_SECURITY') return 'auth'
  return 'unknown'
}

function prettyClass(value?: string | null): string {
  if (!value) return '—'
  return CLASS_LABEL[value] || value.replaceAll('_', ' ')
}

function prettySubtype(value?: string | null): string {
  if (!value) return ''
  return SUBTYPE_LABEL[value] || value.replaceAll('_', ' ').toLowerCase()
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
    return 'Waiting for the GitHub Actions run to finish. Triage starts after the pipeline completes.'
  }
  if (pipelineConclusion === 'success') {
    return 'This GitHub run succeeded, so there is no failure report to show.'
  }
  const where = [failedJob, failedStep].filter(Boolean).join(' / ')
  if (where) {
    return `Failed at ${where}. No classification is available for this run ID yet.`
  }
  return 'This GitHub run failed, but no classification is available for this run ID yet.'
}

function countByClass(tests: FailedTestTriage[]): Array<{ key: string; count: number }> {
  const counts = new Map<string, number>()
  for (const test of tests) {
    counts.set(test.classification, (counts.get(test.classification) || 0) + 1)
  }
  return [...counts.entries()].map(([key, count]) => ({ key, count }))
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
  const tests = result?.failedTests || []
  const evidence = evidenceItems(result?.evidence)
  const summary = result?.executiveSummary || result?.probableCause
  const modeLabel = result?.analysisMode === 'AI_ASSISTED' ? 'AI assisted' : 'Deterministic'

  return (
    <div className="triage-panel">
      <div className="triage-header">
        <strong>Failure report</strong>
        <span className="triage-header-meta">
          {result?.analysisMode ? <span className="triage-mode">{modeLabel}</span> : null}
          <span className={stateClass(state)}>{state.replaceAll('_', ' ')}</span>
        </span>
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

      {!error && loading && !showFullResult ? (
        <p className="meta triage-analyzing">Reading failed tests and writing the report…</p>
      ) : null}

      {!error && !loading && state === 'NOT_STARTED' ? (
        <p className="meta">
          {notStartedCopy(pipelineComplete, pipelineConclusion, githubFailedJob, githubFailedStep)}
          {missCount < 4 ? ' Checking again…' : ''}
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
            <div className="triage-review">Human review required — treat these as separate findings</div>
          ) : null}

          <div className="triage-summary-card">
            <div className="triage-summary-kicker">
              {tests.length > 0
                ? `${tests.length} failed test${tests.length === 1 ? '' : 's'}`
                : 'Pipeline failure'}
            </div>
            <p className="triage-summary-text">{summary || '—'}</p>
            {tests.length > 0 ? (
              <div className="triage-pills">
                {countByClass(tests).map((item) => (
                  <span key={item.key} className={`triage-pill ${classTone(item.key)}`}>
                    {item.count} {prettyClass(item.key).toLowerCase()}
                  </span>
                ))}
              </div>
            ) : (
              <div className="triage-pills">
                <span className={`triage-pill ${classTone(result.classification)}`}>
                  {prettyClass(result.classification)}
                  {prettySubtype(result.subtype) ? ` · ${prettySubtype(result.subtype)}` : ''}
                </span>
              </div>
            )}
          </div>

          <div className="triage-meta-row">
            <span>{result.pipelineName || 'Pipeline'}{result.pipelineStatus ? ` · ${result.pipelineStatus}` : ''}</span>
            <span>
              {result.failedJob || 'Unknown job'}
              {result.failedStep ? ` / ${result.failedStep}` : ''}
            </span>
            <span>{result.confidence == null ? 'Confidence —' : `${result.confidence}% confidence`}</span>
          </div>

          {tests.length > 0 ? (
            <ol className="triage-test-list">
              {tests.map((test, index) => (
                <li key={test.fullName || `${test.title}-${index}`} className={`triage-test-card ${classTone(test.classification)}`}>
                  <div className="triage-test-top">
                    <span className="triage-test-index">Test {index + 1}</span>
                    <span className={`triage-pill ${classTone(test.classification)}`}>
                      {prettyClass(test.classification)}
                      {prettySubtype(test.subtype) ? ` · ${prettySubtype(test.subtype)}` : ''}
                    </span>
                    {test.owner ? <span className="triage-owner">Owner: {test.owner}</span> : null}
                  </div>
                  <h3 className="triage-test-title">{test.title}</h3>
                  {test.file ? <p className="meta triage-test-file">{test.file}</p> : null}
                  <div className="triage-test-body">
                    <div>
                      <div className="label">What happened</div>
                      <p>{test.whatHappened}</p>
                    </div>
                    <div>
                      <div className="label">Why it failed</div>
                      <p>{test.whyItFailed}</p>
                    </div>
                    <div>
                      <div className="label">What to do next</div>
                      <p>{test.recommendedAction}</p>
                    </div>
                  </div>
                  {(test.evidence && test.evidence.length > 0) || test.errorExcerpt ? (
                    <details className="triage-evidence-details">
                      <summary>Technical evidence</summary>
                      <ul className="triage-evidence">
                        {(test.evidence && test.evidence.length > 0 ? test.evidence : [test.errorExcerpt || '']).map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                </li>
              ))}
            </ol>
          ) : (
            <>
              <div className="triage-block">
                <div className="label">Recommended action</div>
                <p>{result.recommendedAction || '—'}</p>
              </div>
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
            </>
          )}

          {tests.length > 0 && result.recommendedAction ? (
            <div className="triage-block">
              <div className="label">Overall next step</div>
              <p>{result.recommendedAction}</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
