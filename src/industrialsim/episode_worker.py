"""One local Episode owned by a serialized worker, independent of HTTP clients."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Condition, Event, RLock
from time import monotonic
from typing import Any
from uuid import uuid4

from industrialsim.application import EpisodeSession, validate_config
from industrialsim.audit import event_page_end
from industrialsim.config import SimulationConfig
from industrialsim.decisions import BaselineDecisionProvider


class EpisodeWorker:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve(strict=True)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='industrialsim-episode')
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._stop = Event()
        self._episode: dict[str, Any] | None = None
        self._events: list[dict[str, Any]] = []
        self._started_at = 0.0
        self._submission: tuple[str, list[dict[str, Any]], Future[dict[str, Any]]] | None = None

    def snapshot(self, *, include_history: bool = True) -> dict[str, Any]:
        """Read the last published state; never access the advancing engine."""
        with self._lock:
            published = self._episode
            if published and published['summary'] and not include_history:
                published = {**published, 'summary': {key: published['summary'][key] for key in (
                    'status', 'result_hash', 'raw_metrics', 'reward', 'seed',
                )}}
            episode = deepcopy(published)
            if episode and episode['state'] in {'running', 'pausing', 'paused', 'seeking_batch', 'awaiting_decisions', 'resolving'}:
                episode['wall_clock_seconds'] = monotonic() - self._started_at
            return {'episode': episode}

    def start(self, source: str | Path | dict[str, Any] | SimulationConfig, mode: str = 'baseline') -> dict[str, Any]:
        with self._lock:
            if mode not in {'baseline', 'manual'}:
                return {**self.snapshot(include_history=False), 'accepted': False, 'diagnostics': ['Choose Baseline or manual decisions']}
            if self._stop.is_set():
                return {**self.snapshot(include_history=False), 'accepted': False, 'diagnostics': ['Episode worker is closed']}
            if self._episode and self._episode['state'] in {'running', 'pausing', 'paused', 'seeking_batch', 'awaiting_decisions', 'resolving'}:
                return {**self.snapshot(include_history=False), 'accepted': False, 'diagnostics': ['An Episode is already active']}
            validation = validate_config(source)
            if not validation.is_valid or validation.config is None:
                return {**self.snapshot(include_history=False), 'accepted': False, 'diagnostics': validation.errors}
            if not (self.directory / 'runs').resolve().is_relative_to(self.directory):
                return {**self.snapshot(include_history=False), 'accepted': False, 'diagnostics': ['Episode results must stay inside the project']}
            config = validation.config.model_copy(deep=True)
            episode_id = uuid4().hex
            self._started_at = monotonic()
            self._events = []
            self._episode = {
                'id': episode_id, 'state': 'running', 'provider': 'Manual' if mode == 'manual' else 'Baseline', 'mode': mode,
                'seed': str(config.seed), 'result_path': f'runs/{episode_id}',
                'simulated_time_ns': str(config.episode.start_time_ns),
                'events_processed': 0, 'summary': None, 'diagnostics': [],
                'wall_clock_seconds': 0.0, 'observation': None, 'decision_batch': None,
            }
            result = {**self.snapshot(include_history=False), 'accepted': True, 'diagnostics': []}
            self._executor.submit(self._execute, config, self.directory / self._episode['result_path'])
            return result

    def _control(self, episode_id: str, allowed: set[str], state: str) -> dict[str, Any]:
        with self._condition:
            if (self._stop.is_set() or not self._episode or self._episode['id'] != episode_id
                    or self._episode['state'] not in allowed):
                return {**self.snapshot(include_history=False), 'accepted': False, 'diagnostics': ['Episode control is not available in this state']}
            if not (state == 'pausing' and self._episode['state'] == 'paused'):
                self._episode['state'] = state
            self._condition.notify_all()
            return {**self.snapshot(include_history=False), 'accepted': True, 'diagnostics': []}

    def pause(self, episode_id: str) -> dict[str, Any]:
        """Request a pause; the worker acknowledges it at a settled boundary."""
        return self._control(episode_id, {'running', 'seeking_batch', 'pausing', 'paused'}, 'pausing')

    def continue_episode(self, episode_id: str) -> dict[str, Any]:
        with self._lock:
            if self._episode and self._episode['state'] == 'awaiting_decisions' and self._episode['mode'] == 'baseline' and self._submission is None:
                return self._control(episode_id, {'awaiting_decisions'}, 'resolving')
            return self._control(episode_id, {'paused'}, 'running')

    def next_decision_batch(self, episode_id: str) -> dict[str, Any]:
        return self._control(episode_id, {'running', 'paused'}, 'seeking_batch')

    def submit_decision_batch(self, episode_id: str, batch_id: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
        """Queue a proposal for validation/application by the session owner."""
        with self._condition:
            if (self._stop.is_set() or not self._episode or self._episode['id'] != episode_id
                    or self._episode['state'] != 'awaiting_decisions' or self._submission is not None
                    or self._episode['decision_batch']['batch']['batch_id'] != batch_id):
                return {**self.snapshot(include_history=False), 'accepted': False,
                        'diagnostics': ['This Episode/Decision Batch is no longer awaiting this submission']}
            future: Future[dict[str, Any]] = Future()
            self._submission = (batch_id, deepcopy(actions), future)
            self._condition.notify_all()
        return future.result()

    def events(self, episode_id: str, cursor: int = 0, limit: int = 100) -> dict[str, Any]:
        """Page only published events. Cursors are scoped to one Episode."""
        with self._lock:
            if not self._episode or self._episode['id'] != episode_id:
                raise ValueError('Episode is no longer available')
            end = event_page_end(len(self._events), cursor, limit)
            return {'episode_id': episode_id, 'records': deepcopy(self._events[cursor:end]),
                    'next_cursor': end, 'has_more': end < len(self._events)}

    def _publish(self, session: EpisodeSession, **changes: Any) -> None:
        observation = session.observe()
        summary = session.snapshot()
        records: list[dict[str, Any]] = []
        cursor = len(self._events)
        while True:
            page = session.events(cursor, 500)
            records.extend(page['records'])
            cursor = page['next_cursor']
            if not page['has_more']:
                break
        with self._lock:
            assert self._episode is not None
            self._events.extend(records)
            self._episode.update(observation=observation, decision_batch=session.decision_batch(), simulated_time_ns=str(summary.simulated_time_ns),
                                 events_processed=summary.events_processed,
                                 wall_clock_seconds=monotonic() - self._started_at, **changes)

    def _execute(self, config: SimulationConfig, output_dir: Path) -> None:
        session: EpisodeSession | None = None
        try:
            session = EpisodeSession(config, decision_provider=BaselineDecisionProvider(), output_dir=output_dir)
            self._publish(session)
            published_at = monotonic()
            while not session.finished and not self._stop.is_set():
                submission = None
                with self._condition:
                    assert self._episode is not None
                    if self._episode['state'] == 'pausing':
                        self._publish(session, state='paused')
                    self._condition.wait_for(lambda: self._stop.is_set() or self._submission is not None
                        or bool(self._episode and self._episode['state'] not in {'paused', 'awaiting_decisions'}))
                    if self._stop.is_set():
                        break
                    state = self._episode['state']
                    if self._submission is not None:
                        submission = self._submission
                    seek_batch = self._episode['mode'] == 'manual' or state == 'seeking_batch'
                if submission is not None:
                    batch_id, actions, future = submission
                    result = session.submit_decision_batch(batch_id, actions)
                    self._publish(session, state='paused' if result['accepted'] else 'awaiting_decisions')
                    with self._condition:
                        self._submission = None
                        future.set_result({**self.snapshot(include_history=False), **result})
                    continue
                if state == 'resolving':
                    session.resolve_decision_batch()
                    self._publish(session, state='running')
                    continue
                session.advance(pause_at_decision_batch=seek_batch, max_events=1000)
                if session.awaiting_decision_batch:
                    self._publish(session, state='awaiting_decisions')
                    published_at = monotonic()
                elif monotonic() - published_at >= .1:
                    self._publish(session)
                    published_at = monotonic()
            if self._stop.is_set():
                self._publish(session, state='interrupted', diagnostics=['Service stopped before Episode finalization'])
            else:
                summary = session.finalize()
                self._publish(session, state='finished', summary=summary.to_dict())
        except Exception as exc:
            with self._lock:
                assert self._episode is not None
                self._episode.update(state='failed', diagnostics=[str(exc)],
                                     wall_clock_seconds=monotonic() - self._started_at)
        finally:
            with self._condition:
                if self._submission is not None:
                    _, _, future = self._submission
                    self._submission = None
                    future.set_result({**self.snapshot(include_history=False), 'accepted': False,
                                       'diagnostics': ['Episode worker stopped before submission completed']})
            if session is not None:
                session.close()

    def close(self) -> None:
        """Stop at the next consistent boundary and leave unfinished output marked."""
        with self._condition:
            self._stop.set()
            self._condition.notify_all()
        self._executor.shutdown(wait=True)

    def __enter__(self) -> EpisodeWorker:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
