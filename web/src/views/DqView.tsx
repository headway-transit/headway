import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ApiError,
  attestDqIssue,
  getDqIssue,
  getDqIssueCounts,
  listAttestations,
  listDqIssues,
  resolveDqIssue,
} from "../api/client";
import type {
  AttestationRecord,
  DqIssue,
  DqIssueCounts,
  DqIssuePage,
  DqIssueSummary,
  DqSubjectContext,
  DqSubjectGroup,
} from "../api/types";
import { canResolveDqIssues, useSession } from "../auth/session";
import { Modal } from "../components/Modal";
import { QuoteFigure } from "../components/QuoteFigure";
import { SeverityIcon } from "../components/SeverityIcon";
import { Skeleton } from "../components/Skeleton";
import { SummaryCards } from "../components/SummaryCards";
import { copy } from "../copy";
import { quoteContaining } from "../regulatory/quotes";
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
 * one click. Counts are workflow tallies of ISSUES — not regulatory figures.
 *
 * Since handoff 0024 (consuming 0023's rewritten counts endpoint) the
 * header counts are SERVER-side: GET /dq/issues/counts counts over exactly
 * the rows GET /dq/issues serves under the same filters (the 0017
 * cards-match-table guarantee), and it answers in milliseconds over the
 * live queue.
 *
 * Handoff 0030 — THE QUEUE IS READ ONE PAGE AT A TIME. Until this wave the
 * screen downloaded every issue: measured live at 98,497 issues, 850 MB,
 * 17 seconds, and a frozen tab. Three rules hold it honest:
 *
 *  1. The summary cards are always the SERVER's whole-queue counts, never a
 *     tally of the loaded page, and the copy says so in words under them.
 *  2. The filters run on the SERVER. Filtering the loaded page would put a
 *     card reading "8,824 blocking" above two visible rows.
 *  3. The page line states which issues are on screen and how many match in
 *     total, so the visible rows are never mistaken for the queue.
 *
 * Provenance moved with the same discipline: `source_record_ids` is no
 * longer in the queue rows (716 MB of that 850 MB), so each card fetches
 * it from GET /dq/issues/{id} when a reader opens the disclosure. Every
 * row still has the path from a finding back to its raw records.
 */
export function DqView() {
  const session = useSession();
  // Deep link (handoff 0026): /dq?issue=<id> — a calculation refusal links
  // straight to the exact finding that blocked it. The linked finding is
  // rendered prominently above the queue; an unknown id is stated plainly,
  // never silently ignored.
  const [searchParams] = useSearchParams();
  const linkedIssueId = searchParams.get("issue");
  // The linked finding is fetched DIRECTLY (GET /dq/issues/{id}) so it
  // renders immediately — the whole-queue list download (97k issues live)
  // must never gate the link a refusal handed the user.
  const [linkedIssue, setLinkedIssue] = useState<DqIssue | null>(null);
  const [linkedError, setLinkedError] = useState<string | null>(null);
  /**
   * The page on screen: its rows, what it is not showing, AND which page
   * number it actually is. The index rides WITH the rows (set in the same
   * state update) so the "Showing issues N–M" line can never get ahead of
   * the list — during a fetch the old page keeps its own true range
   * instead of the next page's range appearing over the old rows.
   */
  const [view, setView] = useState<{
    page: DqIssuePage;
    index: number;
  } | null>(null);
  const [pageLoading, setPageLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /**
   * Where we are in the keyset walk. `cursors[n]` is the cursor that
   * fetches page n (page 0 needs none), so "Previous" is a step back
   * through markers this client already holds — no server round trip is
   * needed to know where it has been, and no page can be skipped.
   */
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [pageIndex, setPageIndex] = useState(0);
  // Whole-queue tallies from the server: unresolved severity split needs
  // open + owned (their by_severity covers exactly the unresolved rows);
  // the unfiltered call carries the by_status totals (resolved etc.).
  const [countsOpen, setCountsOpen] = useState<DqIssueCounts | null>(null);
  const [countsOwned, setCountsOwned] = useState<DqIssueCounts | null>(null);
  const [countsAll, setCountsAll] = useState<DqIssueCounts | null>(null);
  const [countsError, setCountsError] = useState<string | null>(null);
  /** null = no filter (all). */
  const [severityFilter, setSeverityFilter] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);

  // The three server counts: cheap since 0023 (SQL GROUP BY), refetched
  // after every workflow action so the cards stay the SERVER's tallies —
  // never a client-side adjustment.
  const refreshCounts = () => {
    const onCountsError = (err: unknown) =>
      setCountsError(err instanceof ApiError ? err.message : String(err));
    getDqIssueCounts("open").then(setCountsOpen).catch(onCountsError);
    getDqIssueCounts("owned").then(setCountsOwned).catch(onCountsError);
    getDqIssueCounts().then(setCountsAll).catch(onCountsError);
  };

  // One page, from the server, under the CURRENT filters. Refetched when a
  // filter changes or the reader moves a page — the filters and the paging
  // both live where the rows are.
  useEffect(() => {
    let stale = false;
    setPageLoading(true);
    listDqIssues({
      ...(statusFilter !== null && { status: statusFilter }),
      ...(severityFilter !== null && { severity: severityFilter }),
      limit: DQ_PAGE_SIZE,
      ...(cursors[pageIndex] !== null && { cursor: cursors[pageIndex]! }),
    })
      .then((next) => {
        if (stale) return;
        setView({ page: next, index: pageIndex });
        setError(null);
        // Remember the marker for the page after this one, so Next is a
        // step forward and Previous a step back through markers already
        // held. A page can be neither skipped nor served twice.
        if (next.next_cursor !== null) {
          setCursors((prev) => {
            const grown = prev.slice(0, pageIndex + 1);
            grown.push(next.next_cursor);
            return grown;
          });
        }
      })
      .catch((err) => {
        if (stale) return;
        setError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => {
        if (!stale) setPageLoading(false);
      });
    return () => {
      stale = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, severityFilter, pageIndex]);

  useEffect(() => {
    refreshCounts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (linkedIssueId === null) {
      setLinkedIssue(null);
      setLinkedError(null);
      return;
    }
    getDqIssue(linkedIssueId)
      .then((issue) => {
        setLinkedIssue(issue);
        setLinkedError(null);
      })
      .catch((err) =>
        // The server's 404 (or any refusal) verbatim — an unknown id is
        // stated plainly, never silently ignored.
        setLinkedError(err instanceof ApiError ? err.message : String(err)),
      );
  }, [linkedIssueId]);

  // Documented-effort total: EFFORT METADATA (the minutes stewards typed
  // into the resolve form) — a workflow tally like the issue counts, NEVER
  // a reported regulatory figure. Summed BY THE SERVER over the whole
  // queue since handoff 0030: with one page loaded, summing the rows on
  // screen would have quietly turned "hours of documented work" into
  // "hours on the 50 issues you can see".
  const totalEffortMinutes = countsAll?.resolution_minutes_total ?? 0;
  const effortHours = (totalEffortMinutes / 60).toFixed(1);

  const replaceOnPage = (updated: DqIssueSummary) =>
    setView((prev) =>
      prev === null
        ? null
        : {
            ...prev,
            page: {
              ...prev.page,
              issues: prev.page.issues.map((i) =>
                i.issue_id === updated.issue_id ? updated : i,
              ),
            },
          },
    );

  const handleResolved = (updated: DqIssueSummary) => {
    replaceOnPage(updated);
    // The shell-wide confirmation pattern (handoff 0017 #4).
    pushToast(copy.dq.resolveSuccess(updated.title));
    // The header cards are SERVER counts — recount, never adjust locally.
    refreshCounts();
  };

  const handleAttested = (updated: DqIssueSummary) => {
    replaceOnPage(updated);
    pushToast(copy.dq.attest.success(updated.title));
    refreshCounts();
  };

  /** Any filter change restarts the walk — a cursor is a position in one
   *  ordering, and carrying it across a different filter would land the
   *  reader in the middle of a queue they have not seen the start of. */
  const changeSeverityFilter = (next: string | null) => {
    setSeverityFilter(next);
    setCursors([null]);
    setPageIndex(0);
  };
  const changeStatusFilter = (next: string | null) => {
    setStatusFilter(next);
    setCursors([null]);
    setPageIndex(0);
  };

  const mayResolve = canResolveDqIssues(session);

  // SERVER-side queue tallies (workflow counts, never regulatory figures).
  // "Open" means status open or owned: 'resolved' and 'attested'
  // (migration 0029 — the p. 146 statistician closure) are both CLOSED
  // states, exactly as the certification gate counts them. Adding the
  // open and owned per-severity counts is a tally of two disjoint
  // server-counted sets — the same composition /today's blocker line uses.
  const countsReady = countsOpen !== null && countsOwned !== null;
  const countBy = (severity: string) =>
    (countsOpen?.by_severity[severity] ?? 0) +
    (countsOwned?.by_severity[severity] ?? 0);
  const resolvedCount = countsAll?.by_status.resolved ?? 0;
  // Empty queue: the server's whole-queue total when we have it; the
  // page's own whole-queue total as the fallback when the counts call
  // failed. Neither is a count of the rows on screen.
  const anyFilter = severityFilter !== null || statusFilter !== null;
  const page = view?.page ?? null;
  const queueEmpty =
    countsAll !== null
      ? countsAll.total === 0
      : page !== null && page.total === 0 && !anyFilter;

  // What this page holds, said in the queue's own numbering — numbered by
  // the index the DISPLAYED rows belong to (view.index), never by where
  // the reader has clicked to (pageIndex): while the next page is in
  // flight the old rows keep their own true range. The ordering is
  // oldest-first and new findings land at the END, so a row's position
  // does not shift under a reader while a calc run is writing.
  const shown = page?.issues ?? [];
  const matching = page?.total ?? 0;
  const rangeFrom = (view?.index ?? 0) * DQ_PAGE_SIZE + 1;
  const rangeTo = (view?.index ?? 0) * DQ_PAGE_SIZE + shown.length;

  return (
    <>
      <h1>{copy.dq.heading}</h1>
      <p>{copy.dq.intro}</p>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {/* A counts failure is stated verbatim — the cards never silently
          vanish into a clean-looking header. */}
      {countsError && (
        <div role="alert" className="alert">
          {countsError}
        </div>
      )}
      {/* The linked finding (handoff 0026), above the queue — fetched
          directly by id, so it paints without waiting for the whole-queue
          download. An unknown id renders the server's own words. */}
      {linkedIssueId !== null && linkedError !== null && (
        <div role="alert" className="alert">
          {copy.dq.linked.notFound(linkedIssueId)} {linkedError}
        </div>
      )}
      {linkedIssue !== null && (
        <section aria-label={copy.dq.linked.heading} className="dq-linked">
          <h2>{copy.dq.linked.heading}</h2>
          <p>{copy.dq.linked.intro}</p>
          <ul className="issue-list">
            <IssueCard
              issue={linkedIssue}
              mayResolve={mayResolve}
              onResolved={(updated) => {
                // Keep the linked card's provenance array: the update is a
                // queue-shaped row, the linked finding a full detail row.
                setLinkedIssue((prev) =>
                  prev === null ? prev : { ...prev, ...updated },
                );
                handleResolved(updated);
              }}
              onAttested={(updated) => {
                setLinkedIssue((prev) =>
                  prev === null ? prev : { ...prev, ...updated },
                );
                handleAttested(updated);
              }}
            />
          </ul>
        </section>
      )}
      {queueEmpty && <p>{copy.dq.empty}</p>}
      {/* The queue-at-a-glance header paints from the SERVER counts the
          moment they land (milliseconds since handoff 0023) — the 41k-row
          list download no longer holds the whole page hostage. */}
      {!countsReady && !countsError && !queueEmpty && (
        <Skeleton variant="cards" count={4} />
      )}
      {!queueEmpty && (countsReady || (page !== null && page.total > 0)) && (
        <>
          <section aria-label={copy.dq.summaryHeading} className="dq-summary">
            <h2>{copy.dq.summaryHeading}</h2>
            {/* Summary cards ARE the filter toggles (handoff 0017 #2):
                count + colored top border + label, aria-pressed. The three
                severity cards toggle the severity filter; the Resolved card
                toggles the status filter to resolved. Counts cover the
                WHOLE queue (server-counted over exactly the rows the list
                endpoint serves) — filtering hides nothing from them. */}
            {countsReady && (
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
                  changeStatusFilter(pressed ? "resolved" : null);
                } else {
                  changeSeverityFilter(pressed ? key : null);
                }
              }}
            />
            )}
            {/* The distinction the whole screen turns on, said in words
                rather than left to be inferred (handoff 0030): the cards
                are the WHOLE queue; the list below is one page of it. */}
            {countsAll !== null && (
              <p className="dq-showing">
                {copy.dq.summaryScope(formatCount(countsAll.total))}
              </p>
            )}
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
              onChange={changeStatusFilter}
            />
          </section>
          {/* Skeleton (handoff 0021 #2): the LIST's shape while its page
              is in flight — now milliseconds, not the multi-second
              whole-queue download this screen used to start with. */}
          {page === null && !error && <Skeleton variant="table" count={5} />}
          {page !== null && (page.total === 0 ? (
            <div className="banner">
              <p>
                {copy.dq.noMatch(formatCount(countsAll?.total ?? 0))}
              </p>
              <button
                type="button"
                onClick={() => {
                  changeSeverityFilter(null);
                  changeStatusFilter(null);
                }}
              >
                {copy.dq.clearFilters}
              </button>
            </div>
          ) : (
            <>
              {/* Which issues are on screen, and how many match in total.
                  Never "showing 50 issues" full stop — that sentence would
                  let the page pass for the queue. */}
              <p className="dq-showing">
                {anyFilter
                  ? copy.dq.showingRange(
                      formatCount(rangeFrom),
                      formatCount(rangeTo),
                      formatCount(matching),
                    )
                  : copy.dq.showingRangeUnfiltered(
                      formatCount(rangeFrom),
                      formatCount(rangeTo),
                      formatCount(matching),
                    )}
              </p>
              <ul className="issue-list">
                {shown.map((issue) => (
                  <IssueCard
                    key={issue.issue_id}
                    issue={issue}
                    mayResolve={mayResolve}
                    onResolved={handleResolved}
                    onAttested={handleAttested}
                  />
                ))}
              </ul>
              <nav className="dq-pager" aria-label={copy.dq.pageNavLabel}>
                <button
                  type="button"
                  onClick={() => setPageIndex((n) => Math.max(0, n - 1))}
                  disabled={pageIndex === 0 || pageLoading}
                >
                  {copy.dq.pagePrevious}
                </button>{" "}
                <button
                  type="button"
                  onClick={() => setPageIndex((n) => n + 1)}
                  disabled={!page.has_more || pageLoading}
                >
                  {copy.dq.pageNext}
                </button>
                {/* Politely announced, never a silent swap of content. */}
                <span role="status">
                  {pageLoading ? copy.dq.pageLoading : ""}
                </span>
              </nav>
            </>
          ))}
        </>
      )}
    </>
  );
}

/**
 * Queue tallies for display: thousands-separated ("8,824"). Since handoff
 * 0024 the header tallies are the SERVER's own counts (GET
 * /dq/issues/counts) — this helper only formats them; it never originates
 * a regulatory figure, which would be displayed verbatim from the API.
 */
function formatCount(count: number): string {
  return count.toLocaleString("en-US");
}

/**
 * One page of the queue (handoff 0030). Matches the server's default; the
 * server enforces its own hard maximum of 200 regardless of what any
 * client asks for — an unbounded request is impossible, not discouraged.
 */
const DQ_PAGE_SIZE = 50;

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

/**
 * The one issue class with a statistician cure (handoff 0019): the calc's
 * p. 146 refusal — more than 2% of trips missing passenger counts. The
 * server enforces the same wall on POST /dq/issues/{id}/attest (any other
 * type is a 409 quoting the p. 149 no-smaller-sample rule); this constant
 * only decides where the affordance is OFFERED.
 */
const ATTESTABLE_ISSUE_TYPE = "apc_missing_trips_above_fta_threshold";

/** The p. 146 statistician sentence — the existing quote map (upt_v0 is
 *  the tracker's home for the rule), the AttestationsView discipline. */
const STATISTICIAN_QUOTE = quoteContaining(
  "upt_v0",
  "qualified statistician approve the factoring method",
);

interface IssueCardProps {
  /** A queue row (no provenance array — handoff 0030); the linked finding
   *  arrives as a full DqIssue, which is assignable. Provenance renders
   *  via the on-demand disclosure below either way. */
  issue: DqIssueSummary;
  mayResolve: boolean;
  onResolved: (updated: DqIssueSummary) => void;
  onAttested: (updated: DqIssueSummary) => void;
}

function IssueCard({ issue, mayResolve, onResolved, onAttested }: IssueCardProps) {
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
        <p className="issue-description">{issue.description}</p>
        {/* What the finding is ABOUT, in the agency's words (handoff 0029).
            Renders nothing at all when the API served no context — which is
            every finding raised before migration 0035 — so those issues look
            exactly as they always have. */}
        <SubjectContext context={issue.subject_context} />
        <dl>
          <dt>{copy.dq.statusLabel}</dt>
          <dd>{issue.status}</dd>
          <dt>{copy.dq.ownerLabel}</dt>
          <dd>{issue.owner ?? copy.dq.ownerUnassigned}</dd>
          <dt>{copy.dq.createdLabel}</dt>
          <dd>{issue.created_at}</dd>
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
        {/* Provenance on demand (handoff 0030): the raw-record ids left the
            queue payload (716 MB of the 850 MB whole-queue response) and
            are fetched from GET /dq/issues/{id} when a reader opens this.
            Every finding keeps its path back to the raw records. */}
        <SourceRecords issue={issue} />
        {mayResolve && !isClosed && (
          <>
            <ResolveForm issue={issue} onResolved={onResolved} />
            {/* The attest closure (handoff 0019 follow-up): offered ONLY
                on the p. 146 refusal class — the one gap a recorded
                statistician approval can close. Same role gate as
                resolving (data_steward+), mirroring the API exactly. */}
            {issue.issue_type === ATTESTABLE_ISSUE_TYPE && (
              <AttestControl issue={issue} onAttested={onAttested} />
            )}
          </>
        )}
      </article>
    </li>
  );
}

/**
 * The provenance disclosure (handoff 0030): "Source records" for one
 * finding, fetched from GET /dq/issues/{id} the first time a reader opens
 * it and never truncated once fetched.
 *
 * Why a fetch and not a field: the queue listing used to carry every
 * finding's raw-record ids — 716 MB of an 850 MB response, 11.5 million
 * identifiers, for a screen that renders 50 rows. The ids are lineage, not
 * list furniture; they now load for the one finding actually being worked.
 * A load failure is stated in the reader's face and can be retried — the
 * disclosure never quietly renders "no records" over an error.
 */
function SourceRecords({ issue }: { issue: DqIssueSummary }) {
  // undefined = not asked yet; null = asked, the finding cites no records.
  const [records, setRecords] = useState<string[] | null | undefined>(
    undefined,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    getDqIssue(issue.issue_id)
      .then((detail) => setRecords(detail.source_record_ids))
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : String(err)),
      )
      .finally(() => setLoading(false));
  };

  return (
    <details
      className="dq-source-records"
      onToggle={(event) => {
        if (
          (event.currentTarget as HTMLDetailsElement).open &&
          records === undefined &&
          !loading &&
          error === null
        ) {
          load();
        }
      }}
    >
      <summary>{copy.dq.sourceRecords.toggle}</summary>
      {loading && <p role="status">{copy.dq.sourceRecords.loading}</p>}
      {error !== null && (
        <div role="alert" className="alert">
          <p>{copy.dq.sourceRecords.failed}</p>
          <p>{error}</p>
          <button type="button" onClick={load}>
            {copy.dq.sourceRecords.retry}
          </button>
        </div>
      )}
      {records === null && <p>{copy.dq.sourceRecords.none}</p>}
      {records != null && (
        <>
          <p>
            {copy.dq.sourceRecords.count(formatCount(records.length))}{" "}
            {copy.dq.sourceRecords.intro}
          </p>
          <code>{records.join(", ")}</code>
        </>
      )}
    </details>
  );
}

/**
 * The context schema version this UI understands (migration 0035). A blob
 * carrying anything else is rendered as if it were absent: a shape we do
 * not understand is worse than none, and the finding's prose description
 * still says what happened.
 */
const SUBJECT_CONTEXT_VERSION = 1;

/**
 * "Which trips this affects" — the finding's subject in the vocabulary the
 * agency uses (handoff 0029).
 *
 * The UAT sentence this exists to answer: *"staff/users will need an easier
 * way to know what exact block they are looking for that had the issue."*
 * So blocks, trip counts, routes and times of day are the PRIMARY content,
 * and the raw identifiers sit in a collapsed disclosure — still there, still
 * copyable for anyone working a ticket, just no longer the headline.
 *
 * Nothing here is computed: every label was resolved once by the calc runner
 * and frozen on the row, and this component only formats it. Nothing here is
 * invented either — where the feed carries no block, no route name or no
 * scheduled time, the copy says so in words rather than substituting a
 * plausible-looking stand-in.
 */
function SubjectContext({
  context,
}: {
  context?: DqSubjectContext | null;
}) {
  const headingId = useId();
  if (!context || context.version !== SUBJECT_CONTEXT_VERSION) return null;
  const { groups, group_count: groupCount, unmatched } = context;
  if (groups.length === 0 && !unmatched) return null;
  const capped = groupCount > groups.length;

  return (
    <section className="dq-subject" aria-labelledby={headingId}>
      <h3 id={headingId}>{copy.dq.subject.heading}</h3>
      <p>
        {copy.dq.subject.intro(
          formatCount(context.total),
          formatCount(groupCount),
        )}
      </p>
      {capped && <p className="banner">
        {copy.dq.subject.groupCap(
          formatCount(groups.length),
          formatCount(groupCount),
        )}
      </p>}
      {groups.length > 0 && (
        <div className="table-wrap">
          <table>
            <caption>{copy.dq.subject.tableCaption}</caption>
            <thead>
              <tr>
                <th scope="col">{copy.dq.subject.columns.block}</th>
                <th scope="col">{copy.dq.subject.columns.trips}</th>
                <th scope="col">{copy.dq.subject.columns.routes}</th>
                <th scope="col">{copy.dq.subject.columns.span}</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group, i) => (
                <SubjectGroupRow
                  key={`${group.block_id ?? "no-block"}-${i}`}
                  group={group}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="field-hint">{copy.dq.subject.spanNote}</p>
      {/* Trips Headway saw operating that the schedule feed does not
          contain. Their own bucket — never folded into a block they do not
          belong to, never quietly dropped. */}
      {unmatched && (
        <div className="banner">
          <h4>{copy.dq.subject.unmatchedHeading}</h4>
          <p>
            {copy.dq.subject.unmatchedBody(
              formatCount(unmatched.trip_count),
            )}
          </p>
        </div>
      )}
      {/* Forensic on demand: collapsed by default, never removed. */}
      <details className="dq-subject-technical">
        <summary>{copy.dq.subject.technicalToggle}</summary>
        <p>
          {copy.dq.subject.technicalIntro(formatCount(context.trip_id_cap))}
        </p>
        <dl>
          {groups.map((group, i) => (
            <div key={`${group.block_id ?? "no-block"}-ids-${i}`}>
              <dt>{group.block_id ?? copy.dq.subject.blockAbsent}</dt>
              <dd>
                <code>{group.trip_ids.join(", ")}</code>
              </dd>
            </div>
          ))}
          {unmatched && (
            <div>
              <dt>{copy.dq.subject.unmatchedHeading}</dt>
              <dd>
                <code>{unmatched.trip_ids.join(", ")}</code>
              </dd>
            </div>
          )}
        </dl>
      </details>
    </section>
  );
}

/** One block's row: the identity, how many trips, which routes, when. */
function SubjectGroupRow({ group }: { group: DqSubjectGroup }) {
  return (
    <tr>
      <th scope="row">
        {group.block_id ?? (
          <>
            <em>{copy.dq.subject.blockAbsent}</em>
            <span className="field-hint">
              {copy.dq.subject.blockAbsentHint}
            </span>
          </>
        )}
      </th>
      <td className="figure">
        {copy.dq.subject.tripCount(formatCount(group.trip_count))}
      </td>
      <td>
        <RouteNames group={group} />
      </td>
      <td>
        {group.first_departure === null && group.last_departure === null ? (
          <em>{copy.dq.subject.spanAbsent}</em>
        ) : (
          `${group.first_departure ?? "—"}–${group.last_departure ?? "—"}`
        )}
      </td>
    </tr>
  );
}

/**
 * Route names, or the honest absence of them. A route with no short name in
 * the feed shows its id LABELLED as an id — the id is the only thing that
 * exists, and calling it what it is beats dressing it up as a name.
 */
function RouteNames({ group }: { group: DqSubjectGroup }) {
  if (group.routes.length === 0) {
    return <em>{copy.dq.subject.routesNone}</em>;
  }
  return (
    <>
      <ul className="dq-subject-routes">
        {group.routes.map((route) => (
          <li key={route.route_id}>
            {route.short_name ??
              route.long_name ??
              copy.dq.subject.routeIdOnly(route.route_id)}
          </li>
        ))}
      </ul>
      {group.route_count > group.routes.length && (
        <span className="field-hint">
          {copy.dq.subject.routesMore(
            formatCount(group.routes.length),
            formatCount(group.route_count),
          )}
        </span>
      )}
    </>
  );
}

interface AttestControlProps {
  issue: DqIssueSummary;
  onAttested: (updated: DqIssueSummary) => void;
}

/**
 * The attest action: a button opening a plain-language dialog (house Modal
 * — APG dialog pattern) that explains what attestation means, quotes the
 * p. 146 rule VERBATIM via the existing quote map, and offers ONLY the
 * standing (unrevoked) attestations already on record to pick from. The
 * server builds the resolution text and enforces every wall (issue type,
 * scope match, revocation) — its refusals render here word for word.
 */
function AttestControl({ issue, onAttested }: AttestControlProps) {
  const titleId = useId();
  const pickId = useId();
  const pickHintId = useId();
  const [open, setOpen] = useState(false);
  const [attestations, setAttestations] = useState<
    AttestationRecord[] | null
  >(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [picked, setPicked] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleOpen = () => {
    setOpen(true);
    setPicked("");
    setError(null);
    setLoadError(null);
    setAttestations(null);
    // Fetched on open so the dialog always offers the CURRENT record.
    listAttestations()
      .then(setAttestations)
      .catch((err) =>
        setLoadError(err instanceof ApiError ? err.message : String(err)),
      );
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (picked === "") {
      setError(copy.dq.attest.pickRequired);
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const response = await attestDqIssue(issue.issue_id, {
        attestation_id: picked,
      });
      setOpen(false);
      onAttested({
        ...issue,
        status: response.status,
        resolved_at: response.resolved_at,
        resolution: response.resolution,
      });
    } catch (err) {
      // The server's refusal (wrong type, revoked attestation, scope
      // mismatch, already closed), verbatim — never softened.
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  // Revoked attestations stay on the /attestations record but are never
  // offered here — the server would refuse them (409), so offering one
  // would promise an action that cannot succeed.
  const standing = (attestations ?? []).filter((a) => a.revoked_at === null);

  return (
    <>
      <button type="button" onClick={handleOpen}>
        {copy.dq.attest.button(issue.title)}
      </button>
      {open && (
        <Modal titleId={titleId} onClose={() => setOpen(false)}>
          <h2 id={titleId}>{copy.dq.attest.dialogHeading}</h2>
          {/* Plain-language framing; the RULE renders verbatim below it —
              the lead-in never stands alone (the house discipline). */}
          <p>{copy.dq.attest.intro}</p>
          <QuoteFigure
            quote={STATISTICIAN_QUOTE}
            missingMessage={copy.receipt.attested.quoteMissing("upt_v0")}
          />
          {error && (
            <div role="alert" className="alert">
              {error}
            </div>
          )}
          {loadError && (
            <div role="alert" className="alert">
              {loadError}
            </div>
          )}
          {!attestations && !loadError && (
            <p>{copy.dq.attest.loadingAttestations}</p>
          )}
          {attestations && standing.length === 0 && (
            <>
              <p className="banner">{copy.dq.attest.noneAvailable}</p>
              <p>
                <Link to="/attestations">
                  {copy.dq.attest.attestationsLink}
                </Link>
              </p>
            </>
          )}
          {attestations && standing.length > 0 && (
            <form onSubmit={handleSubmit}>
              <label htmlFor={pickId}>{copy.dq.attest.pickLabel}</label>
              <p id={pickHintId} className="field-hint">
                {copy.dq.attest.pickHint}
              </p>
              <select
                id={pickId}
                aria-describedby={pickHintId}
                value={picked}
                onChange={(e) => setPicked(e.target.value)}
              >
                <option value="">—</option>
                {standing.map((a) => (
                  <option key={a.attestation_id} value={a.attestation_id}>
                    {copy.dq.attest.optionLabel(
                      a.attestation_id,
                      a.statistician_name,
                      a.metric,
                      a.scope_pattern,
                      a.period_start,
                      a.period_end,
                    )}
                  </option>
                ))}
              </select>
              <p>
                <Link to="/attestations">
                  {copy.dq.attest.attestationsLink}
                </Link>
              </p>
              <button type="submit" className="primary" disabled={submitting}>
                {copy.dq.attest.submit}
              </button>{" "}
              <button type="button" onClick={() => setOpen(false)}>
                {copy.dq.attest.cancel}
              </button>
            </form>
          )}
        </Modal>
      )}
    </>
  );
}

interface ResolveFormProps {
  issue: DqIssueSummary;
  onResolved: (updated: DqIssueSummary) => void;
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
