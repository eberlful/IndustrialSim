"""Real browser-test service with an isolated project, using public interfaces."""
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

import uvicorn
from industrialsim.local_service import create_app
from industrialsim.project import ProjectSession

root = Path(__file__).resolve().parents[2]
with TemporaryDirectory(prefix='industrialsim-browser-') as directory:
    shutil.copy(root / 'examples/reference_automotive_plant.yaml', Path(directory) / 'reference.yaml')
    uvicorn.run(create_app(ProjectSession(directory), root / 'frontend/dist'), host='127.0.0.1', port=18765)
