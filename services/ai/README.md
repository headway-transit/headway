# services/ai — provider abstraction, grounding harness, anomaly detection

The first three AI Systems Engineer deliverables, in the order the role file
mandates (`.claude/roles/AI_SYSTEMS_ENGINEER.md`, "First 90 Days" items 1–3):

1. **A pluggable text-generation abstraction** whose every output is
   structurally labeled AI-generated.
2. **The grounding evaluation harness — built FIRST, before any AI feature
   emits output.** Nothing in Headway's AI layer may ship a draft, flag, or
   explanation until the harness can prove it cites real records and
   fabricates no numbers. Ordering rationale: an ungrounded or unlabeled AI
   figure in an NTD context is a compliance defect, not a quality issue —
   so the system that *detects* grounding failures must exist before the
   first system that could *produce* one.
3. **Explainable anomaly detection over computed metrics** — the first
   user-facing AI feature, built ON the harness: deterministic detectors
   flag suspicious `computed.metric_values` history as `info`/`warning`
   `dq.issues` rows for a human, with grounding-gated AI explanations.

The HARD BOUNDARY applies throughout: this package never computes,
estimates, or adjusts a reported number. It generates prose (behind the
harness) and *verifies* prose. All numbers it compares come from the
caller — ultimately `computed.metric_values`, written only by the calc
library.

## Layout

- `headway_ai/provider.py` — `Provider` protocol, `StubProvider`
  (deterministic, template-based, no network — what every test uses), and
  `OllamaProvider` (adapter for a local OpenAI-compatible endpoint;
  optional `ollama` extra). **No hosted/proprietary provider exists in this
  increment**; per the role file one may only ever be an optional
  off-critical-path adapter. Every `generate()` returns a `LabeledOutput`
  whose `ai_generated` field is frozen, non-constructor, and always `True`
  — presenting unlabeled AI text is structurally impossible.
- `headway_ai/claims.py` — the output contract features must emit: `Claim`
  (text + `cited_record_kind`/`cited_record_id` + declared string
  `numeric_values`) inside a `GroundedDraft` (≥1 claim enforced at
  construction, provider metadata, always-`True` `ai_generated`). Free
  prose without citations is not representable.
- `headway_ai/grounding.py` — the harness core. Three deterministic checks
  over a `GroundedDraft`, an injected DB-API connection, and a
  caller-supplied allowed-numbers set.
- `headway_ai/regression.py` — the CI gate over `eval_fixtures/*.json`.
- `eval_fixtures/` — the fixture suite the gate runs (see below).
- `headway_ai/anomaly.py` — deterministic, explainable detectors over
  injected metric-history rows (pure functions; Decimal arithmetic on the
  value STRINGS; no clock/random/network). Three detectors: period-over-
  period swing (warning), coverage drop (warning), calc-version change
  (info — figures not comparable across versions, both rows cited). Each
  finding is a candidate `dq.issues` row whose plain-language description
  cites the compared `metric_value_id`s; severity `blocking` is
  structurally unrepresentable — **detectors flag, they never correct,
  and a flag never blocks; a human decides.**
- `headway_ai/anomaly_explain.py` — grounding-gated explanations: the
  provider (StubProvider default — deterministic template path) phrases
  the explanation, the draft cites the compared `computed.metric_values`
  rows, and `grounding.evaluate` must PASS before emission. A failing
  draft is DROPPED with a loud ERROR log and returned in a `rejected`
  list; the finding still stands without prose — **flags never depend on
  prose, and an ungrounded sentence is never surfaced.**
- `headway_ai/anomaly_runner.py` — loads history via an injected
  connection, runs detectors + the explanation gate, inserts the
  `dq.issues` rows (`anomaly_metric_swing` / `anomaly_coverage_drop` /
  `anomaly_calc_version_change`; `source_record_ids` empty — the compared
  computed rows are cited in the description and their lineage to raw
  records already exists in `lineage.edges`), returns a frozen
  `AnomalyRunReport`. CLI: `python -m headway_ai.anomaly_runner` using
  the standard libpq `PG*` env vars (guarded psycopg import via the
  `persist` extra, mirroring `headway_calc._cli`).

## What each check proves

- **`check_citations(conn, draft)`** — every `(cited_record_kind,
  cited_record_id)` resolves to a real row per the handoff-0001 schema
  contract (`raw.records`, `canonical.routes`, `canonical.trips`,
  `computed.metric_values`, `lineage.edges`; `canonical.vehicle_positions`
  resolves via its `lineage.edges` node because its natural key is
  composite — consistent with ADR-0007: citations resolve in the explicit
  lineage graph). One parameterized SELECT per claim; the id is always a
  bound parameter; an **unknown kind is a failure**, never a skip. Proves:
  no dangling or invented reference survives.
- **`check_fabrication(draft, allowed_numbers, record_count_whitelist=…)`**
  — every numeric token extracted from claim text (decimals and thousands
  separators handled; `12,794.92` ≡ `12794.92`) plus every declared
  `Claim.numeric_values` entry must appear in the allowed set (strings from
  `computed.metric_values.value` and caller-supplied detail fields) or the
  explicit record-count whitelist. Comparison is by normalized `Decimal`
  string — floats never enter. Proves: any number absent from the
  calculation library's computed results fails the draft.
  Token policy (deliberate, tested in `tests/test_numeric_extraction.py`):
  dotted triples like `0.4.0` are **version tokens**, not numeric claims
  (calc/transform versions legitimately appear in grounded prose and are
  covered by citations); digits glued to words/hyphens (`abc123`,
  `route-66`) are identifier fragments; an extractable-but-unparseable
  digit run counts as fabricated (fail loudly).
- **`evaluate(conn, draft, allowed_numbers)`** — frozen `EvalReport` with
  per-claim detail, `citation_resolution_rate`, and
  `fabricated_number_count`. **Pass requires resolution == 1.0 AND zero
  fabrications** — computed from exact integer counts.

## How CI gates on it

`.github/workflows/ci.yml` runs `ai` in the `python-services` matrix
(unit tests via the `[test]` extra) and then executes

```
python3 -m headway_ai.regression
```

which loads every fixture in `eval_fixtures/`, builds a fake DB-API
connection from the fixture's record universe, runs `evaluate`, and
compares against the fixture's expected verdict. Any mismatch — or an
empty fixture directory — exits nonzero and **fails the build**. The
shipped fixtures pin both directions of the gate:

| fixture | expects | pins |
| --- | --- | --- |
| `01_grounded_pass.json` | PASS | a fully grounded draft stays green |
| `02_dangling_citation_fail.json` | FAIL | a nonexistent record id is caught |
| `03_fabricated_number_fail.json` | FAIL | "13,000.00 miles" when only 12794.92 is allowed |
| `04_wrong_record_kind_fail.json` | FAIL | correct number, real id, wrong cited kind |
| `05_anomaly_swing_explanation_pass.json` | PASS | a real anomaly explanation (generated by the actual `anomaly_explain` code path) stays grounded |
| `06_anomaly_fabricated_explanation_fail.json` | FAIL | an explanation stating a DERIVED swing percentage (42.6 — in no cited row) is caught |

Adding an AI feature means adding fixtures for it; a grounding regression
anywhere fails CI, per the role's regression-gate requirement.

## Anomaly detection (first user-facing AI feature)

Scans the `computed.metric_values` history the calc library wrote and files
`info`/`warning` `dq.issues` flags for a human — nothing more. The runner
writes ONLY dq rows; it never touches a metric value, and detector
comparisons (used solely to decide whether to flag) never surface as
figures. Where an explanation passes the grounding gate it is appended to
the dq description under an explicit "AI-generated explanation …
requires human review" label; where it fails the gate, the flag ships
without prose.

**Thresholds are ENGINEERING DEFAULTS** — `swing_threshold 0.25` and
`coverage_drop_threshold 0.05` are explicit Decimal inputs, recorded in
every run report and overridable on the CLI; they are not FTA numbers and
not statistical baselines. The statistical detectors the role file calls
for (robust z-scores / MAD, seasonal decomposition) are the next increment
once **>30 days of computed history** exist; per-agency configuration is
planned. Full provenance per detector: `DETECTOR_THRESHOLDS.md`.

Run against a live database (read history, insert flags):

```
PGHOST=... PGDATABASE=... PGUSER=... PGPASSWORD=... \
  python3 -m headway_ai.anomaly_runner [--swing-threshold 0.25] [--coverage-drop-threshold 0.05]
```

(requires `pip install 'headway-ai[persist]'`; every non-CLI path takes an
injected connection and stays stdlib-only).

## Running locally

```
python3 -m pip install -e "services/ai[test]"
cd services/ai
python3 -m pytest tests/ -q
python3 -m headway_ai.regression
```

No test or gate path touches the network or a live database: the harness
takes an *injected* connection, and tests/CI inject fakes.

## Verification status (honest)

- Unit suite and regression gate: green locally (output in the delivering
  session) — all checks exercised against fake connections.
- **`OllamaProvider` is NOT live-verified**: no model runtime exists in the
  authoring environment. The request shape follows Ollama's
  OpenAI-compatible `/v1/chat/completions` contract; live verification
  against a running Ollama (and fixing the default open-weight model per
  the role file's "verify before fixing the default" instruction) is an
  explicit next-increment item.
- **Real-database citation checks are exercised only via fakes** until an
  integration increment adds a TimescaleDB-backed job (the pattern exists:
  `tests/integration/` + the `integration-postgres` CI job).
- **The anomaly runner has NOT been executed against a live database** in
  the authoring environment (constraint: never touch the live stack from a
  work session). All SQL shapes are pinned by fake-connection tests; a live
  `python3 -m headway_ai.anomaly_runner` run against the Compose stack is
  an explicit next-increment verification item.

## Licenses (ADR-0001)

- This package: Apache-2.0 (core).
- Core runtime dependencies: **none** (stdlib only).
- `ollama` extra: `httpx` — BSD-3-Clause (OSI permissive).
- `test` extra: `pytest` — MIT (OSI permissive).
