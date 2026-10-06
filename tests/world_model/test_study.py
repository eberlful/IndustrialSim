from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import pytest

from industrialsim.application import EpisodeEngine
from industrialsim.checkpoint import deserialize_checkpoint, serialize_checkpoint
from industrialsim.config import SimulationConfig
from industrialsim.world_model.contracts import ACTION_TYPES, SensorReading, digest
from industrialsim.world_model.observation import StudyObservationAdapter, graph_from_engine
from industrialsim.world_model.study import COUNTS, StudySettings, generate_dataset, research_configuration, verify_manifest


def test_declared_process_state_survives_rework_and_checkpoint() -> None:
    config = SimulationConfig.model_validate({"schema_version": "1.0", "seed": 42,
        "episode": {"end_condition": {"type": "all_units_terminal"}},
        "stations": [{"id": "st", "operations": [
            {"id": "weld", "duration": "5s", "process_effects": {"stress": {"bias": .4}}},
            {"id": "rework", "duration": "5s", "restores_quality": True,
             "process_effects": {"coating": {"bias": .1, "inputs": {"stress": .5}}}}]}],
        "production_units": [{"id": "u", "variant": "sedan", "quality_state": "defect"}]})
    parent = EpisodeEngine.create(config)
    parent.run(pause_at_ns=6 * 10**9)
    assert parent.units["u"].process_state == {"stress": .4}
    checkpoint = deserialize_checkpoint(serialize_checkpoint(parent.create_checkpoint()))
    child = EpisodeEngine.restore(checkpoint, config)
    parent.run()
    child.run()
    assert child.units["u"].process_state == pytest.approx({"stress": .4, "coating": .3})
    assert child.units["u"].quality_state == "nominal"
    assert child.units["u"].to_snapshot() == parent.units["u"].to_snapshot()


def test_sensor_reads_repeat_across_checkpoint_without_changing_production_randomness() -> None:
    settings = StudySettings()
    config = research_configuration(settings, 42, "train")
    parent = EpisodeEngine.create(config)
    graph = graph_from_engine(parent)
    adapter = StudyObservationAdapter(missing_probability=.2)
    before = dict(parent.random_occurrence_counters)
    first = adapter.observe(parent, graph, "episode")
    child = EpisodeEngine.restore(parent.create_checkpoint(), config)
    assert adapter.observe(child, graph, "episode") == first
    assert parent.random_occurrence_counters == before
    assert any(r.missing for r in first.readings)
    assert all((r.value is None) == r.missing for r in first.readings)


def test_hidden_quality_and_process_attributes_are_not_exported_as_features() -> None:
    engine = EpisodeEngine.create(research_configuration(StudySettings(), 42, "train"))
    adapter = StudyObservationAdapter()
    graph = graph_from_engine(engine)
    first = adapter.observe(engine, graph, "episode")
    unit = next(iter(engine.units.values()))
    unit.quality_state = "secret_defect"
    unit.process_state = {"secret_process_attribute": .8}
    second = adapter.observe(engine, graph, "episode")
    assert first == second  # Unreleased units have no measured process signal.
    serialized = json.dumps(asdict(second))
    assert all(key not in serialized for key in ("health_state", "quality_state", "secret_process_attribute"))
    assert "secret_process_attribute" in json.dumps(adapter.labels(engine))


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("world-model") / "dataset"
    settings = StudySettings(duration_ns=1500 * 10**9, counts={key: 1 for key in COUNTS})
    generate_dataset(output, settings)
    return output


def test_dataset_covers_actual_effects_and_groups_counterfactual_branches(dataset: Path) -> None:
    manifest = verify_manifest(dataset)
    assert set(ACTION_TYPES) <= set(manifest["applied_action_counts"])
    assert all(manifest["applied_action_counts"][kind] > 0 for kind in ACTION_TYPES)
    assert any(item["episode_id"] != item["root_id"] for item in manifest["episodes"])
    for root in {item["root_id"] for item in manifest["episodes"]}:
        assert len({item["split"] for item in manifest["episodes"] if item["root_id"] == root}) == 1
    data = json.loads((dataset / manifest["episodes"][0]["path"]).read_text())
    assert {a["status"] for a in data["actions"]} >= {"proposed", "applied", "no_effect"}
    assert all(b["time_ns"] - a["time_ns"] == 30 * 10**9
               for a, b in zip(data["observations"], data["observations"][1:]))


def test_manifest_rejects_cross_split_relatives(dataset: Path, tmp_path: Path) -> None:
    manifest = json.loads((dataset / "manifest.json").read_text())
    branch = next(item for item in manifest["episodes"] if item["root_id"] != item["episode_id"])
    branch["split"] = "unknown_combinations"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    for item in manifest["episodes"]:
        (tmp_path / item["path"]).write_bytes((dataset / item["path"]).read_bytes())
    with pytest.raises(ValueError, match="cross study splits"):
        verify_manifest(tmp_path)


def test_sensor_contract_rejects_fake_missing_values() -> None:
    with pytest.raises(ValueError, match="null"):
        SensorReading(0, "m", "temperature", "degC", 0., missing=True)
