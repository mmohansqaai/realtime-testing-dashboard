from datetime import datetime
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload, undefer

from .models import TestCaseResult, TestRun, TriageResult
from .settings import DATA_SOURCE

FINAL_STATUSES = {'PASSED', 'FAILED', 'BLOCKED', 'SKIPPED'}


def _ci_identity(run: TestRun):
    if run.ci_provider and run.ci_repository and run.ci_run_id:
        return {
            'provider': run.ci_provider,
            'repository': run.ci_repository,
            'runId': run.ci_run_id,
        }
    return None


def create_run(db: Session, payload, report_zip: Optional[bytes] = None):
    index_path = None
    if report_zip is not None:
        from .report_zip import validate_report_zip_bytes

        index_path = validate_report_zip_bytes(report_zip)

    ci = payload.ci
    run = TestRun(
        suite_name=payload.suite_name,
        environment=payload.environment,
        build_version=payload.build_version,
        status='RUNNING',
        html_report_url=payload.html_report_url,
        html_report_html=payload.html_report_html,
        html_report_zip=report_zip,
        html_report_index_path=index_path,
        ci_provider=ci.provider if ci else None,
        ci_repository=ci.repository if ci else None,
        ci_run_id=ci.run_id if ci else None,
    )
    db.add(run)
    db.flush()

    for tc in payload.test_cases:
        db.add(
            TestCaseResult(
                run_id=run.id,
                name=tc.name,
                module=tc.module,
                status=tc.status,
                duration_ms=tc.duration_ms,
                defect_id=tc.defect_id,
            )
        )

    db.commit()
    db.refresh(run)
    run_full = get_run(db, run.id)
    _recompute_run_status(db, run_full)
    return get_run(db, run.id)


def get_run(db: Session, run_id: int):
    return (
        db.query(TestRun)
        .options(
            joinedload(TestRun.test_cases),
            undefer(TestRun.html_report_zip),
            undefer(TestRun.html_report_html),
        )
        .filter(TestRun.id == run_id)
        .first()
    )


def get_runs(db: Session, limit: int = 10):
    q = db.query(TestRun).options(joinedload(TestRun.test_cases))
    # In github mode, show CI runs first so the feed is not dominated by old seeded rows.
    if DATA_SOURCE == 'github':
        q = q.order_by(
            case((TestRun.environment == 'CI', 0), else_=1),
            TestRun.started_at.desc(),
        )
    else:
        q = q.order_by(TestRun.started_at.desc())
    return q.limit(limit).all()


def update_case_status(db: Session, case_id: int, status: str, duration_ms: Optional[int] = None, defect_id: Optional[str] = None):
    case = db.query(TestCaseResult).filter(TestCaseResult.id == case_id).first()
    if not case:
        return None
    case.status = status
    case.updated_at = datetime.utcnow()
    if duration_ms is not None:
        case.duration_ms = duration_ms
    if defect_id is not None:
        case.defect_id = defect_id
    db.commit()
    run = get_run(db, case.run_id)
    _recompute_run_status(db, run)
    return get_run(db, case.run_id)


def _recompute_run_status(db: Session, run: TestRun):
    statuses = [tc.status for tc in run.test_cases]
    if statuses and all(s in FINAL_STATUSES for s in statuses):
        if any(s == 'FAILED' for s in statuses):
            run.status = 'FAILED'
        elif any(s == 'BLOCKED' for s in statuses):
            run.status = 'BLOCKED'
        else:
            run.status = 'PASSED'
        if run.completed_at is None:
            run.completed_at = datetime.utcnow()
    else:
        run.status = 'RUNNING'
        run.completed_at = None
    db.commit()


def get_summary(db: Session):
    total_runs = db.query(func.count(TestRun.id)).scalar() or 0
    total_cases = db.query(func.count(TestCaseResult.id)).scalar() or 0

    status_counts = {
        status: count
        for status, count in db.query(TestCaseResult.status, func.count(TestCaseResult.id)).group_by(TestCaseResult.status).all()
    }

    environment_counts = {
        env: count
        for env, count in db.query(TestRun.environment, func.count(TestRun.id)).group_by(TestRun.environment).all()
    }

    modules = (
        db.query(
            TestCaseResult.module,
            func.sum(case((TestCaseResult.status == 'PASSED', 1), else_=0)),
            func.sum(case((TestCaseResult.status == 'FAILED', 1), else_=0)),
            func.count(TestCaseResult.id),
        )
        .group_by(TestCaseResult.module)
        .all()
    )

    module_quality = [
        {
            'module': module,
            'passed': int(passed or 0),
            'failed': int(failed or 0),
            'total': int(total or 0),
            'pass_rate': round((int(passed or 0) / total) * 100, 1) if total else 0,
        }
        for module, passed, failed, total in modules
    ]

    runs = get_runs(db, limit=6)
    run_ids = [run.id for run in runs]
    inline_ids: set[int] = set()
    if run_ids:
        inline_ids = {
            row[0]
            for row in db.query(TestRun.id)
            .filter(TestRun.id.in_(run_ids), TestRun.html_report_html.isnot(None))
            .all()
        }
    latest_runs = []
    for run in runs:
        passed = len([tc for tc in run.test_cases if tc.status == 'PASSED'])
        failed = len([tc for tc in run.test_cases if tc.status == 'FAILED'])
        latest_runs.append(
            {
                'id': run.id,
                'suite_name': run.suite_name,
                'environment': run.environment,
                'build_version': run.build_version,
                'status': run.status,
                'started_at': run.started_at.isoformat(),
                'completed_at': run.completed_at.isoformat() if run.completed_at else None,
                'passed': passed,
                'failed': failed,
                'total': len(run.test_cases),
                'html_report_url': run.html_report_url,
                'has_html_report_inline': run.id in inline_ids,
                'has_html_report_zip': bool(run.html_report_index_path),
                'html_report_index_path': run.html_report_index_path,
                'ci': _ci_identity(run),
            }
        )

    pass_rate = round((status_counts.get('PASSED', 0) / total_cases) * 100, 1) if total_cases else 0

    return {
        'totals': {
            'runs': total_runs,
            'cases': total_cases,
            'pass_rate': pass_rate,
            'open_defects': db.query(func.count(TestCaseResult.id)).filter(TestCaseResult.defect_id.is_not(None)).scalar() or 0,
        },
        'status_counts': status_counts,
        'environment_counts': environment_counts,
        'module_quality': module_quality,
        'latest_runs': latest_runs,
        'generated_at': datetime.utcnow().isoformat(),
    }


def upsert_triage_result(db: Session, payload) -> TriageResult:
    values = payload.model_dump()
    now = datetime.utcnow()
    row = (
        db.query(TriageResult)
        .filter(
            TriageResult.provider == payload.provider,
            TriageResult.repository == payload.repository,
            TriageResult.run_id == payload.run_id,
        )
        .first()
    )
    if row:
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = now
    else:
        row = TriageResult(**values, created_at=now, updated_at=now)
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_triage_result(db: Session, provider: str, repository: str, run_id: str) -> Optional[TriageResult]:
    return (
        db.query(TriageResult)
        .filter(
            TriageResult.provider == provider,
            TriageResult.repository == repository,
            TriageResult.run_id == run_id,
        )
        .first()
    )


def list_triage_results(db: Session, limit: int = 20):
    return db.query(TriageResult).order_by(TriageResult.updated_at.desc()).limit(limit).all()
