"""Agency branding with the accessibility guardrail (handoff 0008, pillar C):
WCAG 2.1 contrast math verified against W3C-published values, brand-color
PUTs refused below AA with the surface and ratio named, the logo upload
(role-gated, type-whitelisted, size-capped, audited), and the two
unauthenticated GET surfaces for the app shell."""

import json

import pytest
from conftest import auth_header

from headway_api import branding
from headway_api.machine_auth import RateLimiter

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"headway-test-png-payload"
SVG_BYTES = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'


# ---------------------------------------------------------------------------
# The contrast math, against W3C-published values (never our own memory):
# the WCAG 2.1 "contrast ratio" definition publishes the range 1:1 to 21:1,
# and the "relative luminance" definition publishes the channel coefficients.
# ---------------------------------------------------------------------------


def test_white_on_black_is_exactly_21_the_published_maximum():
    # WCAG 2.1 dfn-contrast-ratio: "contrast ratios can range from 1 to 21".
    assert branding.contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert branding.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)


def test_same_color_is_exactly_1_the_published_minimum():
    assert branding.contrast_ratio("#1a5fb4", "#1a5fb4") == pytest.approx(1.0)


def test_luminance_coefficients_match_the_published_formula():
    # L = 0.2126*R + 0.7152*G + 0.0722*B, so each pure primary's luminance
    # IS its published coefficient (channel 255 linearizes to exactly 1.0).
    assert branding.relative_luminance("#ff0000") == pytest.approx(0.2126)
    assert branding.relative_luminance("#00ff00") == pytest.approx(0.7152)
    assert branding.relative_luminance("#0000ff") == pytest.approx(0.0722)
    assert branding.relative_luminance("#ffffff") == pytest.approx(1.0)
    assert branding.relative_luminance("#000000") == pytest.approx(0.0)


def test_ratios_agree_with_the_web_token_checker():
    # Cross-implementation check: web/src/styles.css documents these ratios,
    # verified by the independent web/scripts/check-contrast.mjs.
    assert branding.contrast_ratio("#1f2328", "#ffffff") == pytest.approx(
        15.80, abs=0.005
    )
    assert branding.contrast_ratio("#0b57d0", "#ffffff") == pytest.approx(
        6.39, abs=0.005
    )


def test_surfaces_are_the_web_root_tokens():
    assert branding.LIGHT_SURFACE == "#ffffff"  # --color-bg
    assert branding.DARK_SURFACE == "#f6f8fa"  # --color-surface


def test_brand_color_problem_accepts_the_seeded_defaults():
    assert branding.brand_color_problem("#1a5fb4") is None
    assert branding.brand_color_problem("#0b57d0") is None


def test_brand_color_problem_names_failing_surface_and_ratio():
    # Fails on the page background (1.96:1 on #ffffff).
    msg = branding.brand_color_problem("#aabbcc")
    assert msg is not None
    assert "1.96:1" in msg
    assert "page background" in msg and "#ffffff" in msg
    assert "4.5:1" in msg
    # Passes white (4.54:1) but fails the card surface (4.27:1) — the
    # refusal must name the surface that actually failed.
    msg = branding.brand_color_problem("#767676")
    assert msg is not None
    assert "4.27:1" in msg
    assert "raised card surface" in msg and "#f6f8fa" in msg


def test_brand_color_problem_refuses_non_hex_formats():
    for bad in ("blue", "1a5fb4", "#1a5fb", "#1a5fb4a", "#1g5fb4", "rgb(0,0,0)"):
        msg = branding.brand_color_problem(bad)
        assert msg is not None, bad
        assert "#1a5fb4" in msg  # the example format in the message


# ---------------------------------------------------------------------------
# PUT /settings/brand_color_* — the guardrail on the wire
# ---------------------------------------------------------------------------


def test_put_failing_color_is_422_with_ratio_nothing_persisted(client, fake_db):
    r = client.put(
        "/settings/brand_color_primary",
        json={"value": "#aabbcc"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "doesn't have enough contrast" in detail
    assert "1.96:1" in detail and "page background" in detail
    assert fake_db.settings["brand_color_primary"]["setting_value"] == "#1a5fb4"
    assert fake_db.audit_events == []  # a refused change leaves nothing behind


def test_put_bad_hex_format_is_422(client, fake_db):
    r = client.put(
        "/settings/brand_color_accent",
        json={"value": "blue"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422
    assert "six-digit hex color" in r.json()["detail"]
    assert fake_db.settings["brand_color_accent"]["setting_value"] == "#0b57d0"


def test_put_passing_color_persists_and_is_audited(client, fake_db):
    r = client.put(
        "/settings/brand_color_primary",
        json={"value": "#1f2328"},  # 15.80:1 / 14.84:1 — comfortably AA
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 200
    assert r.json()["setting_value"] == "#1f2328"
    assert fake_db.settings["brand_color_primary"]["setting_value"] == "#1f2328"
    events = [e for e in fake_db.audit_events if e["action"] == "setting_updated"]
    assert len(events) == 1
    detail = json.loads(events[0]["detail"])
    assert detail["old_value"] == "#1a5fb4"
    assert detail["new_value"] == "#1f2328"


def test_put_brand_logo_meta_directly_is_refused(client, fake_db):
    r = client.put(
        "/settings/brand_logo_meta",
        json={"value": "image/png"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422
    assert "POST /branding/logo" in r.json()["detail"]
    assert fake_db.settings["brand_logo_meta"]["setting_value"] == "unset"


def test_put_display_name_is_plain_text_no_guardrail(client, fake_db):
    r = client.put(
        "/settings/agency_display_name",
        json={"value": "Springfield Transit"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 200
    assert fake_db.settings["agency_display_name"]["setting_value"] == (
        "Springfield Transit"
    )


# ---------------------------------------------------------------------------
# POST /branding/logo
# ---------------------------------------------------------------------------


def _upload(client, fake_db, username="cora", *, data=PNG_BYTES,
            content_type="image/png", filename="logo.png"):
    return client.post(
        "/branding/logo",
        files={"file": (filename, data, content_type)},
        headers=auth_header(fake_db, username),
    )


def test_logo_upload_stores_records_meta_and_audits(client, fake_db, fake_store):
    r = _upload(client, fake_db)
    assert r.status_code == 200
    body = r.json()
    assert body["content_type"] == "image/png"
    assert body["bytes"] == len(PNG_BYTES)
    # Bytes at the fixed object key; content type recorded in the setting.
    assert fake_store.objects["branding/logo"] == PNG_BYTES
    assert fake_db.settings["brand_logo_meta"]["setting_value"] == "image/png"
    assert fake_db.settings["brand_logo_meta"]["updated_by"] == "cora"
    events = [
        e for e in fake_db.audit_events if e["action"] == "branding_logo_uploaded"
    ]
    assert len(events) == 1
    assert events[0]["actor"] == "cora"
    assert events[0]["subject_kind"] == "app.settings"
    assert events[0]["subject_id"] == "brand_logo_meta"
    detail = json.loads(events[0]["detail"])
    assert detail == {
        "content_type": "image/png",
        "bytes": len(PNG_BYTES),
        "object_key": "branding/logo",
    }
    assert body["audit_event_id"] == events[0]["event_id"]


def test_logo_upload_oversize_is_413_nothing_stored(client, fake_db, fake_store):
    too_big = b"x" * (512 * 1024 + 1)
    r = _upload(client, fake_db, data=too_big)
    assert r.status_code == 413
    assert "512 KiB" in r.json()["detail"]
    assert fake_store.objects == {}
    assert fake_db.settings["brand_logo_meta"]["setting_value"] == "unset"
    assert fake_db.audit_events == []


def test_logo_upload_exactly_512_kib_is_accepted(client, fake_db, fake_store):
    exact = b"x" * (512 * 1024)
    r = _upload(client, fake_db, data=exact)
    assert r.status_code == 200
    assert fake_store.objects["branding/logo"] == exact


def test_logo_upload_wrong_type_is_415(client, fake_db, fake_store):
    r = _upload(client, fake_db, data=b"jpegbytes",
                content_type="image/jpeg", filename="logo.jpg")
    assert r.status_code == 415
    detail = r.json()["detail"]
    assert "image/svg+xml" in detail and "image/png" in detail
    assert fake_store.objects == {}
    assert fake_db.audit_events == []


def test_logo_upload_empty_file_is_422(client, fake_db, fake_store):
    r = _upload(client, fake_db, data=b"")
    assert r.status_code == 422
    assert fake_store.objects == {}


def test_logo_upload_requires_certifying_official(client, fake_db, fake_store):
    for username in ("vera", "stella", "petra"):
        r = _upload(client, fake_db, username)
        assert r.status_code == 403, username
    assert fake_store.objects == {}
    assert fake_db.settings["brand_logo_meta"]["setting_value"] == "unset"


def test_logo_upload_unauthenticated_is_401(client, fake_store):
    r = client.post(
        "/branding/logo", files={"file": ("logo.png", PNG_BYTES, "image/png")}
    )
    assert r.status_code == 401
    assert fake_store.objects == {}


def test_logo_upload_without_object_store_is_503(client, app, fake_db):
    app.state.object_store = None
    r = _upload(client, fake_db)
    assert r.status_code == 503
    assert "Nothing was stored" in r.json()["detail"]


# ---------------------------------------------------------------------------
# GET /branding/logo — unauthenticated, cached, rate limited
# ---------------------------------------------------------------------------


def test_get_logo_404_plain_language_when_unset(client):
    r = client.get("/branding/logo")  # NO Authorization header
    assert r.status_code == 404
    assert "No agency logo has been uploaded" in r.json()["detail"]


def test_get_logo_serves_bytes_type_and_cache_headers(client, fake_db):
    _upload(client, fake_db)
    r = client.get("/branding/logo")  # NO Authorization header
    assert r.status_code == 200
    assert r.content == PNG_BYTES
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "public, max-age=300"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_get_logo_svg_carries_script_blocking_csp(client, fake_db):
    _upload(client, fake_db, data=SVG_BYTES,
            content_type="image/svg+xml", filename="logo.svg")
    r = client.get("/branding/logo")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_get_logo_ip_rate_limit_429_with_retry_after(client, app):
    app.state.public_rate_limiter = RateLimiter(requests_per_minute=2)
    assert client.get("/branding/logo").status_code == 404
    assert client.get("/branding/logo").status_code == 404
    r = client.get("/branding/logo")
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


# ---------------------------------------------------------------------------
# GET /branding — the app-shell bundle
# ---------------------------------------------------------------------------


def test_get_branding_shape_and_defaults(client):
    r = client.get("/branding")  # NO Authorization header
    assert r.status_code == 200
    body = r.json()
    chrome_note = body.pop("chrome_note")
    assert "dark" in chrome_note  # the standing dark-mode statement travels
    assert body == {
        "display_name": "Transit Agency",
        "primary": "#1a5fb4",
        "accent": "#0b57d0",
        "has_logo": False,
        # Branding v2 (handoff 0017): chrome is null until the agency sets
        # ALL THREE brand_chrome_* keys — neutral Headway out of the box.
        "chrome": None,
    }


def test_get_branding_reflects_changes_and_logo(client, fake_db):
    client.put(
        "/settings/agency_display_name",
        json={"value": "Springfield Transit"},
        headers=auth_header(fake_db, "cora"),
    )
    _upload(client, fake_db)
    r = client.get("/branding")
    body = r.json()
    assert body["display_name"] == "Springfield Transit"
    assert body["has_logo"] is True


# ---------------------------------------------------------------------------
# Branding v2 — themed chrome (handoff 0017, design point 7): the SAME WCAG
# math applied to the chrome PAIRS (fg-on-header-bg, accent-on-header-bg),
# checked against the values that WOULD result from each change, so no
# sequence of single-key updates reaches an unreadable header. 'unset'
# deactivates; GET /branding serves chrome only when all three are set.
# ---------------------------------------------------------------------------


def _put_setting(client, fake_db, key, value, username="cora"):
    return client.put(
        f"/settings/{key}", json={"value": value},
        headers=auth_header(fake_db, username),
    )


def test_chrome_value_accepts_hex_and_unset_refuses_garbage():
    assert branding.chrome_value_problem("#1f2328") is None
    assert branding.chrome_value_problem("unset") is None
    msg = branding.chrome_value_problem("navy")
    assert msg is not None and "'unset'" in msg


def test_chrome_pair_refusal_names_pair_and_ratio(client, fake_db):
    ok = _put_setting(client, fake_db, "brand_chrome_header_bg", "#1f2328")
    assert ok.status_code == 200  # fg/accent unset: no pair to fail yet
    r = _put_setting(client, fake_db, "brand_chrome_header_fg", "#767676")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "3.48:1" in detail
    assert "header text on the themed header background" in detail
    assert "4.5:1" in detail
    assert fake_db.settings["brand_chrome_header_fg"]["setting_value"] == "unset"

    ok = _put_setting(client, fake_db, "brand_chrome_header_fg", "#ffffff")
    assert ok.status_code == 200  # 15.80:1

    r = _put_setting(client, fake_db, "brand_chrome_accent", "#0b57d0")
    assert r.status_code == 422  # 2.47:1 on the dark header
    assert "active-item accent" in r.json()["detail"]
    ok = _put_setting(client, fake_db, "brand_chrome_accent", "#ffd700")
    assert ok.status_code == 200  # 11.26:1


def test_chrome_bg_change_cannot_break_existing_pairs(client, fake_db):
    for key, value in (
        ("brand_chrome_header_bg", "#1f2328"),
        ("brand_chrome_header_fg", "#ffffff"),
        ("brand_chrome_accent", "#ffd700"),
    ):
        assert _put_setting(client, fake_db, key, value).status_code == 200
    # Whitening the header would strand the white fg AND the gold accent —
    # the prospective-pair check refuses the bg change itself.
    r = _put_setting(client, fake_db, "brand_chrome_header_bg", "#ffffff")
    assert r.status_code == 422
    assert fake_db.settings["brand_chrome_header_bg"]["setting_value"] == (
        "#1f2328"
    )


def test_get_branding_serves_chrome_only_when_complete(client, fake_db):
    assert client.get("/branding").json()["chrome"] is None
    assert _put_setting(
        client, fake_db, "brand_chrome_header_bg", "#1f2328"
    ).status_code == 200
    # Incomplete theme: still null (neutral chrome).
    assert client.get("/branding").json()["chrome"] is None
    _put_setting(client, fake_db, "brand_chrome_header_fg", "#ffffff")
    _put_setting(client, fake_db, "brand_chrome_accent", "#ffd700")
    body = client.get("/branding").json()
    assert body["chrome"] == {
        "header_bg": "#1f2328",
        "header_fg": "#ffffff",
        "accent": "#ffd700",
    }
    # 'unset' turns the theme off again — back to neutral Headway.
    assert _put_setting(
        client, fake_db, "brand_chrome_header_bg", "unset"
    ).status_code == 200
    assert client.get("/branding").json()["chrome"] is None


def test_chrome_changes_are_certifying_official_only_and_audited(client, fake_db):
    r = _put_setting(
        client, fake_db, "brand_chrome_header_bg", "#1f2328", username="stella"
    )
    assert r.status_code == 403
    r = _put_setting(client, fake_db, "brand_chrome_header_bg", "#1f2328")
    assert r.status_code == 200
    events = [
        e for e in fake_db.audit_events if e["action"] == "setting_updated"
    ]
    assert len(events) == 1
    detail = json.loads(events[0]["detail"])
    assert detail["old_value"] == "unset"
    assert detail["new_value"] == "#1f2328"
