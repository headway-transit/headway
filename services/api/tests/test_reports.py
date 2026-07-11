"""GET /reports/mr20 — the calc library's MR-20 package served VERBATIM.

The endpoint is a passthrough: headway_calc.mr20.build_mr20_package is
monkeypatched to return a canned package, and the response bytes must be
byte-identical to that package's json.dumps serialization — no reshaping,
no re-keying, no float trip. Plus the plain-language 422 on a bad month and
the auth gate (any signed-in role; no anonymous access).
"""

import json

from conftest import auth_header

from headway_api.routers import reports

# A canned package echoing the real generator's shape (handoff 0009): header,
# NOT-REPORTABLE banner, caveats, per-mode cells with provenance, a missing
# cell with an explicit reason, and a fleet block. Key order is deliberately
# non-alphabetical so byte-identity proves order-preserving passthrough.
CANNED_PACKAGE = {
    "form": "MR-20",
    "generator": {"name": "headway_calc.mr20", "version": "0.1.0"},
    "month": "2026-07",
    "period_start": "2026-07-01",
    "period_end": "2026-08-01",
    "reportable": False,
    "banner": "NOT REPORTABLE — preview package only.",
    "caveats": [{"id": "D2", "status": "open", "text": "Rail passenger-car measure."}],
    "data_points": ["upt", "vrh", "vrm", "voms"],
    "modes": {
        "bus": {
            "upt": {
                "value": "12345",
                "unit": "unlinked_passenger_trips",
                "metric_value_id": "mv-0001",
                "calc_name": "upt_v0",
                "calc_version": "0.1.0",
                "certification_status": "uncertified",
                "flags": ["pre_verification", "uncertified"],
                "coverage": None,
            },
            "vrh": {"value": None, "reason": "No computed row; never invented."},
            "non_reportable_pending_d2": False,
        }
    },
    "fleet": {
        "voms": {
            "value": "42",
            "unit": "vehicles",
            "metric_value_id": "mv-0002",
            "calc_name": "voms_v0",
            "calc_version": "0.1.0",
            "certification_status": "uncertified",
            "flags": ["uncertified", "voms_day_level_proxy"],
            "coverage": None,
        }
    },
}


def _patch_build(monkeypatch, package=CANNED_PACKAGE):
    calls = []

    def fake_build(conn, month):
        calls.append((conn, month))
        return package

    monkeypatch.setattr(reports.mr20, "build_mr20_package", fake_build)
    return calls


def test_mr20_package_served_byte_identical(client, fake_db, monkeypatch):
    calls = _patch_build(monkeypatch)
    r = client.get(
        "/reports/mr20",
        params={"month": "2026-07"},
        headers=auth_header(fake_db, "vera"),  # any signed-in role, even viewer
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    # VERBATIM: the exact bytes of the calc package's serialization — key
    # order preserved, nothing added, nothing renamed, nothing recomputed.
    assert r.content == json.dumps(CANNED_PACKAGE).encode("utf-8")
    # The calc library was called with the injected connection and the month.
    assert calls == [(fake_db, "2026-07")]


def test_mr20_any_signed_in_role_reads_but_anonymous_cannot(
    client, fake_db, monkeypatch
):
    _patch_build(monkeypatch)
    for username in ("vera", "stella", "petra", "cora"):
        r = client.get(
            "/reports/mr20",
            params={"month": "2026-07"},
            headers=auth_header(fake_db, username),
        )
        assert r.status_code == 200, username
    assert client.get("/reports/mr20", params={"month": "2026-07"}).status_code == 401


def test_mr20_bad_month_is_plain_language_422(client, fake_db, monkeypatch):
    calls = _patch_build(monkeypatch)
    for bad in ("2026-7", "July 2026", "2026-13", "2026", "26-07", "2026-00"):
        r = client.get(
            "/reports/mr20",
            params={"month": bad},
            headers=auth_header(fake_db, "vera"),
        )
        assert r.status_code == 422, bad
        detail = r.json()["detail"]
        assert "YYYY-MM" in detail and "2026-07" in detail, bad
    # A refused month never reaches the calc library.
    assert calls == []


def test_mr20_missing_month_param_422(client, fake_db):
    r = client.get("/reports/mr20", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 422
