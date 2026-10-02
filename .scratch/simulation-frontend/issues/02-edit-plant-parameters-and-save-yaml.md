# 02: Edit Plant parameters and save YAML

**What to build:** Select graph elements, edit common production and transport properties, and save or download valid simulation YAML without losing advanced configuration.

**Blocked by:** 01: Open a local project and display a Plant.

**Status:** ready-for-agent

- [x] Forms edit Hall assignment, applicable node capacities, Operation durations and explicit route transit time, capacity and existing transport requirements.
- [x] Edits update the same authoritative project draft used by validation and export; untouched configuration sections retain their meaning.
- [x] Undo and redo restore parameter changes and their validation state.
- [x] Schema/domain/reference errors identify the relevant properties; executable YAML export is rejected until the full configuration is valid.
- [x] Project-local saves and YAML downloads retain all valid semantic content; comments, formatting and field order need not be preserved.
- [x] An imported original is overwritten only by an explicit save action; reopen/reload reflects the saved values.
- [x] Public-session integration checks cover edit, undo/redo, validation and semantic roundtrip against a model containing advanced untouched sections.
- [x] A browser acceptance workflow selects an element, changes a capacity or duration, exports and reloads the model.


## Comments

Implemented common node, Operation and route parameter forms backed by the
public `ProjectSession` draft. Invalid parameter values remain correctable;
undo/redo restore values and validation state. YAML export and explicit
project-local saves reuse full configuration validation. Existing files require
explicit overwrite, and saves replace files atomically. Raw configuration is
patched without normalizing away untouched settings; editing an aliased Operation
detaches it from other Stations.

Verification: full Python suite **279 passed, 1 optional ML test skipped**;
`mypy src` and frontend TypeScript/build passed; all **4 Chromium workflows**
passed, including edit/undo/redo/validation/download/save/reload. Seven integration
checks cover semantic roundtrip with advanced sections, history, explicit saves,
transport/reference diagnostics, project-local path restrictions and YAML aliases. A browser regression also
checks exact large-integer transit times and capability names containing commas.


Review fixes: detached aliased graph containers so advanced parameter archives
remain untouched; property forms submit only changed fields; capabilities use
one name per line; large editable integers cross the JSON boundary as exact text.
Regression checks demonstrated each preservation case before its fix.

Final review against `67fd501`: **Standards: 0 outstanding findings; Spec: 0
outstanding findings**. Both reviewers confirmed the preservation fixes. Existing
unrelated workspace changes remain unstaged.
