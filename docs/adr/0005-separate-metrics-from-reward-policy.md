# Separate simulation metrics from reward policy

The simulation reports an unweighted metric vector including good output, lead time, work in progress, scrap, downtime, lateness, and resource utilization. An experiment-specific Reward Policy may derive a scalar reward from normalized components with all weights visible in configuration, while safety and capacity limits remain hard constraints with separate violations or episode termination; this preserves evidence for different optimization strategies instead of embedding one set of trade-off weights in the model.
