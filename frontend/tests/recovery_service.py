"""Real restartable service for the browser recovery workflow."""
from pathlib import Path
import sys

import uvicorn
from industrialsim.local_service import create_app
from industrialsim.project import ProjectSession

root = Path(__file__).resolve().parents[2]
uvicorn.run(create_app(ProjectSession(sys.argv[1]), root / 'frontend/dist'), host='127.0.0.1', port=18766)
