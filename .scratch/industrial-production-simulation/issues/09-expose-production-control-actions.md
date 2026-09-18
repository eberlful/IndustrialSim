# 09: Expose production-control Actions to a Decision Provider

**What to build:** Let an in-process Decision Provider make bounded tactical and strategic production decisions across routing, logistics, Machine operation, maintenance, and quality while preserving physical capacity, hidden information, and hard safety constraints.

**Blocked by:** 05: Route Process Plans and observe quality; 06: Degrade, fail, and maintain Machines; 07: Dispatch Transport Orders with shared vehicles; 08: Pause on a Decision Batch and recover by Fallback Policy.

Status: ready-for-agent

- [ ] Versioned Actions cover queue priority, admissible route, vehicle assignment, allowed Machine mode, and maintenance timing.
- [ ] Strategic Actions for reconfiguration, Worker reassignment, and quality-control changes are accepted only at explicit safe decision points and carry duration and cost.
- [ ] Quality Actions may adjust inspection intensity, sampling, and release thresholds only inside configured bounds.
- [ ] No Action can create capacity, access latent Quality State, alter immutable safety limits, or mutate arbitrary domain state.
- [ ] Simultaneous Actions with competing resource or control claims are rejected as a batch instead of being resolved by incidental order.
- [ ] The deterministic baseline uses FIFO, earliest due date as tie-breaker, nearest suitable vehicle, shortest admissible route, and Health-based preventive maintenance.
- [ ] Application-level comparisons demonstrate that baseline and custom providers can produce different valid outcomes from the same Episode input.

