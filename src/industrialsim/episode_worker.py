"""One local Episode owned by a serialized worker, independent of HTTP clients."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event, RLock
from typing import Any
from uuid import uuid4

from industrialsim.application import EpisodeSession, validate_config
from industrialsim.config import SimulationConfig
from industrialsim.decisions import BaselineDecisionProvider


class EpisodeWorker:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve(strict=True)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='industrialsim-episode')
        self._lock = RLock()
        self._stop = Event()
        self._episode: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        """Read the last published state; never access the advancing engine."""
        with self._lock:
            return {'episode': deepcopy(self._episode)}

    def start(self, source: str | Path | dict[str, Any] | SimulationConfig) -> dict[str, Any]:
        with self._lock:
            if self._stop.is_set():
                return {**self.snapshot(), 'accepted': False, 'diagnostics': ['Episode worker is closed']}
            if self._episode and self._episode['state'] == 'running':
                return {**self.snapshot(), 'accepted': False, 'diagnostics': ['An Episode is already active']}
            validation = validate_config(source)
            if not validation.is_valid or validation.config is None:
                return {**self.snapshot(), 'accepted': False, 'diagnostics': validation.errors}
            if not (self.directory / 'runs').resolve().is_relative_to(self.directory):
                return {**self.snapshot(), 'accepted': False, 'diagnostics': ['Episode results must stay inside the project']}
            config = validation.config.model_copy(deep=True)
            episode_id = uuid4().hex
            self._episode = {
                'id': episode_id, 'state': 'running', 'provider': 'Baseline',
                'seed': str(config.seed), 'result_path': f'runs/{episode_id}',
                'simulated_time_ns': str(config.episode.start_time_ns),
                'events_processed': 0, 'summary': None, 'diagnostics': [],
            }
            result = {**self.snapshot(), 'accepted': True, 'diagnostics': []}
            self._executor.submit(self._execute, config, self.directory / self._episode['result_path'])
            return result

    def _publish(self, **changes: Any) -> None:
        with self._lock:
            assert self._episode is not None
            self._episode.update(changes)

    def _execute(self, config: SimulationConfig, output_dir: Path) -> None:
        session: EpisodeSession | None = None
        try:
            session = EpisodeSession(config, decision_provider=BaselineDecisionProvider(), output_dir=output_dir)
            while not session.finished and not self._stop.is_set():
                summary = session.advance(max_events=1000)
                self._publish(simulated_time_ns=str(summary.simulated_time_ns), events_processed=summary.events_processed)
            if self._stop.is_set():
                self._publish(state='interrupted', diagnostics=['Service stopped before Episode finalization'])
            else:
                summary = session.finalize()
                self._publish(state='finished', summary=summary.to_dict(),
                              simulated_time_ns=str(summary.simulated_time_ns), events_processed=summary.events_processed)
        except Exception as exc:
            self._publish(state='failed', diagnostics=[str(exc)])
        finally:
            if session is not None:
                session.close()

    def close(self) -> None:
        """Stop at the next consistent boundary and leave unfinished output marked."""
        with self._lock:
            self._stop.set()
        self._executor.shutdown(wait=True)

    def __enter__(self) -> EpisodeWorker:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
