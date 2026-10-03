"""Explicit, project-local durable recovery for Baseline/manual sessions."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from industrialsim.checkpoint import Checkpoint, deserialize_checkpoint, serialize_checkpoint


class SavedCheckpoints:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, name: str) -> Path:
        folder = (self.directory / 'checkpoints').resolve()
        path = (self.directory / name).resolve()
        if not folder.is_relative_to(self.directory) or not path.is_relative_to(folder) or path.suffix != '.json':
            raise ValueError('Select a saved Checkpoint inside this project’s checkpoints directory')
        return path

    def save(self, checkpoint: Checkpoint, *, episode_id: str, result_path: str, mode: str) -> dict[str, Any]:
        name = f'checkpoints/{uuid4().hex}.json'
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.loads(serialize_checkpoint(checkpoint))
        metadata = {'path': name, 'episode_id': episode_id, 'result_path': result_path, 'mode': mode,
                    'config_hash': checkpoint.config_hash, 'model_hash': checkpoint.model_hash,
                    'simulated_time_ns': str(checkpoint.simulated_time_ns),
                    'checkpoint_hash': payload['checksum'], 'created_at': datetime.now(timezone.utc).isoformat()}
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False, prefix='.checkpoint-') as stream:
            temporary = Path(stream.name)
            try:
                json.dump({'version': 1, 'metadata': metadata, 'checkpoint': payload}, stream)
                stream.flush()
                os.fsync(stream.fileno())
                os.link(temporary, path)
                folder_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(folder_fd)
                finally:
                    os.close(folder_fd)
            finally:
                temporary.unlink(missing_ok=True)
        return metadata

    def load(self, name: str) -> tuple[Checkpoint, dict[str, Any]]:
        document = json.loads(self._path(name).read_text(encoding='utf-8'))
        if document['version'] != 1:
            raise ValueError('Unsupported saved Checkpoint version; choose a compatible Checkpoint')
        metadata = document['metadata']
        if metadata['mode'] not in {'baseline', 'manual'}:
            raise ValueError('Recovery supports only Baseline and manual decisions')
        cp = deserialize_checkpoint(document['checkpoint'])
        if (metadata['config_hash'] != cp.config_hash or metadata['model_hash'] != cp.model_hash
                or metadata['checkpoint_hash'] != cp.checksum):
            raise ValueError('Saved Checkpoint metadata does not match its continuation state')
        return cp, {**metadata, 'path': name}

    def list(self) -> list[dict[str, Any]]:
        folder = (self.directory / 'checkpoints').resolve()
        if not folder.is_relative_to(self.directory):
            return []
        entries = []
        for path in sorted(folder.glob('*.json')):
            name = str(path.relative_to(self.directory))
            try:
                _, metadata = self.load(name)
                entries.append(metadata)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                entries.append({'path': name, 'diagnostic': f'Checkpoint cannot be read: {exc}'})
        return entries
