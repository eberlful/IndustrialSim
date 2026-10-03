"""Loopback service and single-command source-checkout frontend launcher."""
from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Sequence
import webbrowser

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict
import uvicorn

from industrialsim.project import ProjectSession
from industrialsim.episode_worker import EpisodeWorker


class OpenModel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str


class ImportModel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    yaml: str
    name: str = 'Imported YAML'


class EditYaml(BaseModel):
    model_config = ConfigDict(extra='forbid')
    yaml: str
    expected_yaml: str | None = None


class EditParameters(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['node', 'route', 'machine', 'worker']
    element_id: str
    changes: dict[str, Any]
    operation_id: str | None = None


class StartEpisode(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['baseline', 'manual'] = 'baseline'


class SubmitDecisionBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    episode_id: str
    batch_id: str
    actions: list[dict[str, Any]]


class RestoreCheckpoint(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str


class EpisodeCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    episode_id: str


class EditEpisode(BaseModel):
    model_config = ConfigDict(extra='forbid')
    changes: dict[str, Any]


class EditStructure(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['add', 'update', 'delete']
    kind: Literal['node', 'route']
    element_id: str
    changes: dict[str, Any] = {}


class EditLayout(BaseModel):
    model_config = ConfigDict(extra='forbid')
    positions: dict[str, Any] | None = None
    grouping: Literal['none', 'area', 'hall'] | None = None


class SaveModel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str
    overwrite: bool = False


def browser_episode_response(result: dict[str, Any]) -> dict[str, Any]:
    """Preserve exact Decision Batch nanoseconds across JSON/JavaScript."""
    def exact_times(value: Any, key: str = '') -> Any:
        if type(value) is int and key.endswith('_ns'):
            return str(value)
        if isinstance(value, dict):
            return {field: exact_times(item, field) for field, item in value.items()}
        if isinstance(value, list):
            return [exact_times(item, key) for item in value]
        return value
    episode = result.get('episode')
    if episode and episode.get('observation_views'):
        episode['observation_views']['available'] = exact_times(episode['observation_views']['available'])
    if episode and episode.get('decision_batch'):
        episode['decision_batch'] = exact_times(episode['decision_batch'])
    return result


def create_app(session: ProjectSession, assets: Path, *, browser_url: str | None = None) -> FastAPI:
    episodes = EpisodeWorker(session.directory)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if browser_url:
            threading.Timer(0.5, webbrowser.open, args=(browser_url,)).start()
        try:
            yield
        finally:
            await run_in_threadpool(episodes.close)

    app = FastAPI(title='IndustrialSim local project', lifespan=lifespan)

    @app.middleware('http')
    async def local_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Bind to loopback and reject foreign Host/Origin values, including DNS
        # rebinding. Browsers on another site must not control the local session.
        host = request.headers.get('host', '').split(':')[0]
        origin = request.headers.get('origin')
        if host not in {'127.0.0.1', 'localhost', 'testserver'} or (
            origin and origin != f"{request.url.scheme}://{request.headers.get('host')}"
        ):
            return JSONResponse({'detail': 'Use the local project origin'}, status_code=403)
        return await call_next(request)

    @app.get('/api/episode')
    def episode() -> dict[str, Any]:
        return browser_episode_response(episodes.snapshot(include_history=False))

    @app.post('/api/episode/start')
    def start_episode(body: StartEpisode | None = None) -> JSONResponse:
        exported = session.export_yaml()
        if not exported['accepted']:
            return JSONResponse({**episodes.snapshot(include_history=False), 'accepted': False,
                                 'diagnostics': exported['diagnostics']}, status_code=422)
        result = episodes.start(exported['yaml'], mode=body.mode if body else 'baseline')
        return JSONResponse(browser_episode_response(result), status_code=200 if result['accepted'] else 409)

    @app.get('/api/episode/checkpoints')
    def saved_checkpoints() -> dict[str, Any]:
        return {'checkpoints': episodes.checkpoints()}

    @app.post('/api/episode/checkpoint')
    def checkpoint_episode(body: EpisodeCommand) -> JSONResponse:
        result = episodes.create_checkpoint(body.episode_id)
        return JSONResponse(browser_episode_response(result), status_code=200 if result['accepted'] else 409)

    @app.post('/api/episode/restore')
    def restore_episode(body: RestoreCheckpoint) -> JSONResponse:
        result = episodes.restore_checkpoint(body.path)
        return JSONResponse(browser_episode_response(result), status_code=200 if result['accepted'] else 409)

    @app.post('/api/episode/pause')
    def pause_episode(body: EpisodeCommand) -> JSONResponse:
        result = episodes.pause(body.episode_id)
        return JSONResponse(browser_episode_response(result), status_code=200 if result['accepted'] else 409)

    @app.post('/api/episode/continue')
    def continue_episode(body: EpisodeCommand) -> JSONResponse:
        result = episodes.continue_episode(body.episode_id)
        return JSONResponse(browser_episode_response(result), status_code=200 if result['accepted'] else 409)

    @app.post('/api/episode/next-batch')
    def next_decision_batch(body: EpisodeCommand) -> JSONResponse:
        result = episodes.next_decision_batch(body.episode_id)
        return JSONResponse(browser_episode_response(result), status_code=200 if result['accepted'] else 409)

    @app.post('/api/episode/submit-batch')
    def submit_decision_batch(body: SubmitDecisionBatch) -> JSONResponse:
        result = episodes.submit_decision_batch(body.episode_id, body.batch_id, body.actions)
        return JSONResponse(browser_episode_response(result), status_code=200 if result['accepted'] else 409)

    @app.get('/api/episode/events')
    def episode_events(episode_id: str, cursor: int = Query(0, ge=0),
                       limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
        try:
            result = episodes.events(episode_id, cursor, limit)
            for record in result['records']:
                record['simulated_time_ns'] = str(record['simulated_time_ns'])
            return result
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get('/api/project')
    def project() -> dict[str, Any]:
        return {**session.snapshot(), 'models': session.models(), 'drafts': session.drafts()}

    @app.post('/api/project/open')
    def open_model(body: OpenModel) -> JSONResponse:
        result = session.open_model(body.path)
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

    @app.post('/api/project/import')
    def import_model(body: ImportModel) -> JSONResponse:
        result = session.import_yaml(body.yaml, body.name)
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

    @app.post('/api/project/yaml')
    def edit_yaml(body: EditYaml) -> JSONResponse:
        result = session.edit_yaml(body.yaml, expected_yaml=body.expected_yaml)
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

    @app.post('/api/project/edit')
    def edit_parameters(body: EditParameters) -> JSONResponse:
        result = session.edit_parameters(body.kind, body.element_id, body.changes,
                                         operation_id=body.operation_id)
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

    @app.post('/api/project/episode')
    def edit_episode(body: EditEpisode) -> JSONResponse:
        result = session.edit_episode(body.changes)
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

    @app.post('/api/project/structure')
    def edit_structure(body: EditStructure) -> JSONResponse:
        result = session.edit_structure(body.action, body.kind, body.element_id, body.changes)
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

    @app.post('/api/project/draft/save')
    def save_draft(body: SaveModel) -> JSONResponse:
        result = session.save_draft(body.path, overwrite=body.overwrite)
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

    @app.post('/api/project/draft/open')
    def open_draft(body: OpenModel) -> JSONResponse:
        result = session.open_draft(body.path)
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

    @app.post('/api/project/layout')
    def edit_layout(body: EditLayout) -> JSONResponse:
        result = session.edit_layout(positions=body.positions, grouping=body.grouping)
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

    @app.post('/api/project/layout/save')
    def save_layout() -> JSONResponse:
        result = session.save_layout()
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

    @app.post('/api/project/undo')
    def undo() -> JSONResponse:
        result = session.undo()
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

    @app.post('/api/project/redo')
    def redo() -> JSONResponse:
        result = session.redo()
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

    @app.get('/api/project/export')
    def export_yaml() -> Response:
        result = session.export_yaml()
        if not result['accepted']:
            return JSONResponse(result, status_code=422)
        return Response(result['yaml'], media_type='application/yaml',
                        headers={'Content-Disposition': 'attachment; filename="plant.yaml"'})

    @app.post('/api/project/save')
    def save_model(body: SaveModel) -> JSONResponse:
        result = session.save_model(body.path, overwrite=body.overwrite)
        return JSONResponse({**result, 'models': session.models()},
                            status_code=200 if result['accepted'] else 422)

    app.mount('/', StaticFiles(directory=assets, html=True), name='frontend')
    return app


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Open a local IndustrialSim project')
    parser.add_argument('project', type=Path)
    parser.add_argument('--model', help='Project-relative YAML file to load initially')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    try:
        session = ProjectSession(args.project)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.model:
        result = session.open_model(args.model)
        if not result['accepted']:
            parser.error('\n'.join(result['diagnostics']))
    frontend = Path(__file__).resolve().parents[2] / 'frontend'
    if not (frontend / 'package.json').is_file():
        parser.error('Run industrialsim-ui from a source checkout containing frontend/')
    npm = shutil.which('npm')
    if npm is None:
        parser.error('Node.js and npm are required to build the browser UI')
    # One command builds the browser bundle and serves it from the same origin.
    try:
        subprocess.run([npm, 'ci', '--no-audit', '--no-fund'], cwd=frontend, check=True)
        subprocess.run([npm, 'run', 'build'], cwd=frontend, check=True)
    except subprocess.CalledProcessError as exc:
        parser.error(f'Frontend build failed (exit {exc.returncode})')
    url = f'http://127.0.0.1:{args.port}'
    app = create_app(session, frontend / 'dist', browser_url=None if args.no_browser else url)
    uvicorn.run(app, host='127.0.0.1', port=args.port)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
