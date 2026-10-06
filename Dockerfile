FROM node:22-bookworm-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM rocm/pytorch:rocm7.2.1_ubuntu24.04_py3.12_pytorch_release_2.9.1
USER root
ARG APP_UID=1000
ARG APP_GID=1000
RUN apt-get update \
    && apt-get install --yes --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && (getent group "${APP_GID}" || groupadd --gid "${APP_GID}" industrialsim) \
    && useradd --non-unique --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /bin/bash industrialsim
RUN curl --fail --silent --show-error --location https://astral.sh/uv/0.12.15/install.sh \
        --output /tmp/install-uv.sh \
    && env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh /tmp/install-uv.sh \
    && rm /tmp/install-uv.sh

WORKDIR /app
ENV UV_PYTHON=/usr/bin/python3.12 \
    UV_NO_GROUP=ml-cpu \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    XDG_CACHE_HOME=/home/industrialsim/.cache \
    PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY .devcontainer/requirements-rocm.txt /tmp/requirements-rocm.txt
RUN uv sync --locked --no-default-groups --extra frontend \
    && uv pip install --python /app/.venv/bin/python --requirements /tmp/requirements-rocm.txt \
    && /app/.venv/bin/python -c 'import torch; assert torch.version.hip, "Expected ROCm PyTorch"'
COPY frontend/package.json ./frontend/package.json
COPY --from=frontend-build /frontend/dist/ ./frontend/dist/
COPY experiments/world_model/ ./experiments/world_model/
COPY ml/ ./ml/
COPY docker/entrypoint.sh /usr/local/bin/industrialsim-entrypoint
RUN chmod 755 /usr/local/bin/industrialsim-entrypoint
WORKDIR /project
EXPOSE 8765
ENTRYPOINT ["/usr/local/bin/industrialsim-entrypoint"]
CMD ["industrialsim-ui", "/project", "--host", "0.0.0.0", "--skip-build", "--no-browser"]
