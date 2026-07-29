# Handoff: platform → backend+frontend — The DQ queue at scale

## Context
Measured during handoff 0029's live verification, on the real queue: **`GET /dq/issues`
returns 97,782 rows ≈ 900 MB in 18 seconds and freezes the browser tab.** 86% of that
payload is `source_record_ids` — provenance arrays nobody reads in a list view. This is
pre-existing (not 0029's doing) and it is now the binding constraint on the most-used
operational screen in the product.

It has not bitten the first partner agency yet only because their queue is young. It
will. A steward's queue is the screen they live in, and a screen that cannot be opened
is a screen that teaches people the product is slow.

Related, already shipped: `/dq/issues/counts` is fast (33–49 ms, handoff 0023) and
`GET /dq/issues/{id}` exists (handoff 0026), so the pieces a paginated list needs are
in place.

## Design (binding)

1. **Bound the list, always.** `GET /dq/issues` gains pagination — `limit` (default a
   sane page, documented; hard maximum enforced) and a stable ordering with either
   `offset` or a keyset cursor (your call; keyset is better on a growing queue, and the
   ordering must be deterministic and total so pages cannot drop or duplicate rows).
   An unbounded request must become impossible, not merely discouraged. Response states
   the total (the counts endpoint is already fast) and whether more remain.
2. **Provenance leaves the list.** `source_record_ids` is not returned by the list
   endpoint; it is served by the existing per-issue detail endpoint. State the change in
   the endpoint docstring and README: the ids are not gone, they moved to where they are
   actually used. Check every existing consumer (web, client library, notebooks,
   exports) before removing, and fix any that read it from the list.
3. **The UI paginates honestly.** `/dq` loads a page at a time — the house pattern for
   caps applies: what is shown, what remains, and no pretending the visible rows are the
   whole queue. Filters and the summary cards keep working against the server counts,
   which already reflect the WHOLE queue rather than the loaded page (that distinction
   must be visible in the copy — a filtered count that silently meant "of what's
   loaded" would be exactly the kind of quiet lie this project refuses).
4. **Measure it, before and after,** against the live queue: payload bytes, server time,
   time to interactive on `/dq`. Record all three in the evidence. The target is a page
   that opens in well under a second on the real 97k-issue queue.
5. **Honest scope:** no change to what a finding *says* (0029 just shipped that), no
   change to severity/status semantics, no new filters, no infinite-scroll cleverness if
   simple paging serves — this is about making the queue usable at real volume.

## Outputs
API tests incl. pagination edges (first/last page, beyond-the-end, cap enforcement,
stable ordering under concurrent inserts if feasible) + full suite green; openapi
regenerated; every consumer of the removed list field checked and fixed; web tests +
axe + contrast green; before/after measurements against the live queue; evidence
appended here. No commits — the orchestrator integrates.

## Open Questions
- Server-side sort options (severity, age) once paging exists.
- Whether the exports/workbook paths need the same treatment at volume.

## Outputs — evidence
(appended by the implementing agent)
