# 13: Inspect saved Episode results and Deadlock causes

**What to build:** Reopen saved Episode results, inspect raw metrics and decision diagnostics, and understand Deadlock causes against the configuration that produced them.

**Blocked by:** 08: Run a Baseline Episode independently of the browser.

**Status:** ready-for-agent

- [x] The project lists saved Episode outputs and opens completed results after browser or service restart without rerunning simulation.
- [x] Result views display available final metrics, terminal status and decision diagnostics through existing summary/audit semantics.
- [x] Deadlocked Episodes expose existing diagnostic causes and affected entities; normal completion is clearly distinguished from Deadlock and incomplete execution.
- [x] The result graph/details use the original resolved Episode configuration rather than the current mutable project draft.
- [x] Missing or incomplete outputs are represented truthfully and never reinitialized or overwritten merely by inspection.
- [x] Presentation uses labeled statuses and symbols as well as color; unsupported or absent diagnostics are identified without invented explanations.
- [x] Public-session checks inspect normal, Deadlocked and incomplete outputs and confirm byte-preservation of earlier artifacts.
- [x] A browser workflow reopens saved results after restart, examines metrics and navigates a Deadlock diagnosis.


## Comments

Implemented read-only project-local saved Episode listing and inspection using existing artifact inspection and summary semantics. Inspection does not construct an engine, restore execution, or write artifacts. The browser displays final raw metrics, terminal status, decision diagnostics, recorded Deadlock reasons, wait relationships, capacities and ownership. Affected entities and graph selections open configuration details including routes and vehicles. The result graph and configuration details come only from the original resolved configuration; dynamic final occupancy is explicitly unavailable. Missing, corrupt and incomplete output is labeled without invented diagnostics.

Validation: full Python suite passed (347 tests, 1 skipped), with both saved-result tests subsequently passing including an additional corrupt-output case. All 21 browser workflows passed; the restart/results workflow passed again after the review fix. TypeScript typechecking, frontend build and Python typechecking of the changed service/reader passed. Public inspection and browser restart checks confirm byte-preservation for completed, Deadlocked and incomplete artifacts.

Code review against starting commit `a10fd58`: Standards: 0 findings; Spec: 0 remaining findings. The review found route and vehicle selections omitted from saved entity lookup; fixed and verified with a browser assertion that failed before the fix and passed afterwards. Unrelated existing workspace changes are excluded from these implementation commits.
