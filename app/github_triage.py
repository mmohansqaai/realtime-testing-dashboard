"""Deterministic CI Failure Triage from GitHub Actions jobs, steps, and logs."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from . import github_ci, schemas

ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')
TIMESTAMP_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s+', re.M)
LOW_VALUE_RE = re.compile(
    r'demo_dashboard_failures|deprecationwarning|node\.js 20 is deprecated|ubuntu-latest label will migrate',
    re.I,
)

Signature = tuple[str, str, int, int, bool, list[re.Pattern[str]], Optional[str]]


def _first_failure(flow: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    for job in flow.get('jobs') or []:
        for step in job.get('steps') or []:
            if step.get('conclusion') == 'failure':
                return job.get('name'), step.get('name') or f"Step {step.get('number')}"
        if job.get('conclusion') == 'failure':
            return job.get('name'), None
    return None, None


def _normalize_log(text: str) -> str:
    cleaned = ANSI_RE.sub('', text or '')
    return TIMESTAMP_RE.sub('', cleaned)


def _is_test_stage(blob: str) -> bool:
    return any(token in blob for token in ('playwright', 'test', 'spec', 'e2e'))


def _is_downstream_stage(blob: str) -> bool:
    return any(token in blob for token in ('publish', 'dashboard', 'ingest', 'health', 'curl'))


def _is_setup_stage(blob: str) -> bool:
    return any(token in blob for token in ('setup', 'checkout', 'install', 'node', 'browser', 'cache'))


def _signatures(is_test: bool, is_downstream: bool) -> list[Signature]:
    auth = [
        re.compile(r'401\s*Unauthorized', re.I),
        re.compile(r'Request failed with status code 401', re.I),
        re.compile(r'token(?: has)? expired', re.I),
        re.compile(r'invalid(?: or expired)? token', re.I),
        re.compile(r'authentication failed', re.I),
    ]
    downstream = [
        re.compile(r'curl:\s*\(28\)', re.I),
        re.compile(r'exit code 28', re.I),
        re.compile(r'operation timed out', re.I),
    ]
    env_5xx = [
        re.compile(r'Request failed with status code 50[0234]', re.I),
        re.compile(r'50[0234]\s*Service Unavailable', re.I),
        re.compile(r'service unavailable', re.I),
    ]
    env_conn = [
        re.compile(r'net::ERR_CONNECTION_REFUSED', re.I),
        re.compile(r'ERR_CONNECTION_REFUSED', re.I),
        re.compile(r'ECONNREFUSED'),
        re.compile(r'connection refused', re.I),
    ]
    automation_locator = [
        re.compile(r'expect\(locator\)\.toBeVisible', re.I),
        re.compile(r'waiting for getBy(?:Role|Text|Label|Placeholder|TestId)', re.I),
        re.compile(r'waiting for locator', re.I),
        re.compile(r'toBeVisible\(\) failed', re.I),
        re.compile(r'element(?:\(s\))? not found', re.I),
        re.compile(r'strict mode violation', re.I),
    ]
    product = [
        re.compile(r'expect\(received\)\.to(?:Be|Equal|StrictEqual|Contain)', re.I),
        re.compile(r'Expected:\s+".+"\s+Received:\s+".+"', re.I | re.S),
        re.compile(r'AssertionError', re.I),
    ]

    rules: list[Signature] = [
        ('AUTH_SECURITY', 'TOKEN_OR_UNAUTHORIZED', 10, 88, False, auth, None),
        ('CI_INFRASTRUCTURE', 'DOWNSTREAM_SERVICE_UNAVAILABLE', 20, 91, False, downstream, 'downstream'),
        ('ENVIRONMENT', 'HTTP_5XX_UNAVAILABLE', 30, 84, False, env_5xx, None),
        ('ENVIRONMENT', 'SERVICE_CONNECTION_REFUSED', 31, 83, False, env_conn, 'test'),
        ('AUTOMATION_DEFECT', 'LOCATOR_FAILURE', 60, 85, False, automation_locator, 'test'),
        ('PRODUCT_DEFECT', 'ASSERTION_MISMATCH', 80, 62, True, product, 'test'),
    ]
    applicable: list[Signature] = []
    for rule in rules:
        applies = rule[6]
        if applies == 'downstream' and not is_downstream:
            continue
        if applies == 'test' and not is_test:
            continue
        applicable.append(rule)
    return applicable


def _match_rules(log_text: str, is_test: bool, is_downstream: bool) -> list[Signature]:
    haystack = log_text
    matched: list[Signature] = []
    for rule in _signatures(is_test, is_downstream):
        if any(pattern.search(haystack) for pattern in rule[5]):
            matched.append(rule)
    matched.sort(key=lambda item: item[2])
    return matched


def _failed_playwright_tests(log_text: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'^\s*\d+\)\s+\[[^\]]+\]\s+›\s+(.+)$', log_text, re.M):
        name = match.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names[:5]


def _evidence_lines(log_text: str, matches: list[Signature], failed_tests: list[str]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        text = re.sub(r'\s+', ' ', item).strip()
        if not text or text in seen or LOW_VALUE_RE.search(text):
            return
        seen.add(text)
        lines.append(text[:240])

    for test_name in failed_tests:
        add(f'Failed Playwright test: {test_name}')
    for rule in matches:
        add(f'Matched {rule[0]}/{rule[1]}')

    high_value = re.compile(
        r'toBeVisible|element\(s\) not found|getByRole|ERR_CONNECTION_REFUSED|Expected:\s+"|Received:\s+"|curl:\s*\(28\)|exit code 28|strict mode|401 Unauthorized|503',
        re.I,
    )
    for raw in log_text.splitlines():
        trimmed = raw.strip()
        if high_value.search(trimmed):
            add(trimmed)
    return lines[:8]


def classify_github_flow(flow: dict[str, Any], log_text: str = '') -> Optional[dict[str, Any]]:
    conclusion = (flow.get('conclusion') or '').lower()
    if conclusion in {'', 'success', 'skipped'}:
        return None
    if (flow.get('status') or '').lower() not in {'completed', 'cancelled'}:
        return None

    failed_job, failed_step = _first_failure(flow)
    step_blob = (failed_step or '').lower()
    job_blob = (failed_job or '').lower()
    is_test = _is_test_stage(step_blob) or (not failed_step and _is_test_stage(job_blob))
    is_downstream = _is_downstream_stage(step_blob) or (not failed_step and _is_downstream_stage(job_blob))
    is_setup = _is_setup_stage(step_blob) or (not failed_step and _is_setup_stage(job_blob))
    normalized = _normalize_log(log_text)
    matches = _match_rules(normalized, is_test, is_downstream) if normalized.strip() else []

    if matches:
        winner = matches[0]
        distinct = []
        seen_class = {winner[0]}
        for rule in matches[1:]:
            if rule[0] not in seen_class:
                seen_class.add(rule[0])
                distinct.append(f'{rule[0]}/{rule[1]}')
        mixed = bool(distinct)
        classification = getattr(schemas.TriageClassification, winner[0])
        subtype = winner[1]
        confidence = min(winner[3], 72) if mixed else winner[3]
        review = True if mixed else winner[4]
        if mixed:
            labels = [f'{winner[0]}/{winner[1]}'] + distinct
            cause = (
                f"Multiple distinct failures were found ({'; '.join(labels)}). "
                f'Primary signal is {winner[1].replace("_", " ").lower()} from the GitHub job logs.'
            )
            action = (
                'Inspect the primary failure first, then review the other failed tests; '
                'they do not share a single root cause.'
            )
        elif winner[0] == 'ENVIRONMENT' and winner[1] == 'SERVICE_CONNECTION_REFUSED':
            cause = 'The target application or service refused connections and was unavailable during the run.'
            action = 'Confirm the application is listening and reachable from CI, then re-run.'
        elif winner[0] == 'AUTOMATION_DEFECT':
            cause = 'A UI locator failed to target the intended element during test execution.'
            action = 'Update the locator/test to match the current UI, then re-run.'
        elif winner[0] == 'PRODUCT_DEFECT':
            cause = 'A business assertion compared expected and actual values and they did not match.'
            action = 'Have a human confirm whether the product behavior or the test expectation is wrong.'
        elif winner[0] == 'CI_INFRASTRUCTURE':
            cause = 'Downstream dashboard/service did not respond to health checks.'
            action = 'Verify dashboard/health-check endpoint availability and retry publishing once the service recovers.'
        elif winner[0] == 'AUTH_SECURITY':
            cause = 'The pipeline or tests received an authentication failure such as HTTP 401 or an expired/invalid token.'
            action = 'Refresh credentials, tokens, and secrets used by the pipeline, then re-run.'
        else:
            cause = 'A known failure signature was matched in the GitHub job logs.'
            action = 'Inspect the failed step logs and the matching signature evidence.'
        failed_tests = _failed_playwright_tests(normalized)
        evidence = [
            f"GitHub conclusion: {flow.get('status')} / {flow.get('conclusion')}",
            f'Failed job: {failed_job or "unknown"}',
            f'Failed step: {failed_step or "unknown"}',
            *([f'Related failures: {", ".join(distinct)}'] if distinct else []),
            *_evidence_lines(normalized, matches, failed_tests),
        ]
        related_failures = distinct
    elif is_downstream:
        classification = schemas.TriageClassification.CI_INFRASTRUCTURE
        subtype = 'DOWNSTREAM_SERVICE'
        cause = 'A CI publishing or health-check step failed after tests, not the product under test.'
        action = 'Check the dashboard ingest URL, token, and service availability, then re-run the workflow.'
        confidence = 82
        review = False
        related_failures = []
        evidence = [
            f"GitHub conclusion: {flow.get('status')} / {flow.get('conclusion')}",
            f'Failed job: {failed_job or "unknown"}',
            f'Failed step: {failed_step or "unknown"}',
        ]
    elif is_setup and not is_test:
        classification = schemas.TriageClassification.ENVIRONMENT
        subtype = 'RUNNER_SETUP'
        cause = 'The GitHub runner failed while preparing the environment before or around test execution.'
        action = 'Inspect the failed setup step logs, pin action versions, and retry the job.'
        confidence = 76
        review = True
        related_failures = []
        evidence = [
            f"GitHub conclusion: {flow.get('status')} / {flow.get('conclusion')}",
            f'Failed job: {failed_job or "unknown"}',
            f'Failed step: {failed_step or "unknown"}',
        ]
    else:
        classification = schemas.TriageClassification.UNKNOWN
        subtype = 'INSUFFICIENT_EVIDENCE'
        cause = (
            'A GitHub Actions step failed, but job logs do not contain a specific failure signature. '
            'A failed Playwright step is not enough to classify an automation defect.'
        )
        action = 'Open the failed job logs on GitHub and inspect the actual test or step error.'
        confidence = 20
        review = True
        related_failures = []
        evidence = [
            f"GitHub conclusion: {flow.get('status')} / {flow.get('conclusion')}",
            f'Failed job: {failed_job or "unknown"}',
            f'Failed step: {failed_step or "unknown"}',
        ]

    now = datetime.utcnow()
    state = schemas.TriageState.REVIEW_REQUIRED if review else schemas.TriageState.COMPLETED
    return {
        'id': 0,
        'provider': 'github-actions',
        'repository': '',
        'run_id': str(flow.get('id') or ''),
        'triage_state': state,
        'pipeline_name': flow.get('name'),
        'pipeline_status': 'FAILED' if conclusion == 'failure' else conclusion.upper(),
        'failed_job': failed_job,
        'failed_step': failed_step,
        'classification': classification,
        'subtype': subtype,
        'confidence': confidence,
        'probable_cause': cause,
        'evidence': evidence,
        'recommended_action': action,
        'human_review_required': review,
        'analysis_mode': schemas.AnalysisMode.DETERMINISTIC,
        'related_failures': related_failures or None,
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
        log_text = await github_ci.get_failed_job_logs(flow)
    except github_ci.GitHubCiError:
        return None
    payload = classify_github_flow(flow, log_text)
    if not payload:
        return None
    payload['repository'] = repository
    payload['run_id'] = str(run_id)
    payload['provider'] = 'github-actions'
    return schemas.TriageResultResponse.model_validate(payload)
