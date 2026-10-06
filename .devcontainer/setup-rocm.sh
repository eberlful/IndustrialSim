#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# A host .venv can contain broken absolute interpreter paths in the container.
# Preserve a working project environment; recreate only an incompatible one.
if [[ -d .venv ]] && ! .venv/bin/python -c \
    'import sys; assert sys.version_info[:2] == (3, 12)' 2>/dev/null; then
    uv venv --clear --python /usr/bin/python3.12 .venv
fi

uv sync --locked --no-group ml-cpu --inexact --python /usr/bin/python3.12
uv pip install --python .venv/bin/python --requirements .devcontainer/requirements-rocm.txt
.venv/bin/python -c \
    'import torch; assert torch.version.hip, "Expected ROCm PyTorch"; print(f"PyTorch {torch.__version__}, HIP {torch.version.hip}")'

cat <<'MESSAGE'
ROCm is installed in the shared root .venv.
Use `uv sync --inexact` to retain the ROCm wheels (ml-cpu is disabled by the container).
Run `uv run industrialsim world-model preflight --output-dir runs/amd-preflight` to test the GPU.
MESSAGE
