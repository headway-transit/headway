"""Headway API — serves computed truth with provenance; never originates a figure.

Walking-skeleton API scope (ADR-0009, handoff 0001):
- local-account auth (ADR-0011; the OIDC relying party is the next increment),
- computed-value reads with lineage traversal ("explain this number"),
- the audited, role-gated certification action,
- the DQ issue list/resolve workflow.
"""

__version__ = "0.1.0"
