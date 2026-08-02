"""MEASUREMENT HARNESS (not a test — nothing here asserts a product claim).

Carried forward from the 2026-08-02 external review: ``MAX_RAW_RECORD_LABELS``
caps the LABEL list in an evidence bundle, but nothing caps the number of
figures a certification may cover, or the size of the per-figure lineage walk.
This file measures what that costs, so the decision (cap / paginate / refuse)
is made against numbers instead of intuition.

Run it explicitly — it is not part of the suite::

    cd services/api && python -m pytest tests/bench_evidence_cost.py -s -q

THE SHAPE BEING MEASURED IS THE PRODUCTION SHAPE
------------------------------------------------
``services/calc/headway_calc/persist.py`` writes one lineage edge per input
record, straight from ``computed.metric_values`` to ``raw.records``:

    for record_id in result.input_record_ids:
        cur.execute(_INSERT_LINEAGE_EDGE_SQL, ("computed.metric_values",
            metric_value_id, ..., "raw.records", record_id))

So a certified figure's lineage is a two-level STAR — a root and its raw
leaves — not a deep tree. (The ``canonical.*`` layer exists in
``lineage.edges``, written by the transform service, but nothing points from a
metric value INTO it, so a figure's walk never reaches it.) That rules out the
path-explosion failure mode a recursive ``UNION ALL`` invites: with leaves that
have no outgoing edges, the CTE returns exactly one row per edge.

What is left is plain multiplication, and it is not bounded anywhere:

    cost  ~  figures_in_certification  x  leaves_per_figure

Handoff 0035 measured ``leaves_per_figure`` live: 1,138 raw records under a
single VRH figure. The figure count is whatever a certifying official passed to
``POST /certifications`` — the request model asks only for ``min_length=1``.

AND THE SAME RECORDS ARE MATERIALIZED ONCE PER FIGURE
-----------------------------------------------------
The bundle de-duplicates ``all_leaf_ids`` before labelling them, so the LABEL
list is bounded twice over (dedup, then the 5,000 cap). The lineage trees are
not de-duplicated: VRM and VRH for the same month are computed from the same
frames, so the same 1,138 leaves are materialized as Pydantic nodes, serialized
into ``figures[].lineage``, listed AGAIN in ``figures[].raw_record_ids``, and
canonicalized a third time for ``bundle_sha256`` — once per figure. The
``distinct`` column below is what the cap sees; the ``leaf nodes`` column is
what the process actually builds.

WHAT THIS MEASURED, AND WHAT CHANGED
------------------------------------
Before ``MAX_LINEAGE_NODES`` existed (2026-08-02), with the 5,000-label cap
already in force::

    shape                                figs  leaf nodes  distinct   body   peak    time
    1 figure                                1       1,138     1,138   2.1MB   13MB   0.3s
    12 figures - one metric, a year        12      13,656    13,656  11.3MB   69MB   1.9s
    60 figures - 5 NTD metrics, a year     60      68,280    13,656  23.5MB  166MB   4.7s
    360 figures - a full annual filing    360     409,680    13,656  99.7MB  776MB  22.6s

The ``distinct`` column stops growing after row 2 — the label cap is doing its
job and it does not matter. After the bound, the last two rows cost the same as
each other (20 MB, 142 MB peak, 4.3 s): the response stopped tracking the figure
count. Re-run this file after any change to the bundle assembler or to
``lineage_tree``; the shape of the ladder is the regression signal, not any one
number, since absolute timings are machine-specific.
"""

from __future__ import annotations

import json
import time
import tracemalloc
from decimal import Decimal

from conftest import auth_header


# --------------------------------------------------------------- graph shapes


def build_graph(fake_db, *, months, figures_per_month, leaves_per_figure):
    """Seed a certification's worth of figures over the production shape.

    Figures within a month cite the SAME raw records — that is what makes VRM
    and VRH for June the same evidence counted twice, and it is the realistic
    case, not a pathological one.
    """
    metric_value_ids = []
    distinct = 0
    for month in range(months):
        record_ids = []
        for leaf in range(leaves_per_figure):
            record_id = f"{month:04d}{leaf:060d}"
            record_ids.append(record_id)
            fake_db.add_raw_record(
                record_id=record_id,
                source="gtfs_rt",
                connector="headway-gtfs-rt",
                payload_encoding="base64",
            )
        distinct += len(record_ids)
        for figure in range(figures_per_month):
            mv = fake_db.add_metric_value(
                metric="vrm", unit="miles", value=Decimal("12003.75")
            )
            metric_value_ids.append(mv["metric_value_id"])
            for record_id in record_ids:
                fake_db.add_edge(
                    "computed.metric_values", mv["metric_value_id"],
                    "vrm_v0", "0.1.0", "raw.records", record_id,
                )
    return metric_value_ids, distinct


def count_nodes(node) -> int:
    return 1 + sum(count_nodes(child) for child in node.get("inputs", ()))


# ------------------------------------------------------------------ the bench


#: 1,138 leaves per figure is the one number this project has actually
#: measured (handoff 0035, a live VRH figure). The ladder holds that fixed and
#: varies what is unbounded: how many figures one certification covers.
LEAVES = 1138

SHAPES = [
    # label,                            months, figures/month
    ("1 figure",                             1,   1),
    ("12 figures — one metric, a year",     12,   1),
    ("60 figures — 5 NTD metrics, a year",  12,   5),
    ("360 figures — a full annual filing",  12,  30),
]


def test_bench(client, fake_db, fake_store):
    print()
    header = (
        f"{'shape':<38} {'figs':>5} {'leaf nodes':>11} {'distinct':>9} "
        f"{'body MB':>8} {'peak MB':>8} {'seconds':>8}"
    )
    print(header)
    print("-" * len(header))
    for label, months, per_month in SHAPES:
        run_one(client, fake_db, fake_store, label, months, per_month)


def run_one(client, fake_db, fake_store, label, months, per_month):
    # A fresh graph per shape: reuse would let one shape's edges leak into the
    # next one's walk and quietly inflate it.
    fake_db.lineage_edges.clear()
    fake_db._lineage_by_output = None  # the double's stand-in for edges_output_idx
    fake_db.metric_values.clear()
    fake_db.raw_records.clear()

    metric_value_ids, distinct = build_graph(
        fake_db, months=months, figures_per_month=per_month,
        leaves_per_figure=LEAVES,
    )
    r = client.post(
        "/certifications",
        json={
            "metric_value_ids": metric_value_ids,
            "attestation": "I certify these figures are accurate.",
            "signer_full_name": "Cora Certifier",
            "signer_title": "Chief Executive Officer",
        },
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 201, r.text[:2000]
    certification_id = r.json()["certification_id"]

    tracemalloc.start()
    started = time.perf_counter()
    response = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "vera"),
    )
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert response.status_code == 200, response.text[:2000]

    body = response.content
    bundle = json.loads(body)
    leaf_nodes = sum(
        count_nodes(f["lineage"]) - 1 for f in bundle["figures"] if f["lineage"]
    )
    print(
        f"{label:<38} {len(metric_value_ids):>5} {leaf_nodes:>11,} "
        f"{distinct:>9,} {len(body) / 1e6:>8.2f} {peak / 1e6:>8.1f} "
        f"{elapsed:>8.2f}"
    )
