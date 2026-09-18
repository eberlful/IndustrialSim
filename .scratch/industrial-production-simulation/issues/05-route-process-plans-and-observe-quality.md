# 05: Route Process Plans and observe quality

**What to build:** Materialize a Production Plan with two product variants, route each Production Unit through its Process Plan, and model hidden quality changes that become actionable only through imperfect Quality Findings, including a complete rework and Scrap path.

**Blocked by:** 02: Move Production Units through typed material flow; 04: Allocate Machines and Workers atomically.

Status: ready-for-agent

- [ ] A Production Plan declares release times, variants, quantities, and optional due dates and is fully materialized before the Episode starts.
- [ ] Production Unit identities are deterministic and stable across repeated Episodes and Counterfactual preparation.
- [ ] Each variant has a declarative Process Plan with required Operations and compatible Station alternatives.
- [ ] A deterministic Routing Policy selects a compatible Station and route without rewriting Process Plan history.
- [ ] Operations can alter latent Quality State without exposing hidden truth to normal observations.
- [ ] Inspection produces Quality Findings with configurable sensitivity and false-positive behavior under deterministic randomness.
- [ ] A Quality Finding can send a Production Unit through an explicit rework cycle or to Scrap while preserving history and location invariants.
- [ ] End-to-end tests demonstrate both variants, undetected defects, detected defects, rework, and Scrap.

