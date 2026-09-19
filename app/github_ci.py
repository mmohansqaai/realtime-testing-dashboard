"""GitHub Actions API: trigger workflows and fetch run/job/step status."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx

from .settings import (
    GITHUB_CI_DEFAULT_REF,
    GITHUB_CI_REPO,
    GITHUB_CI_TOKEN,
    GITHUB_CI_WORKFLOW_FILE,
    github_ci_enabled,
)


_CACHE: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str) -> Any:
    item = _CACHE.get(key)
    if not item:
        return None
    expires, value = item
    if expires < time.monotonic():
        _CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Any, ttl_seconds: float) -> None:
    _CACHE[key] = (time.monotonic() + ttl_seconds, value)


class GitHubCiError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _require_ci() -> tuple[str, str, str]:
    if not github_ci_enabled():
        raise GitHubCiError(
            'CI trigger is not configured. Set GITHUB_CI_TOKEN and GITHUB_CI_REPO on the API server.',
            status_code=503,
        )
    assert GITHUB_CI_TOKEN and GITHUB_CI_REPO
    return GITHUB_CI_TOKEN, GITHUB_CI_REPO, GITHUB_CI_WORKFLOW_FILE


def _headers(token: str) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }


async def _request(
    method: str,
    path: str,
    *,
    token: str,
    json_body: Optional[dict] = None,
    params: Optional[dict] = None,
) -> Any:
    url = f'https://api.github.com{path}'
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.request(
            method,
            url,
            headers=_headers(token),
            json=json_body,
            params=params,
        )
    if response.status_code >= 400:
        detail = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict) and payload.get('message'):
                detail = str(payload['message'])
        except Exception:
            pass
        hint = ''
        if response.status_code == 403 and 'rate limit' not in detail.lower():
            hint = (
                ' Regenerated classic PAT needs scopes repo + workflow. '
                'Fine-grained PAT needs this repo and Actions = Read and write. '
                'Org SSO: authorize the token on GitHub → Settings → Developer settings.'
            )
        raise GitHubCiError(f'GitHub API {response.status_code}: {detail}.{hint}', status_code=response.status_code)
    if response.status_code == 204:
        return None
    return response.json()


def ci_config() -> dict[str, Any]:
    enabled = github_ci_enabled()
    return {
        'enabled': enabled,
        'repo': GITHUB_CI_REPO if enabled else None,
        'default_workflow_file': GITHUB_CI_WORKFLOW_FILE if enabled else None,
        'default_ref': GITHUB_CI_DEFAULT_REF if enabled else 'main',
    }


async def list_workflows() -> list[dict[str, Any]]:
    cached = _cache_get('workflows')
    if cached is not None:
        return cached
    token, repo, _ = _require_ci()
    data = await _request('GET', f'/repos/{repo}/actions/workflows', token=token, params={'per_page': 30})
    workflows = []
    for wf in data.get('workflows', []):
        workflows.append(
            {
                'id': wf.get('id'),
                'name': wf.get('name'),
                'path': wf.get('path'),
                'state': wf.get('state'),
            }
        )
    _cache_set('workflows', workflows, 600)
    return workflows


async def trigger_workflow(
    *,
    ref: Optional[str] = None,
    workflow_file: Optional[str] = None,
    inputs: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    token, repo, default_wf = _require_ci()
    wf_file = (workflow_file or default_wf).strip()
    if not wf_file:
        raise GitHubCiError('workflow_file is required', status_code=400)
    branch = (ref or GITHUB_CI_DEFAULT_REF).strip() or 'main'

    await _request(
        'POST',
        f'/repos/{repo}/actions/workflows/{wf_file}/dispatches',
        token=token,
        json_body={'ref': branch, 'inputs': inputs or {}},
    )

    await asyncio.sleep(2.0)
    run = await _find_latest_run(token, repo, wf_file)
    return {
        'message': 'Workflow dispatched',
        'repo': repo,
        'workflow_file': wf_file,
        'ref': branch,
        'run_id': run['id'] if run else None,
        'html_url': run.get('html_url') if run else None,
    }


async def _find_latest_run(token: str, repo: str, workflow_file: str) -> Optional[dict[str, Any]]:
    data = await _request(
        'GET',
        f'/repos/{repo}/actions/workflows/{workflow_file}/runs',
        token=token,
        params={'per_page': 5},
    )
    runs = data.get('workflow_runs') or []
    return runs[0] if runs else None


async def list_recent_runs(*, limit: int = 10, workflow_file: Optional[str] = None) -> list[dict[str, Any]]:
    token, repo, default_wf = _require_ci()
    wf = workflow_file or default_wf
    cache_key = f'runs:{wf}:{limit}'
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    path = f'/repos/{repo}/actions/workflows/{wf}/runs' if wf else f'/repos/{repo}/actions/runs'
    data = await _request('GET', path, token=token, params={'per_page': min(limit, 30)})
    runs = [_map_run_summary(r) for r in data.get('workflow_runs', [])]
    _cache_set(cache_key, runs, 45)
    return runs


async def get_run_flow(run_id: int) -> dict[str, Any]:
    cache_key = f'flow:{run_id}'
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    token, repo, _ = _require_ci()
    run_data = await _request('GET', f'/repos/{repo}/actions/runs/{run_id}', token=token)
    jobs_data = await _request('GET', f'/repos/{repo}/actions/runs/{run_id}/jobs', token=token)
    jobs = []
    for job in jobs_data.get('jobs', []):
        steps = []
        for step in job.get('steps', []):
            steps.append(
                {
                    'number': step.get('number'),
                    'name': step.get('name'),
                    'status': step.get('status'),
                    'conclusion': step.get('conclusion'),
                    'started_at': step.get('started_at'),
                    'completed_at': step.get('completed_at'),
                }
            )
        jobs.append(
            {
                'id': job.get('id'),
                'name': job.get('name'),
                'status': job.get('status'),
                'conclusion': job.get('conclusion'),
                'started_at': job.get('started_at'),
                'completed_at': job.get('completed_at'),
                'html_url': job.get('html_url'),
                'steps': steps,
            }
        )
    flow = _map_run_summary(run_data)
    flow['jobs'] = jobs
    flow['event'] = run_data.get('event')
    flow['head_branch'] = run_data.get('head_branch')
    flow['head_sha'] = (run_data.get('head_sha') or '')[:7]
    ttl = 600 if flow.get('status') in {'completed', 'cancelled'} else 8
    _cache_set(cache_key, flow, ttl)
    return flow


def _map_run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': run.get('id'),
        'name': run.get('name'),
        'status': run.get('status'),
        'conclusion': run.get('conclusion'),
        'html_url': run.get('html_url'),
        'created_at': run.get('created_at'),
        'updated_at': run.get('updated_at'),
        'run_started_at': run.get('run_started_at'),
        'run_attempt': run.get('run_attempt'),
    }
