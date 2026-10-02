"""Parameter editing and executable YAML at the public project-session seam."""
from pathlib import Path
from industrialsim.application import validate_config
from industrialsim.project import ProjectSession

REFERENCE = Path(__file__).resolve().parents[1] / 'examples/reference_automotive_plant.yaml'


def test_edit_capacity_and_duration_exports_complete_semantic_model(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    session.import_yaml(REFERENCE.read_text(), 'original.yaml')
    reference = validate_config(REFERENCE).config
    assert reference is not None
    changed = session.edit_parameters('node', 'buf-body-out', {'capacity': 9})
    assert changed['accepted']
    assert changed['model']['valid']
    session.edit_parameters('node', 'st-body-1', {'duration': '125s'}, operation_id='op-body-weld')
    exported = session.export_yaml()
    assert exported['accepted'], exported['diagnostics']
    roundtrip = validate_config(exported['yaml']).config
    assert roundtrip is not None and roundtrip.material_flow is not None
    assert next(n for n in roundtrip.material_flow.nodes if n.id == 'buf-body-out').capacity == 9
    operation = next(n for n in roundtrip.material_flow.nodes if n.id == 'st-body-1').operations[0]
    assert operation.duration_ns == 125_000_000_000
    # Independent existing validator oracle: only these two fields may change.
    expected = reference.model_dump(mode='json')
    actual = roundtrip.model_dump(mode='json')
    expected['material_flow']['nodes'][3]['capacity'] = 9
    expected['material_flow']['nodes'][1]['operations'][0]['duration'] = '125s'
    expected['material_flow']['nodes'][1]['operations'][0]['duration_ns'] = 125_000_000_000
    assert actual == expected
    assert list(tmp_path.iterdir()) == []


def test_invalid_edits_remain_correctable_and_undo_redo_restore_validation(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    session.import_yaml(REFERENCE.read_text())
    changed = session.edit_parameters('node', 'buf-body-out', {'capacity': 0})
    assert changed['accepted']
    assert not changed['model']['valid']
    assert any('capacity' in error and 'buf-body-out' in error for error in changed['diagnostics'])
    assert not session.export_yaml()['accepted']
    undone = session.undo()
    assert undone['model']['valid']
    assert session.export_yaml()['accepted']
    redone = session.redo()
    assert not redone['model']['valid']
    assert not session.export_yaml()['accepted']
    corrected = session.edit_parameters('node', 'buf-body-out', {'capacity': 7})
    assert corrected['model']['valid']
    assert not corrected['can_redo']
    assert session.undo()['model']['valid'] is False
    session.undo()
    session.redo()
    assert session.snapshot()['model']['valid'] is False
    # Reopening/importing another model begins an independent history.
    session.import_yaml(REFERENCE.read_text())
    assert not session.snapshot()['can_undo']
    assert not session.snapshot()['can_redo']


def test_explicit_save_roundtrip_preserves_original_until_overwrite(tmp_path: Path) -> None:
    original = REFERENCE.read_text()
    (tmp_path / 'original.yaml').write_text(original)
    session = ProjectSession(tmp_path)
    session.import_yaml(original, 'original.yaml')
    session.edit_parameters('node', 'buf-body-out', {'capacity': 12})
    assert (tmp_path / 'original.yaml').read_text() == original
    assert not session.save_model('original.yaml')['accepted']
    assert (tmp_path / 'original.yaml').read_text() == original
    saved = session.save_model('edited.yaml')
    assert saved['accepted'], saved['diagnostics']
    reopened = ProjectSession(tmp_path).open_model('edited.yaml')
    assert reopened['accepted']
    assert next(n for n in reopened['model']['graph']['nodes'] if n['id'] == 'buf-body-out')['capacity'] == 12
    assert validate_config(tmp_path / 'edited.yaml').config == validate_config(session.export_yaml()['yaml']).config
    assert session.save_model('original.yaml', overwrite=True)['accepted']
    assert validate_config(tmp_path / 'original.yaml').config == validate_config(tmp_path / 'edited.yaml').config
    session.edit_parameters('node', 'buf-body-out', {'capacity': -1})
    before = (tmp_path / 'original.yaml').read_text()
    assert not session.save_model('original.yaml', overwrite=True)['accepted']
    assert (tmp_path / 'original.yaml').read_text() == before
    assert not (tmp_path / 'invalid.yaml').exists()


def test_route_transport_parameters_and_reference_diagnostics(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    session.import_yaml(REFERENCE.read_text())
    changed = session.edit_parameters('route', 'r-body-paint', {
        'transit_time': '45s', 'capacity': 3, 'required_capabilities': ['body_transport'],
        'pool_id': 'pool-transporters',
    })
    assert changed['accepted'] and changed['model']['valid']
    config = validate_config(session.export_yaml()['yaml']).config
    assert config is not None and config.material_flow is not None
    route = next(r for r in config.material_flow.routes if r.id == 'r-body-paint')
    assert route.transit_time_ns == 45_000_000_000
    assert route.capacity == 3
    assert route.required_capabilities == ['body_transport']
    invalid = session.edit_parameters('route', 'r-body-paint', {'pool_id': 'missing-pool'})
    assert not invalid['model']['valid']
    assert any('r-body-paint' in error and 'missing-pool' in error for error in invalid['diagnostics'])
    assert session.undo()['model']['valid']
    invalid = session.edit_parameters('node', 'buf-body-out', {'hall_id': 'missing-hall'})
    assert any('buf-body-out' in error and 'missing-hall' in error for error in invalid['diagnostics'])
    session.undo()
    # A property command cannot change unrelated sections or graph identity.
    before = session.snapshot()
    assert not session.edit_parameters('node', 'buf-body-out', {'id': 'renamed'})['accepted']
    assert session.snapshot() == before
    assert not session.edit_parameters('node', 'src-bodies', {'capacity': 20})['accepted']


def test_saves_are_project_local_and_failed_paths_leave_files_intact(tmp_path: Path) -> None:
    project = tmp_path / 'project'
    project.mkdir()
    outside = tmp_path / 'outside.yaml'
    outside.write_text('original content')
    (project / 'outside-link.yaml').symlink_to(outside)
    session = ProjectSession(project)
    session.import_yaml(REFERENCE.read_text())
    for path in ('../outside.yaml', 'outside-link.yaml', str(outside), 'config.txt', 'missing/model.yaml'):
        result = session.save_model(path, overwrite=True)
        assert not result['accepted']
        assert result['diagnostics']
        assert outside.read_text() == 'original content'
    assert sorted(p.name for p in project.iterdir()) == ['outside-link.yaml']


def test_operation_alias_edit_changes_only_selected_station(tmp_path: Path) -> None:
    text = '''
episode:
  end_condition: {type: all_units_terminal}
production_units: [{id: unit-1, variant: sedan}]
stations:
  - id: first
    operations: &shared
      - {id: weld, duration: 5s}
  - id: second
    operations: *shared
'''
    session = ProjectSession(tmp_path)
    assert session.import_yaml(text)['accepted']
    result = session.edit_parameters('node', 'first', {'duration': '10s'}, operation_id='weld')
    assert result['model']['valid']
    config = validate_config(session.export_yaml()['yaml']).config
    assert config is not None
    assert config.stations[0].operations[0].duration_ns == 10_000_000_000
    assert config.stations[1].operations[0].duration_ns == 5_000_000_000


def test_graph_list_alias_in_advanced_parameters_is_preserved(tmp_path: Path) -> None:
    text = '''
episode:
  end_condition: {type: all_units_terminal}
production_units: [{id: unit-1, variant: sedan}]
material_flow:
  routes: &original_routes
    - id: transport
      source_node_id: source
      source_port_id: out
      target_node_id: sink
      target_port_id: in
      transit_time: 1s
  nodes:
    - id: source
      kind: source
      parameters: {original_routes: *original_routes}
      output_ports: [{id: out, direction: output, port_type: body}]
    - id: sink
      kind: sink
      input_ports: [{id: in, direction: input, port_type: body}]
'''
    session = ProjectSession(tmp_path)
    assert session.import_yaml(text)['accepted']
    session.edit_parameters('route', 'transport', {'transit_time': '2s'})
    config = validate_config(session.export_yaml()['yaml']).config
    assert config is not None and config.material_flow is not None
    assert config.material_flow.routes[0].transit_time_ns == 2_000_000_000
    assert config.material_flow.nodes[0].parameters['original_routes'][0]['transit_time'] == '1s'
