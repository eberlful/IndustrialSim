"""Episode preparation through the public session and application boundaries."""
from pathlib import Path

from industrialsim.application import validate_config
from industrialsim.project import ProjectSession

REFERENCE = Path(__file__).resolve().parents[1] / 'examples/reference_automotive_plant.yaml'


def test_episode_inputs_round_trip_and_materialize_reproducibly(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    opened = session.import_yaml(REFERENCE.read_text())
    original = validate_config(REFERENCE).config
    assert original is not None
    rows = opened['model']['episode_inputs']['production_plan']
    rows[0].update(release_time=1000000001, quantity=2, due_date='2h')
    edited = session.edit_episode({'seed': 9007199254740993, 'max_time': '3h', 'production_plan': rows})
    assert edited['accepted'] and edited['model']['valid'], edited['diagnostics']
    assert edited['model']['episode_inputs']['seed'] == '9007199254740993'
    assert session.undo()['model']['yaml'] == opened['model']['yaml']
    assert session.redo()['model']['yaml'] == edited['model']['yaml']
    assert session.save_model('episode.yaml')['accepted']
    reopened = ProjectSession(tmp_path).open_model('episode.yaml')
    config = validate_config(reopened['model']['yaml']).config
    assert config is not None
    expected = original.model_dump(mode='json')
    actual = config.model_dump(mode='json')
    for section in ('seed', 'episode', 'production_plan', 'production_units'):
        expected.pop(section)
        actual.pop(section)
    assert actual == expected
    assert config.seed == 9007199254740993
    assert config.episode.end_condition.type == original.episode.end_condition.type
    assert config.episode.end_condition.max_time_ns == 10800000000000
    assert [unit.id for unit in config.production_units[:2]] == [f'{rows[0]["id"]}-1', f'{rows[0]["id"]}-2']
    assert config.production_units[0].release_time_ns == 1000000001
    assert config.production_units[0].due_date_ns == 7200000000000
    assert validate_config(session.export_yaml()['yaml']).config == config


def test_invalid_inputs_are_correctable_and_share_execution_validation(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    session.import_yaml(REFERENCE.read_text())
    for changes, field in [({'seed': 'bad'}, 'seed'), ({'max_time': '-1s'}, 'episode.end_condition'),
                           ({'production_plan': [{'variant': 'sedan', 'quantity': 0}]}, 'production_plan.0'),
                           ({'production_plan': [{'variant': 'sedan', 'release_time': '0.5s'}]}, 'production_plan.0')]:
        result = session.edit_episode(changes)
        assert result['accepted'] and not result['model']['valid']
        assert any(field in error for error in result['diagnostics'])
        assert not validate_config(result['model']['yaml']).is_valid
        assert not session.export_yaml()['accepted']
        assert not session.save_model('invalid.yaml')['accepted']
        assert session.save_draft('invalid.json', overwrite=True)['accepted']
        reopened = ProjectSession(tmp_path)
        assert not reopened.open_draft('invalid.json')['model']['valid']
        assert reopened.edit_episode({'seed': 42, 'max_time': '1h', 'production_plan': [
            {'id': 'batch', 'variant': 'sedan', 'quantity': 1, 'source_id': 'src-bodies', 'release_time': 0}
        ]})['model']['valid']
        assert session.undo()['model']['valid']
        assert not session.redo()['model']['valid']
        assert session.undo()['model']['valid']


def test_terminal_end_condition_and_explicit_units_are_not_reinterpreted(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    session.import_yaml('''
episode: {start_time: 1s, warm_up_time: 2s, end_condition: {type: all_units_terminal}}
production_units: [{id: original, variant: sedan}]
stations: [{id: station, operations: [{id: op, duration: 1s}]}]
''')
    assert session.edit_episode({'max_time': '5s'})['model']['valid']
    config = validate_config(session.export_yaml()['yaml']).config
    assert config is not None
    assert config.episode.end_condition.type == 'all_units_terminal'
    assert config.episode.start_time_ns == 1000000000
    assert config.episode.warm_up_time_ns == 2000000000
    result = session.edit_episode({'production_plan': [{'variant': 'sedan', 'quantity': 2}]})
    assert not result['model']['valid']
    assert 'original' in result['model']['yaml']
    assert any('conflicting' in error for error in result['diagnostics'])
    before = session.snapshot()
    assert not session.edit_episode({'end_condition': {'type': 'max_time'}})['accepted']
    assert session.snapshot() == before


def test_setup_and_plan_keep_exact_times_and_row_metadata(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    session.import_yaml('''
episode: {end_condition: {type: all_units_terminal, max_time: 9007199254740993}}
production_plan:
  - {id: batch, variant: sedan, quantity: 1, release_time: 9007199254740993, due_date: 9007199254740994, quality_state: rework}
stations: [{id: station, operations: [{id: op, duration: 1s}]}]
''')
    inputs = session.snapshot()['model']['episode_inputs']
    assert inputs['episode']['end_condition']['max_time'] == '9007199254740993'
    assert inputs['production_plan'][0]['release_time'] == '9007199254740993'
    row = inputs['production_plan'][0]
    row.update(quantity=2, variant='suv')
    result = session.edit_episode({'production_plan': [row]})
    assert result['model']['valid'], result['diagnostics']
    config = validate_config(session.export_yaml()['yaml']).config
    assert config is not None
    assert [(unit.id, unit.variant, unit.release_time_ns, unit.due_date_ns, unit.quality_state)
            for unit in config.production_units] == [
        ('batch-1', 'suv', 9007199254740993, 9007199254740994, 'rework'),
        ('batch-2', 'suv', 9007199254740993, 9007199254740994, 'rework'),
    ]
