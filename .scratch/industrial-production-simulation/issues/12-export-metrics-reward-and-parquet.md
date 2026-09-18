# 12: Export metrics, Reward, and Parquet telemetry

**What to build:** Give analysts raw production metrics, a transparent configurable scalar Reward, runtime-selectable snapshots, and efficient closed Parquet fragments without making optional telemetry part of the simulation's correctness path.

**Blocked by:** 11: Audit each run losslessly.

Status: ready-for-agent

- [ ] The run reports raw good output, lead time, WIP, Scrap, downtime, lateness, and resource-utilization metrics without embedded objective weights.
- [ ] A configured Reward Policy normalizes selected components and exposes every weight in the resolved experiment configuration.
- [ ] Hard-constraint violations remain separate from scalar Reward and can independently terminate an Episode.
- [ ] State telemetry can be enabled or disabled at runtime and sampled at configured intervals and domain events.
- [ ] Optional telemetry obeys an explicit backpressure policy that may thin samples but cannot drop critical audit records.
- [ ] Metrics and training records are written in bounded batches to closed, rotating Parquet fragments with stable schemas.
- [ ] Parquet content is demonstrably derived from canonical run data, and incomplete fragments are not advertised as complete datasets.
- [ ] Tests verify metrics, Warm-up exclusion, Reward calculation, sampling, thinning, fragment rotation, and schema stability through observable artifacts.

