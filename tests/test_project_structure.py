"""Structural graph editing and durable incomplete work at the project seam."""
from pathlib import Path

from ruamel.yaml import YAML

from industrialsim.application import validate_config
from industrialsim.project import ProjectSession

SIMPLE = '''
seed: 42
episode:
  end_condition: {type: all_units_terminal}
production_units: [{id: unit-1, variant: sedan, source_id: source}]
material_flow:
  nodes:
    - id: source
      kind: source
      output_ports: [{id: out, direction: output, port_type: body}]
    - id: sink
      kind: sink
      input_ports: [{id: in, direction: input, port_type: body}]
  routes:
    - {id: direct, source_node_id: source, source_port_id: out, target_node_id: sink, target_port_id: in, transit_time: 3s}
'''


def route(session: ProjectSession, route_id: str, source: str, output: str, target: str, input_: str) -> dict:
    return session.edit_structure('add', 'route', route_id, {
        'source_node_id': source, 'source_port_id': output,
        'target_node_id': target, 'target_port_id': input_,
    })


def test_incomplete_station_draft_reopens_with_errors_and_can_be_completed(tmp_path: Path) -> None:
    (tmp_path / 'original.yaml').write_text(SIMPLE)
    session = ProjectSession(tmp_path)
    session.open_model('original.yaml')
    added = session.edit_structure('add', 'node', 'new-station', {'kind': 'station'})
    assert added['accepted'] and not added['model']['valid']
    assert any('new-station' in error and 'source' in error for error in added['diagnostics'])
    assert not session.export_yaml()['accepted']
    assert not session.save_model('incomplete.yaml')['accepted']
    assert session.save_draft('unfinished.json')['accepted']
    assert session.drafts() == ['unfinished.json']
    reopened = ProjectSession(tmp_path)
    restored = reopened.open_draft('unfinished.json')
    assert restored['accepted'] and not restored['model']['valid']
    assert restored['model']['configuration'] == added['model']['configuration']
    assert restored['diagnostics'] == added['diagnostics']
    route(reopened, 'incoming', 'source', 'out', 'new-station', 'in')
    completed = route(reopened, 'outgoing', 'new-station', 'out', 'sink', 'in')
    assert completed['model']['valid'], completed['diagnostics']
    exported = reopened.export_yaml()
    assert exported['accepted']
    config = validate_config(exported['yaml']).config
    assert config is not None and config.material_flow is not None
    assert [node.id for node in config.material_flow.nodes] == ['source', 'sink', 'new-station']
    assert config.material_flow.routes[0].transit_time_ns == 3_000_000_000
    assert (tmp_path / 'original.yaml').read_text() == SIMPLE
    assert not (tmp_path / 'incomplete.yaml').exists()
    assert reopened.undo()['model']['valid'] is False
    assert reopened.redo()['model']['valid'] is True


def test_ports_routes_cycles_and_deletions_keep_references_undoable(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    session.import_yaml(SIMPLE)
    session.edit_structure('add', 'node', 'holding', {'kind': 'buffer'})
    route(session, 'incoming', 'source', 'out', 'holding', 'in')
    route(session, 'outgoing', 'holding', 'out', 'sink', 'in')
    route(session, 'parallel', 'source', 'out', 'holding', 'in')
    cycled = route(session, 'cycle', 'holding', 'out', 'holding', 'in')
    assert cycled['model']['valid'], cycled['diagnostics']
    changed = session.edit_structure('update', 'node', 'holding', {
        'input_ports': [{'id': 'in', 'direction': 'input', 'port_type': 'painted-body'}],
    })
    assert changed['accepted'] and not changed['model']['valid']
    assert any('Incompatible port types' in error and 'incoming' in error for error in changed['diagnostics'])
    assert not session.export_yaml()['accepted']
    assert session.undo()['model']['valid']
    session.edit_structure('update', 'node', 'holding', {'input_ports': []})
    assert any('incoming' in error and 'Port' in error for error in session.snapshot()['diagnostics'])
    assert len(session.snapshot()['model']['graph']['routes']) == 5
    session.undo()
    # Deletion retains routes, Production Unit source references and other sections.
    deleted = session.edit_structure('delete', 'node', 'source')
    assert deleted['accepted'] and not deleted['model']['valid']
    assert len(deleted['model']['graph']['routes']) == 5
    assert deleted['model']['configuration']['production_units'][0]['source_id'] == 'source'
    assert any('production_units.0.source_id' in error for error in deleted['diagnostics'])
    assert any('direct' in error and 'source_node_id' in error for error in deleted['diagnostics'])
    assert session.undo()['model']['valid']
    assert session.redo()['model']['valid'] is False
    session.undo()
    session.edit_structure('delete', 'route', 'direct')
    assert session.snapshot()['model']['valid']
    config = validate_config(session.export_yaml()['yaml']).config
    assert config is not None and config.material_flow is not None
    assert {r.id for r in config.material_flow.routes} == {'incoming', 'outgoing', 'parallel', 'cycle'}


def test_deleted_station_diagnostics_preserve_requirements_and_layout(tmp_path: Path) -> None:
    reference = Path(__file__).resolve().parents[1] / 'examples/reference_automotive_plant.yaml'
    session = ProjectSession(tmp_path)
    session.import_yaml(reference.read_text())
    session.edit_layout(positions={'st-body-1': {'x': 17, 'y': 19}})
    before = session.snapshot()
    removed = session.edit_structure('delete', 'node', 'st-body-1')
    assert removed['accepted'] and not removed['model']['valid']
    assert removed['model']['configuration']['process_plans'] == YAML(typ='safe').load(before['model']['yaml'])['process_plans']
    assert any('compatible_stations' in error and 'st-body-1' in error for error in removed['diagnostics'])
    assert 'st-body-1' not in removed['model']['layout']['positions']
    session.save_draft('removed.json')
    assert ProjectSession(tmp_path).open_draft('removed.json')['diagnostics'] == removed['diagnostics']
    assert session.undo()['model'] == before['model']
    assert session.redo()['model'] == removed['model']


def test_draft_paths_overwrite_and_malformed_documents_are_transactional(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    assert not session.save_draft('empty.json')['accepted']
    session.import_yaml(SIMPLE)
    session.edit_structure('add', 'node', 'isolated', {'kind': 'sink'})
    assert session.save_draft('work.json')['accepted']
    assert not session.save_draft('work.json')['accepted']
    assert session.save_draft('work.json', overwrite=True)['accepted']
    before = session.snapshot()
    outside = tmp_path / 'outside.json'
    outside.write_text('original')
    (tmp_path / '.drafts' / 'link.json').symlink_to(outside)
    for name in ('../outside.json', 'link.json', str(outside), 'model.yaml'):
        assert not session.save_draft(name, overwrite=True)['accepted']
        assert not session.open_draft(name)['accepted']
        assert session.snapshot() == before
        assert outside.read_text() == 'original'
    (tmp_path / '.drafts' / 'malformed.json').write_text('{"version": 999}')
    assert not session.open_draft('malformed.json')['accepted']
    assert session.snapshot() == before
    for action, kind, id_, changes in (
        ('add', 'node', 'source', {'kind': 'source'}),
        ('add', 'node', 'invalid', {'kind': 'machine'}),
        ('add', 'route', 'broken', {}),
        ('update', 'node', 'sink', {'input_ports': 'bad'}),
        ('delete', 'node', 'missing', {}),
    ):
        assert not session.edit_structure(action, kind, id_, changes)['accepted']
        assert session.snapshot() == before


def test_all_node_types_and_structural_aliases_preserve_advanced_configuration(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    session.import_yaml(SIMPLE)
    baseline = validate_config(SIMPLE).config
    assert baseline is not None
    session.edit_structure('add', 'node', 'another-source', {'kind': 'source'})
    assert route(session, 'another-entry', 'another-source', 'out', 'sink', 'in')['model']['valid']
    session.edit_structure('add', 'node', 'another-sink', {'kind': 'sink'})
    assert route(session, 'another-exit', 'source', 'out', 'another-sink', 'in')['model']['valid']
    for kind, id_ in (('route', 'another-entry'), ('route', 'another-exit'),
                      ('node', 'another-source'), ('node', 'another-sink')):
        session.edit_structure('delete', kind, id_)
    assert validate_config(session.export_yaml()['yaml']).config == baseline
    # Editing Ports must detach a shared list from advanced node parameters.
    aliased = SIMPLE.replace('output_ports: [{id: out, direction: output, port_type: body}]',
                            'output_ports: &original_ports [{id: out, direction: output, port_type: body}]\n      parameters: {original_ports: *original_ports}')
    assert session.import_yaml(aliased)['accepted']
    session.edit_structure('update', 'node', 'source', {
        'output_ports': [{'id': 'renamed', 'direction': 'output', 'port_type': 'body'}],
    })
    corrected = session.edit_structure('update', 'route', 'direct', {'source_port_id': 'renamed'})
    assert corrected['model']['valid']
    config = validate_config(session.export_yaml()['yaml']).config
    assert config is not None and config.material_flow is not None
    assert config.material_flow.nodes[0].parameters['original_ports'][0]['id'] == 'out'
    assert config.material_flow.nodes[0].output_ports[0].id == 'renamed'
    assert config.material_flow.routes[0].transit_time_ns == 3_000_000_000


def test_deleted_inspection_rework_target_blocks_export_after_routes_are_removed(tmp_path: Path) -> None:
    from json import dumps

    draft = YAML(typ='safe').load(SIMPLE)
    for id_ in ('inspection', 'rework'):
        draft['material_flow']['nodes'].append({
            'id': id_, 'kind': 'station',
            'input_ports': [{'id': 'in', 'direction': 'input', 'port_type': 'body'}],
            'output_ports': [{'id': 'out', 'direction': 'output', 'port_type': 'body'}],
            'operations': [{'id': 'check' if id_ == 'inspection' else 'repair', 'duration': '1s'}],
        })
        for route_id, source, output, target, input_ in (
            (f'{id_}-entry', 'source', 'out', id_, 'in'),
            (f'{id_}-exit', id_, 'out', 'sink', 'in'),
        ):
            draft['material_flow']['routes'].append({
                'id': route_id, 'source_node_id': source, 'source_port_id': output,
                'target_node_id': target, 'target_port_id': input_,
            })
    draft['material_flow']['nodes'][2]['operations'][0]['inspection'] = {
        'rework_station_id': 'rework', 'rework_operation_id': 'repair',
    }
    session = ProjectSession(tmp_path)
    assert session.import_yaml(dumps(draft))['model']['valid']
    session.edit_structure('delete', 'node', 'rework')
    session.edit_structure('delete', 'route', 'rework-entry')
    removed = session.edit_structure('delete', 'route', 'rework-exit')
    assert not removed['model']['valid']
    assert any('inspection.rework_station_id' in error and 'rework' in error for error in removed['diagnostics'])
    assert not session.export_yaml()['accepted']
    assert session.save_draft('rework.json')['accepted']
    assert ProjectSession(tmp_path).open_draft('rework.json')['diagnostics'] == removed['diagnostics']
    session.undo()
    session.undo()
    assert session.undo()['model']['valid']
    session.redo()
    session.redo()
    assert not session.redo()['model']['valid']
    session.undo()
    session.undo()
    assert session.undo()['model']['valid']
    assert session.export_yaml()['accepted']
