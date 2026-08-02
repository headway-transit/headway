# Handoff: platform → backend+frontend — the auditor's evidence surface

## Context

**Wave F (handoff 0046) shipped the `auditor` role and no place to be one.**

The role itself is modelled well and enforced in three independent places: it
sits off `ROLE_RANK` entirely (`authz.py:55-64`), so rank arithmetic fails it by
construction; every unsafe HTTP method is refused at the single authentication
choke point (`auth.py:262-276`); and content sensitivity evaluates an auditor at
*viewer* breadth (`authz.py:71-73`), so rider-location withholding is not waived
for them. That is the correct shape and this wave does not touch it.

The withholding lives in `raw_payloads.classify` + `RESTRICTED_MINIMUM_ROLE`
(`data_steward`). It is **not** migration 0028 — that is the parallel SQL-layer
rule for the `headway_readonly` analyst role, and conflating the two hides the
fact that they are maintained separately.

What is missing is everything above the API. An auditor signs in and lands on
`/today` — the operations control room, a queue of things to do, built for
people who act. To a reader it is noise. Nothing in `Layout.tsx` knows the role
exists; the auditor is simply a viewer with some links hidden.

Three symptoms, each verified in the code rather than inferred:

1. **`copy.roleLabels` has no `auditor` entry** (`web/src/copy.ts:47-52`). The
   header falls through to the raw enum string. It renders acceptably *by
   accident*, because the other labels happen to be lowercase too.
2. **The nav hides a surface the API grants.** `/calc-runs` is gated on
   `canComputeFigures` (`Layout.tsx:366`), which is false for an auditor — but
   `GET /calc/runs` is `require_authenticated`, and which calc version produced
   a figure is *evidence*. The comment there already says the gate is "UX only,
   never security"; for this role the UX guess is wrong.
3. **The verify contradiction** — below. It is severe enough to set the shape of
   the whole wave.

## The verify contradiction

Four facts, each confirmed directly:

- `POST /raw/records/{record_id}/verify` (`raw_records.py:461`) re-reads the
  stored bytes, recomputes SHA-256, and returns the verdict with both digests.
- An auditor is refused every non-safe method at the choke point, and
  `services/api/tests/test_auditor_role.py:267-268` **pins that 403 as intended
  behaviour**. This is not an oversight anyone forgot to test; it is tested in.
- The withholding refusal tells the caller, verbatim (`raw_payloads.py:170-171`):
  *"You can still see this record's label and prove its bytes are unaltered —
  only the contents are withheld."*
- `RawRecordInspector.tsx:217` renders the Verify control as
  `disabled={verifying}`. It is never disabled by role.

Put together: **the product tells an auditor they can prove the bytes are
unaltered, renders an enabled button to do it, and refuses when they press it**
— with a message explaining that their account cannot change things. For the one
role whose entire job is verification. And because the block is by HTTP method,
it applies to *every* record, not only withheld ones.

This is the exact failure mode the shared constraints exist to prevent: a
surface that promises something the system will not do.

### Decision (binding): an auditor may verify

The write guard exists so that **an auditor's account cannot alter what the
auditor is reviewing**. Verification alters nothing under review. Its two side
effects — an audit event, and a blocking DQ issue when the digest does not match
— are both *records of an observation*, never modifications of the thing
observed. An auditor discovering that stored bytes no longer match their content
address is the single most valuable finding this system can produce. Suppressing
it to preserve a tidy method-based invariant trades the product's thesis for an
implementation detail.

**Implementation is a narrow route allowlist, not a loosening of the method
rule.** Not "auditors may POST" — "this route, for this reason, written down."
The allowlist ships with a test asserting it has exactly one member, so the next
person who wants to add to it has to argue for it in a review rather than append
a string. `test_auditor_role.py:267` is rewritten to assert the new behaviour
and to keep asserting the 403 on every other write.

## Design (binding)

### 1. The auditor does not land in the control room

`/today` answers "what should I do now?". An auditor's question is "what was
filed, and does it hold up?". Those are different surfaces, and giving the
second person the first one is how a reviewer learns to distrust a tool.

The auditor lands on **`/review`**. It is not a second dashboard and it carries
no queue, no counts-that-want-clearing, and no call to action.

### 2. Start from the certification, not the metric

Auditors work top-down from the filed thing. `/review` is a worklist of
**certifications**, because a certification is the object being audited: it is
the moment a named person put their name to a set of figures.

Each row states period, signer, signed-at, figure count, and the
server-computed verification verdict. The existing `CertificateView` already
renders a signature block, an on-load verdict and re-verification
(`/certifications/{id}/verify` is a GET, so it is already open to auditors);
this wave routes *into* it rather than rebuilding it.

### 3. A withheld field is drawn as withheld, never as absent

Rider-location withholding is not waived for auditors, on purpose, and that
decision stands.
But an auditor who sees a blank where a coordinate should be will record it as
**missing data** — a false finding against an agency that did nothing wrong.

The API already returns the reason verbatim in `SensitivityBlock.refusal`. The
surface renders it. This is the house rule about gaps drawn as gaps, applied to
the one reader most likely to be harmed by the difference between "withheld" and
"absent".

### 4. The auditor is told they are on the record

`audit_trail_read` already logs every sweep of `/audit/events`, recording the
filters and the row count but never the rows (`audit_trail.py:164-188`). The
surface says so once, plainly, on entry.

Not a warning. It protects the auditor as much as the agency: their diligence is
on the record too, and a reviewer who learns later that they were logged without
being told will trust nothing else on the screen.

### 5. Evidence leaves the building

An auditor takes things away. The wave ships an **evidence bundle** for a
certification: the certification and its signed bytes, each covered figure
verbatim, each figure's receipt, the lineage walk, the raw-record labels with
their digests, and a manifest listing every hash in the bundle.

It never contains withheld payloads. **The manifest lists what was withheld and
why**, so the bundle is honest about its own gaps rather than quietly shorter
than it looks.

### 6. What an auditor still cannot see is stated, not hidden

Account roster, SSO configuration and machine keys are `certifying_official`
only. Handoff 0046 deferred auditor access deliberately, and 0045's
separation-of-duties view may reopen it.

Until it does, `/review` **says** those are out of scope for this role. A reader
who cannot see the roster should learn that from the product, not from a 403
they hit by guessing at a URL.

## Design-system work folded in

Three items from the 2026-08-02 design review, kept because they are correct and
cheap, and because a data-dense reviewing surface is exactly where they pay:

1. **Numeric columns right-align.** `td.figure` already carried
   `tabular-nums`, which equalises digit *width* — only half the job. Left
   aligned, `987.25` and `12,003.75` still land their decimal points in
   different columns, and reading a column of VRM *down* the page is precisely
   the comparison an auditor makes. `th.figure` follows its column.
2. **`check:contrast` runs in CI.** It shipped 2026-07-09 and had never once
   been executed by CI (`git log -S` on `.github/workflows/ci.yml` returns
   nothing). Every token pair in `styles.css` carries its contrast ratio in a
   comment; those comments were a claim with nothing behind them. It passes
   today — that is why wiring it now is cheap.
3. **`auditor` joins `copy.roleLabels`.** Relying on the enum-string fallback
   is how a role ends up displayed as `certifying_official` to a user.

## Outputs

- `POST /raw/records/{id}/verify` reachable by `auditor` via an explicit,
  single-entry route allowlist; every other write still refused.
- `/review` — the auditor's landing surface, and the role's redirect target.
- Certification → figure → receipt → lineage → raw record, walkable end to end
  as a reviewer, with withholding rendered as withholding.
- The evidence bundle with its hash manifest.
- `auditor` labelled in `copy.roleLabels`; `/calc-runs` linked for readers.
- Right-aligned numeric columns; `check:contrast` in CI.
- Tests: the allowlist has exactly one member; an auditor reaches `/review` and
  not `/today`; a withheld field renders its reason; the bundle manifest names
  every withheld item.

## Open Questions

1. **DECIDED 2026-08-02 — the bundle is labels-and-digests only.** It does not
   re-read bytes. A raw record's id *is* the SHA-256 of its bytes, so the
   manifest carries every digest without touching the broker or the object
   store. Re-reading a 1,138-leaf VRH figure needs the batched read that
   handoff 0035 left unbuilt, and past the retention window most leaves return
   `410 not_retained` regardless. Per-record verification stays the auditor's
   own action, which as of this wave actually works.
2. **DECIDED 2026-08-02 — a mismatch raises a blocking DQ issue whoever finds
   it.** Including an auditor. It is the correct outcome regardless of who
   pressed the button, and routing an auditor's finding somewhere quieter
   would hide it from the people who have to act on it. Recorded because it is
   the one place this wave lets an auditor's action surface in an agency
   workflow — deliberately, not incidentally.
3. **One auditor role or two?** 0045 left this open (internal self-audit vs
   external reviewer). `/review` is designed for the external reader; confirm
   before an agency's own staff are given the role as a convenience.
4. **Retention makes some evidence unverifiable.** 99.9% of raw records are
   realtime frames on the Kafka envelope, and anything past the broker window
   returns `410 not_retained` (handoff 0035). An auditor will meet this. The
   surface must explain it as a retention boundary, not as a failed check.
