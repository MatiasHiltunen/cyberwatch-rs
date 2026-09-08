FROM node:24-bookworm-slim AS node
FROM rust:1.88.0-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential ca-certificates clang cmake curl git libclang-dev \
       pkg-config python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 vscode \
    && useradd --uid 1000 --gid vscode --create-home --shell /bin/bash vscode

# Only Node's executable is needed for the browser syntax check.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY rust-toolchain.toml /tmp/cyberwatch-toolchain/rust-toolchain.toml
COPY tools/requirements-dev.txt /tmp/cyberwatch-requirements-dev.txt
WORKDIR /tmp/cyberwatch-toolchain
RUN rustup show active-toolchain \
    && rustup component add rustfmt clippy rust-src \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/cyberwatch-requirements-dev.txt \
    && mv /usr/local/cargo /home/vscode/.cargo \
    && mv /usr/local/rustup /home/vscode/.rustup \
    && mkdir -p /home/vscode/cyberwatch-target \
    && chown -R vscode:vscode /home/vscode \
    && rm -rf /tmp/cyberwatch-toolchain /tmp/cyberwatch-requirements-dev.txt

# Homes under /home/vscode remain writable after Dev Containers remaps the UID.
ENV CARGO_HOME=/home/vscode/.cargo \
    RUSTUP_HOME=/home/vscode/.rustup \
    PATH=/opt/venv/bin:/home/vscode/.cargo/bin:${PATH}
USER vscode
WORKDIR /home/vscode
