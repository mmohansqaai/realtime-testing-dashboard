from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


# Guardrail for JSON ingest body size; raise MAX_HTML_REPORT_CHARS if you need larger uploads.
MAX_HTML_REPORT_CHARS = 12_000_000


class TestCaseCreate(BaseModel):
    name: str
    module: str
    status: str
    duration_ms: int
    defect_id: Optional[str] = None


class CiIdentity(BaseModel):
    """External CI execution identity. JSON uses runId; columns stay snake_case."""

    model_config = ConfigDict(populate_by_name=True)

    provider: str
    repository: str
    run_id: str = Field(validation_alias='runId', serialization_alias='runId')

    @field_validator('provider', 'repository', mode='before')
    @classmethod
    def strip_required(cls, v: Any) -> str:
        if v is None:
            raise ValueError('must be non-empty')
        s = str(v).strip()
        if not s:
            raise ValueError('must be non-empty')
        return s

    @field_validator('run_id', mode='before')
    @classmethod
    def coerce_run_id(cls, v: Any) -> str:
        if v is None:
            raise ValueError('must be non-empty')
        s = str(v).strip()
        if not s:
            raise ValueError('must be non-empty')
        return s


class TestRunCreate(BaseModel):
    suite_name: str
    environment: str
    build_version: str
    test_cases: list[TestCaseCreate]
    # Optional: link to a hosted HTML report (e.g. GitHub Pages, public artifact URL).
    html_report_url: Optional[str] = None
    # Optional: single-file HTML body for inline viewing on the dashboard (pytest-html, etc.).
    html_report_html: Optional[str] = Field(default=None, max_length=MAX_HTML_REPORT_CHARS)
    ci: Optional[CiIdentity] = None

    @field_validator('html_report_url')
    @classmethod
    def trim_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        return s or None


class TestCaseResponse(TestCaseCreate):
    id: int
    updated_at: datetime

    class Config:
        from_attributes = True


class TestRunResponse(BaseModel):
    id: int
    suite_name: str
    environment: str
    build_version: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    test_cases: list[TestCaseResponse]
    html_report_url: Optional[str] = None
    has_html_report_inline: bool = False
    has_html_report_zip: bool = False
    html_report_index_path: Optional[str] = None
    ci: Optional[CiIdentity] = None

    class Config:
        from_attributes = True


class CiTriggerRequest(BaseModel):
    ref: Optional[str] = None
    workflow_file: Optional[str] = None
    inputs: Optional[dict[str, str]] = None


class CiStepFlow(BaseModel):
    number: int
    name: str
    status: str
    conclusion: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class CiJobFlow(BaseModel):
    id: int
    name: str
    status: str
    conclusion: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    html_url: Optional[str] = None
    steps: list[CiStepFlow] = []


class CiRunFlow(BaseModel):
    id: int
    name: str
    status: str
    conclusion: Optional[str] = None
    html_url: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    run_started_at: Optional[str] = None
    run_attempt: Optional[int] = None
    event: Optional[str] = None
    head_branch: Optional[str] = None
    head_sha: Optional[str] = None
    jobs: list[CiJobFlow] = []


class TriageState(str, Enum):
    NOT_STARTED = 'NOT_STARTED'
    ANALYZING = 'ANALYZING'
    COMPLETED = 'COMPLETED'
    REVIEW_REQUIRED = 'REVIEW_REQUIRED'
    FAILED_TO_ANALYZE = 'FAILED_TO_ANALYZE'


class TriageClassification(str, Enum):
    PRODUCT_DEFECT = 'PRODUCT_DEFECT'
    AUTOMATION_DEFECT = 'AUTOMATION_DEFECT'
    FLAKY_TEST = 'FLAKY_TEST'
    TEST_DATA = 'TEST_DATA'
    ENVIRONMENT = 'ENVIRONMENT'
    CI_INFRASTRUCTURE = 'CI_INFRASTRUCTURE'
    DEPENDENCY_CONFIG = 'DEPENDENCY_CONFIG'
    AUTH_SECURITY = 'AUTH_SECURITY'
    UNKNOWN = 'UNKNOWN'


class AnalysisMode(str, Enum):
    DETERMINISTIC = 'DETERMINISTIC'
    AI_ASSISTED = 'AI_ASSISTED'


class TriageResultWrite(BaseModel):
    """Inbound TriageResult from the CI Failure Triage platform (camelCase JSON)."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel, use_enum_values=True)

    provider: str
    repository: str
    run_id: str
    triage_state: TriageState
    pipeline_name: Optional[str] = None
    pipeline_status: Optional[str] = None
    failed_job: Optional[str] = None
    failed_step: Optional[str] = None
    classification: Optional[TriageClassification] = None
    subtype: Optional[str] = None
    confidence: Optional[int] = Field(default=None, ge=0, le=100)
    probable_cause: Optional[str] = None
    evidence: Optional[Any] = None
    recommended_action: Optional[str] = None
    human_review_required: Optional[bool] = None
    analysis_mode: Optional[AnalysisMode] = None
    related_failures: Optional[list[str]] = None

    @field_validator('provider', 'repository', mode='before')
    @classmethod
    def strip_required(cls, v: Any) -> str:
        if v is None:
            raise ValueError('must be non-empty')
        s = str(v).strip()
        if not s:
            raise ValueError('must be non-empty')
        return s

    @field_validator('run_id', mode='before')
    @classmethod
    def coerce_run_id(cls, v: Any) -> str:
        if v is None:
            raise ValueError('must be non-empty')
        s = str(v).strip()
        if not s:
            raise ValueError('must be non-empty')
        return s

    @model_validator(mode='after')
    def completed_fields(self):
        state = self.triage_state.value if isinstance(self.triage_state, Enum) else self.triage_state
        terminal = {'COMPLETED', 'REVIEW_REQUIRED'}
        if state in terminal:
            missing = []
            if self.classification is None:
                missing.append('classification')
            if self.confidence is None:
                missing.append('confidence')
            if self.analysis_mode is None:
                missing.append('analysisMode')
            if missing:
                raise ValueError(f'{state} results require {", ".join(missing)}')
        if state == 'REVIEW_REQUIRED' and self.human_review_required is not True:
            raise ValueError('REVIEW_REQUIRED requires humanReviewRequired=true')
        return self


class TriageResultResponse(TriageResultWrite):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        from_attributes=True,
        use_enum_values=True,
    )

    id: int
    created_at: datetime
    updated_at: datetime
