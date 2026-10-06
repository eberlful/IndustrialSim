# Simulation frontend — design interview

## Confirmed decisions

- The frontend supports both visual Plant modeling and starting, observing, and understanding Episodes (Q1: A and C).
- Usage is local (Q2).
- Load an existing Plant and edit material flow plus associated capacities, processing durations, Machines and Worker assignments. Include YAML import and export (Q3).
- Use a movable 2D Material Flow Graph, groupable by Area and Hall. Display positions do not change transport times (Q4).
- Support start, pause, continue and advance to the next Decision Batch, with optional human action submission at that batch (Q5).
- Plant edits apply to the next Episode, not the active Episode (Q5; ADR-0019).
- Provide clearly identified, switchable views of simulator truth and available observations; observation visibility must reflect the applicable Decision Provider contract (Q6).
- Export semantically complete simulation YAML and store graph positions/grouping in a separate layout file. Preserve configuration fields not exposed by the editor; YAML comments/formatting need not survive. Overwrite an original only through explicit saving (Q7).
- Episode setup exposes seed, simulation duration, Production Plan and Decision Provider, initialized from existing configuration. Edit Production Plans in a table with release time, variant, quantity and optional due date (Q8).
- Provide automatic and manual decision modes. In manual mode, show all Decision Requests and action forms, validate the complete Decision Batch before applying it, and keep invalid submissions editable with explanations (Q9).
- Show live node occupancy/status, metrics and an event list; node/resource/Production Unit detail views; distinguish simulated and wall-clock time. Show final results and Deadlock causes when applicable (Q10).
- Allow one active Episode, continuing independently of browser connections. Persist drafts and results locally; explicit durable Checkpoints support resumption after a backend restart (Q11).
- Use a light engineering UI: central graph, right-hand properties, top controls and collapsible metrics/events. Pair status colors with text and symbols (Q12).
- Use React/TypeScript and React Flow with a local FastAPI service and a simulation worker; provide one startup command and bind the service to loopback (Q13).
- First-version Decision Provider choices are Baseline and manual. Observation views reflect the actual applicable information contract, including any exact state it exposes (Q14).
- Permit invalid intermediate drafts, node/route creation and deletion, undo/redo and explicit reference diagnostics. Require a valid configuration for Episode start and executable YAML export. Provide a validated YAML editor for fields outside specialized forms (Q15).
- Use a project directory selected at startup for models, layouts, drafts and Episode artifacts, complemented by YAML import/download. Checkpoint continuations write new output directories with origin provenance (Q16).
- Run as fast as possible, throttle display updates and paginate events. Pause at a consistent state; support next-Decision-Batch control. Create Checkpoints explicitly; restored pending manual batches wait again for input (Q17).

## Existing constraints

- The Material Flow Graph is separate from the Plant / Area / Hall location hierarchy (ADR-0014).
- Model configuration uses strictly validated YAML (ADR-0012).
- Simulation time freezes for a consistent Decision Batch (ADR-0003).
- Simulator truth and the observations available to Decision Providers can differ (ADR-0016).
- This effort expands the original simulation specification, which excluded GUI and interactive 2D/3D visualization.

## Published specification

The decision frontier is empty. At the user's explicit `/to-spec` request, [spec.md](spec.md) was synthesized using the specification template and published to the local Markdown issue tracker with `Status: ready-for-agent`. It contains the agreed scope, extensive User Stories, implementation decisions and behavior-oriented testing decisions.

The proposed testing boundary is one public project/Episode session facade above the existing Application API, complemented by a small number of browser end-to-end workflows. This was presented for a focused expectation check during synthesis; no alternative was supplied at publication.

No frontend implementation was performed as part of the interview or specification publication.
