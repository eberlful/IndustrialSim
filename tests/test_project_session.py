"""Integration behavior at the public project-session boundary."""
from pathlib import Path
import shutil

import pytest
from industrialsim.application import validate_config
from industrialsim.project import ProjectSession

REFERENCE = Path(__file__).resolve().parents[1] / 'examples/reference_automotive_plant.yaml'


def test_open_reference_plant_preserves_complete_configuration(tmp_path: Path) -> None:
    original = REFERENCE.read_text()
    shutil.copy(REFERENCE, tmp_path / 'plant.yaml')
    session = ProjectSession(tmp_path)
    opened = session.open_model('plant.yaml')
    assert opened['accepted'], opened['diagnostics']
    model = opened['model']
    assert len(model['graph']['nodes']) == 15
    assert len(model['graph']['routes']) == 16
    assert {node['kind'] for node in model['graph']['nodes']} == {'source', 'sink', 'station', 'buffer'}
    assert model['plant']['id'] == 'plant-reference-automotive'
    reference = validate_config(REFERENCE).config
    assert reference is not None
    assert validate_config(model['yaml']).config == reference
    assert model['configuration'] == reference.model_dump(mode='json')
    assert model['configuration']['production_plan']
    assert model['configuration']['machines']
    assert model['configuration']['process_plans']
    assert model['configuration']['decision_triggers']
    assert (tmp_path / 'plant.yaml').read_text() == original
    # Callers cannot mutate the accepted model through returned snapshots.
    model['graph']['nodes'].clear()
    assert len(session.snapshot()['model']['graph']['nodes']) == 15


@pytest.mark.parametrize('text, diagnostic', [
    ('episode: [', 'YAML parsing error'),
    ('[]', 'dictionary mapping'),
    ('seed: 42', 'episode'),
    (REFERENCE.read_text().replace('hall_id: "hall-body-construction"', 'hall_id: "missing-hall"', 1), 'unknown hall'),
], ids=['syntax', 'non-mapping', 'schema', 'hall-reference'])
def test_rejected_import_retains_last_valid_model(tmp_path: Path, text: str, diagnostic: str) -> None:
    session = ProjectSession(tmp_path)
    accepted = session.import_yaml(REFERENCE.read_text(), 'reference.yaml')
    assert accepted['accepted']
    rejected = session.import_yaml(text)
    assert not rejected['accepted']
    assert any(diagnostic in message for message in rejected['diagnostics'])
    assert rejected['model'] == accepted['model']
    assert session.snapshot()['model'] == accepted['model']
    assert list(tmp_path.iterdir()) == []


def test_project_paths_cannot_read_outside_selected_directory(tmp_path: Path) -> None:
    project = tmp_path / 'project'
    project.mkdir()
    shutil.copy(REFERENCE, tmp_path / 'outside.yaml')
    (project / 'linked.yaml').symlink_to(tmp_path / 'outside.yaml')
    session = ProjectSession(project)
    assert session.models() == []
    for path in ('../outside.yaml', str(tmp_path / 'outside.yaml'), 'linked.yaml', 'missing.yaml'):
        result = session.open_model(path)
        assert not result['accepted']
        assert result['diagnostics']
        assert result['model'] is None


def test_yaml_named_like_local_file_is_parsed_as_content(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path)
    result = session.import_yaml(str(REFERENCE))
    assert not result['accepted']
    assert 'dictionary mapping' in result['diagnostics'][0]


def test_legacy_stations_are_shown_without_fabricated_topology(tmp_path: Path) -> None:
    text = (REFERENCE.parent / 'minimal_episode.yaml').read_text()
    session = ProjectSession(tmp_path)
    result = session.import_yaml(text, 'legacy.yaml')
    assert result['accepted']
    graph = result['model']['graph']
    assert [node['id'] for node in graph['nodes']] == ['station-001']
    assert graph['nodes'][0]['input_ports'] == []
    assert graph['routes'] == []
    assert validate_config(result['model']['yaml']).config == validate_config(text).config
