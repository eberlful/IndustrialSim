# 07: Prepare Episode inputs and the Production Plan

**What to build:** Prepare reproducible Episode inputs using setup controls and a Production Plan table, then save the intended configuration for execution.

**Blocked by:** 02: Edit Plant parameters and save YAML.

**Status:** ready-for-agent

- [x] Seed and simulation duration controls initialize from the loaded configuration and write validated values back into the project draft.
- [x] The Production Plan table edits release time, product variant, quantity and optional due date using existing domain semantics.
- [x] Input errors are associated with table rows or setup fields; invalid input prevents executable export and is available to the Episode-start validation gate.
- [x] The interface preserves existing episode end-condition semantics and does not silently reinterpret unrelated configuration.
- [x] Saved/exported configuration reloads with the chosen values and preserves unrelated Process Plans and other sections.
- [x] Undo/redo applies to setup and table changes; time values are handled without introducing floating-point simulation time.
- [x] Public-session checks verify valid/invalid inputs and the materialized Production Plan through existing application APIs; a browser workflow edits and reopens the setup.

## Comments

Implemented Episode setup and a Production Plan table backed by `ProjectSession.edit_episode`
and the loopback service. Setup changes preserve the end-condition type, start time and
warm-up time. Table edits preserve row metadata and explicit Production Units; existing
domain validation reports conflicts instead of replacing those units. Inputs and invalid
values share the authoritative draft, history, incomplete-draft persistence and executable
export gate. Large integer values cross the browser boundary as exact decimal text; time
parsing stays in the existing integer-nanosecond domain parser.

Verification uses the issue's public-session/application and browser seams. Session checks
cover reproducible materialization, complete semantic preservation, exact large times,
invalid setup/rows, incomplete-draft reload, undo/redo and explicit-unit conflicts. Browser
workflows cover setup and row edits, validation, row addition/removal, history and saved
configuration reopen. Python suite: 299 passed, 1 skipped. TypeScript build/typecheck and
Python typechecking of changed modules pass. Browser workflows run serially because the
service owns one shared ProjectSession.

Review: Standards found no violations. Spec review identified pending edits lost
between preparation forms, row removal changing omitted defaults, and history
changes leaving displayed pending values after clearing dirty tracking. All were
corrected: preparation forms retain independent pending state, omitted values
remain omitted, and explicit model/history transitions reset both forms. Browser
regressions cover each case. Final review has no outstanding Standards or Spec
findings; all 13 browser workflows pass.
