"""Grounded, labeled explanations for anomaly findings — or no explanation.

For each :class:`~headway_ai.anomaly.AnomalyFinding`, this module asks a
:class:`~headway_ai.provider.Provider` (``StubProvider`` by default — the
deterministic template path; no network, no model) to phrase a
plain-language explanation, wraps it as a :class:`LabeledOutput`, builds a
:class:`~headway_ai.claims.GroundedDraft` whose claims cite the compared
``computed.metric_values`` rows, and runs the FULL grounding harness
(:func:`headway_ai.grounding.evaluate`) over the draft BEFORE anything is
emitted:

- every claim cites a real ``computed.metric_values`` id (checked against
  the injected connection);
- every numeric token in the prose — including whatever the provider
  produced — must be a number present in the cited rows' ``value`` /
  ``detail`` strings (or their period dates). Declared
  ``Claim.numeric_values`` list ONLY numbers taken verbatim from the rows.

A draft that fails grounding is DROPPED with a loud ``ERROR`` log and
returned in the ``rejected`` list — it is NEVER emitted. The finding
itself still stands: flags are deterministic and never depend on prose.
An explanation is a convenience; a grounded flag without prose beats an
ungrounded sentence every time.

This module never computes a number: every numeric string it handles is
copied verbatim from injected metric-value rows. Deterministic with the
default provider: no clock, no randomness, no network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from headway_ai.anomaly import AnomalyFinding, HistoryRow, normalize_history
from headway_ai.claims import Claim, GroundedDraft
from headway_ai.grounding import EvalReport, evaluate, normalize_number
from headway_ai.provider import LabeledOutput, Provider, StubProvider

__all__ = [
    "ExplainedFinding",
    "RejectedExplanation",
    "ExplanationBatch",
    "allowed_numbers_for_rows",
    "explain_findings",
]

logger = logging.getLogger(__name__)

#: The template prompt (the provider phrases; it must not add numbers —
#: and the grounding gate below makes that a hard guarantee, not a hope).
_PROMPT_TEMPLATE = (
    "Explain in plain language, for a transit operations manager, why the "
    "anomaly flag {issue_type} was raised for the computed metric {metric}. "
    "Use ONLY the numbers present in the provided context values; never "
    "introduce a number that is not in the context. The flag is assistive "
    "and for human review; it does not change any figure."
)


@dataclass(frozen=True)
class ExplainedFinding:
    """A finding whose explanation PASSED the grounding gate."""

    finding: AnomalyFinding
    draft: GroundedDraft
    output: LabeledOutput  # the labeled prose actually surfaced to humans
    eval_report: EvalReport

    def __post_init__(self) -> None:
        if not self.eval_report.passed:
            raise ValueError(
                "ExplainedFinding requires a PASSING EvalReport — an ungrounded "
                "explanation is unrepresentable here"
            )


@dataclass(frozen=True)
class RejectedExplanation:
    """A finding whose explanation FAILED grounding and was dropped.

    The finding still stands (flags never depend on prose); only the
    explanation is withheld. ``eval_report`` records exactly why.
    """

    finding: AnomalyFinding
    eval_report: EvalReport
    reason: str


@dataclass(frozen=True)
class ExplanationBatch:
    explained: tuple[ExplainedFinding, ...]
    rejected: tuple[RejectedExplanation, ...]


def _numeric_leaves(node: Any) -> list[str]:
    """Numeric strings present in a detail JSON tree, verbatim.

    Collects string leaves that parse as Decimal and int leaves (rendered
    via str). Booleans and non-numeric strings are skipped. Nothing is
    computed — this is extraction of numbers the calc library persisted.
    """
    leaves: list[str] = []
    if isinstance(node, Mapping):
        for value in node.values():
            leaves.extend(_numeric_leaves(value))
    elif isinstance(node, (list, tuple)):
        for value in node:
            leaves.extend(_numeric_leaves(value))
    elif isinstance(node, bool):
        pass
    elif isinstance(node, int):
        leaves.append(str(node))
    elif isinstance(node, str) and normalize_number(node) is not None:
        leaves.append(node)
    return leaves


def allowed_numbers_for_rows(rows: Iterable[HistoryRow]) -> tuple[str, ...]:
    """The complete allowed-numbers set for explanations of these rows.

    Every entry is copied verbatim from row data: the ``value`` strings,
    numeric leaves of the persisted ``detail`` JSON, and the components of
    the period dates (an ISO date like ``2026-05-01`` contributes
    ``2026``, ``05``, ``01``). Nothing here is calculated; any number a
    draft uses that is NOT in this set is a fabrication by definition.
    """
    allowed: list[str] = []
    for row in rows:
        allowed.append(row.value)
        allowed.extend(_numeric_leaves(row.detail))
        for period in (row.period_start, row.period_end):
            allowed.extend(part for part in period.split("-") if part.isdigit())
    # Deterministic order, deduplicated.
    return tuple(sorted(set(allowed)))


def _context_for(finding: AnomalyFinding, cited_rows: tuple[HistoryRow, ...]) -> dict[str, str]:
    """Provider context: role-keyed row facts, all values verbatim.

    Keys are role names ('previous_*', 'current_*'), never raw ids —
    citations live in the structured Claim fields, and ids inside prose
    would read as digit noise to the fabrication check.
    """
    context: dict[str, str] = {"metric": finding.metric, "issue_type": finding.issue_type}
    roles = ("previous", "current") if len(cited_rows) == 2 else tuple(
        f"row_{index}" for index in range(len(cited_rows))
    )
    for role, row in zip(roles, cited_rows):
        context[f"{role}_value"] = row.value
        context[f"{role}_period_start"] = row.period_start
        context[f"{role}_period_end"] = row.period_end
        context[f"{role}_calc_version"] = row.calc_version
        if row.coverage is not None:
            context[f"{role}_coverage"] = row.coverage
    return context


def _evidence_claim(row: HistoryRow) -> Claim:
    """Deterministic per-row evidence claim; numbers verbatim from the row."""
    numeric_values = [row.value]
    text = (
        f"The computed {row.metric} value for the period {row.period_start} "
        f"to {row.period_end} is {row.value} (calculation version "
        f"{row.calc_version})."
    )
    if row.coverage is not None:
        text += f" Its recorded input coverage is {row.coverage}."
        numeric_values.append(row.coverage)
    return Claim(
        text=text,
        cited_record_kind="computed.metric_values",
        cited_record_id=row.metric_value_id,
        numeric_values=tuple(numeric_values),
    )


def build_draft(
    finding: AnomalyFinding,
    cited_rows: tuple[HistoryRow, ...],
    output: LabeledOutput,
) -> GroundedDraft:
    """Assemble the draft the grounding gate will judge.

    Claim 1 carries the provider's labeled prose (so every token the model
    produced is fabrication-checked), cited to the finding's current row;
    one deterministic evidence claim follows per cited row, so EVERY
    compared metric_value_id is citation-checked. Declared numeric_values
    are only strings copied verbatim from the cited rows.
    """
    prose_numeric_values = tuple(
        dict.fromkeys(
            value
            for row in cited_rows
            for value in ([row.value] + ([row.coverage] if row.coverage is not None else []))
        )
    )
    prose_claim = Claim(
        text=output.text,
        cited_record_kind="computed.metric_values",
        cited_record_id=cited_rows[-1].metric_value_id,
        numeric_values=prose_numeric_values,
    )
    return GroundedDraft(
        claims=(prose_claim,) + tuple(_evidence_claim(row) for row in cited_rows),
        provider_name=output.provider_name,
        provider_version=output.provider_version,
    )


def explain_findings(
    conn: Any,
    findings: Iterable[AnomalyFinding],
    rows: Iterable[Mapping[str, Any]],
    *,
    provider: Provider | None = None,
) -> ExplanationBatch:
    """Explain each finding — grounded and labeled, or not at all.

    ``conn`` is the injected read-only connection the citation check runs
    against (this function never writes). A finding citing a
    metric_value_id absent from ``rows`` fails loudly (ValueError): an
    explanation can only be built from the very rows the detector compared.

    Returns an :class:`ExplanationBatch`: ``explained`` carries drafts that
    PASSED :func:`headway_ai.grounding.evaluate`; ``rejected`` carries the
    dropped ones, each with the failing EvalReport and an ERROR log line
    already emitted. Nothing ungrounded is ever returned as explained.
    """
    active_provider: Provider = provider if provider is not None else StubProvider()
    history = normalize_history(rows)
    rows_by_id = {row.metric_value_id: row for row in history}

    explained: list[ExplainedFinding] = []
    rejected: list[RejectedExplanation] = []
    for finding in findings:
        missing = [mvid for mvid in finding.cited_metric_value_ids if mvid not in rows_by_id]
        if missing:
            raise ValueError(
                f"finding {finding.issue_type} cites metric_value_id(s) {missing} "
                "absent from the supplied history rows — cannot ground an "
                "explanation on rows the detector never saw"
            )
        cited_rows = tuple(rows_by_id[mvid] for mvid in finding.cited_metric_value_ids)
        output = active_provider.generate(
            _PROMPT_TEMPLATE.format(issue_type=finding.issue_type, metric=finding.metric),
            _context_for(finding, cited_rows),
        )
        draft = build_draft(finding, cited_rows, output)
        report = evaluate(conn, draft, allowed_numbers_for_rows(cited_rows))
        if report.passed:
            explained.append(
                ExplainedFinding(finding=finding, draft=draft, output=output, eval_report=report)
            )
        else:
            reason = (
                f"grounding FAILED (citation_resolution_rate="
                f"{report.citation_resolution_rate}, fabricated_number_count="
                f"{report.fabricated_number_count})"
            )
            logger.error(
                "DROPPING ungrounded anomaly explanation for %s on metric %s "
                "(cited %s): %s. The finding still stands and is emitted "
                "WITHOUT an explanation — an ungrounded sentence is never surfaced.",
                finding.issue_type,
                finding.metric,
                ",".join(finding.cited_metric_value_ids),
                reason,
            )
            rejected.append(
                RejectedExplanation(finding=finding, eval_report=report, reason=reason)
            )
    return ExplanationBatch(explained=tuple(explained), rejected=tuple(rejected))
