# services/ai — provider abstraction + grounding evaluation harness

The first two AI Systems Engineer deliverables, in the order the role file
mandates (`.claude/roles/AI_SYSTEMS_ENGINEER.md`, "First 90 Days" items 1–2):

1. **A pluggable text-generation abstraction** whose every output is
   structurally labeled AI-generated.
2. **The grounding evaluation harness — built FIRST, before any AI feature
   emits output.** Nothing in Headway's AI layer may ship a draft, flag, or
   explanation until the harness can prove it cites real records and
   fabricates no numbers. Ordering rationale: an ungrounded or unlabeled AI
   figure in an NTD context is a compliance defect, not a quality issue —
   so the system that *detects* grounding failures must exist before the
   first system that could *produce* one.

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

Adding an AI feature means adding fixtures for it; a grounding regression
anywhere fails CI, per the role's regression-gate requirement.

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

## Licenses (ADR-0001)

- This package: Apache-2.0 (core).
- Core runtime dependencies: **none** (stdlib only).
- `ollama` extra: `httpx` — BSD-3-Clause (OSI permissive).
- `test` extra: `pytest` — MIT (OSI permissive).
