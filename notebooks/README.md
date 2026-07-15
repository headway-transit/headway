# Example notebooks — the analyst surface, worked

Three executable examples of exploring a Headway deployment with
[`headway-client`](../clients/python/README.md). Each was **executed once
against a live Headway demo stack (2026-07-15) and committed with its real
outputs**, so GitHub renders them as documentation — some demo figures come
from simulated feeds and say so in their provenance columns, which is
rather the point.

> Explore and compute freely: nothing computed outside Headway's
> calculation library (services/calc) can ever become a reported figure.
> Only the calculation library writes computed.metric_values, and the
> walls are structural database CHECKs, not policy.

| Notebook | What it shows | Credential |
| --- | --- | --- |
| [01-ridership-exploration](01-ridership-exploration.ipynb) | UPT/VRM/VRH with coverage context, the missing-trip accounting, the simulated-data rule, and a full lineage walk from a certified figure to its 326 raw records | machine key (`read:metrics`) |
| [02-otp-headway-adherence](02-otp-headway-adherence.ipynb) | On-time performance and headway adherence — `category='ops'`, honestly labeled, with the derivation's refusal accounting surfaced | machine key (`read:metrics`) |
| [03-dq-triage](03-dq-triage.ipynb) | The data-quality queue: counts, severity × status, issue types, and the owning workflow | Headway account (session) |

## Running them yourself

You need a running Headway API (the Compose stack serves it on
`http://127.0.0.1:8000`) and credentials in the environment — notebooks
never contain credentials, in source or output:

```sh
pip install './clients/python[pandas]' jupyter

export HEADWAY_API_URL=http://127.0.0.1:8000
export HEADWAY_MACHINE_KEY=hwk_…       # notebooks 01 and 02 — see docs/analyst-access.md
export HEADWAY_USERNAME=…              # notebook 03 (session-only endpoints)
export HEADWAY_PASSWORD=…

jupyter lab notebooks/
```

How to get each credential — and everything else about analyst access,
including the read-only SQL role — is in
[docs/analyst-access.md](../docs/analyst-access.md).

## What CI checks about these — honestly

CI validates that every notebook is **well-formed nbformat** (it parses,
and its structure is schema-valid). CI does **not** re-execute them:
execution needs a live Headway stack with data in it, which CI does not
have. That means committed outputs can drift from current code until a
contributor re-runs the notebooks against a live stack — if you change the
client or the API surface these notebooks touch, re-run them and commit
the fresh outputs (and strip any credentials from your environment, never
into the file).
