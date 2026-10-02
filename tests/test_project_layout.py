"""Presentation editing through the agreed public project-session seam."""
from pathlib import Path

from industrialsim.application import validate_config
from industrialsim.project import ProjectSession

REFERENCE = Path(__file__).resolve().parents[1] / 'examples/reference_automotive_plant.yaml'


def test_layout_reopens_separately_without_changing_simulation(tmp_path: Path) -> None:
    original = REFERENCE.read_text()
    (tmp_path / 'plant.yaml').write_text(original)
    session = ProjectSession(tmp_path)
    opened = session.open_model('plant.yaml')
    baseline = opened['model']['configuration']
    assert opened['model']['layout']['grouping'] == 'none'
    changed = session.edit_layout(positions={'st-body-1': {'x': 123, 'y': -45}}, grouping='hall')
    assert changed['accepted']
    assert changed['model']['configuration'] == baseline
    assert session.undo()['model']['layout'] == opened['model']['layout']
    assert session.redo()['model']['layout'] == changed['model']['layout']
    saved = session.save_layout()
    assert saved['accepted'], saved['diagnostics']
    assert (tmp_path / 'plant.yaml').read_text() == original
    assert validate_config(session.export_yaml()['yaml']).config == validate_config(REFERENCE).config
    reopened = ProjectSession(tmp_path).open_model('plant.yaml')
    assert reopened['model']['layout'] == changed['model']['layout']
    assert reopened['model']['configuration'] == baseline


def test_unrelated_and_replaced_models_do_not_inherit_layout(tmp_path: Path) -> None:
    text = REFERENCE.read_text()
    (tmp_path / 'one.yaml').write_text(text)
    (tmp_path / 'two.yaml').write_text(text)
    session = ProjectSession(tmp_path)
    session.open_model('one.yaml')
    session.edit_layout(grouping='area')
    session.save_layout()
    assert session.open_model('two.yaml')['model']['layout']['grouping'] == 'none'
    (tmp_path / 'one.yaml').write_text(text.replace('seed: 42', 'seed: 43'))
    # A changed configuration under the same filename is a different model.
    if (tmp_path / 'one.yaml').read_text() == text:
        (tmp_path / 'one.yaml').write_text(text + '\nseed: 123456\n')
    assert session.open_model('one.yaml')['model']['layout']['grouping'] == 'none'


def test_layout_rejections_and_save_as_keep_history_and_semantics(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    assert not session.edit_layout(grouping='hall')['accepted']
    session.import_yaml(REFERENCE.read_text())
    before = session.snapshot()
    for positions in ({'missing': {'x': 1, 'y': 2}}, {'st-body-1': {'x': float('nan'), 'y': 2}}):
        assert not session.edit_layout(positions=positions)['accepted']
        assert session.snapshot() == before
    session.edit_layout(grouping='area')
    session.edit_parameters('node', 'buf-body-out', {'capacity': 9})
    assert session.undo()['model']['layout']['grouping'] == 'area'
    assert session.undo()['model']['layout']['grouping'] == 'none'
    session.redo()
    session.redo()
    saved = session.save_model('./copy.yaml')
    assert saved['accepted']
    reopened = ProjectSession(tmp_path).open_model('copy.yaml')
    assert reopened['model']['layout']['grouping'] == 'area'
    assert reopened['model']['configuration'] == saved['model']['configuration']
