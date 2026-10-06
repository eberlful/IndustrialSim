FROM rocm/pytorch:rocm7.2.1_ubuntu24.04_py3.12_pytorch_release_2.9.1

USER root

# The AMD image already includes Python 3.12, venv, Git, curl and certificates.
RUN /usr/bin/python3.12 -c 'import venv' \
    && curl --fail --silent --show-error --location https://astral.sh/uv/0.12.15/install.sh \
        --output /tmp/install-uv.sh \
    && env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh /tmp/install-uv.sh \
    && rm /tmp/install-uv.sh

COPY .devcontainer/gpu-entrypoint.sh /usr/local/bin/industrialsim-gpu-entrypoint
RUN chmod 755 /usr/local/bin/industrialsim-gpu-entrypoint

# Device group IDs are assigned by the host, so resolve them at container startup.
ENTRYPOINT ["/usr/local/bin/industrialsim-gpu-entrypoint"]
