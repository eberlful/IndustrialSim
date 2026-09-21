import pytest
from pathlib import Path
import ruamel.yaml

from industrialsim.application import run_episode, create_checkpoint, resume_episode
from industrialsim.plugins import get_plugin_registry, reset_plugin_registry, MicroSubgraphPlugin


MACRO_SIMULATION_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0s
  end_condition:
    type: "all_units_terminal"
production_units:
  - id: "unit-1"
    variant: "sedan"
    release_time: 0s
material_flow:
  nodes:
    - id: "src"
      kind: "source"
      output_ports: [{ id: "out", port_type: "body", direction: "output" }]
    - id: "cell_1"
      kind: "station"
      input_ports: [{ id: "in", port_type: "body", direction: "input" }]
      output_ports: [{ id: "out", port_type: "body", direction: "output" }]
      operations:
        - id: "op_weld"
          duration: 10s
    - id: "snk"
      kind: "sink"
      input_ports: [{ id: "in", port_type: "body", direction: "input" }]
  routes:
    - id: "r1"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "cell_1"
      target_port_id: "in"
      transit_time: 1s
    - id: "r2"
      source_node_id: "cell_1"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
      transit_time: 1s
"""

MICRO_SIMULATION_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0s
  end_condition:
    type: "all_units_terminal"
approved_plugins:
  - "micro_station_plugin"
production_units:
  - id: "unit-1"
    variant: "sedan"
    release_time: 0s
material_flow:
  nodes:
    - id: "src"
      kind: "source"
      output_ports: [{ id: "out", port_type: "body", direction: "output" }]
    - id: "cell_1"
      kind: "station"
      type_id: "micro_subgraph_station"
      parameters:
        stages:
          - id: "tack_weld"
            duration: 4s
          - id: "seam_weld"
            duration: 6s
      input_ports: [{ id: "in", port_type: "body", direction: "input" }]
      output_ports: [{ id: "out", port_type: "body", direction: "output" }]
      operations:
        - id: "op_weld"
          duration: 10s
    - id: "snk"
      kind: "sink"
      input_ports: [{ id: "in", port_type: "body", direction: "input" }]
  routes:
    - id: "r1"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "cell_1"
      target_port_id: "in"
      transit_time: 1s
    - id: "r2"
      source_node_id: "cell_1"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
      transit_time: 1s
"""


@pytest.fixture(autouse=True)
def setup_registry():
    reset_plugin_registry()
    registry = get_plugin_registry()
    registry.register(MicroSubgraphPlugin())
    yield
    reset_plugin_registry()


def test_swap_macro_station_for_plugin_micro_subgraph(tmp_path: Path):
    # 1. Run macro baseline
    macro_dir = tmp_path / "macro_run"
    macro_summary = run_episode(source=MACRO_SIMULATION_YAML, output_dir=macro_dir)

    assert macro_summary.status == "completed"
    assert len(macro_summary.production_units) == 1
    macro_st = next(st for st in macro_summary.stations if st.id == "cell_1")
    assert macro_st.operations_completed == 1
    assert macro_st.total_busy_time_ns == 10_000_000_000

    # 2. Run micro model with swapped station
    micro_dir = tmp_path / "micro_run"
    micro_summary = run_episode(source=MICRO_SIMULATION_YAML, output_dir=micro_dir)

    assert micro_summary.status == "completed"
    assert len(micro_summary.production_units) == 1
    micro_st = next(st for st in micro_summary.stations if st.id == "cell_1")
    assert micro_st.operations_completed == 1
    assert micro_st.total_busy_time_ns == 10_000_000_000

    # End-to-end timing:
    # t=0s: unit released at src, enters r1 (1s)
    # t=1s: unit arrives at cell_1
    # Macro: runs 10s -> finishes at t=11s, enters r2 (1s) -> arrives at snk at t=12s.
    # Micro: tack_weld (4s, finishes at t=5s) -> seam_weld (6s, finishes at t=11s), enters r2 (1s) -> arrives at snk at t=12s.
    # Both deliver the unit to sink at t=12s!
    macro_unit = macro_summary.production_units[0]
    micro_unit = micro_summary.production_units[0]
    assert macro_unit.location == "terminal"
    assert micro_unit.location == "terminal"
    assert macro_summary.simulated_time_ns == micro_summary.simulated_time_ns

    # Verify manifest records plugin metadata
    manifest_file = micro_dir / "manifest.json"
    assert manifest_file.exists()
    import json
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["plugin_metadata"] == {"micro_station_plugin": "1.0.0"}


def test_micro_subgraph_checkpoint_compatibility(tmp_path: Path):
    # Checkpoint at t=3s (during first micro stage tack_weld)
    cp = create_checkpoint(MICRO_SIMULATION_YAML, at_time_ns=3_000_000_000)
    assert cp.plugin_metadata == {"micro_station_plugin": "1.0.0"}

    cp_file = tmp_path / "checkpoint_micro.json"
    from industrialsim.checkpoint import save_checkpoint
    save_checkpoint(cp, cp_file)

    # Resuming from checkpoint succeeds
    resumed_summary = resume_episode(cp_file)
    assert resumed_summary.status == "completed"
    assert len(resumed_summary.production_units) == 1
    assert resumed_summary.production_units[0].location == "terminal"


def test_checkpoint_restore_fails_when_plugin_missing(tmp_path: Path):
    from industrialsim.checkpoint import save_checkpoint, IncompatibleCheckpointError

    cp = create_checkpoint(MICRO_SIMULATION_YAML, at_time_ns=3_000_000_000)
    cp_file = tmp_path / "checkpoint_micro.json"
    save_checkpoint(cp, cp_file)

    reset_plugin_registry(register_defaults=False)
    with pytest.raises(IncompatibleCheckpointError, match="plugin 'micro_station_plugin' is not available"):
        resume_episode(cp_file)


def test_checkpoint_restore_fails_when_plugin_version_mismatched(tmp_path: Path):
    from industrialsim.checkpoint import save_checkpoint, IncompatibleCheckpointError

    cp = create_checkpoint(MICRO_SIMULATION_YAML, at_time_ns=3_000_000_000)
    cp_file = tmp_path / "checkpoint_micro.json"
    save_checkpoint(cp, cp_file)

    class MismatchedMicroPlugin(MicroSubgraphPlugin):
        version = "2.0.0"

    reset_plugin_registry(register_defaults=False)
    registry = get_plugin_registry()
    registry.register(MismatchedMicroPlugin())

    with pytest.raises(IncompatibleCheckpointError, match="Incompatible plugin version"):
        resume_episode(cp_file)


def test_unapproved_plugin_fails_before_episode_starts():
    unapproved_yaml = MICRO_SIMULATION_YAML.replace('approved_plugins:\n  - "micro_station_plugin"', "approved_plugins: []")
    with pytest.raises(ValueError, match="is not approved"):
        run_episode(source=unapproved_yaml)


def test_unknown_station_type_id_fails_before_episode_starts():
    unknown_yaml = MICRO_SIMULATION_YAML.replace('type_id: "micro_subgraph_station"', 'type_id: "unknown_station_type"')
    with pytest.raises(ValueError, match="Unknown type ID"):
        run_episode(source=unknown_yaml)


def test_checkpoint_restore_fails_when_unapproved_in_target_config(tmp_path: Path):
    from industrialsim.checkpoint import save_checkpoint, IncompatibleCheckpointError

    cp = create_checkpoint(MICRO_SIMULATION_YAML, at_time_ns=3_000_000_000)
    cp_file = tmp_path / "checkpoint_micro.json"
    save_checkpoint(cp, cp_file)

    # MACRO_SIMULATION_YAML has no approved_plugins: ["micro_station_plugin"]
    with pytest.raises(IncompatibleCheckpointError, match="is not approved in provided configuration"):
        resume_episode(cp_file, config_source=MACRO_SIMULATION_YAML)

