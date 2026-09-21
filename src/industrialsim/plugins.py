from __future__ import annotations

from dataclasses import dataclass, field
import importlib.metadata
from typing import Any, Sequence


class PluginValidationError(ValueError):
    """Raised when plugin registration, discovery, or selection validation fails."""


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    version: str
    type_id: str
    description: str = ""


class Plugin:
    """Base class for IndustrialSim trusted local plugins."""

    plugin_id: str
    version: str
    type_id: str
    description: str = ""

    def get_manifest(self) -> PluginManifest:
        return PluginManifest(
            plugin_id=self.plugin_id,
            version=self.version,
            type_id=self.type_id,
            description=getattr(self, "description", ""),
        )


class PluginRegistry:
    """Registry for discovering, validating, and managing trusted plugins under stable versioned type IDs."""

    def __init__(self) -> None:
        self._plugins_by_type: dict[str, Plugin] = {}
        self._plugins_by_id: dict[str, Plugin] = {}

    def register(self, plugin_or_cls: Plugin | type[Plugin]) -> Plugin:
        plugin = plugin_or_cls() if isinstance(plugin_or_cls, type) else plugin_or_cls

        plugin_id = getattr(plugin, "plugin_id", None)
        version = getattr(plugin, "version", None)
        type_id = getattr(plugin, "type_id", None)

        if not plugin_id or not str(plugin_id).strip():
            raise PluginValidationError("Plugin has absent or empty 'plugin_id'")

        if not version or not str(version).strip():
            raise PluginValidationError(
                f"Plugin '{plugin_id}' has absent version. Stable version is required."
            )

        if not type_id or not str(type_id).strip():
            raise PluginValidationError(
                f"Plugin '{plugin_id}' has absent or empty 'type_id'"
            )

        plugin_id_str = str(plugin_id).strip()
        version_str = str(version).strip()
        type_id_str = str(type_id).strip()

        if type_id_str in self._plugins_by_type:
            existing = self._plugins_by_type[type_id_str]
            if existing.plugin_id != plugin_id_str or existing.version != version_str:
                raise PluginValidationError(
                    f"Duplicate type ID '{type_id_str}' registered by plugins '{existing.plugin_id}' and '{plugin_id_str}'"
                )

        self._plugins_by_type[type_id_str] = plugin
        self._plugins_by_id[plugin_id_str] = plugin
        return plugin

    def discover_entry_points(self, group: str = "industrialsim.plugins") -> list[Plugin]:
        discovered: list[Plugin] = []
        group_eps: Any
        try:
            group_eps = importlib.metadata.entry_points(group=group)
        except TypeError:
            eps = importlib.metadata.entry_points()
            group_eps = eps.select(group=group) if hasattr(eps, "select") else getattr(eps, "get", lambda _: [])(group)
        except Exception:
            group_eps = []

        for ep in group_eps:
            try:
                loaded = ep.load()
                plugin = self.register(loaded)
                discovered.append(plugin)
            except PluginValidationError:
                raise
            except Exception as e:
                raise PluginValidationError(
                    f"Failed to load plugin from entry point '{ep.name}': {e}"
                ) from e
        return discovered

    def has_type(self, type_id: str) -> bool:
        return type_id in self._plugins_by_type

    def has_plugin(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins_by_id

    def get_plugin_by_type(self, type_id: str) -> Plugin | None:
        return self._plugins_by_type.get(type_id)

    def get_plugin_by_id(self, plugin_id: str) -> Plugin | None:
        return self._plugins_by_id.get(plugin_id)

    def get_manifest(self, type_id: str) -> PluginManifest | None:
        plugin = self.get_plugin_by_type(type_id)
        if plugin is None:
            return None
        return plugin.get_manifest()

    def validate_type_selection(
        self,
        type_id: str,
        approved_plugins: Sequence[str] | None = None,
    ) -> Plugin:
        if type_id not in self._plugins_by_type:
            raise PluginValidationError(
                f"Unknown type ID '{type_id}'. Ensure the providing plugin is installed and registered."
            )

        plugin = self._plugins_by_type[type_id]

        if approved_plugins is not None:
            approved_set = set(approved_plugins)
            if plugin.plugin_id not in approved_set:
                raise PluginValidationError(
                    f"Plugin '{plugin.plugin_id}' providing type_id '{type_id}' is not approved. "
                    f"Approved plugins in configuration: {sorted(approved_set)}"
                )

        return plugin

    def clear(self) -> None:
        self._plugins_by_type.clear()
        self._plugins_by_id.clear()


@dataclass
class MicroStage:
    id: str
    duration_ns: int
    required_machines: list[str] = field(default_factory=list)
    required_workers: list[dict[str, Any]] = field(default_factory=list)
    defect_probability: float = 0.0
    defect_name: str | None = None


from industrialsim.domain import Operation, Station
from industrialsim.material_flow import Port


@dataclass
class MicroSubgraphStation(Station):
    stages: list[MicroStage] = field(default_factory=list)
    active_stage_index: int | None = None
    stage_start_ns: int | None = None
    active_token: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)

    def get_current_stage(self) -> MicroStage | None:
        if self.active_stage_index is not None and 0 <= self.active_stage_index < len(self.stages):
            return self.stages[self.active_stage_index]
        return None

    def advance_stage(self, time_ns: int) -> bool:
        if self.active_stage_index is None:
            return False
        self.active_stage_index += 1
        self.stage_start_ns = time_ns
        if self.active_stage_index < len(self.stages):
            return True
        return False

    def to_snapshot(self) -> dict[str, Any]:
        snap = super().to_snapshot()
        snap["custom_state"] = {
            "active_stage_index": self.active_stage_index,
            "stage_start_ns": self.stage_start_ns,
            "active_token": self.active_token,
            "stages": [
                {
                    "id": s.id,
                    "duration_ns": s.duration_ns,
                    "required_machines": list(s.required_machines),
                    "required_workers": list(s.required_workers),
                    "defect_probability": s.defect_probability,
                    "defect_name": s.defect_name,
                }
                for s in self.stages
            ],
        }
        return snap

    def restore_state(self, state: Any) -> None:
        super().restore_state(state)
        custom: dict[str, Any] = {}
        if hasattr(state, "custom_state") and isinstance(state.custom_state, dict):
            custom = state.custom_state
        elif hasattr(state, "get") and state.get("custom_state"):
            custom = dict(state.get("custom_state"))
        elif isinstance(state, dict):
            custom = state

        self.active_stage_index = custom.get("active_stage_index")
        self.stage_start_ns = custom.get("stage_start_ns")
        self.active_token = custom.get("active_token")
        self.parameters = dict(custom.get("parameters", getattr(self, "parameters", {})))
        if custom.get("stages"):
            self.stages = [
                MicroStage(
                    id=s["id"] if isinstance(s, dict) else s.id,
                    duration_ns=int(s["duration_ns"] if isinstance(s, dict) else s.duration_ns),
                    required_machines=list(s.get("required_machines", []) if isinstance(s, dict) else getattr(s, "required_machines", [])),
                    required_workers=list(s.get("required_workers", []) if isinstance(s, dict) else getattr(s, "required_workers", [])),
                    defect_probability=float(s.get("defect_probability", 0.0) if isinstance(s, dict) else getattr(s, "defect_probability", 0.0)),
                    defect_name=s.get("defect_name") if isinstance(s, dict) else getattr(s, "defect_name", None),
                )
                for s in custom.get("stages", [])
            ]


class MicroSubgraphPlugin(Plugin):
    """Trusted plugin providing a detailed micro-level subgraph station model."""

    plugin_id = "micro_station_plugin"
    version = "1.0.0"
    type_id = "micro_subgraph_station"
    description = "Trusted plugin providing detailed micro-level subgraph station modeling."

    def create_station(
        self,
        node_id: str,
        operations: dict[str, Operation],
        input_ports: dict[str, Port],
        output_ports: dict[str, Port],
        output_capacity: int = 0,
        parameters: dict[str, Any] | None = None,
    ) -> MicroSubgraphStation:
        params = dict(parameters or {})
        stages_data = params.get("stages", [])
        stages: list[MicroStage] = []

        if stages_data:
            from industrialsim.config import parse_duration_ns

            for s in stages_data:
                dur = s.get("duration", 0)
                dur_ns = parse_duration_ns(dur) if isinstance(dur, str) else int(dur)
                stages.append(
                    MicroStage(
                        id=s.get("id", f"stage_{len(stages)}"),
                        duration_ns=dur_ns,
                        required_machines=list(s.get("required_machines", [])),
                        required_workers=list(s.get("required_workers", [])),
                        defect_probability=float(s.get("defect_probability", 0.0)),
                        defect_name=s.get("defect_name"),
                    )
                )
        else:
            primary_op = next(iter(operations.values())) if operations else None
            tot_ns = primary_op.duration_ns if primary_op else 0
            dur1 = int(tot_ns * 0.4)
            dur2 = tot_ns - dur1
            stages = [
                MicroStage(id="stage_1", duration_ns=dur1),
                MicroStage(id="stage_2", duration_ns=dur2),
            ]

        return MicroSubgraphStation(
            id=node_id,
            operations=operations,
            input_ports=input_ports,
            output_ports=output_ports,
            output_capacity=output_capacity,
            type_id=self.type_id,
            plugin_id=self.plugin_id,
            plugin_version=self.version,
            stages=stages,
            parameters=params,
        )


_GLOBAL_REGISTRY: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = PluginRegistry()
        _GLOBAL_REGISTRY.register(MicroSubgraphPlugin())
        _GLOBAL_REGISTRY.discover_entry_points()
    return _GLOBAL_REGISTRY


def reset_plugin_registry(register_defaults: bool = True) -> None:
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is not None:
        _GLOBAL_REGISTRY.clear()
    _GLOBAL_REGISTRY = PluginRegistry()
    if register_defaults:
        _GLOBAL_REGISTRY.register(MicroSubgraphPlugin())

