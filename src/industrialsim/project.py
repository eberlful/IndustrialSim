"""Public local-project boundary for accepting and inspecting simulation models."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from io import StringIO
import os
import hashlib
import json
import math
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Any

from ruamel.yaml import YAML

from industrialsim.application import validate_config


class ProjectSession:
    """Own a validated or correctable parameter draft independently of browsers.

    Loads are transactional: validation failures leave the last accepted model
    intact. Edits retain invalid values for correction; export and explicit saves
    require full validation. Import and parameter edits never write source files.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).expanduser().resolve(strict=True)
        if not self.directory.is_dir():
            raise ValueError(f"Project must be a directory: {self.directory}")
        self._model: dict[str, Any] | None = None
        self._lock = RLock()
        self._draft: dict[str, Any] | None = None
        self._layout_identity = ''
        self._undo: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self._redo: list[tuple[dict[str, Any], dict[str, Any]]] = []

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
            return {"project": str(self.directory), "model": deepcopy(self._model),
                    "can_undo": bool(self._undo), "can_redo": bool(self._redo),
                    "diagnostics": list(self._model['diagnostics']) if self._model else []}

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
            return self.import_yaml(text, str(path.relative_to(self.directory)))

    def import_yaml(self, text: str, name: str = 'Imported YAML') -> dict[str, Any]:
        with self._lock:
            # A trailing newline ensures uploaded text is never interpreted as a path
            # by the existing validator's combined file/text API.
            result = validate_config(text + '\n')
            if not result.is_valid or result.config is None:
                return self._rejected(result.errors)
            draft = YAML(typ='safe', pure=True).load(text)
            self._set_draft(draft, name, text)
            assert self._model is not None
            self._layout_identity = self._identity(name, self._model['configuration'])
            self._model['layout'] = {'positions': {}, 'grouping': 'none'}
            warnings: list[str] = []
            try:
                path = self._layout_path()
                if path.exists():
                    document = json.loads(path.read_text(encoding='utf-8'))
                    if document['version'] != 1 or document['model_identity'] != self._layout_identity:
                        raise ValueError('Layout identity or version does not match')
                    self._validate_layout(document['layout'])
                    self._model['layout'] = document['layout']
            except (OSError, ValueError, KeyError, TypeError) as exc:
                warnings.append(f'Layout could not be restored; using initial arrangement: {exc}')
            self._undo.clear()
            self._redo.clear()
            return {**self.snapshot(), 'accepted': True, 'diagnostics': warnings}

    def _set_draft(self, draft: dict[str, Any], name: str, text: str | None = None) -> None:
        result = validate_config(draft)
        config = result.config.model_dump(mode='json') if result.config else deepcopy(draft)
        flow = config.get('material_flow')
        graph = deepcopy(flow) if flow else {
            'nodes': [dict(deepcopy(station), kind='station') for station in config.get('stations', [])],
            'routes': [],
        }
        for node in graph['nodes']:
            node.setdefault('input_ports', [])
            node.setdefault('output_ports', [])
        # JSON numbers cannot carry every Python integer exactly. Editable graph
        # values outside JavaScript's safe range travel as decimal text.
        for element in [*graph['nodes'], *graph['routes']]:
            for field in ('capacity', 'output_capacity', 'transit_time'):
                value = element.get(field)
                if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
                    element[field] = str(value)
            for operation in element.get('operations', []):
                value = operation.get('duration')
                if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
                    operation['duration'] = str(value)
        if text is None:
            buffer = StringIO()
            YAML(typ='safe', pure=True).dump(draft, buffer)
            text = buffer.getvalue()
        self._draft = draft
        layout = deepcopy(self._model['layout']) if self._model else {'positions': {}, 'grouping': 'none'}
        self._model = {'layout': layout, 'name': name, 'yaml': text, 'configuration': config,
                       'graph': graph, 'plant': config.get('plant'),
                       'valid': result.is_valid, 'diagnostics': result.errors}

    def edit_parameters(
        self, kind: str, element_id: str, changes: dict[str, Any],
        *, operation_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._draft is None or self._model is None:
                return self._rejected(['Open a model before editing'])
            draft = deepcopy(self._draft)
            flow = draft.get('material_flow')
            if kind not in {'node', 'route'}:
                return self._rejected([f"Unknown element kind '{kind}'"])
            if flow:
                flow = dict(flow)
                draft['material_flow'] = flow
                collection = 'routes' if kind == 'route' else 'nodes'
                elements = list(flow[collection])
                flow[collection] = elements
            elif kind == 'node':
                elements = list(draft.get('stations', []))
                draft['stations'] = elements
            else:
                elements = []
            element = next((item for item in elements if item['id'] == element_id), None)
            if element is None:
                return self._rejected([f"Unknown {kind} '{element_id}'"])
            # Detach the edited mapping/list from YAML aliases shared elsewhere.
            element_index = elements.index(element)
            element = dict(element)
            elements[element_index] = element
            allowed = ({'transit_time', 'capacity', 'required_capabilities', 'pool_id'}
                       if kind == 'route' else {'hall_id'} if flow else set())
            if kind == 'node':
                node_kind = element.get('kind', 'station')
                if node_kind == 'buffer':
                    allowed.add('capacity')
                elif node_kind == 'station':
                    allowed.add('output_capacity')
            if operation_id is not None:
                allowed = {'duration'}
                element['operations'] = [dict(op) for op in element.get('operations', [])]
                element = next((op for op in element.get('operations', [])
                                if op['id'] == operation_id), None)
                if element is None:
                    return self._rejected([f"Unknown Operation '{operation_id}'"])
            unsupported = set(changes) - allowed
            if unsupported:
                return self._rejected([f"Properties not editable here: {', '.join(sorted(unsupported))}"])
            if not changes:
                return {**self.snapshot(), 'accepted': True}
            element.update(deepcopy(changes))
            self._undo.append((deepcopy(self._draft), deepcopy(self._model)))
            self._redo.clear()
            self._set_draft(draft, self._model['name'])
            return {**self.snapshot(), 'accepted': True}

    def undo(self) -> dict[str, Any]:
        with self._lock:
            return self._restore(self._undo, self._redo)

    def redo(self) -> dict[str, Any]:
        with self._lock:
            return self._restore(self._redo, self._undo)

    def _restore(
        self, source: list[tuple[dict[str, Any], dict[str, Any]]],
        destination: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> dict[str, Any]:
        if not source or self._draft is None or self._model is None:
            return self._rejected(['No change to restore'])
        destination.append((deepcopy(self._draft), deepcopy(self._model)))
        self._draft, self._model = source.pop()
        return {**self.snapshot(), 'accepted': True}

    def export_yaml(self) -> dict[str, Any]:
        with self._lock:
            if self._model is None or self._draft is None:
                return self._rejected(['Open a model before exporting'])
            result = validate_config(self._draft)
            if not result.is_valid:
                return self._rejected(result.errors)
            return {'accepted': True, 'diagnostics': [], 'yaml': self._model['yaml']}

    def save_model(self, relative_path: str, *, overwrite: bool = False) -> dict[str, Any]:
        with self._lock:
            exported = self.export_yaml()
            if not exported['accepted']:
                return exported
            temporary: Path | None = None
            try:
                if Path(relative_path).is_absolute():
                    raise ValueError('Save with a project-relative YAML path')
                path = (self.directory / relative_path).resolve()
                if not path.is_relative_to(self.directory):
                    raise ValueError('Save inside the project directory')
                if path.suffix.lower() not in {'.yaml', '.yml'}:
                    raise ValueError('Save to a .yaml or .yml file')
                if path.exists() and not overwrite:
                    raise ValueError('File already exists. Explicitly enable overwrite or choose a new filename.')
                with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                        prefix='.industrialsim-', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(exported['yaml'])
                    stream.flush()
                    os.fsync(stream.fileno())
                if overwrite:
                    os.replace(temporary, path)
                else:
                    # Exclusive creation also protects against a concurrent save.
                    os.link(temporary, path)
                assert self._model is not None
                self._layout_identity = self._identity(str(path.relative_to(self.directory)), self._model['configuration'])
                layout_result = self.save_layout()
                return {**self.snapshot(), 'accepted': True, 'saved_path': relative_path,
                        'diagnostics': layout_result['diagnostics']}
            except (OSError, ValueError) as exc:
                return self._rejected([str(exc)])
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    @staticmethod
    def _identity(name: str, configuration: dict[str, Any]) -> str:
        content = json.dumps([name, configuration], sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(content.encode()).hexdigest()

    def _layout_path(self) -> Path:
        path = self.directory / '.layouts' / f'{self._layout_identity}.json'
        if not path.resolve().is_relative_to(self.directory):
            raise ValueError('Layout must remain inside the project directory')
        return path

    def _validate_layout(self, layout: dict[str, Any]) -> None:
        if not isinstance(layout, dict) or set(layout) != {'positions', 'grouping'}:
            raise ValueError('Layout requires positions and grouping')
        if layout['grouping'] not in ('none', 'area', 'hall'):
            raise ValueError('Grouping must be none, area or hall')
        if not isinstance(layout['positions'], dict):
            raise ValueError('Positions must be a node mapping')
        assert self._model is not None
        ids = {node['id'] for node in self._model['graph']['nodes']}
        for node_id, position in layout['positions'].items():
            if node_id not in ids:
                raise ValueError(f'Unknown layout node {node_id}')
            if not isinstance(position, dict) or set(position) != {'x', 'y'} or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) for value in position.values()
            ):
                raise ValueError('Positions require finite x and y coordinates')

    def edit_layout(
        self, *, positions: dict[str, Any] | None = None, grouping: str | None = None,
    ) -> dict[str, Any]:
        """Edit presentation only; one command is one undoable gesture."""
        with self._lock:
            if self._model is None or self._draft is None:
                return self._rejected(['Open a model before arranging it'])
            layout = deepcopy(self._model['layout'])
            if positions is not None:
                layout['positions'].update(deepcopy(positions))
            if grouping is not None:
                layout['grouping'] = grouping
            try:
                self._validate_layout(layout)
            except (ValueError, TypeError) as exc:
                return self._rejected([str(exc)])
            if layout != self._model['layout']:
                self._undo.append((deepcopy(self._draft), deepcopy(self._model)))
                self._redo.clear()
                self._model['layout'] = layout
            return {**self.snapshot(), 'accepted': True}

    def save_layout(self) -> dict[str, Any]:
        """Explicitly persist presentation separately, including for invalid drafts."""
        with self._lock:
            if self._model is None:
                return self._rejected(['Open a model before saving layout'])
            temporary: Path | None = None
            try:
                path = self._layout_path()
                path.parent.mkdir(exist_ok=True)
                document = {'version': 1, 'model_identity': self._layout_identity,
                            'layout': self._model['layout']}
                with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                        prefix='.layout-', delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(document, stream, allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                return {**self.snapshot(), 'accepted': True}
            except (OSError, ValueError) as exc:
                return self._rejected([f'Could not save layout: {exc}'])
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    def _rejected(self, diagnostics: list[str]) -> dict[str, Any]:
        return {**self.snapshot(), "accepted": False, "diagnostics": diagnostics}
