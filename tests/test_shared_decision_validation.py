"""The same decision rules apply at every Episode interface."""
import pytest

from industrialsim.application import EpisodeSession
from industrialsim.decisions import (
    DecisionBatchResponse, DecisionProvenance, DecisionProvider, MachineModeAction,
)


class InvalidModeProvider(DecisionProvider):
    def __init__(self) -> None:
        self.batches = []

    def decide(self, batch):
        self.batches.append(batch.model_dump(mode='json'))
        return DecisionBatchResponse(batch_id=batch.batch_id,
            provenance=DecisionProvenance(episode_id=batch.episode_id, branch_id=batch.branch_id,
                batch_id=batch.batch_id, provider_id='invalid-mode'),
            actions=[MachineModeAction(target_id='machine', mode='unknown')])


@pytest.mark.parametrize('health,expected_status', [(1.0, 'fallback'), (0.1, 'aborted')])
def test_manual_provider_and_fallback_share_validation_without_partial_effects(health, expected_status):
    model = f'''
episode: {{end_condition: {{type: max_time, max_time: 1s}}}}
production_plan: [{{id: batch, variant: sedan, quantity: 1, release_time: 1s}}]
stations: [{{id: station, operations: [{{id: op, duration: 1s}}]}}]
machines: [{{id: machine, initial_health: {health}}}]
decision_triggers:
  - {{id: safe, trigger_type: safe_point, target_id: machine, times_ns: [0], on_failure: fallback}}
'''
    provider = InvalidModeProvider()
    with_session = EpisodeSession(model, decision_provider=provider)
    try:
        with_session.advance_to_next_decision_batch()
        pending = with_session.decision_batch()
        batch = pending['batch']
        before = with_session.observe()
        cursor = with_session.events()['next_cursor']
        checkpoint = with_session.create_checkpoint()
        rejected = with_session.submit_decision_batch(batch['batch_id'], [
            {'action_type': 'machine_mode', 'target_id': 'machine', 'mode': 'unknown'}])
        assert not rejected['accepted']
        assert any(d['code'] == 'INVALID_ACTION_CHOICE' for d in rejected['diagnostics'])
        assert with_session.observe() == before
        assert with_session.events(cursor)['records'] == []
        assert with_session.create_checkpoint() == checkpoint
        assert with_session.decision_batch() == pending
        assert provider.batches == []

        summary = with_session.resolve_decision_batch()
        assert provider.batches == [batch]
        assert summary.decision_batches[0]['status'] == expected_status
        assert with_session.observe()['machines']['machine']['operating_mode'] == 'nominal'
        assert not with_session.observe()['machines']['machine']['in_maintenance']
        records = with_session.events(cursor)['records']
        assert sum(r['event_type'] == 'decision_request' for r in records) == 1
        assert sum(r['event_type'] == 'validation_outcome' for r in records) == 1
        if expected_status == 'aborted':
            assert summary.is_aborted
            assert any(d['code'] == 'INVALID_FALLBACK_BATCH' for d in summary.decision_diagnostics)
            assert any(r['event_type'] == 'failure' for r in records)
            assert not any(r['event_type'] == 'fallback' for r in records)
    finally:
        with_session.close()
