# 14: Swap a macro Station for a trusted plugin micro model

**What to build:** Demonstrate extensibility by registering trusted local behavior under stable versioned type IDs and replacing one macro Station with a detailed micro-level subgraph that preserves the same external material and observation contract.

**Blocked by:** 02: Move Production Units through typed material flow; 04: Allocate Machines and Workers atomically.

Status: ready-for-agent

- [ ] A thin Station abstraction exposes identity, typed Ports, observable state, and event handling while timing, resources, quality, degradation, and failure behavior remain composed Policies.
- [ ] Local approved plugins are discovered through Python entry points and registered under stable type IDs and versions.
- [ ] Configuration can select registered behavior without dynamic code, implicit imports, or direct callable references.
- [ ] Duplicate type IDs, absent versions, unknown types, and unapproved plugins fail before the Episode starts.
- [ ] A macro Station and a plugin-provided micro subgraph accept and emit compatible Production Units and external events.
- [ ] Swapping macro for micro requires no neighboring topology or kernel change and produces a valid end-to-end run.
- [ ] Checkpoint compatibility metadata includes the selected plugin identity and version.

