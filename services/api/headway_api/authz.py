"""Authorization: RBAC gates over the verified claim set (never self-asserted).

Roles map to real agency functions and form an escalating hierarchy for read
and stewardship actions:

    viewer < data_steward < report_preparer < certifying_official

- Any authenticated role may GET (read) endpoints.
- Resolving a DQ issue requires data_steward or above.
- Certifying requires EXACTLY the certifying_official role — certification is
  a separation-of-duties act, not a convenience escalation.

Every denial is a 403 with a plain-language message a transit operations
manager can read.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException

from .auth import Identity, get_current_identity

ROLE_RANK = {
    "viewer": 0,
    "data_steward": 1,
    "report_preparer": 2,
    "certifying_official": 3,
}

ROLE_LABELS = {
    "viewer": "viewer",
    "data_steward": "data steward",
    "report_preparer": "report preparer",
    "certifying_official": "certifying official",
}


def require_authenticated(
    identity: Identity = Depends(get_current_identity),
) -> Identity:
    """Any signed-in role may read. There is no unauthenticated endpoint."""
    return identity


def require_at_least(minimum_role: str):
    """Dependency factory: the caller's role must rank at or above ``minimum_role``."""
    if minimum_role not in ROLE_RANK:
        raise ValueError(f"Unknown role {minimum_role!r}")

    def dependency(identity: Identity = Depends(get_current_identity)) -> Identity:
        if ROLE_RANK[identity.role] < ROLE_RANK[minimum_role]:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Your account is signed in as a {ROLE_LABELS[identity.role]}, "
                    f"which cannot perform this action. It requires the "
                    f"{ROLE_LABELS[minimum_role]} role or above. Please ask your "
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
                f"Your account is signed in as a {ROLE_LABELS[identity.role]}, "
                f"which cannot certify figures. Only a certifying official may "
                f"certify, because certification is a legal attestation that "
                f"the figures are correct."
            ),
        )
    return identity
