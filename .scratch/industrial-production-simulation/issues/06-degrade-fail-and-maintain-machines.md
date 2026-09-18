# 06: Degrade, fail, and maintain Machines

**What to build:** Make Machine condition operationally relevant by degrading Health State during use, changing cycle and quality behavior, producing scheduled and stochastic failures, and allowing resource-consuming inspection, maintenance, and repair.

**Blocked by:** 04: Allocate Machines and Workers atomically; 05: Route Process Plans and observe quality.

Status: ready-for-agent

- [ ] Machine configuration supports normalized Health State, operating modes, degradation rates, and optional named physical state variables.
- [ ] Use, idle time, inspection, maintenance, and repair change Health State through explicit configurable policies.
- [ ] Health State observably affects cycle time, defect probability, and failure hazard.
- [ ] Planned disruptions and stochastic time-to-failure and repair duration are reproducible for a fixed seed.
- [ ] Failure interruption respects the Operation's Resume, Restart, or Scrap semantics.
- [ ] Maintenance and repair consume simulation time and can require a qualified maintenance Worker.
- [ ] Maintenance restores Health State only to its configured level rather than silently returning every Machine to perfect condition.
- [ ] End-to-end tests cover preventive maintenance, unexpected failure, repair contention, quality impact, and deterministic replay.

