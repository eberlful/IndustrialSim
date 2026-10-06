# EXP-0005 implementation and evaluation contract

`study.json` fixes the full synthetic study; `smoke.json` exercises integration.
The existing study protocol remains the scientific source of truth. Its initial
two-interpreter setup was superseded by the user’s decision to run simulator and
ML on CPython 3.12 in the root `.venv`. HEPA is not part of this implementation.

## Observable and hidden state

All models use 30-second observations of the Material Flow Graph and connected
Machines and Workers. A 32-step history conditions a ten-step action rollout.
Machine temporal encoders share weights by declared operation type, never by
entity ID. Directed edges preserve parallel routes; capacity and node roles are
static inputs. Unknown types use the shared generic encoder.

Hidden Health State, carried Process State, Quality State and evaluation causes
live in separate `.labels.json` files. Training reads only episode feature files.
Observed Quality Findings supervise the quality head; a separate evaluation reads
hidden defects to report the quality proxy's error. Historical inspection records
in the observation are bounded to 32, while per-Station findings counts remain
cumulative. Missing readings have null values and an explicit mask.

The study Decision Request adds an optional versioned finite candidate catalog.
Legacy requests remain valid. Public provider/fallback batches remove exact health,
physical-state dictionaries and legacy aggregate metrics. The fixed compatibility
health value 0.5 is not used as a learned model feature. Only study observations
enter the world model. Candidate validity may use observable availability and
resource occupancy, but never latent quality or exact health.

## Synthetic mechanisms

Declared process transformations read a single prior Process State and apply

`new = clip(bias + sum(input_weight * prior_attribute) + health_weight * (1 - mean_health) + mean(mode_weight), minimum, maximum)`.

Welding writes `weld_stress`; pretreatment maps it to `surface_residue`; spray
maps residue to `coating_variation`; drying maps coating to `cure_deficit`.
Assembly adds weighted carried stress/cure deficit to its bounded defect
probability. Rework changes only coating variation and cure deficit, preserving
weld stress and residue. The coefficients are defined in the resolved study
configuration emitted with each episode; they have no real-plant calibration.

Synthetic machine sensors use:

- Temperature: `45 + 35 * busy * load + 20 * (1 - health)` degrees C.
- Vibration: `0.1 + 0.8 * (1 - health) + 0.15 * busy * load` mm/s.
- Current: `2 + 8 * busy * load` A; pressure: `4 + 2 * busy * load` bar.
- Load multipliers: eco 0.7, nominal 1.0, boost 1.3.
- Process measurement: mean carried attributes of Production Units currently at
  a Station, observed through noise rather than exported as exact latent state.

Gaussian measurement noise scales with signal magnitude; independent missingness
uses the configured probability. Semantic Philox addresses include entity,
channel and sample timestamp, giving identical sensor realizations in restored
branches without advancing production random streams.

Quality control changes sensitivity, sampling rate and release threshold. The
synthetic threshold shifts sensitivity by `0.5 - threshold` and false positives
by `0.1 * (0.5 - threshold)`, clamped to [0,1]. Unconfigured legacy inspections
retain their existing behavior. Reconfiguration changes the cycle-time multiplier
after an explicit 30-second unavailable interval; changed configurations cost 0.1,
worker assignments cost 0.02 and inspection settings cost 0.01. Unchanged
settings have zero cost. Qualified Workers may be bound to compatible Stations.

## Splits, actions and metrics

Full counts are 160 training, 40 validation, 40 regular test and 40 each of unseen
parameters, parallel topology and intervention combinations. These counts denote
independent root episodes. Every third root additionally creates two isolated
checkpoint continuations; siblings stay with their root in all splits and
bootstrap resamples. Resolved configurations, portable checkpoints, dataset
hashes, seeds and action evidence accompany the data.

Training episodes expose either boost or maximum inspection intensity, with the
concurrent combination reserved for the unknown-combination stratum. Parameter
tests increase carried-process sensitivity to machine health; topology tests add
a parallel body Station and its Machine and routes.

Action evidence distinguishes proposals, rejected batches, no-effect actions and
actual effects. Routing effects are timestamped at real dispatch, not when a
preference is recorded. Reordering includes relative permutation and head-deadline
features. The action encoder binds route decisions to source and destination
nodes; it excludes rejected and no-effect actions and preserves subinterval time
offsets. The planner evaluates intended candidates against a common deterministic
future policy retaining settings without further requested interventions.

All candidate batches must pass joint validation, including distinct vehicle
claims, consistent routing/dispatch choices and exclusion of transport targets
under simultaneous Reconfiguration. Strategic requests are withheld while a
Station is busy, blocked or has inbound reservations. Busy Machines receive a
no-effect action and a new request at an eligible idle boundary.

Normalization is fitted only on training observations. Zero-variance channels use
unit scale; nanosecond channels use one second as the fixed fallback scale. The
primary ten-step rollout MAE averages each channel over observed entries, then
averages channels within process and flow groups, weighting groups equally.
Windows are averaged within root episodes before comparison. Three training seeds
are averaged per root; a paired 10,000-sample bootstrap yields the 95% interval of
OPF minus JEPA error. Only a strictly negative upper endpoint supports an OPF
advantage, and smoke runs explicitly disable that conclusion.

Secondary evaluation reports quality proxy error, actual counterfactual action
ranking and injected-cause ranking by the first normalized prediction residual
above three standard deviations. Closed-loop evaluation uses the first three
independent roots of each test stratum for all frozen learned models and the
same public-observation heuristic. Five-day stability uses daily forecast anchors
and horizons up to 1,000 steps. Raw metrics, rewards, fallbacks and applied action
counts are reported independently.

See [ML runtime and commands](../../ml/README.md) for execution. A complete code
path or smoke result is not a completed GPU study.
