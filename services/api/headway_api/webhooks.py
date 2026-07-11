"""Outbound webhooks: certification.created (handoff 0006, design point 7)
and dq.issue.resolved (dated addition on handoff 0006, 2026-07-11).

Delivery model, deliberately v0-simple:
- The certification TRANSACTION COMMITS FIRST. Dispatch is strictly
  post-commit — a webhook can never block, delay, or fail a certification.
- Synchronous best-effort with ONE retry per subscription. A delivery that
  still fails is audit-logged (never silently lost, never re-raised into the
  certification response). A durable outbox/queue is a future increment.

Signing: ``X-Headway-Signature: sha256=<HMAC-SHA256(body, secret)>`` over the
exact body bytes sent, plus ``X-Headway-Timestamp`` (unix seconds). REPLAY
WINDOW NOTE: v0 signs the body only; the timestamp header lets a receiver
reject stale deliveries (recommended window: 5 minutes), but it is not yet
bound into the signature — binding timestamp+body (and a nonce) into the
signed material is the hardening increment tracked in handoff 0006.

The HTTP sender is a small protocol on app.state (httpx in production, a fake
in tests). Subscription secrets are stored plaintext-with-documented-risk
(migration 0013 — read back to sign; DB-at-rest encryption is the compensating
control) and are NEVER returned by any endpoint or written to audit detail.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
import time
from typing import Optional, Protocol

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .audit import write_event
from .auth import Identity
from .authz import require_certifying_official
from .db import get_db

logger = logging.getLogger(__name__)

# v0 event registry — deny-by-default, like machine scopes.
EVENT_CERTIFICATION_CREATED = "certification.created"
EVENT_DQ_ISSUE_RESOLVED = "dq.issue.resolved"
KNOWN_EVENT_TYPES = (EVENT_CERTIFICATION_CREATED, EVENT_DQ_ISSUE_RESOLVED)
# HONEST SCOPE NOTE: "dq.issue.created" is NOT in this registry and cannot be
# — issues are written by the calc/transform services outside this API's
# process, so the API has no post-commit moment to dispatch from. An
# outbox/DB-trigger mechanism is the documented follow-up for full ticketing
# sync; v0 ticketing integration = this resolved-event push + polling
# GET /dq/issues (see the service README and handoff 0006's dated note).

# The audit actor for delivery outcomes: deliveries are performed by the
# system post-commit, not by the certifying human (whose own act is already
# audited by the certification itself).
DISPATCH_ACTOR = "headway-api-webhooks"


class WebhookSender(Protocol):
    """The one HTTP operation dispatch needs: POST and return the status code.
    Raises on connection failure. httpx in production; a fake in tests."""

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> int: ...


class HttpxWebhookSender:
    """Production sender (httpx, already a core dependency)."""

    def __init__(self, timeout_seconds: float = 10.0):
        self._timeout = timeout_seconds

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> int:
        import httpx

        return httpx.post(
            url, content=body, headers=headers, timeout=self._timeout
        ).status_code


def sign_body(secret: str, body: bytes) -> str:
    """The X-Headway-Signature value: ``sha256=<HMAC-SHA256(body, secret)>``."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


_SELECT_ACTIVE_SUBSCRIPTIONS = (
    "SELECT subscription_id, url, event_types, secret "
    "FROM auth.webhook_subscriptions WHERE revoked_at IS NULL"
)

_SELECT_CERTIFIED_VALUES = (
    "SELECT metric_value_id, metric, value FROM computed.metric_values "
    "WHERE metric_value_id = ANY(%s)"
)


def dispatch_certification_created(
    db,
    sender: Optional[WebhookSender],
    *,
    certification_id: str,
    metric_value_ids: list[str],
    certified_by: str,
    certified_at: dt.datetime,
    clock=time.time,
) -> None:
    """Deliver certification.created to every matching live subscription.

    MUST be called only AFTER the certification transaction committed. Never
    raises: every failure path is audit-logged (or, if even the audit write
    fails, logged to the process log) — the certification response is already
    earned and a notification problem must not turn it into an error.
    """
    try:
        rows = db.execute(_SELECT_ACTIVE_SUBSCRIPTIONS, ()).fetchall()
        matching = [r for r in rows if EVENT_CERTIFICATION_CREATED in list(r[2])]
        if not matching:
            return
        value_rows = db.execute(
            _SELECT_CERTIFIED_VALUES, (metric_value_ids,)
        ).fetchall()
        body_dict = {
            "event_type": EVENT_CERTIFICATION_CREATED,
            "certification_id": certification_id,
            "metric_value_ids": metric_value_ids,
            # Values as STRINGS — NUMERIC precision, never float (the same
            # rule as every read endpoint).
            "values": [
                {"metric_value_id": str(r[0]), "metric": r[1], "value": str(r[2])}
                for r in value_rows
            ],
            "certified_by": certified_by,
            "certified_at": certified_at.isoformat(),
        }
        _deliver_to_matching(db, sender, matching, body_dict, clock=clock)
    except Exception:  # noqa: BLE001 — last-resort guard, see docstring
        logger.exception(
            "webhook dispatch failed after certification %s committed "
            "(certification unaffected)",
            certification_id,
        )


def dispatch_dq_issue_resolved(
    db,
    sender: Optional[WebhookSender],
    *,
    issue_id: str,
    issue_type: str,
    severity: str,
    resolved_by: str,
    resolution_minutes: Optional[int],
    resolved_at: dt.datetime,
    clock=time.time,
) -> None:
    """Deliver dq.issue.resolved to every matching live subscription.

    Same contract as dispatch_certification_created: MUST be called only
    AFTER the resolve transaction committed; never raises — every failure
    path is audit-logged (or logged to the process log if even that fails).
    A notification problem must never turn an earned resolution into an
    error. ``resolution_minutes`` is served as-is: null when the resolver
    recorded no effort (never coalesced to zero).
    """
    try:
        rows = db.execute(_SELECT_ACTIVE_SUBSCRIPTIONS, ()).fetchall()
        matching = [r for r in rows if EVENT_DQ_ISSUE_RESOLVED in list(r[2])]
        if not matching:
            return
        body_dict = {
            "event_type": EVENT_DQ_ISSUE_RESOLVED,
            "issue_id": issue_id,
            "issue_type": issue_type,
            "severity": severity,
            "resolved_by": resolved_by,
            "resolution_minutes": resolution_minutes,
            "resolved_at": resolved_at.isoformat(),
        }
        _deliver_to_matching(db, sender, matching, body_dict, clock=clock)
    except Exception:  # noqa: BLE001 — last-resort guard, see docstring
        logger.exception(
            "webhook dispatch failed after dq issue %s resolved "
            "(resolution unaffected)",
            issue_id,
        )


#: The one body key per event type that identifies the subject in delivery
#: audit detail (ids only — never figures, never secrets).
_AUDIT_SUBJECT_KEY = {
    EVENT_CERTIFICATION_CREATED: "certification_id",
    EVENT_DQ_ISSUE_RESOLVED: "issue_id",
}


def _deliver_to_matching(db, sender, matching, body_dict: dict, *, clock) -> None:
    """Shared delivery core: sign the exact body bytes once, deliver to each
    matching subscription with one retry, audit every outcome."""
    event_type = body_dict["event_type"]
    subject_key = _AUDIT_SUBJECT_KEY[event_type]
    audit_context = {
        "event_type": event_type,
        subject_key: body_dict[subject_key],
    }
    body = json.dumps(body_dict).encode("utf-8")
    timestamp = str(int(clock()))
    for subscription_id, url, _event_types, secret in matching:
        headers = {
            "Content-Type": "application/json",
            "X-Headway-Signature": sign_body(secret, body),
            "X-Headway-Timestamp": timestamp,
        }
        _deliver_one(
            db,
            sender,
            subscription_id=str(subscription_id),
            url=url,
            body=body,
            headers=headers,
            audit_context=audit_context,
        )


def _deliver_one(
    db,
    sender: Optional[WebhookSender],
    *,
    subscription_id: str,
    url: str,
    body: bytes,
    headers: dict[str, str],
    audit_context: dict,
) -> None:
    """One subscription: try, retry once, audit the outcome."""
    if sender is None:
        _audit_delivery(
            db,
            action="webhook_delivery_failed",
            subscription_id=subscription_id,
            detail={
                **audit_context,
                "reason": "no webhook sender configured on this instance",
            },
        )
        return
    outcome: dict = {}
    for attempt in (1, 2):  # one retry (design point 7)
        try:
            status = sender.post(url, body, headers)
        except Exception as exc:  # noqa: BLE001 — delivery must not propagate
            outcome = {"attempts": attempt, "error": str(exc)}
            continue
        if 200 <= status < 300:
            _audit_delivery(
                db,
                action="webhook_delivered",
                subscription_id=subscription_id,
                detail={
                    **audit_context,
                    "status": status,
                    "attempts": attempt,
                },
            )
            return
        outcome = {"attempts": attempt, "status": status}
    _audit_delivery(
        db,
        action="webhook_delivery_failed",
        subscription_id=subscription_id,
        detail={**audit_context, **outcome},
    )


def _audit_delivery(db, *, action: str, subscription_id: str, detail: dict) -> None:
    # Detail carries ids and outcomes only — never the URL's secret query
    # strings, never the subscription secret, never the signed body.
    with db.transaction():
        write_event(
            db,
            actor=DISPATCH_ACTOR,
            action=action,
            subject_kind="auth.webhook_subscriptions",
            subject_id=subscription_id,
            detail=detail,
        )


# ---------------------------------------------------------------------------
# Subscription CRUD (admin = certifying_official for v0, like machine keys)
# ---------------------------------------------------------------------------

router = APIRouter(tags=["webhooks"])


class CreateSubscriptionRequest(BaseModel):
    url: str = Field(min_length=1)
    event_types: list[str] = Field(min_length=1)
    # Accepted at create, stored to sign with, NEVER returned by any endpoint.
    secret: str = Field(min_length=16, description="HMAC signing secret (min 16 chars)")


class SubscriptionResponse(BaseModel):
    """Subscription shape served back — deliberately secret-free."""

    subscription_id: str
    url: str
    event_types: list[str]
    created_by: str
    created_at: dt.datetime
    revoked_at: Optional[dt.datetime]


class RevokeSubscriptionResponse(BaseModel):
    subscription_id: str
    revoked_at: dt.datetime
    audit_event_id: int


_INSERT_SUBSCRIPTION = (
    "INSERT INTO auth.webhook_subscriptions (url, event_types, secret, created_by) "
    "VALUES (%s, %s, %s, %s) RETURNING subscription_id, created_at"
)

_LIST_SUBSCRIPTIONS = (
    "SELECT subscription_id, url, event_types, created_by, created_at, revoked_at "
    "FROM auth.webhook_subscriptions ORDER BY created_at"
)

_REVOKE_SUBSCRIPTION = (
    "UPDATE auth.webhook_subscriptions SET revoked_at = now() "
    "WHERE subscription_id = %s AND revoked_at IS NULL "
    "RETURNING subscription_id, revoked_at"
)

_SELECT_SUBSCRIPTION_EXISTS = (
    "SELECT subscription_id FROM auth.webhook_subscriptions WHERE subscription_id = %s"
)


@router.post("/webhooks", response_model=SubscriptionResponse, status_code=201)
def create_subscription(
    body: CreateSubscriptionRequest,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> SubscriptionResponse:
    unknown = [e for e in body.event_types if e not in KNOWN_EVENT_TYPES]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                "These are not webhook events Headway knows: "
                + ", ".join(unknown)
                + ". Valid events are: "
                + ", ".join(KNOWN_EVENT_TYPES)
                + "."
            ),
        )
    if not body.url.startswith(("https://", "http://")):
        raise HTTPException(
            status_code=422,
            detail=(
                "The webhook URL must start with https:// (or http:// for a "
                "local test receiver)."
            ),
        )
    event_types = list(dict.fromkeys(body.event_types))
    with db.transaction():
        row = db.execute(
            _INSERT_SUBSCRIPTION,
            (body.url, event_types, body.secret, identity.username),
        ).fetchone()
        subscription_id, created_at = str(row[0]), row[1]
        write_event(
            db,
            actor=identity.username,
            action="webhook_subscribed",
            subject_kind="auth.webhook_subscriptions",
            subject_id=subscription_id,
            # url + events only — the secret never enters the audit trail.
            detail={"url": body.url, "event_types": event_types},
        )
    return SubscriptionResponse(
        subscription_id=subscription_id,
        url=body.url,
        event_types=event_types,
        created_by=identity.username,
        created_at=created_at,
        revoked_at=None,
    )


@router.get("/webhooks", response_model=list[SubscriptionResponse])
def list_subscriptions(
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> list[SubscriptionResponse]:
    rows = db.execute(_LIST_SUBSCRIPTIONS, ()).fetchall()
    return [
        SubscriptionResponse(
            subscription_id=str(r[0]),
            url=r[1],
            event_types=list(r[2]),
            created_by=r[3],
            created_at=r[4],
            revoked_at=r[5],
        )
        for r in rows
    ]


@router.delete("/webhooks/{subscription_id}", response_model=RevokeSubscriptionResponse)
def revoke_subscription(
    subscription_id: str,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> RevokeSubscriptionResponse:
    with db.transaction():
        row = db.execute(_REVOKE_SUBSCRIPTION, (subscription_id,)).fetchone()
        if row is None:
            exists = db.execute(
                _SELECT_SUBSCRIPTION_EXISTS, (subscription_id,)
            ).fetchone()
            if exists is None:
                raise HTTPException(
                    status_code=404,
                    detail="No webhook subscription with that id exists.",
                )
            raise HTTPException(
                status_code=409,
                detail="This webhook subscription is already removed.",
            )
        revoked_id, revoked_at = str(row[0]), row[1]
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="webhook_unsubscribed",
            subject_kind="auth.webhook_subscriptions",
            subject_id=revoked_id,
            detail={},
        )
    return RevokeSubscriptionResponse(
        subscription_id=revoked_id,
        revoked_at=revoked_at,
        audit_event_id=audit_event_id,
    )
