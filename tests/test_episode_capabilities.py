"""Published availability and admission share one worker policy."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from industrialsim.application import EpisodeSession
from industrialsim.episode_worker import EpisodeWorker
from test_manual_episode_worker import MODEL, wait_for


def test_capabilities_follow_identity_mode_and_terminal_states(tmp_path):
    with EpisodeWorker(tmp_path) as worker:
        initial = worker.snapshot()
        assert initial['episode'] is None
        assert {key for key, enabled in initial['capabilities'].items() if enabled} == {'start', 'restore'}
        started = worker.start(MODEL, mode='manual')
        episode = wait_for(worker, 'awaiting_decisions')
        capabilities = worker.snapshot()['capabilities']
        assert {key for key, enabled in capabilities.items() if enabled} == {'checkpoint', 'submit_batch'}
        assert not worker.create_checkpoint('stale')['accepted']
        assert not worker.continue_episode(episode['id'])['accepted']
        batch = episode['decision_batch']['batch']
        rejected = worker.submit_decision_batch(episode['id'], batch['batch_id'], [])
        assert rejected['capabilities'] == capabilities
        assert worker.snapshot()['episode']['id'] == started['episode']['id']
    assert not any(worker.snapshot()['capabilities'].values())


def test_checkpoint_excludes_competing_commands_until_its_future_completes(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    capture = EpisodeSession.create_checkpoint

    def blocking_capture(session):
        entered.set()
        assert release.wait(5)
        return capture(session)

    monkeypatch.setattr(EpisodeSession, 'create_checkpoint', blocking_capture)
    with EpisodeWorker(tmp_path) as worker, ThreadPoolExecutor(max_workers=1) as callers:
        worker.start(MODEL, mode='manual')
        episode = wait_for(worker, 'awaiting_decisions')
        pending = callers.submit(worker.create_checkpoint, episode['id'])
        try:
            assert entered.wait(5)
            assert not any(worker.snapshot()['capabilities'].values())
            assert not worker.create_checkpoint(episode['id'])['accepted']
            assert not worker.pause(episode['id'])['accepted']
            batch = episode['decision_batch']['batch']
            assert not worker.submit_decision_batch(episode['id'], batch['batch_id'], [])['accepted']
        finally:
            release.set()
        completed = pending.result(timeout=5)
        assert completed['accepted']
        assert completed['capabilities']['checkpoint']
        assert completed['capabilities']['submit_batch']


def test_failed_submission_completes_waiter_and_publishes_terminal_capabilities(tmp_path, monkeypatch):
    def fail(session, batch_id, actions):
        raise RuntimeError('submission failed')

    monkeypatch.setattr(EpisodeSession, 'submit_decision_batch', fail)
    with EpisodeWorker(tmp_path) as worker, ThreadPoolExecutor(max_workers=1) as callers:
        worker.start(MODEL, mode='manual')
        episode = wait_for(worker, 'awaiting_decisions')
        batch_id = episode['decision_batch']['batch']['batch_id']
        result = callers.submit(worker.submit_decision_batch, episode['id'], batch_id, []).result(timeout=5)
        assert not result['accepted']
        assert result['episode']['state'] == 'failed'
        assert result['capabilities']['start']
        assert result['capabilities']['restore']
        assert not result['capabilities']['submit_batch']
