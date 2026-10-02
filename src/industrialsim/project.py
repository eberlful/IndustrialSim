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
from industrialsim.project_graph import check_graph_shape, graph_diagnostics


def _atomic_write(path: Path, text: str, *, overwrite: bool) -> None:
    """Publish a complete file, with exclusive creation unless overwrite is explicit."""
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                prefix='.industrialsim-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
            return {**self.snapshot(), 'accepted': True, 'diagnostics': [*self._model['diagnostics'], *warnings]}

    def _set_draft(self, draft: dict[str, Any], name: str, text: str | None = None) -> None:
        result = validate_config(draft)
        errors = list(dict.fromkeys([*result.errors, *graph_diagnostics(draft)]))
        config = result.config.model_dump(mode='json') if result.config else deepcopy(draft)
        flow = config.get('material_flow')
        graph = deepcopy(flow) if flow else {
            'nodes': [dict(deepcopy(station), kind='station') for station in config.get('stations', [])],
            'routes': [],
        }
        for node in graph['nodes']:
            node.setdefault('input_ports', [])
            node.setdefault('output_ports', [])
        # JSON numbers cannot carry every Python integer exactly. Editable
        # values outside JavaScript's safe range travel as decimal text.
        for element in [*graph['nodes'], *graph['routes'],
                        *config.get('machines', []), *config.get('workers', [])]:
            for field in ('capacity', 'output_capacity', 'transit_time'):
                value = element.get(field)
                if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
                    element[field] = str(value)
            for operation in element.get('operations', []):
                value = operation.get('duration')
                if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
                    operation['duration'] = str(value)
                requirements = operation.get('required_workers', [])
                if isinstance(requirements, list):
                    for requirement in requirements:
                        if not isinstance(requirement, dict):
                            continue
                        count = requirement.get('count')
                        if isinstance(count, int) and not isinstance(count, bool) and abs(count) > 2**53 - 1:
                            requirement['count'] = str(count)
        if text is None:
            buffer = StringIO()
            YAML(typ='safe', pure=True).dump(draft, buffer)
            text = buffer.getvalue()
        self._draft = draft
        layout = deepcopy(self._model['layout']) if self._model else {'positions': {}, 'grouping': 'none'}
        self._model = {'layout': layout, 'name': name, 'yaml': text, 'configuration': config,
                       'graph': graph, 'plant': config.get('plant'),
                       'valid': result.is_valid and not errors, 'diagnostics': errors}

    def edit_parameters(
        self, kind: str, element_id: str, changes: dict[str, Any],
        *, operation_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._draft is None or self._model is None:
                return self._rejected(['Open a model before editing'])
            draft = deepcopy(self._draft)
            flow = draft.get('material_flow')
            if kind not in {'node', 'route', 'machine', 'worker'}:
                return self._rejected([f"Unknown element kind '{kind}'"])
            if kind in {'machine', 'worker'}:
                collection = 'machines' if kind == 'machine' else 'workers'
                elements = list(draft.get(collection, []))
                draft[collection] = elements
            elif flow:
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
            if kind == 'machine':
                allowed = {'name', 'capacity'}
            elif kind == 'worker':
                allowed = {'name', 'kind', 'capacity', 'qualifications'}
            if operation_id is not None:
                if kind != 'node':
                    return self._rejected(['Operations can only be edited on nodes'])
                allowed = {'duration', 'required_machines', 'required_workers'}
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

    def edit_structure(
        self, action: str, kind: str, element_id: str, changes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add, update or delete one graph element without cascading references."""
        with self._lock:
            if self._model is None or self._draft is None:
                return self._rejected(['Open a model before editing'])
            if action not in {'add', 'update', 'delete'} or kind not in {'node', 'route'}:
                return self._rejected(['Unknown structural command'])
            if not isinstance(element_id, str) or not element_id.strip():
                return self._rejected(['Provide a nonempty element ID'])
            if not self._draft.get('material_flow'):
                return self._rejected(['Structural editing requires a material_flow model'])
            changes = deepcopy(changes or {})
            allowed = ({'kind'} if action == 'add' and kind == 'node' else
                       {'input_ports', 'output_ports'} if kind == 'node' else
                       {'source_node_id', 'source_port_id', 'target_node_id', 'target_port_id'})
            if set(changes) - allowed or (action == 'delete' and changes):
                return self._rejected(['Unsupported structural properties'])
            draft = deepcopy(self._draft)
            # Detach lists and the edited mapping from any YAML aliases.
            flow = dict(draft['material_flow'])
            draft['material_flow'] = flow
            collection = 'nodes' if kind == 'node' else 'routes'
            elements = list(flow.get(collection, []))
            flow[collection] = elements
            index = next((i for i, item in enumerate(elements) if item['id'] == element_id), None)
            if action == 'add':
                if index is not None:
                    return self._rejected([f'{kind} {element_id!r} already exists'])
                if kind == 'node':
                    node_kind = changes.get('kind')
                    element: dict[str, Any] = {'id': element_id, 'kind': node_kind}
                    if node_kind != 'source':
                        element['input_ports'] = [{'id': 'in', 'port_type': 'body', 'direction': 'input'}]
                    if node_kind != 'sink':
                        element['output_ports'] = [{'id': 'out', 'port_type': 'body', 'direction': 'output'}]
                    if node_kind == 'station':
                        element['operations'] = [{'id': f'op-{element_id}', 'duration': '1s'}]
                    if node_kind == 'buffer':
                        element['capacity'] = 1
                else:
                    element = {'id': element_id, 'transit_time': 0, **changes}
                elements.append(element)
            else:
                if index is None:
                    return self._rejected([f'Unknown {kind} {element_id!r}'])
                if action == 'delete':
                    elements.pop(index)
                else:
                    elements[index] = {**elements[index], **changes}
            try:
                check_graph_shape(draft)
            except (ValueError, TypeError) as exc:
                return self._rejected([str(exc)])
            self._undo.append((deepcopy(self._draft), deepcopy(self._model)))
            self._redo.clear()
            self._set_draft(draft, self._model['name'])
            if action == 'delete' and kind == 'node':
                self._model['layout']['positions'].pop(element_id, None)
            return {**self.snapshot(), 'accepted': True}

    def drafts(self) -> list[str]:
        with self._lock:
            root = self.directory / '.drafts'
            if not root.resolve().is_relative_to(self.directory):
                return []
            return sorted(path.name for path in root.glob('*.json')
                          if path.is_file() and path.resolve().is_relative_to(root.resolve()))

    def _draft_path(self, name: str) -> Path:
        if Path(name).name != name or not name.endswith('.json'):
            raise ValueError('Use a draft filename ending in .json')
        root = self.directory / '.drafts'
        path = root / name
        if not root.resolve().is_relative_to(self.directory) or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Drafts must stay inside the project draft directory')
        return path

    def save_draft(self, name: str, *, overwrite: bool = False) -> dict[str, Any]:
        """Save incomplete configuration and presentation as a project draft."""
        with self._lock:
            if self._model is None:
                return self._rejected(['Open a model before saving a draft'])
            try:
                path = self._draft_path(name)
                path.parent.mkdir(exist_ok=True)
                document = {'version': 1, 'kind': 'industrialsim-project-draft',
                            'name': self._model['name'], 'yaml': self._model['yaml'],
                            'layout': self._model['layout'], 'layout_identity': self._layout_identity}
                _atomic_write(path, json.dumps(document, allow_nan=False), overwrite=overwrite)
                return {**self.snapshot(), 'accepted': True, 'saved_draft': name, 'drafts': self.drafts()}
            except (OSError, ValueError) as exc:
                return self._rejected([f'Could not save draft: {exc}'])

    def open_draft(self, name: str) -> dict[str, Any]:
        """Restore an editable document transactionally, retaining validation errors."""
        with self._lock:
            previous = (deepcopy(self._draft), deepcopy(self._model), self._layout_identity)
            try:
                document = json.loads(self._draft_path(name).read_text(encoding='utf-8'))
                if document['version'] != 1 or document['kind'] != 'industrialsim-project-draft':
                    raise ValueError('Unsupported draft format')
                if not isinstance(document['name'], str) or not isinstance(document['yaml'], str):
                    raise ValueError('Draft name and YAML must be text')
                identity = document['layout_identity']
                if not isinstance(identity, str) or len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
                    raise ValueError('Invalid draft layout identity')
                draft = YAML(typ='safe', pure=True).load(document['yaml'])
                if not isinstance(draft, dict):
                    raise ValueError('Draft configuration must be a mapping')
                check_graph_shape(draft)
                self._set_draft(draft, document['name'], document['yaml'])
                self._validate_layout(document['layout'])
                assert self._model is not None
                self._model['layout'] = document['layout']
                self._layout_identity = identity
            except Exception as exc:
                self._draft, self._model, self._layout_identity = previous
                return self._rejected([f'Could not open draft: {exc}'])
            self._undo.clear()
            self._redo.clear()
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
            errors = list(dict.fromkeys([*result.errors, *graph_diagnostics(self._draft)]))
            if not result.is_valid or errors:
                return self._rejected(errors)
            return {'accepted': True, 'diagnostics': [], 'yaml': self._model['yaml']}

    def save_model(self, relative_path: str, *, overwrite: bool = False) -> dict[str, Any]:
        with self._lock:
            exported = self.export_yaml()
            if not exported['accepted']:
                return exported
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
                _atomic_write(path, exported['yaml'], overwrite=overwrite)
                assert self._model is not None
                self._layout_identity = self._identity(str(path.relative_to(self.directory)), self._model['configuration'])
                layout_result = self.save_layout()
                return {**self.snapshot(), 'accepted': True, 'saved_path': relative_path,
                        'diagnostics': layout_result['diagnostics']}
            except (OSError, ValueError) as exc:
                return self._rejected([str(exc)])

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
            try:
                path = self._layout_path()
                path.parent.mkdir(exist_ok=True)
                document = {'version': 1, 'model_identity': self._layout_identity,
                            'layout': self._model['layout']}
                _atomic_write(path, json.dumps(document, allow_nan=False), overwrite=True)
                return {**self.snapshot(), 'accepted': True}
            except (OSError, ValueError) as exc:
                return self._rejected([f'Could not save layout: {exc}'])

    def _rejected(self, diagnostics: list[str]) -> dict[str, Any]:
        return {**self.snapshot(), "accepted": False, "diagnostics": diagnostics}
