# 03: Persist graph layout and Area/Hall grouping

**What to build:** Arrange the Plant graph for readability, group it by Area and Hall, and reopen the same presentation without changing simulation behavior.

**Blocked by:** 01: Open a local project and display a Plant.

**Status:** ready-for-agent

- [x] Nodes can be moved and the graph can be grouped by the existing Area/Hall assignments while retaining all material-flow connections.
- [x] Graph positions and presentation grouping are stored in a separate layout document associated with the correct model identity.
- [x] Reopening the project restores its layout and grouping without adding unknown presentation fields to strict simulation YAML.
- [x] Layout edits support undo/redo and do not silently change organizational model assignments.
- [x] Moving nodes or changing display grouping leaves transport durations and all other simulation inputs unchanged.
- [x] Missing layout data is handled by a usable initial arrangement; an unrelated model does not inherit a stale layout silently.
- [x] Public-session checks verify separate persistence and unchanged configuration semantics; a browser workflow moves, groups and reopens graph elements.

## Implementation

Implemented on 2026-10-02. Display grouping uses existing Area/Hall assignments, including an Unassigned group, while keeping every material-flow route. Each drag (including multiple selected nodes) and grouping command participates in the project undo/redo history. Use **Save layout** to persist presentation without saving simulation YAML; **Save YAML** also associates the presentation with the saved model.

Versioned JSON documents live under the project's `.layouts/`, identified by a normalized project-relative model path (or import name) and a fingerprint of the validated configuration. Missing layout data starts with a readable arrangement; invalid layout documents produce a diagnostic and fall back to that arrangement. Replaced or unrelated models use independent layouts.

Validation: Python suite **282 passed, 1 skipped**; all **5 browser workflows passed**, including multiple-node move, Hall/Area grouping, undo/redo and reopening; Python and TypeScript typechecking passed. Public-session checks verify unchanged simulation configuration and source YAML, separate persistence, identity isolation, rejected coordinates, mixed edit history and save-as restoration.

Code review: Standards found no documented violations and one non-blocking duplication suggestion for atomic model/layout file writes. Spec review found path normalization and multiple-node drag persistence issues; both were corrected and covered by regression checks.
