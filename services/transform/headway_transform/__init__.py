"""headway_transform — normalizers turning raw records into canonical rows.

Implements the Data Engineer scope of ADR-0009's walking skeleton against the
schema contract in docs/handoffs/0001-from-platform-architect-to-all-canonical-schema-v0.md.

Invariants (role guardrails, .claude/roles/DATA_ENGINEER.md):
- Fail loudly: no input is ever silently dropped or coalesced; every gap,
  conflict, or malformed input becomes a dq.issues row (DQFinding).
- Every canonical row carries a lineage edge back to its raw record and the
  transform name+version that produced it.
- No tenant_id anywhere (ADR-0004: database-per-agency).
"""

__version__ = "0.1.0"
