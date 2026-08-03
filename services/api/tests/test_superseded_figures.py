"""Two answers to one question, and nothing to tell them apart.

``computed.metric_values`` is append-only on purpose: ``persist.py`` reuses a
row only when every field including the value matches, so recomputing a period
over more data writes a NEW row rather than mutating a figure someone may
already have read, exported, or linked to. That is right, and it is not the
whole story — it leaves two figures on record for one metric, one scope and one
period, with nothing saying which is current.

Found live on 2026-08-02 against a real feed: a partial day computed 263.57 VRM,
the same day recomputed an hour later gave 340.20. Both sat in the list. Both
were certifiable. The only reason the stale one was not signed is that whoever
was driving happened to sort by ``computed_at`` first.

An auditor discovers "you certified the old number". The signer does not. So
this refuses rather than warns.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from conftest import UTC, auth_header


def _figure(fake_db, *, metric="vrm", value="100.00", minutes=0, scope="agency"):
    """One figure, offset from a fixed base so 'newer' is unambiguous."""
    return fake_db.add_metric_value(
        metric=metric,
        unit="miles" if metric == "vrm" else "hours",
        value=Decimal(value),
        scope=scope,
        computed_at=dt.datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
        + dt.timedelta(minutes=minutes),
    )


def _certify(client, fake_db, ids):
    return client.post(
        "/certifications",
        json={
            "metric_value_ids": ids,
            "attestation": "I certify these figures are accurate.",
            "signer_full_name": "Cora Certifier",
            "signer_title": "Chief Executive Officer",
        },
        headers=auth_header(fake_db, "cora"),
    )


def test_a_recomputed_figure_cannot_be_certified(client, fake_db):
    """THE ONE. Signing a figure the installation has already replaced attests
    to a number Headway itself no longer stands behind."""
    stale = _figure(fake_db, value="263.57", minutes=0)
    fresh = _figure(fake_db, value="340.20", minutes=60)

    refused = _certify(client, fake_db, [stale["metric_value_id"]])
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert "recomputed since" in detail
    # The refusal has to be actionable: which figure, both numbers, and the id
    # of the one to use instead.
    assert "263.57" in detail and "340.20" in detail
    assert fresh["metric_value_id"] in detail
    assert "Nothing was signed" in detail

    # And the newer one certifies cleanly.
    assert _certify(client, fake_db, [fresh["metric_value_id"]]).status_code == 201


def test_the_newest_of_several_recomputes_is_the_one_named(client, fake_db):
    """Three runs over one period. The refusal must point at the LATEST, not
    at whichever row the join happened to reach first — being sent to a figure
    that is itself stale would be worse than no advice."""
    oldest = _figure(fake_db, value="100.00", minutes=0)
    _figure(fake_db, value="200.00", minutes=30)
    newest = _figure(fake_db, value="300.00", minutes=90)

    detail = _certify(client, fake_db, [oldest["metric_value_id"]]).json()["detail"]
    assert newest["metric_value_id"] in detail
    assert "300.00" in detail


def test_a_figure_with_no_newer_sibling_is_unaffected(client, fake_db):
    """The guard must be invisible until it bites. Every ordinary certification
    goes through a period with exactly one figure per metric."""
    vrm = _figure(fake_db, metric="vrm", value="340.20")
    vrh = _figure(fake_db, metric="vrh", value="13.83")
    assert _certify(
        client, fake_db, [vrm["metric_value_id"], vrh["metric_value_id"]]
    ).status_code == 201


def test_a_different_scope_is_a_different_question(client, fake_db):
    """agency and mode:bus are separate figures, not versions of each other.
    Treating them as supersessions would block a legitimate certification that
    covers both."""
    agency = _figure(fake_db, value="340.20", scope="agency", minutes=0)
    bus = _figure(fake_db, value="120.00", scope="mode:bus", minutes=60)
    assert _certify(
        client, fake_db, [agency["metric_value_id"], bus["metric_value_id"]]
    ).status_code == 201


def test_a_different_metric_is_a_different_question(client, fake_db):
    """VRH computed after VRM does not supersede it."""
    vrm = _figure(fake_db, metric="vrm", value="340.20", minutes=0)
    vrh = _figure(fake_db, metric="vrh", value="13.83", minutes=60)
    assert _certify(
        client, fake_db, [vrm["metric_value_id"], vrh["metric_value_id"]]
    ).status_code == 201


def test_a_stale_figure_anywhere_in_the_batch_refuses_the_whole_batch(
    client, fake_db
):
    """Certification is one deliberate act over a set. Signing the good half
    and reporting the bad half would leave a certificate whose coverage nobody
    intended."""
    stale = _figure(fake_db, metric="vrm", value="263.57", minutes=0)
    _figure(fake_db, metric="vrm", value="340.20", minutes=60)
    fine = _figure(fake_db, metric="vrh", value="13.83", minutes=0)

    refused = _certify(
        client, fake_db, [stale["metric_value_id"], fine["metric_value_id"]]
    )
    assert refused.status_code == 409
    assert fake_db.certifications == []


def test_the_list_puts_the_newest_figure_first(client, fake_db):
    """Deterministic ordering is the other half: a screen that shows both
    figures in scan order has no answer to 'which of these is current?'."""
    _figure(fake_db, value="263.57", minutes=0)
    fresh = _figure(fake_db, value="340.20", minutes=60)

    rows = client.get(
        "/metrics/values?metric=vrm", headers=auth_header(fake_db, "vera")
    ).json()
    assert [r["value"] for r in rows] == ["340.20", "263.57"]
    assert rows[0]["metric_value_id"] == fresh["metric_value_id"]
