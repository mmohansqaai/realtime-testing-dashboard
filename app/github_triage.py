"""Deterministic CI Failure Triage from GitHub Actions job/step conclusions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from . import github_ci, schemas


def _first_failure(flow: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    for job in flow.get('jobs') or []:
        for step in job.get('steps') or []:
            if step.get('conclusion') == 'failure':
                return job.get('name'), step.get('name') or f"Step {step.get('number')}"
        if job.get('conclusion') == 'failure':
            return job.get('name'), None
    return None, None


def classify_github_flow(flow: dict[str, Any]) -> Optional[dict[str, Any]]:
    conclusion = (flow.get('conclusion') or '').lower()
    if conclusion in {'', 'success', 'skipped'}:
        return None
    if (flow.get('status') or '').lower() not in {'completed', 'cancelled'}:
        return None

    failed_job, failed_step = _first_failure(flow)
    blob = f'{failed_job or ""} {failed_step or ""}'.lower()

    if any(token in blob for token in ('publish', 'dashboard', 'ingest', 'health', 'curl')):
        classification = schemas.TriageClassification.CI_INFRASTRUCTURE
        subtype = 'DOWNSTREAM_SERVICE'
        cause = 'A CI publishing or health-check step failed after tests, not the product under test.'
        action = 'Check the dashboard ingest URL, token, and service availability, then re-run the workflow.'
        confidence = 82
        review = False
    elif any(token in blob for token in ('setup', 'checkout', 'install', 'node', 'browser', 'cache')):
        classification = schemas.TriageClassification.ENVIRONMENT
        subtype = 'RUNNER_SETUP'
        cause = 'The GitHub runner failed while preparing the environment before or around test execution.'
        action = 'Inspect the failed setup step logs, pin action versions, and retry the job.'
        confidence = 76
        review = True
    elif any(token in blob for token in ('playwright', 'test', 'spec', 'e2e')):
        classification = schemas.TriageClassification.AUTOMATION_DEFECT
        subtype = 'PLAYWRIGHT_TEST_FAILURE'
        cause = 'GitHub reports the Playwright test step failed. This is a test/automation failure, not a pipeline setup outage.'
        action = 'Open the Playwright HTML report and the failed spec, then fix the assertion or the application behavior.'
        confidence = 88
        review = False
    else:
        classification = schemas.TriageClassification.UNKNOWN
        subtype = 'UNCLASSIFIED_STEP'
        cause = 'A GitHub Actions step failed, but the step name does not match a known pattern.'
        action = 'Open the failed job on GitHub and inspect the step logs.'
        confidence = 55
        review = True

    now = datetime.utcnow()
    return {
        'id': 0,
        'provider': 'github-actions',
        'repository': '',
        'run_id': str(flow.get('id') or ''),
        'triage_state': schemas.TriageState.COMPLETED,
        'pipeline_name': flow.get('name'),
        'pipeline_status': 'FAILED' if conclusion == 'failure' else conclusion.upper(),
        'failed_job': failed_job,
        'failed_step': failed_step,
        'classification': classification,
        'subtype': subtype,
        'confidence': confidence,
        'probable_cause': cause,
        'evidence': [
            f"GitHub conclusion: {flow.get('status')} / {flow.get('conclusion')}",
            f"Failed job: {failed_job or 'unknown'}",
            f"Failed step: {failed_step or 'unknown'}",
        ],
        'recommended_action': action,
        'human_review_required': review,
        'analysis_mode': schemas.AnalysisMode.DETERMINISTIC,
        'created_at': now,
        'updated_at': now,
    }


async def derive_github_triage(repository: str, run_id: str) -> Optional[schemas.TriageResultResponse]:
    try:
        run_key = int(str(run_id).strip())
    except ValueError:
        return None
    try:
        flow = await github_ci.get_run_flow(run_key)
    except github_ci.GitHubCiError:
        return None
    payload = classify_github_flow(flow)
    if not payload:
        return None
    payload['repository'] = repository
    payload['run_id'] = str(run_id)
    payload['provider'] = 'github-actions'
    return schemas.TriageResultResponse.model_validate(payload)
