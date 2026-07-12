# headway-ai — anomaly runner JOB image (not a long-running service): one
# scan per invocation — read computed history, insert ai.anomaly_flags,
# print the run report as JSON, exit. Schedule it (cron/systemd timer/CI);
# it never computes a reported number (see services/ai/README.md).
# Build: docker build -t headway-ai services/ai
#
# Two stages, same shape as services/ingestion/Dockerfile; runtime is
# non-root. Core headway-ai is stdlib-only; [persist] adds psycopg for this
# CLI process boundary only.
FROM python:3.14-slim AS build
WORKDIR /src
COPY pyproject.toml ./
COPY headway_ai ./headway_ai
RUN pip wheel --no-cache-dir --wheel-dir /wheels ".[persist]"

FROM python:3.14-slim
RUN useradd --system --uid 65532 --user-group --home-dir /nonexistent \
      --shell /usr/sbin/nologin nonroot
COPY --from=build /wheels /tmp/wheels
RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels \
      "headway-ai[persist]" \
    && rm -rf /tmp/wheels
USER nonroot
# Connection via standard libpq PG* env vars (PGHOST, PGDATABASE, PGUSER,
# PGPASSWORD); the runner refuses to start without them — never a guessed
# connection. Threshold overrides pass through as container args, e.g.:
#   docker run ... headway-ai --swing-threshold 0.25
ENTRYPOINT ["python", "-m", "headway_ai.anomaly_runner"]
