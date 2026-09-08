# Reviewed multi-architecture base digests. Refresh deliberately and rescan both images.
ARG RUST_IMAGE=rust:1.88.0-bookworm@sha256:af306cfa71d987911a781c37b59d7d67d934f49684058f96cf72079c3626bfe0
ARG RUNTIME_IMAGE=gcr.io/distroless/cc-debian12:nonroot@sha256:9dac0a79194e45a7da0158a9c6da57b217585af0786db3845d1f0ec1a0dd182f
ARG MAINTENANCE_IMAGE=python:3.13-alpine@sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a

FROM ${RUST_IMAGE} AS builder
WORKDIR /app
COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY sources.default.json ./
COPY src ./src
# Select the builder's installed compiler without installing development-only
# rustfmt/clippy components listed in rust-toolchain.toml.
RUN cargo +1.88.0 build --release --locked --bin cyberwatch-rs \
    && mkdir -p /runtime-data/data \
    && chown 10001:0 /runtime-data/data \
    && chmod 2770 /runtime-data/data

# Export only deployable application files, without source or a compiler cache.
# This is a dynamically linked Linux artifact; use its matching platform runtime.
FROM scratch AS artifacts
COPY --from=builder /app/target/release/cyberwatch-rs /cyberwatch-rs
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
