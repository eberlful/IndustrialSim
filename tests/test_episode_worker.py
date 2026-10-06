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


def wait_for_state(worker: EpisodeWorker, state: str) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        episode = worker.snapshot()['episode']
        if episode and episode['state'] == state:
            return episode
        assert not episode or episode['state'] not in {'failed', 'finished', 'interrupted'}, episode
        time.sleep(.005)
    raise AssertionError(f'Episode did not reach {state}')


def test_pause_continue_preserve_episode_and_lossless_pages_under_reads(tmp_path: Path) -> None:
    model = MODEL.replace('quantity: 2000', 'quantity: 1000') + '\ntelemetry: {enabled: true, sample_interval: 1s}\n'
    with EpisodeWorker(tmp_path) as worker:
        started = worker.start(model)['episode']
        deadline = time.monotonic() + 30
        while worker.snapshot()['episode']['events_processed'] == 0:
            assert time.monotonic() < deadline
            worker.events(started['id'], cursor=0, limit=1)
            time.sleep(.005)
        assert worker.pause(started['id'])['accepted']
        paused = wait_for_state(worker, 'paused')
        assert paused['observation'] is not None
        assert paused['events_processed'] > 0
        for _ in range(25):
            snapshot = worker.snapshot()['episode']
            assert snapshot['simulated_time_ns'] == paused['simulated_time_ns']
            assert snapshot['events_processed'] == paused['events_processed']
            worker.events(started['id'], cursor=0, limit=1)
        assert not worker.start(model)['accepted']
        assert not worker.continue_episode('stale-id')['accepted']
        assert not (tmp_path / paused['result_path'] / 'summary.json').exists()
        assert worker.continue_episode(started['id'])['accepted']
        assert worker.pause(started['id'])['accepted']
        wait_for_state(worker, 'paused')
        assert worker.continue_episode(started['id'])['accepted']
        outcome = wait_for_outcome(worker)
        direct_dir = tmp_path / 'direct'
        assert outcome['summary'] == run_episode(model, decision_provider=BaselineDecisionProvider(), output_dir=direct_dir).to_dict()
        records = []
        cursor = 0
        while True:
            page = worker.events(started['id'], cursor, 7)
            records.extend(page['records'])
            cursor = page['next_cursor']
            if not page['has_more']:
                break
        from industrialsim.audit import load_audit_log
        assert records == [r.model_dump(mode='json') for r in load_audit_log(direct_dir)]
        assert [r['record_id'] for r in records] == list(range(len(records)))
        import pyarrow.parquet as pq
        def telemetry(directory: Path) -> list:
            return [pq.read_table(p).to_pylist() for p in sorted((directory / 'telemetry').glob('metrics_fragment_*.parquet'))]
        assert telemetry(tmp_path / outcome['result_path']) == telemetry(direct_dir)
        assert not worker.pause(started['id'])['accepted']
        compact = worker.snapshot(include_history=False)['episode']['summary']
        assert 'production_units' not in compact
        assert compact['raw_metrics'] == outcome['summary']['raw_metrics']


def test_paced_episode_remains_observable_and_pause_is_responsive(tmp_path: Path) -> None:
    model = MODEL.replace('quantity: 2000', 'quantity: 3')
    with EpisodeWorker(tmp_path) as worker:
        started = worker.start(model, step_delay_seconds=1)['episode']
        time.sleep(.15)
        observed = worker.snapshot()['episode']
        assert observed['state'] == 'running'
        assert observed['observation'] is not None
        assert observed['events_processed'] > 0
        before_pause = time.monotonic()
        assert worker.pause(started['id'])['accepted']
        paused = wait_for_state(worker, 'paused')
        assert time.monotonic() - before_pause < .5
        time.sleep(.1)
        assert worker.snapshot()['episode']['events_processed'] == paused['events_processed']
        assert worker.continue_episode(started['id'])['accepted']
        outcome = wait_for_outcome(worker)
        assert outcome['summary'] == run_episode(model, decision_provider=BaselineDecisionProvider()).to_dict()
