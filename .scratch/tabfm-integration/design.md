# TabFM integration — design interview

## Agreed

- Noncommercial, nonproduction research experiment using TabFM.
- Predict consequences of actions and select actions through a Decision Provider.
- Initial intervention scope: Machine operating modes; five-minute horizon.
- Raw metric prediction is separate from the Industrial World Model state-trajectory contract. See [ADR-0021](../../docs/adr/0021-predict-action-outcomes-with-tabfm.md).

## Open decisions

- Delivery surface and whether the initial integration includes closed-loop control.
- Predicted metric vector and optimization through the Reward Policy.
- Execution budget and CPU versus GPU validation requirements.
- Context collection, continuation policy, feature contract, evaluation, fallback and reproducibility details after the above decisions are settled.

## Observed facts

- `BoundedBatchPlanner` accepts batched scores for complete, jointly valid Decision Batches.
- Existing study branches do not cover every candidate under one shared continuation policy; a dedicated export is needed for controlled candidate comparisons.
- This session has Python 3.12.14 in the shared root environment, no installed Torch/TabFM and no exposed AMD GPU devices. ROCm setup is documented but not verified here.

Implementation awaits the shared-understanding confirmation required by the invoked grilling skill. This file records interview decisions, not a completed specification.
