"""Loopback service and single-command source-checkout frontend launcher."""
from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Any, AsyncIterator, Awaitable, Callable, Sequence
import webbrowser

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
import uvicorn

from industrialsim.project import ProjectSession


class OpenModel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str


class ImportModel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    yaml: str
    name: str = 'Imported YAML'


def create_app(session: ProjectSession, assets: Path, *, browser_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if browser_url:
            threading.Timer(0.5, webbrowser.open, args=(browser_url,)).start()
        yield

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

    @app.get('/api/project')
    def project() -> dict[str, Any]:
        return {**session.snapshot(), 'models': session.models()}

    @app.post('/api/project/open')
    def open_model(body: OpenModel) -> JSONResponse:
        result = session.open_model(body.path)
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

    @app.post('/api/project/import')
    def import_model(body: ImportModel) -> JSONResponse:
        result = session.import_yaml(body.yaml, body.name)
        return JSONResponse(result, status_code=200 if result['accepted'] else 422)

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
