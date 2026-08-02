"""Authorization: RBAC gates over the verified claim set (never self-asserted).

TWO AXES, NOT ONE LADDER
------------------------

**The ladder** — four roles that map to real agency functions and escalate,
because each does everything the one below it does, and more:

    viewer < data_steward < report_preparer < certifying_official

- Any authenticated role may GET (read) endpoints.
- Resolving a DQ issue requires data_steward or above.
- Certifying requires EXACTLY the certifying_official role — certification is
  a separation-of-duties act, not a convenience escalation.

**Its own axis** — ``auditor`` (handoff 0046, migration 0042): reads broadly,
writes nothing at all. It is deliberately NOT in ``ROLE_RANK``.

Putting it on the ladder was the obvious thing and it is wrong. Every write
gate in this API is ``rank(caller) >= rank(required)``, so a rung would hand
an auditor every write permission at or below it *by arithmetic*: above
``certifying_official`` and an auditor can certify a federal submission; at
``data_steward`` and an auditor can resolve the very DQ findings they are
auditing. No rung means "reads more than a viewer, writes less than one" —
that is a second dimension, so it gets a second dimension.

Concretely, ``auditor`` is enforced in three places, none of which is an
if-statement a future wave has to remember:

1. **Not in ROLE_RANK.** ``require_at_least`` looks the caller up on the
   ladder and an off-ladder role is not there, so it fails every rank
   comparison by construction. An endpoint gated with
   ``require_at_least("data_steward")`` is safe from an auditor on the day it
   is written, without its author knowing this role exists.
2. **No unsafe HTTP method**, refused at the single authentication choke
   point (``auth.get_current_identity``). Every state-changing endpoint in
   this API — present and future — passes through it.
3. **Viewer breadth for content sensitivity** (``may_read_sensitivity``).
   Migration 0028 withholds demand-response rider coordinates because a
   paratransit pickup point is a rider's home address. That withholding is
   NOT waived for an auditor. Rider privacy is not an auditor exception.

Every denial is a 403 with a plain-language message a transit operations
manager can read.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException

from .auth import Identity, get_current_identity

#: THE LADDER. Escalating write/stewardship authority. ``auditor`` is
#: deliberately absent — see the module docstring.
ROLE_RANK = {
    "viewer": 0,
    "data_steward": 1,
    "report_preparer": 2,
    "certifying_official": 3,
}

#: Roles that live BESIDE the ladder: broad read, zero write. Membership here
#: is what makes such a role fail every rank gate rather than satisfy some.
READ_ONLY_ROLES = frozenset({"auditor"})

#: For CONTENT-SENSITIVITY decisions only (never for a write gate): the
#: ladder rung whose READ breadth an off-ladder role is treated as. The
#: auditor reads at VIEWER breadth on purpose — see the module docstring and
#: migration 0042. Anything neither on the ladder nor named here sits below
#: everything: an unrecognized role reads nothing.
_SENSITIVITY_EQUIVALENT_RANK = {
    "auditor": ROLE_RANK["viewer"],
}

ROLE_LABELS = {
    "viewer": "viewer",
    "data_steward": "data steward",
    "report_preparer": "report preparer",
    "certifying_official": "certifying official",
    "auditor": "auditor",
}

#: Every role name the system knows, in the order an admin screen lists them.
ALL_ROLES = (
    "viewer",
    "data_steward",
    "report_preparer",
    "certifying_official",
    "auditor",
)


def role_label(role: str) -> str:
    """Plain-language name for a role; never a KeyError inside an error message."""
    return ROLE_LABELS.get(role, role)


def may_read_sensitivity(role: str, minimum_role: str) -> bool:
    """Does ``role`` reach the read breadth that ``minimum_role`` names?

    The ONLY place an off-ladder role is compared against the ladder, and it
    answers a READ question exclusively (``raw_payloads.Sensitivity``).
    Indexing ``ROLE_RANK[role]`` directly for this would raise ``KeyError``
    for an auditor — loudly, but at the wrong moment and in the wrong shape.
    This helper is deny-by-default for anything it does not recognize.
    """
    if role in ROLE_RANK:
        caller = ROLE_RANK[role]
    elif role in _SENSITIVITY_EQUIVALENT_RANK:
        caller = _SENSITIVITY_EQUIVALENT_RANK[role]
    else:
        return False
    return caller >= ROLE_RANK[minimum_role]


def require_authenticated(
    identity: Identity = Depends(get_current_identity),
) -> Identity:
    """Any signed-in role may read. There is no unauthenticated endpoint.

    An auditor reaches every endpoint gated this way — that IS the role's
    breadth. It can turn none of them into a write, because
    ``get_current_identity`` has already refused every unsafe HTTP method
    before this dependency ever runs.
    """
    return identity


def require_at_least(minimum_role: str):
    """Dependency factory: the caller's role must rank at or above ``minimum_role``.

    DENY-BY-DEFAULT FOR OFF-LADDER ROLES. A role that is not on the ladder
    (``auditor``) can never satisfy a rank requirement, because there is no
    rank to compare. That is not a special case bolted on; it falls out of
    ``role not in ROLE_RANK``, which is why a wave that has never heard of the
    auditor role still cannot accidentally grant it a write.
    """
    if minimum_role not in ROLE_RANK:
        raise ValueError(f"Unknown role {minimum_role!r}")

    def dependency(identity: Identity = Depends(get_current_identity)) -> Identity:
        if identity.role in READ_ONLY_ROLES:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Your account is signed in as an {role_label(identity.role)}, "
                    f"which can read Headway but cannot change anything in it. "
                    f"This action requires the {role_label(minimum_role)} role "
                    f"or above. An auditor account is read-only on purpose, so "
                    f"that what you review cannot be altered by the account "
                    f"reviewing it. If your work also needs to change data, ask "
                    f"your Headway administrator for a separate account."
                ),
            )
        if identity.role not in ROLE_RANK:
            # A token carrying a role this build does not recognize. Refuse —
            # never guess a rank for an unknown role name.
            raise HTTPException(
                status_code=403,
                detail=(
                    "Your account's role is not one this version of Headway "
                    "recognizes, so it grants no access. Please ask your "
                    "Headway administrator to check your account."
                ),
            )
        if ROLE_RANK[identity.role] < ROLE_RANK[minimum_role]:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Your account is signed in as a {role_label(identity.role)}, "
                    f"which cannot perform this action. It requires the "
                    f"{role_label(minimum_role)} role or above. Please ask your "
                    f"Headway administrator if you believe you need this access."
                ),
            )
        return identity

    return dependency


def require_certifying_official(
    identity: Identity = Depends(get_current_identity),
) -> Identity:
    """Certification is gated to exactly the certifying_official role."""
    if identity.role != "certifying_official":
        raise HTTPException(
            status_code=403,
            detail=(
                f"Your account is signed in as a {role_label(identity.role)}, "
                f"which cannot certify figures. Only a certifying official may "
                f"certify, because certification is a legal attestation that "
                f"the figures are correct."
            ),
        )
    return identity


def require_audit_trail_reader(
    identity: Identity = Depends(get_current_identity),
) -> Identity:
    """The audit trail: readable by an auditor or a certifying official.

    Narrower than ``require_authenticated`` on purpose. The trail names who
    did what, and when, across the whole installation — it is an oversight
    surface, not an operational one, and a data steward has no need to read
    colleagues' activity to do their job. The two roles that do are the one
    accountable for the installation (certifying official) and the one whose
    entire purpose is oversight (auditor).
    """
    if identity.role not in ("auditor", "certifying_official"):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Your account is signed in as a {role_label(identity.role)}, "
                f"which cannot read Headway's audit trail. The trail records "
                f"what every person did across this installation, so it is "
                f"open to auditors and certifying officials only. Ask your "
                f"Headway administrator if your work requires this access."
            ),
        )
    return identity
