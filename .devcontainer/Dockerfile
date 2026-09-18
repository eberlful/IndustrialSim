FROM mcr.microsoft.com/devcontainers/base:noble

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        python-is-python3 \
        python3.14 \
        python3.14-venv \
    && curl --fail --silent --show-error --location https://astral.sh/uv/install.sh \
        | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh \
    && rm -rf /var/lib/apt/lists/*

USER vscode
