from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .database import Base


class TestRun(Base):
    __tablename__ = 'test_runs'
    __table_args__ = (
        Index('ix_test_runs_ci_correlation', 'ci_provider', 'ci_repository', 'ci_run_id'),
    )

    id = Column(Integer, primary_key=True, index=True)
    suite_name = Column(String, index=True, nullable=False)
    environment = Column(String, index=True, nullable=False)
    build_version = Column(String, nullable=False)
    status = Column(String, default='RUNNING', nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    # Optional CI HTML report: public URL and/or single-file HTML body (served via GET /api/runs/{id}/html-report)
    html_report_url = Column(String, nullable=True)
    html_report_html = Column(Text, nullable=True)
    # Zipped multi-file HTML report (e.g. Playwright playwright-report/ folder).
    html_report_zip = Column(LargeBinary, nullable=True)
    html_report_index_path = Column(String, nullable=True)
    # Optional correlation to an external CI execution (not unique: one run may publish multiple result sets).
    ci_provider = Column(String, nullable=True)
    ci_repository = Column(String, nullable=True)
    ci_run_id = Column(String, nullable=True)

    test_cases = relationship('TestCaseResult', back_populates='run', cascade='all, delete-orphan')

    @property
    def ci(self):
        if self.ci_provider and self.ci_repository and self.ci_run_id:
            return {
                'provider': self.ci_provider,
                'repository': self.ci_repository,
                'runId': self.ci_run_id,
            }
        return None

    @property
    def has_html_report_inline(self) -> bool:
        return bool(self.html_report_html)

    @property
    def has_html_report_zip(self) -> bool:
        return bool(self.html_report_zip)


class TestCaseResult(Base):
    __tablename__ = 'test_case_results'

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey('test_runs.id'), nullable=False)
    name = Column(String, nullable=False)
    module = Column(String, nullable=False)
    status = Column(String, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    defect_id = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    run = relationship('TestRun', back_populates='test_cases')


class TriageResult(Base):
    """Standalone CI Failure Triage payload. No FK to TestRun: a pipeline may fail before ingest."""

    __tablename__ = 'triage_results'
    __table_args__ = (
        UniqueConstraint('provider', 'repository', 'run_id', name='uq_triage_results_correlation'),
    )

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=False)
    repository = Column(String, nullable=False)
    run_id = Column(String, nullable=False)
    triage_state = Column(String, nullable=False)
    pipeline_name = Column(String, nullable=True)
    pipeline_status = Column(String, nullable=True)
    failed_job = Column(String, nullable=True)
    failed_step = Column(String, nullable=True)
    classification = Column(String, nullable=True)
    subtype = Column(String, nullable=True)
    confidence = Column(Integer, nullable=True)
    probable_cause = Column(Text, nullable=True)
    evidence = Column(JSON, nullable=True)
    recommended_action = Column(Text, nullable=True)
    human_review_required = Column(Boolean, nullable=True)
    analysis_mode = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
