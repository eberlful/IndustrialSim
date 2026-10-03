# 11: Distinguish simulator truth and available observations

**What to build:** Switch between clearly labeled simulator-truth and available-observation views to understand what the simulator knows and what the active Decision Provider receives.

**Blocked by:** 10: Answer Decision Batches manually.

**Status:** ready-for-agent

- [x] The interface clearly identifies which view is active and presents appropriate graph/detail/decision information for that view.
- [x] Available-observation data follows the actual selected provider/request contract; exact state already exposed by that contract is not falsely hidden.
- [x] Missing observations are marked unavailable instead of being populated from hidden simulator truth.
- [x] Service snapshots provide separate truth and observation representations without injecting additional truth into Decision Provider payloads.
- [x] Switching views changes presentation only and leaves provider input, action validation and Episode outcomes unchanged.
- [x] Outside a pending batch, only genuinely available observations are shown; absence of a current observation contract does not imply full-state access.
- [x] Public-session tests assert contract fidelity and unavailable values, including a contract that exposes exact state; a browser workflow switches views and inspects their labels and details.


## Comments

Implemented labeled Simulator truth and Available observations presentation views. Public EpisodeSession reads and service snapshots provide separate representations; available dynamic values derive only from the current Decision Request contracts. Static topology and resource identifiers are explicitly labeled workspace context. Exact version 1 Machine Health State remains available, Buffer occupants retain observed details without hidden Quality State, and Routing/Dispatch Production Units retain contracted fields. Partial observed inventories are distinguished from complete inventories. Complete request payloads remain inspectable with genuine nulls preserved, while missing projected values are marked unavailable. Resolving a batch clears its current observations; switching views sends no Episode command and does not alter provider payloads, validation, or outcomes.

Validation: 338 Python tests passed, 1 skipped; all 19 browser workflows passed. Python typechecking passed for all 39 source files; TypeScript typechecking and frontend build passed. Public-session regressions cover unavailable values, exact-state contracts, isolated reads, Buffer and Routing observations, service contract fidelity and unchanged Episode outcomes. Browser workflows verify labels, graph/detail changes, stable provider input, Routing unit details and unavailable observations after submission.

Code review against starting commit `00895b71ebff70ede6dd5afb1967022da7cf562d`: Standards: 0 documented violations, 1 optional minor capacity-format duplication; Spec: 0 remaining findings. The review correction projects Routing unit details rather than leaving them only in the raw request. Implementation commits: `816f0fa`, `9c378a2`. Existing unrelated workspace changes remain outside these commits.
