"""Durable continuation through public EpisodeSession interfaces."""
from pathlib import Path

from industrialsim.application import EpisodeSession, run_episode
from industrialsim.checkpoint import save_checkpoint
from industrialsim.decisions import BaselineDecisionProvider

MODEL = '''
seed: 42
episode: {end_condition: {type: all_units_terminal}}
production_plan: [{id: batch, variant: sedan, quantity: 3}]
stations: [{id: original, operations: [{id: op, duration: 10s}]}]
'''


def test_restored_session_matches_uninterrupted_and_preserves_original_artifacts(tmp_path: Path) -> None:
    original = tmp_path / 'original'
    session = EpisodeSession(MODEL, decision_provider=BaselineDecisionProvider(), output_dir=original)
    session.advance(until_time_ns=5_000_000_000)
    checkpoint = session.create_checkpoint()
    save_checkpoint(checkpoint, tmp_path / 'saved.json')
    session.close()
    before = {path.relative_to(original): path.read_bytes() for path in original.rglob('*') if path.is_file()}
    restored = EpisodeSession.from_checkpoint(tmp_path / 'saved.json', decision_provider=BaselineDecisionProvider(),
                                             output_dir=tmp_path / 'restored', episode_id='restored', parent_run_id='original')
    assert restored.snapshot().simulated_time_ns == 5_000_000_000
    restored.advance()
    assert restored.finalize().to_dict() == run_episode(MODEL, decision_provider=BaselineDecisionProvider()).to_dict()
    assert {path.relative_to(original): path.read_bytes() for path in original.rglob('*') if path.is_file()} == before
    restored.close()


def test_pending_manual_batch_survives_checkpoint_without_answering_or_duplicating() -> None:
    model = MODEL.replace('production_plan:', 'decision_triggers: [{id: safe, trigger_type: safe_point, target_id: original, times_ns: [0]}]\nproduction_plan:')
    session = EpisodeSession(model)
    session.advance_to_next_decision_batch()
    pending = session.decision_batch()
    restored = EpisodeSession.from_checkpoint(session.create_checkpoint())
    assert restored.decision_batch() == pending
    assert restored.snapshot().simulated_time_ns == 0
    assert not restored.submit_decision_batch(pending['batch']['batch_id'], [])['accepted']
    proposal = [{'action_type': 'reconfiguration', 'target_id': 'original', 'configuration': {}, 'duration_ns': 0}]
    assert restored.submit_decision_batch(pending['batch']['batch_id'], proposal)['accepted']
    assert not restored.submit_decision_batch(pending['batch']['batch_id'], proposal)['accepted']
    assert session.submit_decision_batch(pending['batch']['batch_id'], proposal)['accepted']
    restored.advance()
    session.advance()
    assert restored.finalize().to_dict() == session.finalize().to_dict()
    session.close()
    restored.close()


def test_worker_restart_requires_explicit_restore_and_rejects_old_episode_identity(tmp_path: Path) -> None:
    from industrialsim.episode_worker import EpisodeWorker
    from test_episode_worker import wait_for_state
    model = MODEL.replace('production_plan:', 'decision_triggers: [{id: safe, trigger_type: safe_point, target_id: original, times_ns: [0]}]\nproduction_plan:')
    with EpisodeWorker(tmp_path) as worker:
        worker.start(model, mode='manual')
        original = wait_for_state(worker, 'awaiting_decisions')
        saved = worker.create_checkpoint(original['id'])
        assert saved['accepted']
        pending = original['decision_batch']
    before = {path.relative_to(tmp_path): path.read_bytes() for path in (tmp_path / original['result_path']).rglob('*') if path.is_file()}
    with EpisodeWorker(tmp_path) as worker:
        assert worker.snapshot()['episode'] is None
        assert worker.checkpoints()[0]['episode_id'] == original['id']
        result = worker.restore_checkpoint(saved['checkpoint']['path'])
        assert result['accepted'], result
        restored = wait_for_state(worker, 'awaiting_decisions')
        assert restored['id'] != original['id']
        assert restored['decision_batch'] == pending
        assert restored['configuration']['stations'][0]['id'] == 'original'
        proposal = [{'action_type': 'reconfiguration', 'target_id': 'original', 'configuration': {}, 'duration_ns': 0}]
        assert not worker.submit_decision_batch(original['id'], pending['batch']['batch_id'], proposal)['accepted']
        assert worker.submit_decision_batch(restored['id'], pending['batch']['batch_id'], proposal)['accepted']
        assert not worker.submit_decision_batch(restored['id'], pending['batch']['batch_id'], proposal)['accepted']
        worker.continue_episode(restored['id'])
        outcome = wait_for_state(worker, 'finished')
        import json
        manifest = json.loads((tmp_path / outcome['result_path'] / 'manifest.json').read_text())
        assert manifest['parent_run_id'] == original['id']
        assert manifest['checkpoint_hash'] == saved['checkpoint']['checkpoint_hash']
    assert {path.relative_to(tmp_path): path.read_bytes() for path in (tmp_path / original['result_path']).rglob('*') if path.is_file()} == before


def test_incompatible_checkpoints_reject_before_creating_continuation_artifacts(tmp_path: Path) -> None:
    import pytest
    from industrialsim.checkpoint import IncompatibleCheckpointError
    for field, value, message in [
        ('schema_version', 'unsupported', 'schema version'),
        ('kernel_version', 'unsupported', 'kernel version'),
        ('model_hash', 'different', 'Model hash mismatch'),
        ('config_hash', 'different', 'Configuration hash mismatch'),
        ('plugin_metadata', {'missing-plugin': '1'}, 'not available'),
        ('plugin_metadata', {'micro_station_plugin': 'unsupported'}, 'plugin version'),
    ]:
        session = EpisodeSession(MODEL)
        session.advance(until_time_ns=5_000_000_000)
        cp = session.create_checkpoint()
        setattr(cp, field, value)
        destination = tmp_path / field
        with pytest.raises(IncompatibleCheckpointError, match=message):
            EpisodeSession.from_checkpoint(cp, output_dir=destination)
        assert not destination.exists()
        session.close()


def test_worker_rejects_corrupted_checkpoint_without_replacing_session(tmp_path: Path) -> None:
    from industrialsim.episode_worker import EpisodeWorker
    with EpisodeWorker(tmp_path) as worker:
        folder = tmp_path / 'checkpoints'
        folder.mkdir()
        (folder / 'broken.json').write_text('{bad json')
        assert 'cannot be read' in worker.checkpoints()[0]['diagnostic']
        rejected = worker.restore_checkpoint('checkpoints/broken.json')
        assert not rejected['accepted']
        assert 'restore rejected' in rejected['diagnostics'][0]
        assert worker.snapshot()['episode'] is None
        assert not (tmp_path / 'runs').exists()
        assert not worker.restore_checkpoint('../outside.json')['accepted']


def test_pending_buffer_observation_history_survives_durable_restore(tmp_path: Path) -> None:
    from test_decision_simulation_e2e import BASE_DECISION_YAML
    session = EpisodeSession(BASE_DECISION_YAML)
    session.advance_to_next_decision_batch()
    pending = session.decision_batch()
    assert pending is not None
    save_checkpoint(session.create_checkpoint(), tmp_path / 'buffer.json')
    restored = EpisodeSession.from_checkpoint(tmp_path / 'buffer.json')
    assert restored.decision_batch() == pending
    session.close()
    restored.close()


def test_restored_deadlock_clock_and_telemetry_match_uninterrupted_execution() -> None:
    model = MODEL.replace('quantity: 3', 'quantity: 3, release_time: 4s') + '''
deadlock: {enabled: true, max_interval_without_progress: 3s}
telemetry: {enabled: true, sample_interval: 1s}
'''
    session = EpisodeSession(model, decision_provider=BaselineDecisionProvider())
    session.advance(until_time_ns=5_000_000_000)
    restored = EpisodeSession.from_checkpoint(session.create_checkpoint(), decision_provider=BaselineDecisionProvider())
    session.advance()
    restored.advance()
    assert restored.finalize().to_dict() == session.finalize().to_dict()
    session.close()
    restored.close()


def test_checkpoint_after_manual_effects_retains_reconfiguration_and_cost() -> None:
    model = MODEL.replace('production_plan:', 'decision_triggers: [{id: safe, trigger_type: safe_point, target_id: original, times_ns: [0]}]\nproduction_plan:')
    session = EpisodeSession(model, decision_provider=BaselineDecisionProvider())
    session.advance_to_next_decision_batch()
    batch = session.decision_batch()['batch']
    assert session.submit_decision_batch(batch['batch_id'], [
        {'action_type': 'reconfiguration', 'target_id': 'original', 'configuration': {'cycle_time_multiplier': 1.5},
         'duration_ns': 5_000_000_000, 'cost': 7},
    ])['accepted']
    restored = EpisodeSession.from_checkpoint(session.create_checkpoint(), decision_provider=BaselineDecisionProvider())
    assert restored.observe()['stations']['original']['reconfiguring'] is True
    assert restored.snapshot().total_strategic_cost == 7
    session.advance()
    restored.advance()
    assert restored.finalize().to_dict() == session.finalize().to_dict()
    session.close()
    restored.close()
