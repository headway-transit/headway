# headway-api — FastAPI backend (metrics with lineage, DQ workflow, audited
# certification, machine ingest).
# BUILD FROM THE REPO ROOT (headway-api depends on the in-repo headway-calc):
#   docker build -f services/api/Dockerfile -t headway-api .
#
# Two stages, same shape as services/ingestion/Dockerfile: build tooling never
# reaches the runtime image; the runtime runs as a non-root user.
FROM python:3.14-slim AS build
WORKDIR /src
# headway-calc and headway-transform are path dependencies (not on PyPI) -
# build their wheels first. transform is here because POST /admin/block-labels
# reuses headway_transform.block_labels, so the upload screen and
# tools/block-labels/derive.py run THE SAME derivation.
COPY services/calc /calc
COPY services/transform /transform
RUN pip wheel --no-cache-dir --wheel-dir /wheels /calc /transform
COPY services/api/pyproject.toml ./
COPY services/api/headway_api ./headway_api
# [ingest] pulls the MinIO + Kafka clients so the machine-ingest endpoint is
# live; without them it would 503 (see services/api/README.md).
RUN pip wheel --no-cache-dir --wheel-dir /wheels --find-links /wheels ".[ingest]"

FROM python:3.14-slim
RUN useradd --system --uid 65532 --user-group --home-dir /nonexistent \
      --shell /usr/sbin/nologin nonroot
# The resolution spec ships INSIDE the image, for the same reason the wire
# contracts ship inside transform's: the block-label upload parses trip names
# with the agency's declared rules, and a spec that could drift from the code
# reading it is a spec nobody can trust.
#
# The wire contracts ship too, and they are NOT optional. headway_transform's
# adapter modules load their JSON schemas at IMPORT time — spec.py, then
# resolution.py, then envelope.py all `open()` a contract at module scope. So
# `from headway_transform.adapters.resolution import ...` raises
# FileNotFoundError before a single line of block-label code runs. Shipping
# the spec without the contracts produced exactly that: a 500 on the first
# real upload, on a machine, after every test passed. The unit tests import
# from a source checkout where the default repo-root contracts/ path
# resolves; only the container has neither.
#
# Same five files and the same env var as services/transform/Dockerfile, so
# the two images cannot validate against different contract versions.
RUN install -d -m 0755 /app/adapters/tripspark/streets /app/contracts
COPY --chmod=644 adapters/tripspark/streets/resolution.v0.yaml \
     /app/adapters/tripspark/streets/resolution.v0.yaml
COPY --chmod=644 contracts/raw-record-envelope.v0.schema.json \
     contracts/adapter-mapping.v0.schema.json \
     contracts/demand-response-trip.v0.schema.json \
     contracts/adapter-resolution.v0.schema.json \
     contracts/fleet-telematics.v0.schema.json /app/contracts/
ENV HEADWAY_CONTRACTS_DIR=/app/contracts

COPY --from=build /wheels /tmp/wheels
RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels \
      "headway-api[ingest]" \
    && rm -rf /tmp/wheels
USER nonroot
EXPOSE 8000
# Config comes from the environment at runtime (HEADWAY_SESSION_SECRET,
# HEADWAY_DATABASE_URL, S3_*/KAFKA_BROKERS); the app fails loudly at startup
# when the session secret is missing — never a baked-in default.
ENTRYPOINT ["uvicorn", "headway_api.app:create_app", "--factory", \
            "--host", "0.0.0.0", "--port", "8000"]
