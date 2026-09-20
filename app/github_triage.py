"""Deterministic CI Failure Triage from GitHub Actions jobs, steps, and logs."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from . import ai_triage, github_ci, schemas

ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')
TIMESTAMP_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s+', re.M)
LOW_VALUE_RE = re.compile(
    r'demo_dashboard_failures|deprecationwarning|node\.js 20 is deprecated|ubuntu-latest label will migrate',
    re.I,
)
FAILURE_HEADER_RE = re.compile(r'^\s*(\d+)\)\s+\[([^\]]+)\]\s+›\s+(.+)$', re.M)
LOCATOR_RE = re.compile(r'Locator:\s*(.+)', re.I)
EXPECTED_RE = re.compile(r'Expected:\s+"([^"]*)"', re.I)
RECEIVED_RE = re.compile(r'Received:\s+"([^"]*)"', re.I)
URL_RE = re.compile(r'https?://[^\s]+')
ERROR_LINE_RE = re.compile(r'^(?:Error:|Expected:|Received:|Locator:|page\.goto:)', re.I)

Signature = tuple[str, str, int, int, bool, list[re.Pattern[str]], Optional[str]]

FRIENDLY_CLASS = {
    'AUTH_SECURITY': 'Authentication',
    'CI_INFRASTRUCTURE': 'CI / dashboard',
    'ENVIRONMENT': 'Environment',
    'AUTOMATION_DEFECT': 'Test script',
    'PRODUCT_DEFECT': 'Product',
    'UNKNOWN': 'Needs review',
}

FRIENDLY_SUBTYPE = {
    'TOKEN_OR_UNAUTHORIZED': 'Unauthorized or expired token',
    'DOWNSTREAM_SERVICE_UNAVAILABLE': 'Dashboard publish timed out',
    'HTTP_5XX_UNAVAILABLE': 'Service returned HTTP 5xx',
    'SERVICE_CONNECTION_REFUSED': 'App connection refused',
    'LOCATOR_FAILURE': 'Element not found',
    'ASSERTION_MISMATCH': 'Expected value did not match',
    'DOWNSTREAM_SERVICE': 'Publish / health-check failed',
    'RUNNER_SETUP': 'Runner setup failed',
    'INSUFFICIENT_EVIDENCE': 'Not enough log evidence',
}

OWNER_BY_CLASS = {
    'AUTOMATION_DEFECT': 'QE',
    'PRODUCT_DEFECT': 'Product',
    'ENVIRONMENT': 'DevOps',
    'CI_INFRASTRUCTURE': 'CI',
    'AUTH_SECURITY': 'DevOps',
    'UNKNOWN': 'Human review',
}


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
    matched: list[Signature] = []
    for rule in _signatures(is_test, is_downstream):
        if any(pattern.search(log_text) for pattern in rule[5]):
            matched.append(rule)
    matched.sort(key=lambda item: item[2])
    return matched


def _display_title(rest: str) -> str:
    parts = [part.strip() for part in rest.split('›') if part.strip()]
    title = parts[-1] if parts else rest
    return re.sub(r'\s+@[\w-]+$', '', title).strip() or rest


def _file_location(rest: str) -> Optional[str]:
    parts = [part.strip() for part in rest.split('›') if part.strip()]
    if parts and re.search(r'\.(spec|test)\.[jt]sx?:\d+', parts[0]):
        return parts[0]
    return None


def parse_playwright_failures(log_text: str) -> list[dict[str, str]]:
    headers = list(FAILURE_HEADER_RE.finditer(log_text))
    cases: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, match in enumerate(headers[:8]):
        start = match.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(log_text)
        body = log_text[start:end].strip()
        body = re.split(r'\n\s*\d+\s+failed\b', body, maxsplit=1)[0].strip()
        full_name = match.group(3).strip()
        if full_name in seen:
            continue
        seen.add(full_name)
        cases.append(
            {
                'project': match.group(2).strip(),
                'full_name': full_name,
                'title': _display_title(full_name),
                'file': _file_location(full_name) or '',
                'body': body,
            }
        )
    return cases


def _error_excerpt(body: str) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in body.splitlines():
        trimmed = re.sub(r'\s+', ' ', raw).strip()
        if not trimmed or trimmed in seen or LOW_VALUE_RE.search(trimmed):
            continue
        if ERROR_LINE_RE.search(trimmed) or 'ERR_CONNECTION_REFUSED' in trimmed or 'element(s) not found' in trimmed:
            seen.add(trimmed)
            lines.append(trimmed[:240])
        if len(lines) >= 4:
            break
    return lines


def _narrative_for(classification: str, subtype: str, body: str, title: str) -> tuple[str, str, str]:
    locator = (LOCATOR_RE.search(body) or [None, None])[1]
    expected = (EXPECTED_RE.search(body) or [None, None])[1]
    received = (RECEIVED_RE.search(body) or [None, None])[1]
    url_match = URL_RE.search(body)
    url = url_match.group(0).rstrip('.,)') if url_match else None

    if classification == 'AUTOMATION_DEFECT':
        target = locator or 'the expected UI element'
        what = f'The test “{title}” looked for {target} and it never appeared.'
        why = 'This is a locator/script mismatch with the current UI, not a backend outage.'
        action = 'Update the Playwright locator (or remove the assertion if the UI no longer has that element), then re-run this test.'
        return what, why, action
    if classification == 'PRODUCT_DEFECT':
        if expected is not None and received is not None:
            what = f'The test expected “{expected}” but the application showed “{received}”.'
        else:
            what = f'The test “{title}” compared an expected business value with what the app actually rendered, and they did not match.'
        why = 'This is a product vs test-expectation mismatch. A person needs to decide which one is correct.'
        action = 'Confirm with product whether the current application value is intended. If it is, update the test expectation; if not, file a product defect.'
        return what, why, action
    if classification == 'ENVIRONMENT' and subtype == 'SERVICE_CONNECTION_REFUSED':
        where = f' at {url}' if url else ''
        what = f'The browser could not open the application{where} because the connection was refused.'
        why = 'The app or a dependent service was not listening, so this test never reached the UI under test.'
        action = 'Confirm the target URL is deployed and reachable from GitHub Actions, then re-run this test.'
        return what, why, action
    if classification == 'ENVIRONMENT':
        what = f'The test “{title}” failed because a required service was unavailable.'
        why = 'This looks like environment unavailability rather than an assertion in the product UI.'
        action = 'Check the service health/logs for the environment used by CI, then re-run.'
        return what, why, action
    if classification == 'CI_INFRASTRUCTURE':
        what = 'A CI publishing or health-check step failed after (or instead of) the product tests.'
        why = 'The pipeline could not reach the dashboard or another downstream service.'
        action = 'Verify the dashboard ingest URL, token, and service availability, then re-run the workflow.'
        return what, why, action
    if classification == 'AUTH_SECURITY':
        what = 'The pipeline or tests received an authentication failure such as HTTP 401 or an invalid token.'
        why = 'Credentials used by CI are missing, expired, or unauthorized.'
        action = 'Refresh the token/secret used by this workflow, then re-run.'
        return what, why, action
    what = f'The test “{title}” failed, but the logs do not contain a specific known signature.'
    why = 'A failed Playwright step name alone is not enough to classify the defect.'
    action = 'Open the failed job logs and inspect the error for this test.'
    return what, why, action


def classify_test_case(case: dict[str, str], is_test: bool = True) -> dict[str, Any]:
    matches = _match_rules(case.get('body') or '', is_test=is_test, is_downstream=False)
    if matches:
        winner = matches[0]
        classification = winner[0]
        subtype = winner[1]
        confidence = winner[3]
        review = winner[4]
        priority = winner[2]
    else:
        classification = 'UNKNOWN'
        subtype = 'INSUFFICIENT_EVIDENCE'
        confidence = 20
        review = True
        priority = 999
    title = case.get('title') or case.get('full_name') or 'Failed test'
    what, why, action = _narrative_for(classification, subtype, case.get('body') or '', title)
    evidence = _error_excerpt(case.get('body') or '')
    return {
        'title': title,
        'full_name': case.get('full_name') or title,
        'file': case.get('file') or None,
        'classification': getattr(schemas.TriageClassification, classification),
        'subtype': subtype,
        'confidence': confidence,
        'what_happened': what,
        'why_it_failed': why,
        'recommended_action': action,
        'owner': OWNER_BY_CLASS.get(classification, 'Human review'),
        'evidence': evidence,
        'error_excerpt': evidence[0] if evidence else None,
        '_priority': priority,
        '_review': review,
        '_class_name': classification,
    }


def _run_summary(failed_tests: list[dict[str, Any]], mixed: bool, winner_label: str) -> str:
    count = len(failed_tests)
    if count == 0:
        return f'Primary signal is {winner_label.replace("_", " ").lower()} from the GitHub job logs.'
    if mixed:
        labels = []
        seen = set()
        for item in failed_tests:
            key = item['_class_name']
            if key in seen:
                continue
            seen.add(key)
            labels.append(FRIENDLY_CLASS.get(key, key).lower())
        return (
            f'{count} tests failed, and they do not share one root cause '
            f'({", ".join(labels)}). Review each test on its own before changing product or scripts.'
        )
    noun = 'test' if count == 1 else 'tests'
    return f'{count} failed {noun} point to the same area: {FRIENDLY_CLASS.get(winner_label, winner_label).lower()}.'


def _public_tests(failed_tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public = []
    for item in failed_tests:
        row = {key: value for key, value in item.items() if not key.startswith('_')}
        public.append(row)
    return public


def _cause_and_action(winner: Signature, mixed: bool, labels: list[str]) -> tuple[str, str]:
    if mixed:
        cause = (
            f"Multiple distinct failures were found ({'; '.join(labels)}). "
            f'Primary signal is {FRIENDLY_SUBTYPE.get(winner[1], winner[1].replace("_", " ").lower())}.'
        )
        action = 'Work the highest-priority failure first, then the other failed tests; they are separate issues.'
        return cause, action
    if winner[0] == 'ENVIRONMENT' and winner[1] == 'SERVICE_CONNECTION_REFUSED':
        return (
            'The target application or service refused connections and was unavailable during the run.',
            'Confirm the application is listening and reachable from CI, then re-run.',
        )
    if winner[0] == 'AUTOMATION_DEFECT':
        return (
            'A UI locator failed to target the intended element during test execution.',
            'Update the locator/test to match the current UI, then re-run.',
        )
    if winner[0] == 'PRODUCT_DEFECT':
        return (
            'A business assertion compared expected and actual values and they did not match.',
            'Have a human confirm whether the product behavior or the test expectation is wrong.',
        )
    if winner[0] == 'CI_INFRASTRUCTURE':
        return (
            'Downstream dashboard/service did not respond to health checks.',
            'Verify dashboard/health-check endpoint availability and retry publishing once the service recovers.',
        )
    if winner[0] == 'AUTH_SECURITY':
        return (
            'The pipeline or tests received an authentication failure such as HTTP 401 or an expired/invalid token.',
            'Refresh credentials, tokens, and secrets used by the pipeline, then re-run.',
        )
    return (
        'A known failure signature was matched in the GitHub job logs.',
        'Inspect the failed step logs and the matching signature evidence.',
    )


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

    parsed_cases = parse_playwright_failures(normalized) if is_test and normalized.strip() else []
    failed_tests = [classify_test_case(case, is_test=True) for case in parsed_cases]
    matches = _match_rules(normalized, is_test, is_downstream) if normalized.strip() else []
    related_failures: list[str] = []
    executive_summary = ''

    if failed_tests:
        winner_item = min(failed_tests, key=lambda item: item['_priority'])
        winner = (
            winner_item['_class_name'],
            winner_item['subtype'],
            winner_item['_priority'],
            winner_item['confidence'],
            winner_item['_review'],
            [],
            'test',
        )
        seen_class = {winner[0]}
        distinct = []
        for item in failed_tests:
            if item is winner_item or item['_class_name'] in seen_class:
                continue
            seen_class.add(item['_class_name'])
            distinct.append(f"{item['_class_name']}/{item['subtype']}")
        mixed = bool(distinct)
        classification = winner_item['classification']
        subtype = winner_item['subtype']
        confidence = min(winner_item['confidence'], 72) if mixed else winner_item['confidence']
        review = True if mixed else winner_item['_review']
        labels = [f'{winner[0]}/{winner[1]}'] + distinct
        cause, action = _cause_and_action(winner, mixed, labels)
        related_failures = distinct
        executive_summary = _run_summary(failed_tests, mixed, winner[0])
        evidence = [
            f'{len(failed_tests)} failed Playwright test{"s" if len(failed_tests) != 1 else ""}',
            f'Failed job: {failed_job or "unknown"}',
            f'Failed step: {failed_step or "unknown"}',
        ]
        if mixed:
            evidence.append(f'Related failures: {", ".join(distinct)}')
    elif matches:
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
        labels = [f'{winner[0]}/{winner[1]}'] + distinct
        cause, action = _cause_and_action(winner, mixed, labels)
        related_failures = distinct
        executive_summary = cause
        evidence = [
            f"GitHub conclusion: {flow.get('status')} / {flow.get('conclusion')}",
            f'Failed job: {failed_job or "unknown"}',
            f'Failed step: {failed_step or "unknown"}',
        ]
        if distinct:
            evidence.append(f'Related failures: {", ".join(distinct)}')
    elif is_downstream:
        classification = schemas.TriageClassification.CI_INFRASTRUCTURE
        subtype = 'DOWNSTREAM_SERVICE'
        cause, _why, action = _narrative_for('CI_INFRASTRUCTURE', subtype, '', failed_step or 'publish')
        confidence = 82
        review = False
        executive_summary = cause
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
        executive_summary = cause
        evidence = [
            f"GitHub conclusion: {flow.get('status')} / {flow.get('conclusion')}",
            f'Failed job: {failed_job or "unknown"}',
            f'Failed step: {failed_step or "unknown"}',
        ]
    else:
        classification = schemas.TriageClassification.UNKNOWN
        subtype = 'INSUFFICIENT_EVIDENCE'
        cause, _why, action = _narrative_for('UNKNOWN', subtype, '', failed_step or 'failed step')
        confidence = 20
        review = True
        executive_summary = cause
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
        'failed_tests': _public_tests(failed_tests) or None,
        'executive_summary': executive_summary or None,
        'created_at': now,
        'updated_at': now,
    }


async def derive_github_triage(repository: str, run_id: str) -> Optional[schemas.TriageResultResponse]:
    try:
        run_key = int(str(run_id).strip())
    except ValueError:
        return None
    cache_key = f'triage:{repository}:{run_id}'
    cached = github_ci._cache_get(cache_key)
    if cached is not None:
        return cached
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
    payload = await ai_triage.enrich_triage(payload)
    result = schemas.TriageResultResponse.model_validate(payload)
    ttl = 600 if str(flow.get('status') or '') in {'completed', 'cancelled'} else 8
    github_ci._cache_set(cache_key, result, ttl)
    return result
