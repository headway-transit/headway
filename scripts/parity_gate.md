# Parity gate (ADR-0005) — design stub for the next DevOps increment

Status: **stub / not implemented**. This documents the intended shape of the
CI parity gate so the next increment starts from a agreed sketch. Nothing
here runs yet.

## What it must prove

ADR-0005 rejects generating Helm from Compose (or vice versa): Compose is the
source of truth for the single-box small-agency target, Helm/K8s is a
first-class parallel target, and **parity is proven by test, not by a code
generator**. The gate therefore stands up *both* stacks from the *same image
digests* and runs the *identical* suite against each:

1. **Boot Compose** — `docker compose up` the full open dependency set
   (TimescaleDB, Kafka/KRaft, Apicurio, MinIO, Prometheus/Grafana) plus app
   services on the runner; wait for health.
2. **Boot Helm/k3s** — install k3s (or kind), `helm install` the charts with
   the same image digests; wait for readiness.
3. **Run the identical smoke + health + migration suite** against each stack
   through the same entry point (one test suite, parameterized only by
   endpoint): health checks green, schema migrations apply from zero, a
   golden ingest→transform→calc→API round trip returns the expected numbers
   with lineage intact, and "explain this number" resolves to raw records.
4. **Assert digest identity** — the images running under Compose and under
   k3s resolve to the same digests (same artifact, not same Dockerfile), per
   the never-build-a-second-artifact guardrail.
5. **Fail loudly** — any divergence (a service healthy on one stack and not
   the other, a config key consumed by only one target, a migration that
   works once) fails the gate with the diff, never a warning.

Both targets must resolve their configuration from the ONE documented config
schema (Helm `values` and Compose `env` map onto the same keys — ADR-0005).
A config key that exists for only one target is itself a gate failure.

## Where it will live

A `parity-gate` job (or separate workflow, since it is minutes-long) in
`.github/workflows/`, runnable locally as `scripts/parity_gate.sh` — same
suite, no CI-only steps, per the open/self-hostable guardrail. It requires
runners with Docker + enough memory for the Kafka JVM alongside both stacks
(the KRaft broker is the heaviest single-box tenant; pin its heap first, per
the role sizing note).

## Prerequisites before it can land

- Helm charts exist (`deploy/helm/` currently holds only a README).
- Published/buildable images for all app services (Compose `--profile app`).
- The smoke suite extracted so Compose CI, Helm CI, and operators run the
  same entry point.
- A runner profile with Docker available (this authoring environment has
  none — which is why this is a stub and not a workflow).
