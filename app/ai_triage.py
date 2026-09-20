"""Optional OpenAI-compatible enrichment for human-readable per-test triage."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx

from . import settings

ALLOWED_OWNERS = {'QE', 'Product', 'DevOps', 'CI', 'Human review'}


def _chat_url(base_url: str) -> str:
    trimmed = base_url.rstrip('/')
    if trimmed.endswith('/chat/completions'):
        return trimmed
    if trimmed.endswith('/v1'):
        return f'{trimmed}/chat/completions'
    return f'{trimmed}/v1/chat/completions'


def _compact_payload(triage: dict[str, Any]) -> dict[str, Any]:
    tests = []
    for item in triage.get('failed_tests') or []:
        tests.append(
            {
                'fullName': item.get('full_name'),
                'title': item.get('title'),
                'file': item.get('file'),
                'classification': getattr(item.get('classification'), 'value', item.get('classification')),
                'subtype': item.get('subtype'),
                'whatHappened': item.get('what_happened'),
                'whyItFailed': item.get('why_it_failed'),
                'recommendedAction': item.get('recommended_action'),
                'owner': item.get('owner'),
                'evidence': (item.get('evidence') or [])[:4],
            }
        )
    return {
        'pipeline': triage.get('pipeline_name'),
        'runId': triage.get('run_id'),
        'failedJob': triage.get('failed_job'),
        'failedStep': triage.get('failed_step'),
        'runClassification': getattr(triage.get('classification'), 'value', triage.get('classification')),
        'runSubtype': triage.get('subtype'),
        'executiveSummary': triage.get('executive_summary'),
        'tests': tests,
    }


def _parse_json_object(text: str) -> dict[str, Any]:
    trimmed = (text or '').strip()
    fenced = re.search(r'```(?:json)?\s*([\s\S]*?)```', trimmed, re.I)
    body = (fenced.group(1) if fenced else trimmed).strip()
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError('AI response is not a JSON object')
    return parsed


def _merge(triage: dict[str, Any], ai_payload: dict[str, Any]) -> dict[str, Any]:
    summary = str(ai_payload.get('runSummary') or '').strip()
    if summary:
        triage['executive_summary'] = summary[:800]
        triage['probable_cause'] = summary[:800]

    by_name: dict[str, dict[str, Any]] = {}
    for item in ai_payload.get('tests') or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get('fullName') or item.get('title') or '').strip()
        if key:
            by_name[key] = item

    merged_tests = []
    for item in triage.get('failed_tests') or []:
        match = by_name.get(item.get('full_name') or '') or by_name.get(item.get('title') or '')
        if match:
            what = str(match.get('whatHappened') or '').strip()
            why = str(match.get('whyItFailed') or '').strip()
            action = str(match.get('recommendedAction') or '').strip()
            owner = str(match.get('owner') or '').strip()
            if what:
                item['what_happened'] = what[:500]
            if why:
                item['why_it_failed'] = why[:500]
            if action:
                item['recommended_action'] = action[:500]
            if owner in ALLOWED_OWNERS:
                item['owner'] = owner
        merged_tests.append(item)
    if merged_tests:
        triage['failed_tests'] = merged_tests
        first = merged_tests[0]
        if first.get('recommended_action') and len(merged_tests) == 1:
            triage['recommended_action'] = first['recommended_action']
    return triage


async def enrich_triage(triage: dict[str, Any], client: Optional[httpx.AsyncClient] = None) -> dict[str, Any]:
    if not settings.ai_enabled():
        return triage
    compact = _compact_payload(triage)
    if not compact.get('tests'):
        return triage

    messages = {
        'model': settings.AI_MODEL,
        'temperature': 0,
        'response_format': {'type': 'json_object'},
        'messages': [
            {
                'role': 'system',
                'content': (
                    'You are a Quality Engineering triage writer. '
                    'Rewrite the compact CI failure evidence into a report a human can act on. '
                    'Use only the supplied JSON. Do not invent URLs, locators, expected values, files, or tests. '
                    'Keep the given classification for each test. '
                    'Return JSON with keys runSummary and tests. '
                    'tests items must include fullName matching an input fullName, whatHappened, whyItFailed, '
                    'recommendedAction, and owner (QE, Product, DevOps, CI, or Human review). '
                    'runSummary should be 2-4 plain sentences describing how many tests failed and whether causes differ.'
                ),
            },
            {'role': 'user', 'content': json.dumps(compact)},
        ],
    }

    url = _chat_url(settings.AI_BASE_URL)
    own_client = client is None
    http_client = client or httpx.AsyncClient(timeout=25.0)
    try:
        response = await http_client.post(
            url,
            headers={
                'Authorization': f'Bearer {settings.AI_API_KEY}',
                'Content-Type': 'application/json',
            },
            json=messages,
        )
        if response.status_code >= 400:
            return triage
        body = response.json()
        content = (((body.get('choices') or [{}])[0].get('message') or {}).get('content')) or ''
        parsed = _parse_json_object(content)
        enriched = _merge(triage, parsed)
        enriched['analysis_mode'] = 'AI_ASSISTED'
        return enriched
    except Exception:
        return triage
    finally:
        if own_client:
            await http_client.aclose()
