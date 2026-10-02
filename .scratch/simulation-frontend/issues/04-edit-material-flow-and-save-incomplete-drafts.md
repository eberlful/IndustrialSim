# 04: Extend material flow and save incomplete drafts

**What to build:** Add, connect and remove material-flow nodes and routes, keep incomplete work as a draft, and resolve visible reference errors before executable export.

**Blocked by:** 02: Edit Plant parameters and save YAML.

**Status:** ready-for-agent

- [x] Users can add the existing source, sink, Station and Buffer types, edit typed Ports and create directed routes, including valid parallel routes and cycles.
- [x] Deleting nodes, Ports or routes displays affected references rather than silently deleting unrelated policies, requirements or configuration sections.
- [x] Incomplete and invalid drafts are saved separately from executable configuration and can be reopened with their errors and edits intact.
- [x] Validation identifies affected graph elements and properties; a disconnected or otherwise invalid model cannot be exported as executable YAML.
- [x] Correcting the model restores executable export eligibility through the existing full validator.
- [x] Undo/redo covers structural edits, deleted references and their draft validation state.
- [x] Public-session checks cover compatible/incompatible connections, invalid-draft persistence, correction and semantic preservation.
- [x] A browser workflow adds an unconnected Station, saves/reopens it, sees the errors, completes the connection and exports a valid model.

## Comments

Implemented on 2026-10-02. The graph editing panel adds Source, Sink, Station and Buffer nodes and directed routes; selected-element forms edit typed Ports and route endpoints and remove nodes/routes. Parallel routes and cycles remain distinct. Structural editing applies to material_flow models; legacy station-only configuration is preserved without automatic conversion. New Stations start with a 1s Operation and body input/output Ports, and new Buffers start with capacity 1.

Deletion retains referencing routes, Process Plans, inspection/rework targets, Production Unit sources, policies and other configuration. Diagnostics identify affected elements and property paths. Routes with missing endpoints or Ports remain accessible through the route list. Undo/redo restores configuration, layout and validation state.

Use **Save draft** and **Open draft** for unfinished work. Versioned JSON documents under `.drafts/` preserve configuration YAML, layout and model association; errors are recalculated on reopen. Existing drafts require explicit overwrite. Executable YAML export/save still uses full simulation validation, supplemented by project completeness checks that require every graph node to lie on a source-to-sink path and identify retained references, including inspection rework Stations and Operations. Source YAML and unrelated sections remain unchanged.

Validation: **288 Python tests passed, 1 skipped**; all **6 browser workflows passed**; Python and TypeScript typechecking and whitespace checks passed. Six public-session tests cover incomplete-draft persistence/correction, all node types, compatible/incompatible Ports, route endpoints, parallel routes/cycles, deletion references, undo/redo, layout restoration, overwrite/path constraints, malformed documents, YAML aliases and semantic preservation. The browser acceptance workflow saves/reopens an unconnected Station, completes its connections, exports/reimports valid YAML, corrects incompatible Ports and inspects a route after its node is deleted.

Code review: Standards identified repeated atomic file writing, now consolidated while preserving exclusive creation and explicit overwrite. Spec identified a missing inspection rework reference check; it was reproduced, corrected and covered through deletion, draft reopening, export blocking and undo/redo. Rechecks found no remaining Standards or Spec findings.
