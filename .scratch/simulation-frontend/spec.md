# Local simulation frontend

Status: ready-for-agent

## Problem Statement

The user operates the simulation through Python and the CLI. There is no browser interface for understanding or changing a Plant's Material Flow Graph, observing an active Episode, or responding to a Decision Batch. Editing strict YAML and inspecting separate artifacts makes the complete workflow cumbersome and obscures the relationships between production resources, material flow, decisions and outcomes.

The user needs a local tool connecting visual Plant modeling with Episode execution while preserving reproducibility, consistent decision points and the distinction between simulator truth and available observations.

## Solution

Provide a local browser application that loads an existing Plant, presents a movable 2D Material Flow Graph and lets the user edit topology and associated production parameters. A properties panel and validated YAML editor expose configuration; a Production Plan table and Episode setup prepare execution.

The application starts one Episode, displays live occupancy, resource status, metrics and events, and supports consistent pause, continuation and advancement to the next Decision Batch. Baseline and manual modes are available. Manual actions are submitted as a complete, jointly validated batch. Truth and observation views are distinguished. Local project storage preserves configurations, layouts, drafts, results and explicit Checkpoints independently of browser lifetime.

## User Stories

1. As a simulation user, I want one startup command accepting a local project directory, so that I can open my workspace without coordinating services manually.
2. As a simulation user, I want to load an existing Plant configuration, so that I can build on existing simulation models.
3. As a simulation user, I want to import simulation YAML, so that I can use configurations created outside the frontend.
4. As a simulation user, I want Stations, Buffers, sources and sinks displayed in a 2D Material Flow Graph, so that I can understand production structure.
5. As a simulation user, I want typed Ports and transport connections displayed, so that I can understand how Production Units move between nodes.
6. As a simulation user, I want parallel routes and cycles represented faithfully, so that alternative transport and rework paths remain visible.
7. As a simulation user, I want grouping by Area and Hall, so that I can relate material flow to the Plant hierarchy.
8. As a simulation user, I want to move graph elements without changing simulation parameters, so that improving readability does not alter behavior.
9. As a simulation user, I want graph positions and grouping saved separately, so that my layout survives reopening without adding UI fields to simulation YAML.
10. As a simulation user, I want to add Stations, Buffers, sources and sinks, so that I can extend material flow.
11. As a simulation user, I want to connect nodes through compatible Ports and edit routes, so that I can configure production flow.
12. As a simulation user, I want to delete nodes and routes and see affected references, so that restructuring does not silently remove unrelated configuration.
13. As a simulation user, I want forms for Hall assignments, capacities and processing durations, so that common changes do not require manual YAML editing.
14. As a simulation user, I want to edit route transit times, capacities and existing transport requirements, so that logistics behavior remains explicit.
15. As a simulation user, I want to edit Machines and Worker requirements and assignments, so that resources reflect my production model.
16. As a simulation user, I want a validated YAML editor for fields outside specialized forms, so that the full configuration remains accessible.
17. As a simulation user, I want forms and YAML to represent the same draft, so that switching views does not discard edits.
18. As a simulation user, I want undo and redo for configuration and layout changes, so that I can recover from mistakes.
19. As a simulation user, I want to save incomplete or invalid drafts, so that I can pause editing before every connection and reference is resolved.
20. As a simulation user, I want errors associated with relevant fields and graph elements, so that I can correct the model efficiently.
21. As a simulation user, I want invalid configurations blocked from Episode start and executable export, so that I do not run or distribute a broken model.
22. As a simulation user, I want untouched sections preserved semantically, so that visual editing does not remove policies, triggers or advanced settings.
23. As a simulation user, I want valid YAML export, so that I can continue using CLI and Python workflows.
24. As a simulation user, I want imported originals overwritten only through explicit saving, so that experimentation does not unexpectedly replace source files.
25. As a simulation user, I want setup initialized from existing configuration, so that I can run a loaded model without repeated entry.
26. As a simulation user, I want to choose seed and simulation duration, so that I can control reproducible Episode inputs.
27. As a simulation user, I want a Production Plan table with release time, variant, quantity and optional due date, so that production inputs are clear.
28. As a simulation user, I want Baseline or manual decisions, so that I can observe automatic behavior or supply actions myself.
29. As a simulation user, I want to start a valid Episode, so that I can evaluate my configured Plant.
30. As a simulation user, I want consistent pause and continuation, so that inspection preserves simulation semantics.
31. As a simulation user, I want advancement to the next Decision Batch, so that I can reach a meaningful control boundary directly.
32. As a simulation user, I want a second start rejected while an Episode is active, so that I cannot accidentally replace ongoing work.
33. As a simulation user, I want edits to affect the next Episode while the active Episode keeps its input configuration, so that results remain reproducible.
34. As a simulation user, I want fast computation with a responsive UI, so that observation does not impose real-time pacing.
35. As a simulation user, I want simulated time and wall-clock time displayed separately, so that I can distinguish production progress from computation time.
36. As a simulation user, I want all requests in a manual Decision Batch displayed together, so that I can decide against their shared observed state.
37. As a simulation user, I want action forms based on each request's applicable schema, so that I can supply supported actions.
38. As a simulation user, I want time frozen while a manual batch awaits input, so that I can inspect and decide without pressure.
39. As a simulation user, I want individual and joint validation with actionable errors, so that I can correct invalid or conflicting actions.
40. As a simulation user, I want rejected proposals kept editable without fallback or advancement, so that input mistakes do not silently change the Episode.
41. As a simulation user, I want the complete valid batch applied atomically, so that actions preserve consistent decision semantics.
42. As a simulation user, I want repeated and stale submissions rejected safely, so that retries cannot apply actions twice or answer another batch.
43. As a simulation user, I want live Station and Buffer occupancy and resource status, so that I can identify congestion and resource constraints.
44. As a simulation user, I want supported raw metrics beside the graph, so that I can assess production during execution.
45. As a simulation user, I want ordered, paginated events, so that I can inspect activity without loading the entire history.
46. As a simulation user, I want resource and Production Unit details, so that I can investigate individual behavior.
47. As a simulation user, I want labeled truth and observation views, so that simulator knowledge is distinguished from Decision Provider information.
48. As a simulation user, I want unavailable observations identified rather than filled from hidden truth, so that I do not infer nonexistent provider knowledge.
49. As a simulation user, I want final results and decision diagnostics, so that I can understand the Episode's outcome.
50. As a simulation user, I want Deadlock causes explained where applicable, so that I can investigate why production cannot progress.
51. As a simulation user, I want status text and symbols as well as color, so that the interface remains interpretable.
52. As a simulation user, I want a central graph, adjacent properties and collapsible metrics and events, so that I can focus on the current task.
53. As a simulation user, I want the Episode to survive browser closure and reconnect to its current state, so that browser lifetime does not control execution.
54. As a simulation user, I want models, layouts, drafts and results stored in my project directory, so that my work persists locally.
55. As a simulation user, I want results associated with their original configuration, so that later edits do not misrepresent past outcomes.
56. As a simulation user, I want explicit durable Checkpoints, so that I can choose a known recovery point.
57. As a simulation user, I want restoration after backend restart, so that I can continue a saved Episode reproducibly.
58. As a simulation user, I want incompatible Checkpoints rejected clearly, so that I do not continue under invalid assumptions.
59. As a simulation user, I want a restored pending manual batch to await input again, so that recovery does not silently choose actions.
60. As a simulation user, I want continuation in a new output directory with origin provenance, so that previous complete and incomplete artifacts remain intact.
61. As a simulation user, I want refreshes and pauses to preserve audit records without duplicate terminal results, so that monitoring does not corrupt evaluation evidence.

## Implementation Decisions

- **Browser/service:** Use React/TypeScript and React Flow for the browser UI and FastAPI for a loopback-bound Python service. Provide one documented startup command accepting the local project directory.
- **Session ownership:** The service owns one active Episode independently of browser connections. A simulation worker serializes engine mutations and processes control commands while HTTP requests remain responsive. Reconnect observes the existing authoritative session.
- **Public application interface:** Introduce one public project/Episode session facade above the existing application functions for configuration/draft operations, Episode setup, advancement, consistent pause, pending batches, validated atomic submission, snapshots, events and Checkpoints. Reuse existing schema/domain validation and auditing; HTTP handlers do not orchestrate private engine methods or duplicate rules.
- **Engine lifecycle:** Reading intermediate state and pausing must not finalize an Episode or duplicate terminal telemetry, reward or summary records. Preserve integer-nanosecond time, deterministic ordering and reproducible random streams.
- **Configuration authority:** Existing strict Pydantic schemas and domain validation govern all edits and execution. Patch loaded configuration and preserve untouched sections semantically. Comments, formatting and original field order need not survive YAML export. Existing trusted installed-plugin approval remains authoritative.
- **Graph semantics:** Preserve typed Ports, cycles, parallel routes and existing source, sink, Station and Buffer types. Area/Hall grouping does not replace material flow. Moving elements changes presentation only; explicit transport durations remain unchanged.
- **Editing:** Provide graph operations and forms for connectivity, Hall assignment, capacities, processing durations, explicit transport parameters, Machines and Worker requirements/assignments. A validated YAML editor exposes the rest. Forms/YAML share one draft without silent loss on switching. Undo/redo covers configuration and presentation changes.
- **Invalid drafts:** Allow separately persisted incomplete drafts. Associate schema/domain/reference errors with affected fields and elements. Referenced-entity deletion does not silently remove unrelated sections. Full validation gates Episode start and executable YAML export.
- **Layout:** Store positions and grouping separately from strict simulation YAML and associate layout/model identities.
- **Episode inputs:** Initialize seed, duration and Production Plan from configuration. Provide release time, variant, quantity and optional due date columns. Validate and materialize the Production Plan before execution under existing semantics.
- **Providers:** First-version choices are BaselineDecisionProvider and human/manual responses. Model-provider initialization, registry and external-history restoration are outside this version.
- **Execution controls:** Support start, pause, continue and next Decision Batch. Pause at a consistent state. Reject another start while an Episode is active. Active inputs remain fixed; edits apply to the next Episode. Compute as fast as possible, independently throttle display updates and distinguish simulated/wall-clock time.
- **Manual decisions:** Present all pending Decision Requests and applicable action forms. Freeze simulated time until resolution. Validate individually and jointly against the shared state, then apply a complete valid batch atomically. Invalid/conflicting form input stays editable with explanations and causes neither implicit fallback nor advancement. Actual provider failure/abort still follows existing configured policy.
- **Command identity:** Target the intended Episode/batch and prevent stale or repeated submissions from applying actions twice or answering another batch.
- **Observation contract:** Label simulator-truth and available-observation views. Follow the actual provider contract, including exact state it already exposes. Do not fill missing observations from hidden truth or inject additional truth because of view selection. Switching views cannot change provider input or Episode behavior.
- **Views:** Show live node occupancy/status, resources, Production Unit details, supported raw metrics and ordered paginated events. Show final results, decision diagnostics and Deadlock causes through existing summary/audit semantics.
- **Persistence:** Use the startup-selected project directory for models, layouts, drafts and unique Episode outputs. Support YAML import/download and explicit local saves. Overwrite originals only through an explicit save. Associate results with the fixed configuration that produced them.
- **Recovery:** Create Checkpoints explicitly at consistent states and enforce existing compatibility validation. Backend restart requires explicit restore; browser reconnect does not. Continue into a fresh unique output directory with parent/checkpoint provenance, preserving complete and incomplete artifacts. Restored pending manual batches wait again for input. Recovery beyond a saved Checkpoint and unsupported external provider history is not promised.
- **Presentation:** Use a light engineering UI with central graph, right properties, top controls and collapsible metrics/events. Pair status colors with text/symbols and distinguish the active Episode's inputs from future edits.
- **Architecture constraints:** Respect ADR-0002, ADR-0003, ADR-0006, ADR-0009, ADR-0010, ADR-0012, ADR-0014, ADR-0015 and ADR-0016. ADR-0019 records edit boundaries; ADR-0020 records local service/session ownership. This feature expands the original GUI exclusion while retaining simulation invariants.

## Testing Decisions

- **Good tests:** Assert public commands, accepted/rejected inputs, observable state, outcomes and saved artifacts. Avoid private-method assertions, internal worker/component state and exact render timing. Use deterministic seeds and meaningful domain scenarios, not tests mirroring implementation.
- **Primary seam:** Concentrate feature integration tests at the public project/Episode session facade above the existing Application API. Use real schema/domain validation, engine behavior and temporary project storage. Prefer existing application functions as the reference oracle. Do not introduce scattered low-level engine seams for the frontend.
- **Browser seam:** Add a small set of browser end-to-end tests against the real local service for graph/form/YAML synchronization, undo/redo, validation presentation, manual decisions and reconnect. Verify complete workflows rather than duplicating every facade test at component level.
- **Expectation check:** The facade plus limited browser workflows was presented for a focused user expectation check during synthesis. This is the proposed default; no alternative was supplied at publication.
- **Modules:** Cover project/configuration/layout editing and persistence, session lifecycle/control, decision submission, snapshot/observation exposure, recovery and the browser workflows integrating them. Extend existing public application behavior checks where new control lifecycle affects existing execution.
- **Prior art:** Existing application and material-flow integration tests use public configuration validation and Episode execution. Reference automotive Plant tests establish full-model and result-hash determinism checks; decision simulation tests establish batch/action scenarios; checkpoint equivalence tests compare resumed and uninterrupted execution; audit artifact tests assert ordered logging, provenance and output preservation. Deadlock and telemetry integration tests supply diagnostic/metric scenarios. Reuse these patterns and public APIs.
- **Configuration/layout acceptance:** Import the reference Plant with every node, typed connection, parallel route and cycle. Change capacity/duration, move elements, export/reload. Edited fields change, untouched sections retain meaning, layout persists independently and transport durations do not change with positions.
- **Draft acceptance:** Add an unconnected Station or remove a referenced entity. Save/reopen the draft, identify errors and block start/executable export until corrected. Undo/redo restores intended configuration/layout; switching forms/YAML does not discard valid or incomplete edits.
- **Execution equivalence:** For fixed inputs and action sequence, session-driven execution agrees with direct simulator execution. Repeat with pauses and frequent snapshot reads. Assert domain outcomes/result hashes rather than wall-clock values.
- **Batch acceptance:** Requests share a paused state. Invalid or conflicting input leaves time/state unchanged and remains correctable. A complete valid batch applies once atomically. Stale/repeated submissions cannot duplicate effects. Distinguish validation rejection from actual provider failure/fallback.
- **Connection/lifecycle acceptance:** Browser closure leaves the Episode active; reopening reconnects to it. A second start cannot replace it. Verify controls using deterministic scenarios and observable state transitions rather than brittle sleeps.
- **Recovery acceptance:** Create a Checkpoint, restart and restore. Compare continuation to direct execution, verify origin provenance and preservation of old artifacts, and ensure pending manual input waits again. Reject incompatible Checkpoints without starting an invalid continuation.
- **Observation acceptance:** Views honor the applicable contract, missing observations remain unavailable and switching cannot change provider input/outcome. Do not require hiding exact state already exposed by that contract.
- **Artifact/result acceptance:** Finish normal and Deadlocked Episodes and inspect diagnostics. Pauses, reconnects and refreshes must not duplicate terminal records, lose ordered audit events or overwrite earlier outputs. Paginated events preserve order without requiring the full history in browser memory.
- **Validation scope:** During implementation, run relevant existing application, decision, checkpoint, audit, material-flow and reference-Plant checks when their behavior changes, plus new facade/browser acceptance checks. This task changes documentation only and does not require simulator test execution.

## Out of Scope

- Remote deployment, multiple users, authentication and multiple simultaneously active Episodes.
- Physical floorplans, 3D visualization, geometric traffic simulation and transport times derived from graph coordinates.
- Individual Production Unit animation and real-time speed/pacing controls; live occupancy/status is sufficient initially.
- Arbitrary changes to an active Episode's Plant configuration.
- Dedicated Experiment comparison, training, Counterfactual Branch exploration or optimization interfaces.
- Turnkey Predictive/World-Model providers, external model calls and persistence of model/provider contextual history.
- Browser installation/upload of executable plugins; existing trusted installed-plugin handling remains unchanged.
- Preservation of YAML comments, exact formatting or original ordering; semantic preservation is required.
- Specialized forms for every field; validated YAML covers configuration outside the agreed forms.
- Automatic periodic Checkpoints, implicit restart recovery and recovery beyond an explicitly saved compatible Checkpoint.
- New observation semantics or sensor-only guarantees for contracts that expose exact state.
- Numerical scale/latency guarantees not agreed in the interview; use the reference Plant as the initial full acceptance scenario.

## Further Notes

- Q1–Q17 were accepted in the design interview. The user invoked to-spec to synthesize and publish this specification without another product interview.
- Publish in the local Markdown issue tracker with canonical ready-for-agent status. Additional triage and implementation ticket decomposition are outside this request.
- This specification supersedes the earlier feature draft. The interview decision record and ADRs retain rationale.
- No application code or tests were changed. Preserve unrelated working-tree modifications during implementation.
- No new domain-specific term was resolved; use the existing glossary and keep frontend implementation details out of it.
