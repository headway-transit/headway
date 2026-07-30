# Handoff: platform → backend+frontend — The raw-record inspector (the end of the trail)

## Context
First-agency UAT, the sharpest finding of the week (ITS manager, 2026-07-30). He did
exactly what the platform is built for — walked a VRH figure back through its lineage to
the source — and hit a wall of hashes labeled *"raw source record as received — the end
of the trail."* His verdict: **"It doesn't really provide any data to validate or
verify."**

He is right. The content address genuinely proves tamper-evidence (change one byte and
the id no longer matches), but proof you cannot *inspect* asks for trust at the exact
step where this platform must never ask for trust. The chain of custody currently ends
with a sealed evidence bag that has **no label and no window**.

## Design (binding)

1. **`GET /raw/records/{record_id}` — the label.** Serves the record's metadata:
   source, connector + version, fetched_at, content_type, payload encoding, byte size,
   parse_status, the object-store key, and the id itself. Authz: viewer+ (same surface
   as the lineage walk it completes); audited. Never invents a field — absent is absent.
2. **Integrity, as an action rather than a claim.** `POST /raw/records/{id}/verify`
   re-reads the stored bytes, re-computes the SHA-256, and reports **match / mismatch**
   with both digests shown. This turns "content-addressed and immutable" from marketing
   into a button the auditor presses. A mismatch is a loud, unmissable alarm (and would
   itself be a finding — record how it surfaces).
3. **`GET /raw/records/{id}/payload` — the window.** Bounded (documented cap, honest
   truncation note) preview:
   - **GTFS-Realtime protobuf** → decoded, human-readable: feed timestamp, entity count,
     and the first N vehicles/trip updates with their real values. This is the moment a
     steward sees *their own bus, at that minute, at those coordinates* as the origin of
     a number.
   - **CSV / text** → first N rows verbatim (headerless positional files rendered with
     the registered adapter's column names where a label is known — never guessed).
   - **Anything else / undecodable** → say so plainly, offer the raw download.
   - Plus `GET .../download` for the exact bytes.
   Sensitivity: this is agency operational data; the classification doc governs
   (docs/data-classification.md). Paratransit payloads carry rider coordinates —
   **preview must respect the same withholding the analyst role enforces**; decide and
   record the rule (recommendation: gate DR-source payloads to the roles allowed
   coordinates, refuse in plain words otherwise).
4. **Frontend: the lineage leaf becomes readable.** In the receipt/lineage view, each
   raw-record leaf shows the label inline (source · connector · fetched_at · size ·
   parse_status), a **Verify integrity** action with its verdict rendered plainly, and an
   expandable payload preview. The hash stays visible — demoted to the footnote it should
   always have been. Keep the text-view/graph-view parity that exists today.
5. **Honest scope:** read-only; no re-parsing, no editing, no re-ingestion; no
   full-payload rendering of multi-MB files in the browser (bounded preview + download);
   the decoder set is GTFS-RT + CSV/text in v0 — everything else states its type and
   offers bytes.

## Outputs
API tests (authz matrix, verify match AND mismatch paths, bounded preview, unknown type,
missing object, sensitivity refusal) + suite green; openapi regenerated; web tests + axe
+ contrast green; live verification against REAL records on this box (a GTFS-RT frame
decoded to actual vehicles; a vendor CSV previewed; one integrity verify shown passing)
with screenshots; evidence appended here. No commits — the orchestrator integrates.

## Open Questions
- Object-store outage behavior (metadata without payload — degrade honestly).
- Whether verify should be offered in bulk (a "verify this figure's whole evidence
  chain" action) — likely the natural v1 and a superb demo.
- Decoders for the remaining contract types (TIDES, DR, telematics envelopes).

## Outputs — evidence
(appended by the implementing agent)
