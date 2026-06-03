import asyncio
import inspect
from pathlib import Path
from typing import Optional

from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import ValidationError
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import repository, schemas
from .html_theme import inject_dashboard_theme, inject_dashboard_theme_bytes
from .report_zip import ReportZipError, read_member
from .database import Base, engine, get_db, SessionLocal
from .models import TestCaseResult
from .realtime import ConnectionManager
from . import github_ci
from .github_ci import GitHubCiError
from .settings import AUTO_CREATE_SCHEMA, CORS_ORIGINS, DATA_SOURCE, GITHUB_ACTIONS_INGEST_TOKEN

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
FRONTEND_DIST_DIR = PROJECT_DIR / 'frontend' / 'dist'
FRONTEND_INDEX_PATH = FRONTEND_DIST_DIR / 'index.html'

app = FastAPI(title='QA Real-Time Testing Dashboard')
# allow_credentials=True is incompatible with allow_origins=['*'] (browser CORS rules).
# The dashboard uses fetch() without cookies, so credentials can stay false and '*' works for any deploy preview.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS else ['*'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
    expose_headers=['X-Data-Source'],
)

app.mount('/static', StaticFiles(directory=BASE_DIR / 'static'), name='static')
if FRONTEND_DIST_DIR.exists():
    app.mount('/assets', StaticFiles(directory=FRONTEND_DIST_DIR / 'assets'), name='frontend-assets')
manager = ConnectionManager()


@app.on_event('startup')
def startup():
    if AUTO_CREATE_SCHEMA:
        Base.metadata.create_all(bind=engine)


@app.get('/', response_class=HTMLResponse)
def index():
    if FRONTEND_INDEX_PATH.exists():
        return FileResponse(FRONTEND_INDEX_PATH)
    html_path = BASE_DIR / 'templates' / 'index.html'
    return html_path.read_text(encoding='utf-8')


@app.get('/api/health')
def health():
    return {'status': 'ok'}


@app.get('/api/config')
def config():
    return {'data_source': DATA_SOURCE, 'ci': github_ci.ci_config()}


def _github_ci_http_error(exc: GitHubCiError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@app.get('/api/ci/config')
def ci_config():
    return github_ci.ci_config()


@app.get('/api/ci/workflows')
async def ci_workflows():
    try:
        return {'workflows': await github_ci.list_workflows()}
    except GitHubCiError as e:
        raise _github_ci_http_error(e) from e


@app.get('/api/ci/runs')
async def ci_runs(limit: int = 10, workflow_file: Optional[str] = None):
    try:
        return {'runs': await github_ci.list_recent_runs(limit=limit, workflow_file=workflow_file)}
    except GitHubCiError as e:
        raise _github_ci_http_error(e) from e


@app.get('/api/ci/runs/{run_id}', response_model=schemas.CiRunFlow)
async def ci_run_flow(run_id: int):
    try:
        return await github_ci.get_run_flow(run_id)
    except GitHubCiError as e:
        raise _github_ci_http_error(e) from e


@app.post('/api/ci/trigger')
async def ci_trigger(payload: schemas.CiTriggerRequest):
    try:
        return await github_ci.trigger_workflow(
            ref=payload.ref,
            workflow_file=payload.workflow_file,
            inputs=payload.inputs,
        )
    except GitHubCiError as e:
        raise _github_ci_http_error(e) from e


@app.get('/api/summary')
def summary(response: Response, db: Session = Depends(get_db)):
    data = repository.get_summary(db)
    # Helps verify in DevTools → Network → Headers that this JSON is from the real API + current mode.
    response.headers['X-Data-Source'] = DATA_SOURCE
    return data


@app.get('/api/runs', response_model=list[schemas.TestRunResponse])
def runs(limit: int = 10, db: Session = Depends(get_db)):
    return repository.get_runs(db, limit)


@app.get('/api/runs/{run_id}/report/{file_path:path}')
def run_report_file(run_id: int, file_path: str, db: Session = Depends(get_db)):
    """Serves files from a CI-uploaded Playwright-style report ZIP (multi-file HTML report)."""
    run = repository.get_run(db, run_id)
    if not run or not run.html_report_zip:
        raise HTTPException(status_code=404, detail='No report archive for this run')
    try:
        body, mime = read_member(run.html_report_zip, file_path)
    except ReportZipError:
        raise HTTPException(status_code=404, detail='Report file not found') from None
    body = inject_dashboard_theme_bytes(body, mime)
    return Response(content=body, media_type=mime)


@app.get('/api/runs/{run_id}/html-report', response_class=HTMLResponse)
def run_html_report(run_id: int, db: Session = Depends(get_db)):
    """Single-file HTML body, or redirect to bundled report index inside a ZIP."""
    run = repository.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail='Run not found')
    if run.html_report_zip and run.html_report_index_path:
        parts = [quote(seg, safe='') for seg in run.html_report_index_path.split('/')]
        return RedirectResponse(url=f'/api/runs/{run_id}/report/{"/".join(parts)}', status_code=307)
    if not run.html_report_html:
        raise HTTPException(status_code=404, detail='No inline HTML report for this run')
    return HTMLResponse(
        content=inject_dashboard_theme(run.html_report_html),
        media_type='text/html; charset=utf-8',
    )


@app.post('/api/runs', response_model=schemas.TestRunResponse)
async def create_run(payload: schemas.TestRunCreate, db: Session = Depends(get_db)):
    if DATA_SOURCE == 'github':
        raise HTTPException(status_code=403, detail='Disabled in github mode; use ingestion endpoint')
    run = repository.create_run(db, payload)
    await manager.broadcast({'event': 'run_created', 'summary': repository.get_summary(db)})
    return run


@app.post('/api/cases/{case_id}/status')
async def update_case(case_id: int, payload: dict, db: Session = Depends(get_db)):
    run = repository.update_case_status(
        db,
        case_id=case_id,
        status=payload['status'],
        duration_ms=payload.get('duration_ms'),
        defect_id=payload.get('defect_id'),
    )
    if not run:
        raise HTTPException(status_code=404, detail='Test case not found')
    await manager.broadcast({'event': 'case_updated', 'summary': repository.get_summary(db), 'run_id': run.id})
    return {'message': 'updated', 'run_id': run.id}


def _require_ingest_token(x_ingest_token: str) -> None:
    if not GITHUB_ACTIONS_INGEST_TOKEN:
        raise HTTPException(status_code=503, detail='Ingestion not configured')
    if x_ingest_token != GITHUB_ACTIONS_INGEST_TOKEN:
        raise HTTPException(status_code=401, detail='Unauthorized')


async def _multipart_json_text(part) -> str:
    """Read JSON text from a multipart field: plain string, bytes, or file-like (UploadFile)."""
    if isinstance(part, str):
        return part
    if isinstance(part, (bytes, bytearray)):
        return bytes(part).decode('utf-8-sig')
    read = getattr(part, 'read', None)
    if callable(read):
        chunk = read()
        if inspect.isawaitable(chunk):
            chunk = await chunk
        if isinstance(chunk, str):
            return chunk
        if isinstance(chunk, (bytes, bytearray)):
            return bytes(chunk).decode('utf-8-sig')
    raise HTTPException(
        status_code=422,
        detail=(
            f'Unsupported "payload" part type {type(part).__name__!r}; '
            'expected JSON text or a file upload (curl -F payload=@payload.json).'
        ),
    )


async def _multipart_file_bytes(part) -> Optional[bytes]:
    """Read raw bytes from an optional file part (report_zip)."""
    if part is None:
        return None
    if isinstance(part, (bytes, bytearray)):
        return bytes(part) if part else None
    read = getattr(part, 'read', None)
    if callable(read):
        chunk = read()
        if inspect.isawaitable(chunk):
            chunk = await chunk
        if isinstance(chunk, (bytes, bytearray)):
            return bytes(chunk) if chunk else None
    return None


@app.post('/api/ingest/github-actions/run', response_model=schemas.TestRunResponse)
async def ingest_github_actions_run(
    payload: schemas.TestRunCreate,
    db: Session = Depends(get_db),
    x_ingest_token: str = Header('', alias='X-Ingest-Token'),
):
    _require_ingest_token(x_ingest_token)
    run = repository.create_run(db, payload)
    await manager.broadcast({'event': 'github_ingest', 'summary': repository.get_summary(db), 'run_id': run.id})
    return run


@app.post('/api/ingest/github-actions/run-with-report', response_model=schemas.TestRunResponse)
async def ingest_github_actions_run_with_report(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    x_ingest_token: str = Header('', alias='X-Ingest-Token'),
):
    """
    Same as JSON ingest, plus an optional `report_zip` file part.
    Use this from CI when the HTML report is a directory (Playwright); GitHub artifact downloads are not public URLs.

    Multipart parts: `payload` (JSON string **or** file upload like `curl -F payload=@payload.json`) and optional `report_zip`.

    `curl -F payload=@file.json` sends a file part; we parse it manually so FastAPI does not return 422 for type coercion.
    """
    _require_ingest_token(x_ingest_token)
    form = await request.form()
    payload_raw = form.get('payload')
    if payload_raw is None:
        raise HTTPException(status_code=422, detail='Missing form field "payload"')

    try:
        payload_text = await _multipart_json_text(payload_raw)
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=422, detail=f'payload file is not valid UTF-8: {e}') from e

    try:
        data = schemas.TestRunCreate.model_validate_json(payload_text)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=jsonable_encoder(e.errors())) from e

    report_raw = form.get('report_zip')
    zip_bytes = await _multipart_file_bytes(report_raw)
    if zip_bytes is None and report_raw is not None:
        fn = getattr(report_raw, 'filename', None)
        if fn:
            raise HTTPException(
                status_code=400,
                detail='report_zip part was present but empty. Fix the path to your zip or the zip command in CI.',
            )

    response.headers['X-Ingest-Api-Revision'] = '3'

    try:
        run = repository.create_run(db, data, report_zip=zip_bytes)
    except ReportZipError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    stored = len(run.html_report_zip) if run.html_report_zip else 0
    response.headers['X-Ingest-Report-Zip-Bytes'] = str(stored)

    await manager.broadcast({'event': 'github_ingest', 'summary': repository.get_summary(db), 'run_id': run.id})
    return run


@app.websocket('/ws')
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    db = SessionLocal()
    try:
        await websocket.send_json({'event': 'initial', 'summary': repository.get_summary(db)})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    finally:
        db.close()


async def simulator_loop():
    from random import choice, randint

    await asyncio.sleep(2)
    while True:
        db = SessionLocal()
        try:
            running_cases = db.query(TestCaseResult).filter(TestCaseResult.status == 'RUNNING').all()
            if running_cases:
                candidate = choice(running_cases)
                outcome = choice(['PASSED', 'PASSED', 'FAILED', 'BLOCKED'])
                defect_id = f'DEF-{randint(101, 130)}' if outcome in {'FAILED', 'BLOCKED'} else None
                repository.update_case_status(
                    db,
                    case_id=candidate.id,
                    status=outcome,
                    duration_ms=randint(1000, 12000),
                    defect_id=defect_id,
                )
                await manager.broadcast({'event': 'simulation_tick', 'summary': repository.get_summary(db)})
        finally:
            db.close()
        await asyncio.sleep(3)


@app.on_event('startup')
async def start_simulator():
    if DATA_SOURCE == 'demo':
        asyncio.create_task(simulator_loop())


@app.get('/{full_path:path}')
def spa_fallback(full_path: str):
    if full_path.startswith(('api/', 'ws', 'static/', 'docs', 'redoc', 'openapi.json')):
        raise HTTPException(status_code=404, detail='Not found')
    if FRONTEND_INDEX_PATH.exists():
        return FileResponse(FRONTEND_INDEX_PATH)
    raise HTTPException(status_code=404, detail='Not found')
