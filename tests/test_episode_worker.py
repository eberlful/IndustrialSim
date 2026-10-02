"""Public service-owned Episode execution without browser lifetime coupling."""
from pathlib import Path
import time

from industrialsim.application import run_episode
from industrialsim.decisions import BaselineDecisionProvider
from industrialsim.episode_worker import EpisodeWorker
from industrialsim.project import ProjectSession

MODEL = '''
episode: {end_condition: {type: all_units_terminal}}
production_plan: [{id: batch, variant: sedan, quantity: 2000}]
stations: [{id: station, operations: [{id: op, duration: 1s}]}]
'''


def wait_for_outcome(worker: EpisodeWorker) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        episode = worker.snapshot()['episode']
        if episode is not None and episode['state'] != 'running':
            return episode
        time.sleep(.01)
    raise AssertionError('Episode did not finish')


def test_worker_rejects_replacement_freezes_draft_and_publishes_unique_artifacts(tmp_path: Path) -> None:
    project = ProjectSession(tmp_path)
    project.import_yaml(MODEL)
    with EpisodeWorker(tmp_path) as worker:
        started = worker.start(project.export_yaml()['yaml'])
        assert started['accepted']
        first = started['episode']
        rejected = worker.start(MODEL)
        assert not rejected['accepted']
        assert rejected['episode']['id'] == first['id']
        assert project.edit_episode({'seed': 7})['model']['valid']
        outcome = wait_for_outcome(worker)
        assert outcome['state'] == 'finished', outcome
        assert outcome['id'] == first['id']
        assert outcome['summary'] == run_episode(MODEL, decision_provider=BaselineDecisionProvider()).to_dict()
        directory = tmp_path / outcome['result_path']
        assert (directory / 'manifest.json').exists()
        assert (directory / 'summary.json').exists()
        assert (directory / 'audit.jsonl').exists()
        assert not (directory / '.incomplete').exists()
        original = (directory / 'summary.json').read_bytes()
        next_episode = worker.start(project.export_yaml()['yaml'])
        assert next_episode['accepted']
        assert next_episode['episode']['result_path'] != outcome['result_path']
        assert wait_for_outcome(worker)['summary']['seed'] == 7
        assert (directory / 'summary.json').read_bytes() == original


def test_invalid_start_does_not_allocate_output_or_replace_outcome(tmp_path: Path) -> None:
    with EpisodeWorker(tmp_path) as worker:
        rejected = worker.start('seed: 42\n')
        assert not rejected['accepted']
        assert rejected['diagnostics']
        assert rejected['episode'] is None
        assert not (tmp_path / 'runs').exists()
