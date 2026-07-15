import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, listDqIssues, resolveDqIssue } from "../api/client";
import type { DqIssue } from "../api/types";
import { canResolveDqIssues, useSession } from "../auth/session";
import { SeverityIcon } from "../components/SeverityIcon";
import { SummaryCards } from "../components/SummaryCards";
import { copy } from "../copy";
import { pushToast } from "../toasts";

/**
 * The data-quality issue queue. Fail-loudly is the point: every issue is
 * shown with its severity (text + icon + color — never color alone), owner,
 * and status; blocking issues are visually prominent; nothing is hidden or
 * auto-dismissed. Resolving requires the data-steward role or above — that
 * check here is UX only, the API enforces it.
 *
 * The queue-at-a-glance header (2026-07-11 click-through, finding 2): stat
 * chips (text + count + severity color, never color alone) plus severity and
 * status filter toggles (aria-pressed) so a steward can see blocking-only in
 * one click. Counts are workflow tallies of ISSUES — not regulatory figures —
 * computed client-side from the list GET /dq/issues serves. That endpoint
 * returns the ENTIRE queue today (no pagination), so the counts cover
 * everything; if the API ever paginates, these counts must move server-side.
 * Filtering hides nothing from the counts, and the showing-line states how
 * many issues the filters are holding back — an issue is never made to look
 * resolved (or gone) by a filter.
 */
export function DqView() {
  const session = useSession();
  const [issues, setIssues] = useState<DqIssue[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** null = no filter (all). */
  const [severityFilter, setSeverityFilter] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);

  useEffect(() => {
    listDqIssues()
      .then(setIssues)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : String(err)),
      );
  }, []);

  // Documented-effort total: UI ARITHMETIC ON EFFORT METADATA (the minutes
  // stewards typed into the resolve form) — a workflow tally like the issue
  // counts, NEVER a reported regulatory figure (those are displayed verbatim
  // from the API and never computed client-side). Sum of minutes / 60, one
  // decimal.
  const totalEffortMinutes = (issues ?? []).reduce(
    (sum, i) =>
      sum + (typeof i.resolution_minutes === "number" ? i.resolution_minutes : 0),
    0,
  );
  const effortHours = (totalEffortMinutes / 60).toFixed(1);

  const handleResolved = (updated: DqIssue) => {
    setIssues(
      (prev) =>
        prev?.map((i) => (i.issue_id === updated.issue_id ? updated : i)) ??
        null,
    );
    // The shell-wide confirmation pattern (handoff 0017 #4).
    pushToast(copy.dq.resolveSuccess(updated.title));
  };

  const mayResolve = canResolveDqIssues(session);

  // Queue tallies (issue counts, not regulatory figures; full list — see
  // the component comment). "Open" means status open or owned: 'resolved'
  // and 'attested' (migration 0029 — the p. 146 statistician closure) are
  // both CLOSED states, exactly as the certification gate counts them.
  const all = issues ?? [];
  const countBy = (severity: string) =>
    all.filter(
      (i) =>
        i.severity === severity &&
        (i.status === "open" || i.status === "owned"),
    ).length;
  const resolvedCount = all.filter((i) => i.status === "resolved").length;

  const filtered = all.filter(
    (i) =>
      (severityFilter === null || i.severity === severityFilter) &&
      (statusFilter === null || i.status === statusFilter),
  );
  const filtersActive = severityFilter !== null || statusFilter !== null;
  // Render cap (2026-07-14 live finding: 35,456 live issues hung the tab).
  // STATED, never silent: the counts cover the whole queue, the cap line
  // says exactly how many cards are drawn, and filtering narrows the list.
  const shown = filtered.slice(0, DQ_RENDER_CAP);

  return (
    <>
      <h1>{copy.dq.heading}</h1>
      <p>{copy.dq.intro}</p>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {!issues && !error && <p>{copy.loading}</p>}
      {issues && issues.length === 0 && <p>{copy.dq.empty}</p>}
      {issues && issues.length > 0 && (
        <>
          <section aria-label={copy.dq.summaryHeading} className="dq-summary">
            <h2>{copy.dq.summaryHeading}</h2>
            {/* Summary cards ARE the filter toggles (handoff 0017 #2):
                count + colored top border + label, aria-pressed. The three
                severity cards toggle the severity filter; the Resolved card
                toggles the status filter to resolved. Counts always cover
                the whole queue — filtering hides nothing from them. */}
            <SummaryCards
              label={copy.dq.severityFilterLabel}
              cards={[
                {
                  key: "blocking",
                  label: copy.dq.cardLabels.blocking,
                  count: formatCount(countBy("blocking")),
                  tone: "danger",
                  pressed: severityFilter === "blocking",
                  icon: <SeverityIcon severity="blocking" />,
                },
                {
                  key: "warning",
                  label: copy.dq.cardLabels.warning,
                  count: formatCount(countBy("warning")),
                  tone: "warning",
                  pressed: severityFilter === "warning",
                  icon: <SeverityIcon severity="warning" />,
                },
                {
                  key: "info",
                  label: copy.dq.cardLabels.info,
                  count: formatCount(countBy("info")),
                  tone: "info",
                  pressed: severityFilter === "info",
                  icon: <SeverityIcon severity="info" />,
                },
                {
                  key: "resolved",
                  label: copy.dq.cardLabels.resolved,
                  count: formatCount(resolvedCount),
                  tone: "success",
                  pressed: statusFilter === "resolved",
                },
              ]}
              onToggle={(key, pressed) => {
                if (key === "resolved") {
                  setStatusFilter(pressed ? "resolved" : null);
                } else {
                  setSeverityFilter(pressed ? key : null);
                }
              }}
            />
            {totalEffortMinutes > 0 && (
              <ul className="dq-chips">
                <li className="chip effort">
                  {copy.dq.summaryEffort(effortHours)}
                </li>
              </ul>
            )}
            <FilterBar
              label={copy.dq.statusFilterLabel}
              allLabel={copy.dq.filterAllStatuses}
              options={copy.dq.statusLabels}
              value={statusFilter}
              onChange={setStatusFilter}
            />
            {filtersActive && (
              <p className="dq-showing">
                {copy.dq.showingCount(
                  formatCount(filtered.length),
                  formatCount(all.length),
                )}
              </p>
            )}
          </section>
          {filtered.length === 0 ? (
            <div className="banner">
              <p>{copy.dq.noMatch(formatCount(all.length))}</p>
              <button
                type="button"
                onClick={() => {
                  setSeverityFilter(null);
                  setStatusFilter(null);
                }}
              >
                {copy.dq.clearFilters}
              </button>
            </div>
          ) : (
            <>
              {filtered.length > DQ_RENDER_CAP && (
                <p className="banner">
                  {copy.dq.renderCap(
                    formatCount(DQ_RENDER_CAP),
                    formatCount(filtered.length),
                  )}
                </p>
              )}
              <ul className="issue-list">
                {shown.map((issue) => (
                  <IssueCard
                    key={issue.issue_id}
                    issue={issue}
                    mayResolve={mayResolve}
                    onResolved={handleResolved}
                  />
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </>
  );
}

/**
 * Queue tallies for display: thousands-separated ("8,824"). These are counts
 * of workflow issues this component made itself — never a regulatory figure,
 * which would be displayed verbatim from the API instead.
 */
function formatCount(count: number): string {
  return count.toLocaleString("en-US");
}

/** How many issue CARDS are drawn at once (the counts cover everything). */
const DQ_RENDER_CAP = 200;

interface FilterBarProps {
  label: string;
  allLabel: string;
  /** value -> visible label, in display order. */
  options: Record<string, string>;
  value: string | null;
  onChange: (value: string | null) => void;
}

/**
 * One row of filter toggles (severity or status). Plain buttons with
 * aria-pressed: the pressed one is the only filled one AND keeps its text
 * label, so the selection is never conveyed by color alone.
 */
function FilterBar({ label, allLabel, options, value, onChange }: FilterBarProps) {
  return (
    <div className="filter-bar" role="group" aria-label={label}>
      <span className="filter-bar-label">{label}:</span>
      <button
        type="button"
        aria-pressed={value === null}
        onClick={() => onChange(null)}
      >
        {allLabel}
      </button>
      {Object.entries(options).map(([key, optionLabel]) => (
        <button
          key={key}
          type="button"
          aria-pressed={value === key}
          onClick={() => onChange(value === key ? null : key)}
        >
          {optionLabel}
        </button>
      ))}
    </div>
  );
}

/** Text + icon + color: never color alone (WCAG 1.4.1). */
function SeverityBadge({ severity }: { severity: string }) {
  const label = copy.dq.severityLabels[severity] ?? severity;
  const known = severity in copy.dq.severityLabels;
  return (
    <span className={`severity ${known ? severity : "info"}`}>
      <SeverityIcon severity={severity} />
      {label}
    </span>
  );
}

interface IssueCardProps {
  issue: DqIssue;
  mayResolve: boolean;
  onResolved: (updated: DqIssue) => void;
}

function IssueCard({ issue, mayResolve, onResolved }: IssueCardProps) {
  const headingId = useId();
  const isBlocking = issue.severity === "blocking";
  // Two closed states (migration 0029): 'resolved', and 'attested' — the
  // p. 146 statistician closure. A closed issue no longer blocks and takes
  // no resolve form, but it stays fully visible with its resolution story.
  const isClosed = issue.status === "resolved" || issue.status === "attested";

  return (
    <li>
      <article
        className={`issue${isBlocking ? " blocking" : ""}`}
        aria-labelledby={headingId}
      >
        <h2 id={headingId}>{issue.title}</h2>
        <p>
          <SeverityBadge severity={issue.severity} />{" "}
          {isBlocking && !isClosed && <strong>{copy.dq.blockingNote}</strong>}
        </p>
        <p>{issue.description}</p>
        <dl>
          <dt>{copy.dq.statusLabel}</dt>
          <dd>{issue.status}</dd>
          <dt>{copy.dq.ownerLabel}</dt>
          <dd>{issue.owner ?? copy.dq.ownerUnassigned}</dd>
          <dt>{copy.dq.createdLabel}</dt>
          <dd>{issue.created_at}</dd>
          {issue.source_record_ids && issue.source_record_ids.length > 0 && (
            <>
              <dt>{copy.dq.sourceRecordsLabel}</dt>
              <dd>{issue.source_record_ids.join(", ")}</dd>
            </>
          )}
          {isClosed && issue.resolved_at !== null && (
            <>
              <dt>{copy.dq.resolvedLabel}</dt>
              <dd>{issue.resolved_at}</dd>
              <dt>{copy.dq.resolutionLabel}</dt>
              <dd>{issue.resolution}</dd>
              {issue.resolution_minutes != null && (
                <>
                  <dt>{copy.dq.minutesSpentLabel}</dt>
                  {/* Effort metadata (workflow minutes), not a figure. */}
                  <dd>
                    {copy.dq.minutesSpentValue(
                      formatCount(issue.resolution_minutes),
                    )}
                  </dd>
                </>
              )}
            </>
          )}
        </dl>
        {mayResolve && !isClosed && (
          <ResolveForm issue={issue} onResolved={onResolved} />
        )}
      </article>
    </li>
  );
}

interface ResolveFormProps {
  issue: DqIssue;
  onResolved: (updated: DqIssue) => void;
}

function ResolveForm({ issue, onResolved }: ResolveFormProps) {
  const inputId = useId();
  const hintId = useId();
  const minutesId = useId();
  const minutesHintId = useId();
  const [open, setOpen] = useState(false);
  const [resolution, setResolution] = useState("");
  const [minutes, setMinutes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (resolution.trim().length === 0) {
      setError(copy.dq.resolutionRequired);
      return;
    }
    // Optional effort field: blank is fine; anything typed must be a whole
    // number of minutes (this is workflow metadata a person typed, so the
    // form validates it — it is never a served figure).
    const trimmedMinutes = minutes.trim();
    let resolutionMinutes: number | undefined;
    if (trimmedMinutes !== "") {
      if (!/^\d+$/.test(trimmedMinutes) || Number(trimmedMinutes) === 0) {
        setError(copy.dq.minutesInvalid);
        return;
      }
      resolutionMinutes = Number(trimmedMinutes);
    }
    setError(null);
    setSubmitting(true);
    try {
      const response = await resolveDqIssue(issue.issue_id, {
        resolution,
        ...(resolutionMinutes !== undefined && {
          resolution_minutes: resolutionMinutes,
        }),
      });
      onResolved({
        ...issue,
        status: response.status,
        resolved_at: response.resolved_at,
        resolution: response.resolution,
        resolution_minutes: response.resolution_minutes ?? null,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}>
        {copy.dq.resolveButton(issue.title)}
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit}>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <label htmlFor={inputId}>{copy.dq.resolutionInputLabel}</label>
      <p id={hintId}>{copy.dq.resolutionHint}</p>
      <textarea
        id={inputId}
        aria-describedby={hintId}
        value={resolution}
        onChange={(e) => setResolution(e.target.value)}
      />
      <label htmlFor={minutesId}>{copy.dq.minutesLabel}</label>
      <p id={minutesHintId}>{copy.dq.minutesHint}</p>
      <input
        id={minutesId}
        type="text"
        inputMode="numeric"
        aria-describedby={minutesHintId}
        value={minutes}
        onChange={(e) => setMinutes(e.target.value)}
      />
      <button type="submit" className="primary" disabled={submitting}>
        {copy.dq.submitResolution}
      </button>{" "}
      <button type="button" onClick={() => setOpen(false)}>
        {copy.dq.cancelResolution}
      </button>
    </form>
  );
}
