# 06: Edit advanced configuration in the YAML editor

**What to build:** Edit configuration outside specialized forms through validated YAML and switch between textual and visual editing without losing work.

**Blocked by:** 02: Edit Plant parameters and save YAML.

**Status:** ready-for-agent

- [x] The YAML editor exposes the entire loaded simulation configuration, including policies, triggers, Process Plans, telemetry and other advanced sections.
- [x] YAML and forms represent one authoritative draft; switching views or saving cannot silently replace newer edits with stale values.
- [x] Syntax errors and schema/domain errors are visible; invalid text remains editable and can be saved as an incomplete draft without executable export.
- [x] When text cannot be represented as a graph, the interface clearly retains the invalid draft and does not pretend an old graph reflects current text.
- [x] Correcting YAML updates the graph and forms; edits to advanced sections preserve unrelated configuration.
- [x] Undo/redo covers YAML changes and switches between editing views consistently.
- [x] Existing installed trusted-plugin approval is preserved; the editor does not introduce browser-uploaded executable behavior.
- [x] Public-session checks verify text/form consistency, invalid text preservation and validation; a browser workflow switches views, corrects YAML and reloads the exported configuration.

## Comments

Implemented a complete YAML editor backed by the project session. Pending text is submitted before switching to visual editing, saving a draft, saving executable YAML, downloading, or undoing. A starting-text comparison rejects stale YAML replacements. Invalid submitted text stays editable and saveable, with visual editing unavailable until validation succeeds; no old graph is presented as current. Text and form changes share history and semantic export/reload. Installed plugin validation and safe YAML loading remain authoritative.

Checks use the issue's public-session and browser seams. Session checks cover advanced edits, form consistency, semantic preservation, stale text, invalid syntax/schema/domain text, draft reload/history, plugin approval and layout restoration/topology changes. The browser workflow switches views, preserves form edits, saves/reopens invalid text, corrects schema errors, exercises undo/redo and reloads exported YAML. Full Python suite: 295 passed, 1 skipped. Focused advanced-YAML browser workflow passes. The first full browser run passed 9 existing workflows and exposed an import/selection timing issue in the new test; the test now awaits validation before selecting the graph. Frontend typecheck/build and Python typechecking of changed service/session modules pass.
