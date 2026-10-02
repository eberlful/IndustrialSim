"""Text/form consistency at the public project-session seam."""
from pathlib import Path

from industrialsim.application import validate_config
from industrialsim.project import ProjectSession

REFERENCE = Path(__file__).resolve().parents[1] / 'examples/reference_automotive_plant.yaml'


def test_yaml_and_forms_share_one_undoable_semantic_draft(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    original = REFERENCE.read_text()
    assert session.import_yaml(original)['accepted']
    edited = original.replace('initial_health: 1.0', 'initial_health: 0.9', 1)
    changed = session.edit_yaml(edited, expected_yaml=original)
    assert changed['accepted'] and changed['model']['valid']
    assert changed['model']['yaml'] == edited
    assert changed['model']['graph_available']
    assert session.edit_parameters('node', 'buf-body-out', {'capacity': 8})['model']['valid']
    config = validate_config(session.export_yaml()['yaml']).config
    expected = validate_config(edited).config
    assert config is not None and expected is not None
    expected.material_flow.nodes[3].capacity = 8
    assert config == expected
    assert session.undo()['model']['yaml'] == edited
    assert session.undo()['model']['yaml'] == original
    assert session.redo()['model']['yaml'] == edited
    assert session.redo()['model']['valid']
    assert session.save_model('advanced.yaml')['accepted']
    reopened = ProjectSession(tmp_path).open_model('advanced.yaml')
    assert validate_config(reopened['model']['yaml']).config == config
    # A browser holding older text cannot replace a newer form edit.
    before = session.snapshot()
    rejected = session.edit_yaml(original, expected_yaml=edited)
    assert not rejected['accepted']
    assert 'changed' in rejected['diagnostics'][0]
    assert session.snapshot() == before


def test_invalid_text_is_the_draft_and_survives_save_reload_and_history(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    original = REFERENCE.read_text()
    session.import_yaml(original)
    for text, diagnostic in [
        ('episode: [', 'YAML parsing error'),
        ('', 'mapping'),
        ('[one, two]', 'mapping'),
        ('material_flow: {nodes: null}', 'episode'),
        (original.replace('initial_health: 1.0', 'initial_health: 2.0', 1), 'initial_health'),
        (original.replace('m-body-welder-1', 'missing-machine', 1), 'unknown machine'),
        ('!!python/object/apply:os.system ["touch /tmp/industrialsim-should-not-execute"]', 'YAML parsing error'),
    ]:
        invalid = session.edit_yaml(text)
        assert invalid['accepted'] and not invalid['model']['valid']
        assert invalid['model']['yaml'] == text
        assert any(diagnostic in error for error in invalid['diagnostics'])
        assert not invalid['model']['graph_available']
        assert invalid['model']['graph']['nodes'] == []
        assert not session.export_yaml()['accepted']
        assert not session.save_model('invalid.yaml')['accepted']
        assert not session.edit_parameters('node', 'buf-body-out', {'capacity': 8})['accepted']
        assert session.save_draft('invalid-text.json', overwrite=True)['accepted']
        reopened = ProjectSession(tmp_path)
        restored = reopened.open_draft('invalid-text.json')
        assert restored['accepted'] and restored['model']['yaml'] == text
        assert restored['diagnostics'] == invalid['diagnostics']
        assert not restored['model']['graph_available']
        assert not reopened.export_yaml()['accepted']
        assert reopened.edit_yaml(original)['model']['valid']
        assert session.undo()['model']['yaml'] == original
        assert session.redo()['model']['yaml'] == text
        assert session.undo()['model']['valid']
    assert not Path('/tmp/industrialsim-should-not-execute').exists()


def test_yaml_preserves_installed_plugin_approval_and_rejects_unknown_plugins(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    text = REFERENCE.read_text() + '\napproved_plugins: [micro_station_plugin]\n'
    assert session.import_yaml(text)['accepted']
    edited = text.replace('initial_health: 1.0', 'initial_health: 0.8', 1)
    assert session.edit_yaml(edited)['model']['valid']
    session.edit_parameters('node', 'buf-body-out', {'capacity': 6})
    config = validate_config(session.export_yaml()['yaml']).config
    assert config is not None and config.approved_plugins == ['micro_station_plugin']
    invalid = session.edit_yaml(text.replace('[micro_station_plugin]', '[browser-uploaded-code]'))
    assert invalid['accepted'] and not invalid['model']['valid']
    assert any('not registered or installed' in error for error in invalid['diagnostics'])
    assert not session.export_yaml()['accepted']


def test_text_edits_retain_layout_through_invalid_drafts_and_removed_nodes(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    original = REFERENCE.read_text()
    session.import_yaml(original)
    session.edit_layout(positions={'buf-body-out': {'x': 15, 'y': 25}}, grouping='hall')
    session.edit_yaml('episode: [')
    assert session.save_draft('layout-text.json')['accepted']
    restored = ProjectSession(tmp_path)
    result = restored.open_draft('layout-text.json')
    assert result['accepted']
    assert result['model']['layout'] == {'positions': {'buf-body-out': {'x': 15, 'y': 25}}, 'grouping': 'hall'}
    assert restored.edit_yaml(original)['model']['layout'] == result['model']['layout']
    legacy = (REFERENCE.parent / 'minimal_episode.yaml').read_text()
    assert restored.edit_yaml(legacy)['model']['valid']
    assert restored.save_draft('new-topology.json')['accepted']
    assert ProjectSession(tmp_path).open_draft('new-topology.json')['accepted']
