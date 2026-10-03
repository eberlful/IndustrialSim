"""Read durable Episode artifacts without constructing or restoring an engine."""
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from industrialsim.audit import inspect_run


class SavedResults:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()

    def _path(self, path: str) -> Path:
        resolved = (self.directory / path).resolve()
        runs = self.directory / 'runs'
        if not resolved.is_relative_to(runs) or not resolved.is_dir():
            raise ValueError('Select an Episode output inside the project runs directory')
        # Artifact symlinks must not escape the project either.
        if any(not entry.resolve().is_relative_to(self.directory) for entry in resolved.rglob('*')):
            raise ValueError('Result artifacts must stay inside the project')
        return resolved

    def list(self) -> list[dict[str, Any]]:
        runs = self.directory / 'runs'
        if not runs.is_dir() or not runs.resolve().is_relative_to(self.directory):
            return []
        results = []
        for entry in sorted(runs.iterdir()):
            if not entry.is_dir():
                continue
            path = str(entry.relative_to(self.directory))
            try:
                result = self.open(path)
                results.append({'path': path, 'status': result['status'], 'diagnostics': result['diagnostics']})
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                results.append({'path': path, 'status': 'unavailable', 'diagnostics': [str(exc)]})
        return results

    def open(self, path: str) -> dict[str, Any]:
        directory = self._path(path)
        inspection = inspect_run(directory).to_dict()
        summary = inspection['summary']
        diagnostics = []
        status = inspection['status']
        if inspection['has_incomplete_marker'] or not isinstance(summary, dict):
            status = 'incomplete'
            diagnostics.append('Final summary unavailable or execution incomplete; available artifacts are shown as recorded.')
        configuration = None
        try:
            configuration = YAML(typ='safe', pure=True).load((directory / 'resolved_config.yaml').read_text())
            if not isinstance(configuration, dict):
                raise ValueError('Resolved configuration is not a mapping')
        except Exception as exc:
            configuration = None
            diagnostics.append(f'Original resolved configuration unavailable: {exc}')
        return {'path': path, 'status': status, 'summary': summary,
                'configuration': configuration, 'inspection': inspection, 'diagnostics': diagnostics}
