# 05: Edit Machines and Worker assignments

**What to build:** Use resource forms to change Machines, Workers and their Operation requirements or assignments, then save a valid Plant model.

**Blocked by:** 02: Edit Plant parameters and save YAML.

**Status:** ready-for-agent

- [x] The properties interface exposes existing Machine and Worker definitions and allows their editing through the current schemas.
- [x] Users can change Operation resource requirements and assignments with valid references to Machines and Workers.
- [x] Forms do not invent Hall ownership or geometric fields absent from the resource schemas.
- [x] Invalid references, capacities or qualification requirements are reported against affected resources or Operations, and executable export remains gated by full validation.
- [x] Resource edits participate in draft undo/redo, explicit saving and semantic YAML export/reload.
- [x] Unedited resource policies, availability, health and other advanced settings are preserved semantically.
- [x] Public-session checks exercise valid and invalid resource edits and preservation; a browser workflow edits a requirement, corrects an error and reloads the saved model.

## Comments

Implemented resource selection and Machine name/capacity and Worker name/kind/capacity/qualification forms, plus structured Operation Machine and Worker requirements. Resource edits use the authoritative project draft, validation, undo/redo, draft persistence, and explicit YAML saving. Advanced resource settings remain untouched.

Validation uses the issue's public ProjectSession and browser seams. Session checks cover valid/invalid edits, semantic preservation and reload, legacy Stations and YAML aliases. Browser checks edit resources and requirements, correct errors, exercise undo/redo, reload saved YAML and preserve exact large integers.

Code review: Standards found no documented-rule violations and suggested sharing exact-integer conversion; this was applied. Spec identified blank numeric inputs being confused with omitted defaults; corrected and verified by a browser regression. Full Python suite: 291 passed, 1 skipped. Full browser suite: 8 passed before review; all 4 affected browser workflows passed after the review fixes, including the added blank-input regression. Frontend typecheck/build and Python typechecking for the changed service/session modules pass.
