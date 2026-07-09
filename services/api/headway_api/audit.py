"""The single audit-writing helper. Every state-changing endpoint uses it.

Guardrail: audit logging is never best-effort. This helper REFUSES to be a
no-op — no connection means an exception, which (because callers invoke it
inside the same transaction as the state change) aborts the action itself.
There is no code path that changes state silently.

audit.events is append-only at the database level too (migration 0007 rejects
UPDATE/DELETE with a trigger); this helper only ever INSERTs.
"""

from __future__ import annotations

import json


class AuditWriteRefused(RuntimeError):
    """Raised when an audit event cannot be written. The action must fail."""


_INSERT_EVENT = (
    "INSERT INTO audit.events (actor, action, subject_kind, subject_id, detail) "
    "VALUES (%s, %s, %s, %s, %s) RETURNING event_id"
)


def write_event(
    conn,
    *,
    actor: str,
    action: str,
    subject_kind: str | None,
    subject_id: str | None,
    detail: dict,
) -> int:
    """Insert one audit.events row and return its event_id.

    Must be called inside the caller's transaction so the audit record and the
    state change commit (or abort) together. Never writes secrets or PII into
    ``detail`` — callers pass ids and attestation text only.
    """
    if conn is None:
        raise AuditWriteRefused(
            "Audit logging is unavailable (no database connection). The "
            "action was refused because Headway never changes state without "
            "an audit record."
        )
    if not actor or not action:
        raise AuditWriteRefused(
            "An audit event requires both an actor and an action; refusing "
            "to write an anonymous or unlabeled audit record."
        )
    cursor = conn.execute(
        _INSERT_EVENT,
        (actor, action, subject_kind, subject_id, json.dumps(detail)),
    )
    row = cursor.fetchone()
    if row is None:
        raise AuditWriteRefused(
            "The audit record insert returned no event id; refusing to "
            "treat the action as logged."
        )
    return row[0]
