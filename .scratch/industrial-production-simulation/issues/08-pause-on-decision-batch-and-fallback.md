# 08: Pause on a Decision Batch and recover by Fallback Policy

**What to build:** Pause an entire Episode at a consistent Buffer-related decision point, expose a bounded versioned observation and action schema to an in-process Decision Provider, and continue atomically with either valid Actions or a deterministic Fallback Policy.

**Blocked by:** 02: Move Production Units through typed material flow.

Status: ready-for-agent

- [ ] A Buffer threshold state transition emits a typed, versioned Decision Request with local detail, relevant neighborhood, aggregate metrics, and bounded history.
- [ ] Requests at the same pause point form one Decision Batch and observe the same immutable simulation state.
- [ ] No simulation time advances while waiting for the Decision Provider.
- [ ] Responses are jointly validated before any Action is applied, and valid Actions take effect atomically.
- [ ] Invalid, missing, or conflicting responses produce explicit diagnostics and invoke the configured Fallback Policy or configured Episode abort.
- [ ] A Trigger uses re-arm or hysteresis plus a deduplication key and cannot loop indefinitely on unchanged state.
- [ ] The contract carries Episode, Branch, Batch, Provider, model, and prompt provenance without exposing internal objects.
- [ ] End-to-end tests compare valid provider response, invalid response, conflict, Fallback, and abort outcomes.

