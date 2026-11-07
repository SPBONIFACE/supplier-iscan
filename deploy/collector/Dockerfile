# The OpenTelemetry Collector of Google Cloud (Ops Agent distribution), with this repository's
# configuration baked in. The configuration holds no secret. Pinned by digest; the tag is `latest`
# as of 6 Nov 2026 (the digest is what counts; change both together, reviewed by the owner).
FROM us-docker.pkg.dev/cloud-ops-agents-artifacts/google-cloud-opentelemetry-collector/otelcol-google:latest@sha256:871b9e716d8749660c0e5fd7e7fd5a21b04d412919ab86792528ee4cfa258f89

COPY config.yaml /etc/otelcol-google/config.yaml
