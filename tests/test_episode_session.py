"""Public application lifecycle: advancement, observation and finalization."""
import json
from pathlib import Path

import pytest

from industrialsim.application import EpisodeSession, run_episode
from industrialsim.audit import load_audit_log
from industrialsim.decisions import BaselineDecisionProvider

MODEL = '''
seed: 42
episode: {end_condition: {type: all_units_terminal}}
production_plan: [{id: batch, variant: sedan, quantity: 3}]
stations: [{id: station, operations: [{id: op, duration: 10s}]}]
telemetry: {enabled: true, sample_interval: 1s}
'''


def test_advancement_and_reads_do_not_finalize_and_result_matches_direct_execution(tmp_path: Path) -> None:
    session = EpisodeSession(MODEL, decision_provider=BaselineDecisionProvider(), output_dir=tmp_path / 'session')
    session.advance(until_time_ns=5000000000)
    assert not session.finished
    assert session.snapshot().status == 'incomplete'
    assert session.snapshot().simulated_time_ns == 5000000000
    assert not any(record.event_type == 'reward' for record in load_audit_log(tmp_path / 'session'))
    assert not (tmp_path / 'session/summary.json').exists()
    with pytest.raises(ValueError, match='finished'):
        session.finalize()
    session.advance()
    assert session.finished
    assert not any(record.event_type == 'reward' for record in load_audit_log(tmp_path / 'session'))
    summary = session.finalize()
    files = {path.relative_to(tmp_path / 'session'): path.read_bytes()
             for path in (tmp_path / 'session').rglob('*') if path.is_file()}
    assert session.finalize() == summary
    assert session.snapshot() == summary
    assert {path.relative_to(tmp_path / 'session'): path.read_bytes()
            for path in (tmp_path / 'session').rglob('*') if path.is_file()} == files
    direct = run_episode(MODEL, decision_provider=BaselineDecisionProvider(), output_dir=tmp_path / 'direct')
    assert summary.to_dict() == direct.to_dict()
    assert [record.model_dump() for record in load_audit_log(tmp_path / 'session')] == [
        record.model_dump() for record in load_audit_log(tmp_path / 'direct')]
    import pyarrow.parquet as pq
    session_metrics = [pq.read_table(path).to_pylist() for path in sorted((tmp_path / 'session/telemetry').glob('metrics_fragment_*.parquet'))]
    direct_metrics = [pq.read_table(path).to_pylist() for path in sorted((tmp_path / 'direct/telemetry').glob('metrics_fragment_*.parquet'))]
    assert session_metrics == direct_metrics
    assert sum(row['sample_type'] == 'terminal' for fragment in session_metrics for row in fragment) == 1
    assert len([record for record in load_audit_log(tmp_path / 'session') if record.event_type == 'reward']) == 1
    assert json.loads((tmp_path / 'session/manifest.json').read_text())['status'] == 'completed'


def test_bounded_advancement_matches_direct_execution_and_freezes_inputs(tmp_path: Path) -> None:
    from industrialsim.application import validate_config
    config = validate_config(MODEL).config
    assert config is not None
    session = EpisodeSession(config, decision_provider=BaselineDecisionProvider(), output_dir=tmp_path / 'bounded')
    config.seed = 9
    config.stations[0].operations[0].duration_ns = 1
    session.advance(max_events=1)
    assert not session.finished
    while not session.finished:
        session.advance(max_events=1)
    result = session.finalize()
    assert result.to_dict() == run_episode(MODEL, decision_provider=BaselineDecisionProvider()).to_dict()
    with pytest.raises(ValueError, match='finalized'):
        session.advance()


def test_existing_outputs_are_preserved_and_unfinished_sessions_close_cleanly(tmp_path: Path) -> None:
    for state in ('completed', 'incomplete'):
        directory = tmp_path / state
        directory.mkdir()
        (directory / 'manifest.json').write_text(json.dumps({'status': state}))
        (directory / 'audit.jsonl').write_text('existing audit')
        with pytest.raises(FileExistsError):
            EpisodeSession(MODEL, output_dir=directory)
        assert (directory / 'audit.jsonl').read_text() == 'existing audit'
    session = EpisodeSession(MODEL, output_dir=tmp_path / 'unfinished')
    session.advance(until_time_ns=1000000000)
    session.close()
    session.close()
    assert (tmp_path / 'unfinished/.incomplete').exists()
    assert not (tmp_path / 'unfinished/summary.json').exists()
    assert not any(record.event_type == 'reward' for record in load_audit_log(tmp_path / 'unfinished'))
    with pytest.raises(ValueError, match='closed'):
        session.advance()


def test_reference_session_with_decisions_matches_baseline_application() -> None:
    reference = Path(__file__).resolve().parents[1] / 'examples/reference_automotive_plant.yaml'
    session = EpisodeSession(reference, decision_provider=BaselineDecisionProvider())
    while not session.finished:
        session.advance(max_events=37)
    assert session.finalize().to_dict() == run_episode(reference, decision_provider=BaselineDecisionProvider()).to_dict()
    session.close()


@pytest.mark.parametrize('end_condition, deadlock', [
    ('{type: max_time, max_time: 5s}', ''),
    ('{type: all_units_terminal, max_time: 5s}', 'deadlock: {enabled: false}'),
])
def test_time_limits_finish_without_changing_existing_outcomes(end_condition: str, deadlock: str) -> None:
    model = MODEL.replace('{type: all_units_terminal}', end_condition) + '\n' + deadlock
    session = EpisodeSession(model, decision_provider=BaselineDecisionProvider())
    for _ in range(100):
        if session.finished:
            break
        session.advance(max_events=1)
    assert session.finished
    assert session.finalize().to_dict() == run_episode(model, decision_provider=BaselineDecisionProvider()).to_dict()
    session.close()
