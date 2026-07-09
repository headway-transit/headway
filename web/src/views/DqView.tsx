import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, listDqIssues, resolveDqIssue } from "../api/client";
import type { DqIssue } from "../api/types";
import { canResolveDqIssues, useSession } from "../auth/session";
import { copy } from "../copy";

/**
 * The data-quality issue queue. Fail-loudly is the point: every issue is
 * shown with its severity (text + icon + color — never color alone), owner,
 * and status; blocking issues are visually prominent; nothing is hidden or
 * auto-dismissed. Resolving requires the data-steward role or above — that
 * check here is UX only, the API enforces it.
 */
export function DqView() {
  const session = useSession();
  const [issues, setIssues] = useState<DqIssue[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState<string | null>(null);

  useEffect(() => {
    listDqIssues()
      .then(setIssues)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : String(err)),
      );
  }, []);

  const handleResolved = (updated: DqIssue) => {
    setIssues(
      (prev) =>
        prev?.map((i) => (i.issue_id === updated.issue_id ? updated : i)) ??
        null,
    );
    setAnnouncement(copy.dq.resolveSuccess(updated.title));
  };

  const mayResolve = canResolveDqIssues(session);

  return (
    <>
      <h1>{copy.dq.heading}</h1>
      <p>{copy.dq.intro}</p>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {announcement && (
        <div role="status" className="status">
          {announcement}
        </div>
      )}
      {!issues && !error && <p>{copy.loading}</p>}
      {issues && issues.length === 0 && <p>{copy.dq.empty}</p>}
      {issues && issues.length > 0 && (
        <ul className="issue-list">
          {issues.map((issue) => (
            <IssueCard
              key={issue.issue_id}
              issue={issue}
              mayResolve={mayResolve}
              onResolved={handleResolved}
            />
          ))}
        </ul>
      )}
    </>
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

function SeverityIcon({ severity }: { severity: string }) {
  // Decorative (aria-hidden): the adjacent text carries the meaning. Distinct
  // SHAPES per severity so the encoding survives without color.
  const common = {
    "aria-hidden": true,
    width: 14,
    height: 14,
    viewBox: "0 0 16 16",
    fill: "currentColor",
  } as const;
  if (severity === "blocking") {
    // octagon (stop)
    return (
      <svg {...common}>
        <polygon points="5,1 11,1 15,5 15,11 11,15 5,15 1,11 1,5" />
      </svg>
    );
  }
  if (severity === "warning") {
    // triangle
    return (
      <svg {...common}>
        <polygon points="8,1 15,15 1,15" />
      </svg>
    );
  }
  // circle (info / unknown)
  return (
    <svg {...common}>
      <circle cx="8" cy="8" r="7" />
    </svg>
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
  const isResolved = issue.status === "resolved";

  return (
    <li>
      <article
        className={`issue${isBlocking ? " blocking" : ""}`}
        aria-labelledby={headingId}
      >
        <h2 id={headingId}>{issue.title}</h2>
        <p>
          <SeverityBadge severity={issue.severity} />{" "}
          {isBlocking && !isResolved && <strong>{copy.dq.blockingNote}</strong>}
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
          {isResolved && (
            <>
              <dt>{copy.dq.resolvedLabel}</dt>
              <dd>{issue.resolved_at}</dd>
              <dt>{copy.dq.resolutionLabel}</dt>
              <dd>{issue.resolution}</dd>
            </>
          )}
        </dl>
        {mayResolve && !isResolved && (
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
  const [open, setOpen] = useState(false);
  const [resolution, setResolution] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (resolution.trim().length === 0) {
      setError(copy.dq.resolutionRequired);
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const response = await resolveDqIssue(issue.issue_id, { resolution });
      onResolved({
        ...issue,
        status: response.status,
        resolved_at: response.resolved_at,
        resolution: response.resolution,
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
      <button type="submit" className="primary" disabled={submitting}>
        {copy.dq.submitResolution}
      </button>{" "}
      <button type="button" onClick={() => setOpen(false)}>
        {copy.dq.cancelResolution}
      </button>
    </form>
  );
}
