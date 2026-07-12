# headway-api — FastAPI backend (metrics with lineage, DQ workflow, audited
# certification, machine ingest).
# BUILD FROM THE REPO ROOT (headway-api depends on the in-repo headway-calc):
#   docker build -f services/api/Dockerfile -t headway-api .
#
# Two stages, same shape as services/ingestion/Dockerfile: build tooling never
# reaches the runtime image; the runtime runs as a non-root user.
FROM python:3.13-slim AS build
WORKDIR /src
# headway-calc is a path dependency (not on PyPI) - install it first.
COPY services/calc /calc
RUN pip wheel --no-cache-dir --wheel-dir /wheels /calc
COPY services/api/pyproject.toml ./
COPY services/api/headway_api ./headway_api
# [ingest] pulls the MinIO + Kafka clients so the machine-ingest endpoint is
# live; without them it would 503 (see services/api/README.md).
RUN pip wheel --no-cache-dir --wheel-dir /wheels --find-links /wheels ".[ingest]"

FROM python:3.13-slim
RUN useradd --system --uid 65532 --user-group --home-dir /nonexistent \
      --shell /usr/sbin/nologin nonroot
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
