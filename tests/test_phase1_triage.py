"""Phase 1: TestRun CI correlation and standalone TriageResult APIs."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_DB = tempfile.NamedTemporaryFile(prefix='qa_triage_test_', suffix='.db', delete=False)
os.environ['DATABASE_URL'] = f'sqlite:///{_DB.name}'
os.environ['AUTO_CREATE_SCHEMA'] = 'true'
os.environ['DATA_SOURCE'] = 'github'
os.environ['GITHUB_ACTIONS_INGEST_TOKEN'] = 'test-ingest-token'
os.environ['GITHUB_CI_TOKEN'] = ''

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import TriageResult  # noqa: E402

MOCK_PATH = ROOT / 'examples' / 'fixtures' / 'triage-result-32837090794.json'
TOKEN = {'X-Ingest-Token': 'test-ingest-token'}

BASE_RUN = {
    'suite_name': 'SelfHealing Playwright',
    'environment': 'CI',
    'build_version': 'abc123',
    'test_cases': [
        {'name': 'login', 'module': 'Auth', 'status': 'PASSED', 'duration_ms': 10},
    ],
}


class Phase1TriageApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)
        with MOCK_PATH.open(encoding='utf-8') as fh:
            cls.mock_payload = json.load(fh)

    def test_ingest_without_ci_is_backward_compatible(self):
        response = self.client.post('/api/ingest/github-actions/run', json=BASE_RUN, headers=TOKEN)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIsNone(body.get('ci'))
        self.assertEqual(body['status'], 'PASSED')

    def test_ingest_stores_and_returns_ci_identity(self):
        payload = {
            **BASE_RUN,
            'build_version': 'with-ci',
            'ci': {
                'provider': 'github-actions',
                'repository': 'mmohansqaai/SelfHealingPlaywrightFramework',
                'runId': '32837090794',
            },
        }
        response = self.client.post('/api/ingest/github-actions/run', json=payload, headers=TOKEN)
        self.assertEqual(response.status_code, 200, response.text)
        ci = response.json()['ci']
        self.assertEqual(ci['provider'], 'github-actions')
        self.assertEqual(ci['repository'], 'mmohansqaai/SelfHealingPlaywrightFramework')
        self.assertEqual(ci['runId'], '32837090794')

        summary = self.client.get('/api/summary').json()
        matched = [row for row in summary['latest_runs'] if row.get('ci') and row['ci']['runId'] == '32837090794']
        self.assertTrue(matched)
        self.assertEqual(matched[0]['status'], 'PASSED')

    def test_post_triage_requires_ingest_token(self):
        response = self.client.post('/api/triage/results', json=self.mock_payload)
        self.assertEqual(response.status_code, 401)
        response = self.client.post(
            '/api/triage/results',
            json=self.mock_payload,
            headers={'X-Ingest-Token': 'wrong'},
        )
        self.assertEqual(response.status_code, 401)

    def test_mock_triage_round_trip_and_upsert(self):
        created = self.client.post('/api/triage/results', json=self.mock_payload, headers=TOKEN)
        self.assertEqual(created.status_code, 200, created.text)
        first = created.json()
        self.assertEqual(first['runId'], '32837090794')
        self.assertEqual(first['triageState'], 'COMPLETED')
        self.assertEqual(first['classification'], 'CI_INFRASTRUCTURE')
        self.assertEqual(first['confidence'], 91)
        self.assertEqual(first['analysisMode'], 'DETERMINISTIC')
        self.assertFalse(first['humanReviewRequired'])
        self.assertEqual(first['failedStep'], 'Publish results to dashboard')
        self.assertEqual(first['pipelineStatus'], 'FAILED')

        fetched = self.client.get(
            '/api/triage/result',
            params={
                'provider': 'github-actions',
                'repository': 'mmohansqaai/SelfHealingPlaywrightFramework',
                'runId': '32837090794',
            },
        )
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()['id'], first['id'])

        updated_payload = dict(self.mock_payload)
        updated_payload['confidence'] = 95
        updated_payload['probableCause'] = 'Dashboard remained unreachable after retries.'
        updated = self.client.post('/api/triage/results', json=updated_payload, headers=TOKEN)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()['id'], first['id'])
        self.assertEqual(updated.json()['confidence'], 95)

        db = SessionLocal()
        try:
            count = db.query(TriageResult).filter(TriageResult.run_id == '32837090794').count()
            self.assertEqual(count, 1)
        finally:
            db.close()

        listed = self.client.get('/api/triage/results', params={'limit': 20})
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(any(item['runId'] == '32837090794' for item in listed.json()))

    def test_invalid_confidence_rejected(self):
        payload = dict(self.mock_payload)
        payload['runId'] = 'confidence-invalid'
        payload['confidence'] = 150
        response = self.client.post('/api/triage/results', json=payload, headers=TOKEN)
        self.assertEqual(response.status_code, 422)

    def test_missing_result_returns_404(self):
        response = self.client.get(
            '/api/triage/result',
            params={
                'provider': 'github-actions',
                'repository': 'mmohansqaai/SelfHealingPlaywrightFramework',
                'runId': 'does-not-exist',
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_completed_without_classification_rejected(self):
        payload = dict(self.mock_payload)
        payload['runId'] = 'incomplete-completed'
        payload['classification'] = None
        response = self.client.post('/api/triage/results', json=payload, headers=TOKEN)
        self.assertEqual(response.status_code, 422)


if __name__ == '__main__':
    unittest.main()
