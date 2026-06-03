import os
from typing import List


def _parse_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(',') if item.strip()]


DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./qa_dashboard.db')
CORS_ORIGINS = _parse_csv(os.getenv('CORS_ORIGINS', '*'))
AUTO_CREATE_SCHEMA = os.getenv('AUTO_CREATE_SCHEMA', 'true').lower() == 'true'

# demo: seed script + simulator + UI demo control
# github: expect CI (GitHub Actions) to POST real results to ingestion endpoint(s)
DATA_SOURCE = os.getenv('DATA_SOURCE', 'demo').lower()

# Shared secret for CI ingestion. In production, set a strong value.
GITHUB_ACTIONS_INGEST_TOKEN = os.getenv('GITHUB_ACTIONS_INGEST_TOKEN', '')

# GitHub Actions trigger (workflow_dispatch). Token needs repo + actions:write.
GITHUB_CI_TOKEN = os.getenv('GITHUB_CI_TOKEN', '').strip()
GITHUB_CI_REPO = os.getenv('GITHUB_CI_REPO', '').strip()  # owner/repo
GITHUB_CI_WORKFLOW_FILE = os.getenv('GITHUB_CI_WORKFLOW_FILE', 'playwright.yml').strip()
GITHUB_CI_DEFAULT_REF = os.getenv('GITHUB_CI_DEFAULT_REF', 'main').strip() or 'main'


def github_ci_enabled() -> bool:
    return bool(GITHUB_CI_TOKEN and GITHUB_CI_REPO)
