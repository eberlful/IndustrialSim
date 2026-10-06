# EXP-0005 implementation verification — 2026-10-01

The initial checks below used Python 3.14 for simulation and Python 3.12.14
with PyTorch 2.9.1+cpu for ML. The project subsequently migrated to one Python
3.12 environment at the user’s request; these recorded initial artifacts remain historical. The implementation is verified on CPU. The full scientific
GPU study has not run and no OPF superiority conclusion is available.

## Checks

- Simulator and integration suite: 263 passed, 1 skipped. The skipped tests need
  PyTorch and are run separately in the ML environment.
- ML suite: 6 passed, including short causal action training, persistence,
  changing graph sizes and temporal alignment of shared training windows.
- Mypy: all 34 simulator source files pass.
- Four existing reference-plant tests now resolve their YAML relative to the
  repository, replacing a fixed path to an obsolete `/workspaces` checkout.

## Reproducible CPU artifacts

The `smoke.json` configuration generated eight independent roots and six related
checkpoint branches. All eight Decision Action types have recorded actual effects.
JEPA, OPF and supervised models trained with seeds 11/22/33. Evaluation and
closed-loop CLI stages completed using the portable artifact boundary.

- `runs/exp0005-cpu/dataset/manifest.json`: split identities, seeds, feature,
  label and resolved configuration hashes, source hashes and runtime provenance.
- `runs/exp0005-cpu/models/training.json`: nine trained models, settings,
  validation selection, timings and checkpoint hashes.
- `runs/exp0005-cpu/evaluation/report.md` and `evaluation.json`: forecast metrics,
  per-root paired differences and bootstrap mechanics. These are explicitly
  integration results; `opf_superior` is unset.
- `runs/exp0005-cpu/control/control.json`: small closed-loop integration,
  counterfactual ranking, rewards, raw metrics and fallback counts.

The small CPU control run intentionally omits cause-injection and five-day
stability experiments. Official TimesFM remains pending. Large artifacts remain
under ignored `runs/`; regenerate them with the commands in `ml/README.md`.

## GPU acceptance outstanding

The project preflight found no accessible GPU: the installed PyTorch build is CPU
only, ROCm is unavailable and `/dev/kfd` is absent. The full-run CLI returned exit
status 2 and preserved `runs/world-model-verified-full/study.json` as incomplete.
It did not start or claim a GPU benchmark.

After the host exposes a supported GPU and a compatible ROCm PyTorch environment,
rerun the project preflight and full study commands in `ml/README.md`. Full
acceptance requires the configured 360 independent roots plus checkpoint
branches, all nine GPU-trained models, official TimesFM weights/inference,
counterfactual and cause ranking, closed-loop comparisons, and five simulated
days of stability evaluation within the shared memory/time budget. System driver
installation and reboot were outside the authorized implementation scope.

## Shared runtime migration

The user superseded the two-interpreter requirement with a single CPython 3.12
runtime. The root `.venv` now runs simulation, training and inference workers;
workers launch with `sys.executable`. `ml/.venv`, its separate requirements file
and the `--ml-python` option have been removed. Project metadata, the lockfile,
runtime checks and the Devcontainer use Python 3.12.

Post-migration verification: all 270 tests pass together in the root environment,
and all 34 source files pass mypy. The nine-model CPU training smoke run completed
under `runs/exp0005-single-runtime-models`. Closed-loop smoke results are in
`runs/exp0005-single-runtime-control`. The preflight used that same interpreter;
GPU access is still unavailable. Inline YAML detection was corrected for Python
3.12, whose path checks can raise errors for overlong filenames.
