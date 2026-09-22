# Reviewed multi-architecture base digests. Refresh deliberately and rescan both images.
# Docker Hub has not published the 1.98.1 Bookworm image yet. Use the verified
# 1.98.0 base and install 1.98.1 below; Bookworm matches the runtime glibc.
ARG RUST_IMAGE=rust:1.98.0-bookworm@sha256:82150a52ec202c1b14d7817e14516c392bb7f5cfebd88f1ed531cb37ebd39922
ARG RUNTIME_IMAGE=gcr.io/distroless/cc-debian12:nonroot@sha256:9dac0a79194e45a7da0158a9c6da57b217585af0786db3845d1f0ec1a0dd182f
ARG MAINTENANCE_IMAGE=python:3.13-alpine@sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a

FROM --platform=$BUILDPLATFORM ${RUST_IMAGE} AS builder
ARG BUILDPLATFORM
ARG TARGETPLATFORM
# Compile on the builder's CPU. Only the AMD64 -> ARM64 pair needs a cross
# compiler; its Bookworm sysroot matches the production runtime's glibc.
RUN set -eu; \
    case "$BUILDPLATFORM:$TARGETPLATFORM" in \
        linux/amd64:linux/amd64) rust_target=x86_64-unknown-linux-gnu ;; \
        linux/arm64:linux/arm64) rust_target=aarch64-unknown-linux-gnu ;; \
        linux/amd64:linux/arm64) \
            rust_target=aarch64-unknown-linux-gnu; \
            apt-get update; \
            apt-get install -y --no-install-recommends gcc-aarch64-linux-gnu libc6-dev-arm64-cross; \
            rm -rf /var/lib/apt/lists/* ;; \
        *) printf 'Unsupported builder/target pair: %s -> %s\n' "$BUILDPLATFORM" "$TARGETPLATFORM" >&2; exit 1 ;; \
    esac; \
    rustup toolchain install 1.98.1 --profile minimal --no-self-update --target "$rust_target"
WORKDIR /app
COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY sources.default.json ./
COPY src ./src
RUN set -eu; \
    case "$TARGETPLATFORM" in \
        linux/amd64) rust_target=x86_64-unknown-linux-gnu ;; \
        linux/arm64) rust_target=aarch64-unknown-linux-gnu ;; \
        *) exit 1 ;; \
    esac; \
    if [ "$BUILDPLATFORM" != "$TARGETPLATFORM" ]; then \
        export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc; \
        export CC_aarch64_unknown_linux_gnu=aarch64-linux-gnu-gcc; \
        export AR_aarch64_unknown_linux_gnu=aarch64-linux-gnu-ar; \
    fi; \
    cargo +1.98.1 build --release --locked --bin cyberwatch-rs --target "$rust_target"; \
    mkdir -p /out /runtime-data/data; \
    cp "target/$rust_target/release/cyberwatch-rs" /out/cyberwatch-rs; \
    chown 10001:0 /runtime-data/data; \
    chmod 2770 /runtime-data/data

# Export only deployable application files, without source or a compiler cache.
# This is a dynamically linked Linux artifact; use its matching platform runtime.
FROM scratch AS artifacts
COPY --from=builder /out/cyberwatch-rs /cyberwatch-rs
COPY web/index.html web/app.js web/styles.css /web/
COPY LICENSE /LICENSE

# Recovery tools are a separately built image and are never inherited by production.
# Build explicitly with: docker build --target maintenance -t cyberwatch-rs-maintenance:local .
FROM ${MAINTENANCE_IMAGE} AS maintenance
# Only the standard library and BusyBox tar are used; do not retain package-install tooling.
# Patch the base image's libuuid to the reviewed Alpine security release.
RUN apk add --no-cache libuuid=2.42.3-r1 \
    && python3 -c "import sqlite3" \
    && tar --help > /dev/null \
    && rm -rf /usr/local/lib/python3.13/ensurepip \
        /usr/local/lib/python3.13/site-packages/pip* \
        /usr/local/lib/python3.13/site-packages/setuptools* \
        /usr/local/lib/python3.13/site-packages/pkg_resources \
        /usr/local/bin/pip* \
    && mkdir -p /app/data \
    && chown 10001:0 /app/data \
    && chmod 2770 /app/data
WORKDIR /app
COPY tools/backup.py /app/tools/backup.py
USER 10001:0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "/app/tools/backup.py"]
CMD ["--help"]

# Last stage is the default Docker/Compose production image. No shell or package manager.
FROM ${RUNTIME_IMAGE} AS production
WORKDIR /app
COPY --from=builder /runtime-data/ /app/
COPY --from=artifacts /cyberwatch-rs /usr/local/bin/cyberwatch-rs
COPY --from=artifacts /web /app/web
COPY --from=artifacts /LICENSE /app/LICENSE
# Numeric non-root default; OpenShift may assign any non-root UID in group 0.
# An initially empty Docker named volume inherits /app/data's owner and setgid mode.
USER 10001:0
ENV BIND_ADDRESS=0.0.0.0:8080 DATABASE_PATH=/app/data/cyberwatch.db WEB_DIR=/app/web
EXPOSE 8080
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD ["/usr/local/bin/cyberwatch-rs", "--healthcheck"]
ENTRYPOINT ["/usr/local/bin/cyberwatch-rs"]
