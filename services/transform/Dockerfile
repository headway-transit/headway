# headway-transform — Kafka -> canonical.* normalizer with lineage + DQ
# quarantine. BUILD CONTEXT IS THE REPO ROOT (the envelope validator loads
# contracts/raw-record-envelope.v0.schema.json — the checked-in contract file
# IS the contract, ADR-0006):
#   docker build -f services/transform/Dockerfile -t headway-transform .
#
# Two stages, same shape as services/ingestion/Dockerfile; runtime is
# non-root. python-snappy>=0.7 is a pure-Python shim over cramjam (ships
# manylinux wheels), so no C toolchain / libsnappy-dev is needed; if that
# ever regresses, add the apt build deps HERE in the build stage only.
FROM python:3.13-slim AS build
WORKDIR /src
COPY services/transform/pyproject.toml ./
COPY services/transform/headway_transform ./headway_transform
# kafka: kafka-python-ng + snappy codec (the Go producer compresses with
# snappy by default); db: psycopg; s3: MinIO client for object_ref payloads.
RUN pip wheel --no-cache-dir --wheel-dir /wheels ".[kafka,db,s3]"

FROM python:3.13-slim
RUN useradd --system --uid 65532 --user-group --home-dir /nonexistent \
      --shell /usr/sbin/nologin nonroot
COPY --from=build /wheels /tmp/wheels
RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels \
      "headway-transform[kafka,db,s3]" \
    && rm -rf /tmp/wheels
# The wire contract ships inside the image so the validator cannot drift
# from what this build was certified against.
COPY contracts/raw-record-envelope.v0.schema.json /app/contracts/
ENV HEADWAY_CONTRACTS_DIR=/app/contracts
USER nonroot
# Runtime config via env: KAFKA_BROKERS (required), PG*/DATABASE_URL
# (required), S3_* (optional — without it object_ref payloads quarantine as
# dq.issues). See headway_transform/__main__.py.
ENTRYPOINT ["python", "-m", "headway_transform"]
