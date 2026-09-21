import pytest
from unittest.mock import MagicMock, patch

from industrialsim.plugins import (
    Plugin,
    PluginRegistry,
    PluginValidationError,
    get_plugin_registry,
    reset_plugin_registry,
)


@pytest.fixture(autouse=True)
def clean_registry():
    reset_plugin_registry()
    yield
    reset_plugin_registry()


def test_register_and_lookup_plugin():
    registry = PluginRegistry()

    class DummyPlugin(Plugin):
        plugin_id = "test_plugin"
        version = "1.0.0"
        type_id = "dummy_station"

    plugin = DummyPlugin()
    registry.register(plugin)

    assert registry.has_type("dummy_station")
    assert registry.get_plugin_by_type("dummy_station") is plugin
    manifest = registry.get_manifest("dummy_station")
    assert manifest.plugin_id == "test_plugin"
    assert manifest.version == "1.0.0"
    assert manifest.type_id == "dummy_station"


def test_reject_absent_version():
    registry = PluginRegistry()

    class MissingVersionPlugin(Plugin):
        plugin_id = "bad_plugin"
        version = ""  # absent version
        type_id = "bad_station"

    with pytest.raises(PluginValidationError, match=r"absent version"):
        registry.register(MissingVersionPlugin())

    class NoneVersionPlugin(Plugin):
        plugin_id = "bad_plugin_2"
        version = None  # type: ignore
        type_id = "bad_station_2"

    with pytest.raises(PluginValidationError, match=r"absent version"):
        registry.register(NoneVersionPlugin())


def test_reject_duplicate_type_ids():
    registry = PluginRegistry()

    class PluginA(Plugin):
        plugin_id = "plugin_a"
        version = "1.0.0"
        type_id = "shared_type"

    class PluginB(Plugin):
        plugin_id = "plugin_b"
        version = "2.0.0"
        type_id = "shared_type"

    registry.register(PluginA())

    with pytest.raises(PluginValidationError, match=r"Duplicate type ID 'shared_type'"):
        registry.register(PluginB())


def test_discover_plugins_via_entry_points():
    registry = PluginRegistry()

    class DiscoveredPlugin(Plugin):
        plugin_id = "entry_point_plugin"
        version = "1.2.3"
        type_id = "ep_station"

    mock_ep = MagicMock()
    mock_ep.name = "ep_plugin"
    mock_ep.load.return_value = DiscoveredPlugin

    with patch("importlib.metadata.entry_points") as mock_eps:
        mock_eps.return_value = [mock_ep]
        discovered = registry.discover_entry_points(group="industrialsim.plugins")
        assert len(discovered) == 1
        assert registry.has_type("ep_station")
        assert registry.get_plugin_by_type("ep_station").version == "1.2.3"


def test_validate_approval_and_unknown_types():
    registry = PluginRegistry()

    class ApprovedPlugin(Plugin):
        plugin_id = "approved_plugin"
        version = "1.0.0"
        type_id = "approved_station"

    class UnapprovedPlugin(Plugin):
        plugin_id = "unapproved_plugin"
        version = "1.0.0"
        type_id = "unapproved_station"

    registry.register(ApprovedPlugin())
    registry.register(UnapprovedPlugin())

    # Unknown type
    with pytest.raises(PluginValidationError, match=r"Unknown type ID 'unknown_station'"):
        registry.validate_type_selection(type_id="unknown_station", approved_plugins=["approved_plugin"])

    # Unapproved plugin
    with pytest.raises(PluginValidationError, match=r"Plugin 'unapproved_plugin' .* is not approved"):
        registry.validate_type_selection(type_id="unapproved_station", approved_plugins=["approved_plugin"])

    # Approved plugin succeeds
    selected = registry.validate_type_selection(type_id="approved_station", approved_plugins=["approved_plugin"])
    assert selected.plugin_id == "approved_plugin"


def test_simulation_config_validates_plugins():
    from industrialsim.config import SimulationConfig

    registry = get_plugin_registry()

    class ApprovedStationPlugin(Plugin):
        plugin_id = "valid_cell"
        version = "1.0.0"
        type_id = "micro_cell"

    registry.register(ApprovedStationPlugin())

    valid_yaml = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0s
  end_condition:
    type: "max_time"
    max_time: 10s
approved_plugins:
  - "valid_cell"
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
      type_id: "micro_cell"
      input_ports: [{ id: "in", port_type: "body", direction: "input" }]
      output_ports: [{ id: "out", port_type: "body", direction: "output" }]
      operations:
        - id: "op1"
          duration: 2s
    - id: "snk"
      kind: "sink"
      input_ports: [{ id: "in", port_type: "body", direction: "input" }]
  routes:
    - id: "r1"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "cell_1"
      target_port_id: "in"
    - id: "r2"
      source_node_id: "cell_1"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
"""
    import ruamel.yaml
    yaml = ruamel.yaml.YAML(typ="safe")
    data = yaml.load(valid_yaml)

    # Valid configuration parses
    cfg = SimulationConfig.model_validate(data)
    assert cfg.approved_plugins == ["valid_cell"]
    assert cfg.material_flow.nodes[1].type_id == "micro_cell"

    # Reject unknown type_id
    bad_type_data = yaml.load(valid_yaml.replace('type_id: "micro_cell"', 'type_id: "unknown_cell"'))
    with pytest.raises(ValueError, match=r"(?i)unknown type id"):
        SimulationConfig.model_validate(bad_type_data)

    # Reject unapproved plugin (when not in approved_plugins)
    unapproved_data = yaml.load(valid_yaml.replace('approved_plugins:\n  - "valid_cell"', 'approved_plugins: []'))
    with pytest.raises(ValueError, match=r"(?i)not approved"):
        SimulationConfig.model_validate(unapproved_data)

