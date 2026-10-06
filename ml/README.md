# Industrial World Model runtime

Simulator and ML workers use **one CPython 3.12 interpreter and the root `.venv`**.
Workers run in subprocesses with `sys.executable`; versioned JSON artifacts still
keep training inputs separate from simulator state. There is no `ml/.venv` or
`--ml-python` setting.

Initialize the shared environment inside the host or Devcontainer where you run:

```bash
uv sync
uv run pytest
```

The default `ml-cpu` dependency group installs a pinned CPU PyTorch wheel from
the official PyTorch CPU index. Plain `uv sync` and `uv run` include it, so the
preflight and CPU integration work without a separate installation step. A CPU
preflight reports GPU unavailability rather than a missing-PyTorch error.
Virtual environments contain host-specific paths; recreate the root `.venv` when
moving between host and container. Do not create a second ML environment.

For GPU execution, first run `uv sync --no-group ml-cpu`, then install a compatible
ROCm PyTorch wheel into the root
environment using the [official PyTorch installation selector](https://pytorch.org/get-started/locally/).
Run GPU commands with `uv run --no-group ml-cpu industrialsim ...` to prevent the
default CPU group from replacing the ROCm wheel. Use `uv sync --no-group ml-cpu
--inexact` when syncing again to retain the ROCm/TimesFM installations.
The AMD device must be supported by that ROCm release and exposed to the process,
including `/dev/kfd`. System driver changes and restarts are outside this project.
The `cuda` PyTorch device name also identifies AMD GPUs in ROCm builds.

## AMD GPU Devcontainer

The Devcontainer uses AMD's Ubuntu 24.04 image with ROCm 7.2.1 and PyTorch
2.9.1, and passes `/dev/kfd` and `/dev/dri` from the Linux host. Both device paths
must exist on the host before opening the container; the container cannot install
or replace the host kernel driver. The Radeon RX 9070 XT is supported by this
[AMD release](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/native_linux/native_linux_compatibility.html).

In VS Code, run **Dev Containers: Rebuild and Reopen in Container**. On creation,
`.devcontainer/setup-rocm.sh` installs the project and AMD's pinned Python 3.12
Torch/Triton wheels in the root `.venv`. An incompatible `.venv` is recreated.
The image's preinstalled ML environment is not used by project workers. The
startup entrypoint assigns `vscode` to the actual host device groups, including
when their numeric IDs differ from the image. Shared memory is set to 8 GiB.

The container sets `UV_NO_GROUP=ml-cpu`, so normal `uv run` commands preserve
the AMD build. Use **`uv sync --inexact`** when syncing manually: an exact sync
removes separately installed ROCm packages. To restore the GPU environment,
run `bash .devcontainer/setup-rocm.sh`.

After rebuilding, verify an actual model training step:

```bash
uv run industrialsim world-model preflight --output-dir runs/amd-preflight
```

Expect `status: ready`, a non-null `hip` field and your Radeon device name. Choose
a fresh output directory for each check. Training and inference use `--device
cuda` for AMD as well; the deterministic simulator and dataset generation run
on the CPU. TimesFM remains an additional installation for the full study below.

## Verification and study execution

The project preflight checks Python, PyTorch, available GPU memory, device access,
and a real model forward/backward/optimizer step:

```bash
uv run industrialsim world-model preflight --output-dir runs/exp0005-preflight
```

The full benchmark also needs the official `timesfm3` implementation and
`huggingface_hub` in the shared environment. Install from a recorded checkout of the
[official TimesFM repository](https://github.com/google-research/timesfm);
verify `from timesfm3 import TimesFM3Evaluator, ModelConfig` before starting the
GPU run. The worker resolves the weights to an immutable Hub revision and records
hashes of downloaded weight files. Its checkpoint cache lives under the run
directory. TimesFM 3 downloaded weights are used only for the noncommercial
research benchmark, as specified in EXP-0005.

CPU integration, with deliberately small episodes and model width:

```bash
uv run industrialsim world-model generate --study-config experiments/world_model/smoke.json --output-dir runs/exp0005-smoke-data
uv run industrialsim world-model train --dataset runs/exp0005-smoke-data --output-dir runs/exp0005-smoke-models --device cpu --smoke
uv run industrialsim world-model evaluate --dataset runs/exp0005-smoke-data --models runs/exp0005-smoke-models --output-dir runs/exp0005-smoke-evaluation --device cpu
uv run industrialsim world-model control --dataset runs/exp0005-smoke-data --models runs/exp0005-smoke-models --output-dir runs/exp0005-smoke-control --device cpu --smoke
```

Full study after a successful GPU preflight:

```bash
uv run --no-group ml-cpu industrialsim world-model run --study-config experiments/world_model/study.json --output-dir runs/exp0005-full
```

Existing run directories are never overwritten. Commands return exit status 2
for unavailable GPU or incomplete study stages, and 1 for errors. A CPU smoke run
does not establish model quality or an OPF advantage. Without actual TimesFM,
closed-loop and five-day evaluations, a full study remains incomplete.

Training uses seeds 11/22/33, 128-dimensional latents, two graph layers, two local
epochs and ten global epochs. Each global epoch fits readouts with frozen dynamics
and selects checkpoints only by validation ten-step balanced MAE. OPF adds 0.01
times mean cross-factor covariance loss to the common JEPA loss; its four factors
have no asserted causal meanings. SIGReg uses Gaussian characteristic-function
matching over fixed sketched directions. The supervised graph baseline has the
same parameter count.

The pilot symmetrically reduces width/batch size to 64/8 or 32/4 when necessary.
Training has a seven-hour limit, reserving the remainder of the eight-hour GPU
budget for TimesFM and downstream evaluation. A budget failure leaves artifacts
incomplete. CPU checks have no claim to reproduce GPU numerical results.
