# 04: Allocate Machines and Workers atomically

**What to build:** Enable configured Operations to wait for, atomically acquire, use, and release Machines and qualified Workers while respecting shifts, pauses, and explicit interruption semantics.

**Blocked by:** 01: Run one Production Unit deterministically.

Status: ready-for-agent

- [ ] Machines, individual or pooled Workers, qualifications, capacities, shifts, and breaks are strictly configurable.
- [ ] An Operation starts only after all required resources can be acquired atomically; no partial reservation remains while waiting.
- [ ] Resource acquisition and release are deterministic for simultaneous contenders.
- [ ] Shift transitions follow an explicit handover rule and never silently interrupt work.
- [ ] Configurable interruption behavior demonstrably supports Resume, Restart, and Scrap.
- [ ] Application-level scenarios expose waiting time, utilization, completion, and interruption outcomes without inspecting implementation details.
- [ ] Generated resource-contention tests preserve capacity and ownership invariants and cannot create a partial-reservation Deadlock.

