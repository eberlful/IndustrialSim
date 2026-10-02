"""Public local-project boundary for accepting and inspecting simulation models."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

from industrialsim.application import validate_config


class ProjectSession:
    """Own an accepted model independently of browser connections.

    Loads are transactional: validation failures leave the last accepted model
    intact. Import is in memory only; no source file is ever written here.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).expanduser().resolve(strict=True)
        if not self.directory.is_dir():
            raise ValueError(f"Project must be a directory: {self.directory}")
        self._model: dict[str, Any] | None = None
        self._lock = RLock()

    def models(self) -> list[str]:
        paths = set(self.directory.rglob('*.yaml')) | set(self.directory.rglob('*.yml'))
        return sorted(
            str(path.relative_to(self.directory)) for path in paths
            if path.is_file() and path.resolve().is_relative_to(self.directory)
            and not any(part.startswith('.') or part in {'node_modules', 'runs'}
                        for part in path.relative_to(self.directory).parts)
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"project": str(self.directory), "model": deepcopy(self._model)}

    def open_model(self, relative_path: str) -> dict[str, Any]:
        with self._lock:
            try:
                path = (self.directory / relative_path).resolve()
                if not path.is_relative_to(self.directory):
                    raise ValueError("Select a YAML file inside the project directory")
                if path.suffix.lower() not in {'.yaml', '.yml'}:
                    raise ValueError("Select a .yaml or .yml model")
                text = path.read_text(encoding='utf-8')
            except (OSError, ValueError, UnicodeError) as exc:
                return self._rejected([str(exc)])
            return self.import_yaml(text, relative_path)

    def import_yaml(self, text: str, name: str = 'Imported YAML') -> dict[str, Any]:
        with self._lock:
            # A trailing newline ensures uploaded text is never interpreted as a path
            # by the existing validator's combined file/text API.
            result = validate_config(text + '\n')
            if not result.is_valid or result.config is None:
                return self._rejected(result.errors)
            config = result.config.model_dump(mode='json')
            flow = config.get('material_flow')
            # Legacy Stations have no explicit Ports or routes. Present the Stations
            # honestly rather than inventing topology absent from their configuration.
            graph = flow or {"nodes": [dict(station, kind='station', input_ports=[], output_ports=[])
                                      for station in config['stations']], "routes": []}
            self._model = {"name": name, "yaml": text, "configuration": config,
                           "graph": graph, "plant": config.get('plant')}
            return {"accepted": True, "diagnostics": [], **self.snapshot()}

    def _rejected(self, diagnostics: list[str]) -> dict[str, Any]:
        return {"accepted": False, "diagnostics": diagnostics, **self.snapshot()}
