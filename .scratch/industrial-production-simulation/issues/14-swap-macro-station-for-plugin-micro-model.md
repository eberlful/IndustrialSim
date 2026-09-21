# 14: Swap a macro Station for a trusted plugin micro model

**What to build:** Demonstrate extensibility by registering trusted local behavior under stable versioned type IDs and replacing one macro Station with a detailed micro-level subgraph that preserves the same external material and observation contract.

**Blocked by:** 02: Move Production Units through typed material flow; 04: Allocate Machines and Workers atomically.

Status: resolved

- [x] A thin Station abstraction exposes identity, typed Ports, observable state, and event handling while timing, resources, quality, degradation, and failure behavior remain composed Policies.
- [x] Local approved plugins are discovered through Python entry points and registered under stable type IDs and versions.
- [x] Configuration can select registered behavior without dynamic code, implicit imports, or direct callable references.
- [x] Duplicate type IDs, absent versions, unknown types, and unapproved plugins fail before the Episode starts.
- [x] A macro Station and a plugin-provided micro subgraph accept and emit compatible Production Units and external events.
- [x] Swapping macro for micro requires no neighboring topology or kernel change and produces a valid end-to-end run.
- [x] Checkpoint compatibility metadata includes the selected plugin identity and version.

## Answer

Issue 14 has been implemented:
1. **Station Abstraction & Composed Policies (ADR-0013)**:
   - `Station` in `src/industrialsim/domain.py` exposes identity (`id`), typed input and output ports (`input_ports`, `output_ports`, `get_port()`), observable state, and lifecycle event methods.
   - Cycle timing, resource demands, quality effects, degradation, and failure behavior are composed policies (`TimingPolicy`, `ResourceDemandPolicy`, `QualityPolicy`, `DegradationPolicy`, `FailurePolicy`) with standard defaults.
2. **Plugin Registry & Entry Points Discovery (ADR-0012)**:
   - Implemented `Plugin`, `PluginManifest`, `PluginRegistry` in `src/industrialsim/plugins.py`.
   - Entry point group `industrialsim.plugins` registered in `pyproject.toml`.
   - Duplicate type IDs, absent versions, unknown types, and unapproved plugins fail before episode starts during validation.
3. **Declarative Configuration & Macro/Micro Swap (ADR-0004)**:
   - `SimulationConfig` supports `approved_plugins: list[str]`. Stations select plugins declaratively via `type_id` and `parameters` with zero dynamic code or implicit imports.
   - `MicroSubgraphStation` replaces macro Station with multi-stage execution (`tack_weld` + `seam_weld` = 10s) with zero kernel changes (`kernel.py` unmodified) and zero neighboring topology changes, delivering identical timing and completion.
4. **Checkpoint Compatibility & Plugin Metadata (ADR-0009)**:
   - Checkpoints and run manifests record `plugin_metadata: dict[str, str]` (plugin ID to version).
   - Checkpoint restoration strictly verifies plugin availability, version match, and configuration approval. Station snapshots preserve generic state via `custom_state` without schema pollution.

