"""Saved result inspection through the public local service, without execution."""
from pathlib import Path

from industrialsim.saved_results import SavedResults

from industrialsim.application import EpisodeSession, run_episode

MODEL = '''
episode: {end_condition: {type: all_units_terminal}}
production_plan: [{id: batch, variant: sedan, quantity: 1}]
stations: [{id: original, operations: [{id: op, duration: 1s}]}]
'''


def test_saved_results_survive_restart_and_inspection_preserves_bytes(tmp_path: Path) -> None:
    run_episode(MODEL, output_dir=tmp_path / 'runs/completed')
    from test_deadlock_simulation_e2e import BUFFER_CYCLE_YAML
    dead = BUFFER_CYCLE_YAML
    result = run_episode(dead, output_dir=tmp_path / 'runs/deadlocked')
    assert result.status == 'deadlocked'
    session = EpisodeSession(MODEL, output_dir=tmp_path / 'runs/incomplete')
    session.advance(max_events=1)
    session.close()
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    for _ in range(2):
        reader = SavedResults(tmp_path)
        listings = reader.list()
        assert {item['status'] for item in listings} == {'completed', 'deadlocked', 'incomplete'}
        for item in listings:
            saved = reader.open(item['path'])
            assert saved['configuration'] is not None
            if item['status'] == 'incomplete':
                assert saved['summary'] is None
            else:
                assert saved['summary']['raw_metrics'] is not None
            if item['status'] == 'deadlocked':
                assert saved['summary']['deadlock_diagnosis']['involved_entities']
        import pytest
        with pytest.raises(ValueError):
            reader.open('../outside')
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_missing_corrupt_outputs_are_truthful_and_read_only(tmp_path: Path) -> None:
    import json
    directory = tmp_path / 'runs/broken'
    directory.mkdir(parents=True)
    (directory / 'manifest.json').write_text(json.dumps({'status': 'completed'}))
    (directory / 'summary.json').write_text('{truncated')
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    saved = SavedResults(tmp_path).open('runs/broken')
    assert saved['status'] == 'incomplete'
    assert saved['summary'] is None
    assert saved['configuration'] is None
    assert saved['diagnostics']
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
