# 01: Open a local project and display a Plant

**What to build:** Start the local browser application with a project directory, load or import existing simulation YAML, and inspect its Material Flow Graph before editing or execution.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [x] One documented startup command serves the React/TypeScript and React Flow UI through the loopback-bound FastAPI service and opens the selected local project.
- [x] The light interface provides a central graph, adjacent properties area and Episode-control area; statuses use text or symbols in addition to color.
- [x] Opening a project-local model or importing valid YAML displays every existing source, sink, Station, Buffer, typed Port and route, including cycles and parallel routes.
- [x] Organizational Plant information is read without conflating its Area/Hall hierarchy with the Material Flow Graph.
- [x] Invalid YAML or schema/domain-invalid configuration produces actionable diagnostics without replacing an already loaded valid model silently.
- [x] Loading preserves the complete configuration semantically, including sections not displayed by the graph; imported originals are not overwritten.
- [x] A public project-session boundary reuses existing configuration validation; service handlers do not duplicate domain rules.
- [x] Integration checks load the reference Plant through the public project interface; a browser workflow verifies import, graph display and visible validation errors.


## Comments

Implemented the public `ProjectSession` boundary, loopback FastAPI service and
single-command launcher, plus the React/TypeScript and React Flow workspace.
Project-local opens and in-memory YAML imports reuse `validate_config`; failed
loads preserve the accepted model. The original YAML and complete configuration
are retained without overwriting source files. All typed Ports and route identities
are displayed, including parallel routes and cycles. Plant organization remains
separate from material flow. Episode execution is deferred to its subsequent issue.

Verification: full Python suite **272 passed, 1 optional ML test skipped**;
`mypy src` passed; frontend TypeScript/build passed; both real Chromium workflows
passed (reference import/display/errors/reconnect and parallel routes/self-cycle
inspection); documented startup-command smoke check passed; workspace screenshot
visually inspected. Code review against the starting commit `5f625ca` returned
**Standards: 0 findings; Spec: 0 findings**. Existing unrelated workspace changes
were preserved and excluded from the implementation commit.
