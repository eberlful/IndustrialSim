"""Manual control through the service-owned Episode worker's public seam."""
import time
from pathlib import Path
from industrialsim.episode_worker import EpisodeWorker

MODEL = '''
episode: {end_condition: {type: max_time, max_time: 2s}}
production_plan: [{id: batch, variant: sedan, quantity: 1, release_time: 2s}]
stations: [{id: station, operations: [{id: op, duration: 1s}]}]
decision_triggers:
  - {id: safe, trigger_type: safe_point, target_id: station, times_ns: [0, 1000000000], on_failure: abort}
'''


def wait_for(worker: EpisodeWorker, state: str) -> dict:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        episode = worker.snapshot()['episode']
        if episode['state'] == state:
            return episode
        assert episode['state'] not in {'failed', 'interrupted'}, episode
        time.sleep(.005)
    raise AssertionError(f'Worker did not reach {state}')


def test_manual_mode_freezes_batch_rejects_invalid_and_repeated_submissions(tmp_path: Path) -> None:
    with EpisodeWorker(tmp_path) as worker:
        started = worker.start(MODEL, mode='manual')['episode']
        episode = wait_for(worker, 'awaiting_decisions')
        batch = episode['decision_batch']['batch']
        assert episode['id'] == started['id']
        assert not worker.start(MODEL)['accepted']
        assert not worker.continue_episode(episode['id'])['accepted']
        result = worker.submit_decision_batch(episode['id'], batch['batch_id'], [])
        assert not result['accepted']
        assert result['episode']['state'] == 'awaiting_decisions'
        assert result['episode']['simulated_time_ns'] == episode['simulated_time_ns']
        action = {'action_type': 'reconfiguration', 'target_id': 'station', 'configuration': {}}
        accepted = worker.submit_decision_batch(episode['id'], batch['batch_id'], [action])
        assert accepted['accepted'], accepted
        assert accepted['episode']['state'] == 'paused'
        assert not worker.submit_decision_batch(episode['id'], batch['batch_id'], [action])['accepted']
        assert worker.next_decision_batch(episode['id'])['accepted']
        next_episode = wait_for(worker, 'awaiting_decisions')
        assert next_episode['decision_batch']['batch']['batch_id'] != batch['batch_id']
        assert not worker.submit_decision_batch('stale', next_episode['decision_batch']['batch']['batch_id'], [action])['accepted']
        assert not worker.submit_decision_batch(episode['id'], batch['batch_id'], [action])['accepted']
        assert worker.submit_decision_batch(episode['id'], next_episode['decision_batch']['batch']['batch_id'], [action])['accepted']
        assert worker.continue_episode(episode['id'])['accepted']
        outcome = wait_for(worker, 'finished')
        assert len(outcome['summary']['decision_batches']) == 2
        assert all(batch['provenance']['provider_id'] == 'manual' for batch in outcome['summary']['decision_batches'])


def test_baseline_next_batch_control_can_pause_then_use_existing_provider_failure_policy(tmp_path: Path) -> None:
    with EpisodeWorker(tmp_path) as worker:
        episode = worker.start(MODEL)['episode']
        assert worker.next_decision_batch(episode['id'])['accepted']
        pending = wait_for(worker, 'awaiting_decisions')
        assert pending['mode'] == 'baseline'
        assert pending['decision_batch'] is not None
        assert worker.continue_episode(episode['id'])['accepted']
        outcome = wait_for(worker, 'finished')
        assert outcome['summary']['is_aborted']
        assert outcome['summary']['decision_batches'][0]['status'] == 'aborted'
