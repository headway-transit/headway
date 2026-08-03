"""Where the service-day timezone comes from, and which source won.

ADR-0015: configuration an operator must change after installation lives in
``app.settings``, not in a dotfile reachable only over SSH — with the
environment kept as the AUTOMATION path and winning where both are present.

This module is that rule for one value, and it is the worked example the ADR
was written from. On 2026-08-03 a partner agency's telematics feed refused
every page for three days because ``HEADWAY_TELEMATICS_SERVICE_DAY_TZ`` was
documented in this service's README and plumbed nowhere. The refusal was
right — a service date is a LOCAL WALL DATE and must never come from a guessed
zone — but their ITS manager, an expert in his own data and not a systems
administrator, had no path to satisfy it.

Three rules, in order:

1. **The environment wins.** A scripted fleet install must be able to set this
   without a human clicking anything, exactly as ``HEADWAY_ACCESS_MODE`` works
   for ``install.sh --yes``.
2. **Otherwise the database decides**, so an operator can fix their own
   installation from the admin screen, and the change is attributed
   (``app.settings`` records ``updated_by`` and ``updated_at``; a ``.env`` edit
   over SSH records nothing).
3. **Undeclared stays undeclared.** No fallback to UTC, to the server's zone,
   or to anything else. A guessed zone silently dates a federal figure to the
   wrong day, which is the failure the refusal exists to prevent. An
   installation that has not declared its zone is not misconfigured; it is
   undeclared, and Headway says so.

The source is returned alongside the value because two homes for one setting
is a support burden unless the running service can say which one it read.
"""

from __future__ import annotations

import os

ENV_VAR = "HEADWAY_TELEMATICS_SERVICE_DAY_TZ"
SETTING_KEY = "service_day_timezone"

_SELECT_SETTING = "SELECT setting_value FROM app.settings WHERE setting_key = %s"

#: What a caller gets when nothing declares a zone. Not a value — an absence.
UNDECLARED = ""


def resolve_service_day_timezone(conn) -> tuple[str, str]:
    """The declared zone and where it came from.

    Returns ``("", "nothing")`` when undeclared. Never raises for a missing
    setting row or an unreachable settings table: a transform that refuses to
    start because it could not read an OPTIONAL setting would take down every
    other feed over one that may not even be configured.
    """
    from_env = os.environ.get(ENV_VAR, "").strip()
    if from_env:
        return from_env, f"the {ENV_VAR} environment variable"

    try:
        row = conn.execute(_SELECT_SETTING, (SETTING_KEY,)).fetchone()
    except Exception:  # noqa: BLE001 — see the docstring; never fatal here
        return UNDECLARED, "nothing"
    if row is None:
        # Pre-0044 database, or the row was removed. Undeclared, not an error.
        return UNDECLARED, "nothing"
    value = (row[0] or "").strip()
    if not value:
        return UNDECLARED, "nothing"
    return value, "Headway's settings (Admin -> Settings)"
