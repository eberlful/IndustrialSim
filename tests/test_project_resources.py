"""Resource edits through the public project-session interface."""
from pathlib import Path

from industrialsim.application import validate_config
from industrialsim.project import ProjectSession

REFERENCE = Path(__file__).resolve().parents[1] / 'examples/reference_automotive_plant.yaml'


def test_resource_edits_save_and_reload_without_losing_advanced_settings(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    assert session.import_yaml(REFERENCE.read_text())['accepted']
    original = validate_config(REFERENCE).config
    assert original is not None
    machine = session.edit_parameters('machine', 'm-body-welder-1', {'name': 'New welder', 'capacity': 2})
    assert machine['accepted'] and machine['model']['valid']
    worker = session.edit_parameters('worker', 'w-body-1', {'kind': 'pool', 'capacity': 5, 'qualifications': ['body_operator', 'backup']})
    assert worker['accepted'] and worker['model']['valid']
    operation = session.edit_parameters('node', 'st-body-1', {
        'required_machines': ['m-body-welder-2'],
        'required_workers': [{'worker_id': 'w-body-1', 'qualification': 'body_operator', 'count': 2}],
    }, operation_id='op-body-weld')
    assert operation['accepted'] and operation['model']['valid']
    assert session.undo()['model']['valid']
    assert session.redo()['model']['valid']
    assert session.save_model('resources.yaml')['accepted']
    reopened = ProjectSession(tmp_path).open_model('resources.yaml')
    actual = validate_config(reopened['model']['yaml']).config
    assert actual is not None
    expected = original.model_dump(mode='json')
    expected['machines'][0].update(name='New welder', capacity=2)
    expected['workers'][0].update(kind='pool', capacity=5, qualifications=['body_operator', 'backup'])
    expected['material_flow']['nodes'][1]['operations'][0].update(
        required_machines=['m-body-welder-2'],
        required_workers=[{'worker_id': 'w-body-1', 'qualification': 'body_operator', 'count': 2}],
    )
    assert actual.model_dump(mode='json') == expected


def test_invalid_resource_edits_are_correctable_persisted_and_export_gated(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    session.import_yaml(REFERENCE.read_text())
    for kind, resource_id, changes, message in [
        ('machine', 'm-body-welder-1', {'capacity': 0}, 'capacity'),
        ('worker', 'w-body-1', {'capacity': 2}, 'capacity'),
        ('worker', 'w-body-1', {'kind': 'pool', 'capacity': 0}, 'capacity'),
        ('node', 'st-body-1', {'required_machines': ['missing-machine']}, 'missing-machine'),
        ('node', 'st-body-1', {'required_workers': [{'worker_id': 'missing-worker'}]}, 'missing-worker'),
        ('node', 'st-body-1', {'required_workers': [{'qualification': 'missing-qualification'}]}, 'missing-qualification'),
        ('node', 'st-body-1', {'required_workers': [{'worker_id': 'w-body-1', 'count': 0}]}, 'count'),
        ('node', 'st-body-1', {'required_workers': [{}]}, 'qualification'),
    ]:
        invalid = session.edit_parameters(kind, resource_id, changes,
                                          operation_id='op-body-weld' if kind == 'node' else None)
        assert invalid['accepted'] and not invalid['model']['valid']
        assert any(message in error for error in invalid['diagnostics'])
        assert not session.export_yaml()['accepted']
        assert not session.save_model('invalid.yaml')['accepted']
        assert session.undo()['model']['valid']
        assert not session.redo()['model']['valid']
        assert session.undo()['model']['valid']
    session.edit_parameters('machine', 'm-body-welder-1', {'capacity': 0})
    assert session.save_draft('resources.json')['accepted']
    reopened = ProjectSession(tmp_path)
    assert not reopened.open_draft('resources.json')['model']['valid']
    assert reopened.edit_parameters('machine', 'm-body-welder-1', {'capacity': 3})['model']['valid']
    assert reopened.export_yaml()['accepted']
    before = reopened.snapshot()
    for kind, changes in [('machine', {'hall_id': 'hall-body-construction'}),
                          ('worker', {'x': 10}), ('machine', {'id': 'new-id'})]:
        resource_id = 'w-body-1' if kind == 'worker' else 'm-body-welder-1'
        assert not reopened.edit_parameters(kind, resource_id, changes)['accepted']
        assert reopened.snapshot() == before


def test_legacy_and_aliased_resource_requirements_edit_independently(tmp_path: Path) -> None:
    text = '''
episode: {end_condition: {type: all_units_terminal}}
production_units: [{id: unit, variant: sedan}]
machines: [{id: machine}]
workers: [{id: worker, qualifications: [weld]}]
stations:
  - id: first
    operations: &shared
      - id: weld
        duration: 1s
        required_machines: [machine]
        required_workers: [{qualification: weld}]
  - id: second
    operations: *shared
'''
    session = ProjectSession(tmp_path)
    assert session.import_yaml(text)['accepted']
    result = session.edit_parameters('node', 'first', {
        'required_machines': [], 'required_workers': [{'worker_id': 'worker', 'count': 1}],
    }, operation_id='weld')
    assert result['model']['valid']
    config = validate_config(session.export_yaml()['yaml']).config
    assert config is not None
    assert config.stations[0].operations[0].required_machines == []
    assert config.stations[0].operations[0].required_workers[0].worker_id == 'worker'
    assert config.stations[1].operations[0].required_machines == ['machine']
    assert config.stations[1].operations[0].required_workers[0].qualification == 'weld'
