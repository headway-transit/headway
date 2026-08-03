import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  classifyBoarding,
  getBoardingReviewCounts,
  listBoardingReviews,
} from "../api/client";
import type {
  BoardingReview,
  BoardingReviewCounts,
  BoardingReviewPage,
} from "../api/types";
import { canResolveDqIssues, useSession } from "../auth/session";
import { Skeleton } from "../components/Skeleton";
import { SummaryCards } from "../components/SummaryCards";
import { copy } from "../copy";
import { pushToast } from "../toasts";

/**
 * The revenue review queue (handoff 0040): the boardings Headway refused to
 * guess about, and the place a person decides them.
 *
 * A bus can record riders while nobody is logged into a run. Most of the time
 * that is staff during prep, pull-out or pull-in — not public ridership, and
 * the schedule proves it, so Headway excludes those on its own. But a
 * boarding recorded off-run in the MIDDLE of the service day is genuinely
 * ambiguous: it could be prep, or it could be an extra bus dispatch running
 * real riders without a formal trip assignment. No federal rule separates
 * those two, so Headway does not invent one. It holds the boarding OUT of the
 * ridership figure and asks a person — which only works if there is a place
 * to answer. This screen is that place.
 *
 * Three things this screen refuses to let a user misunderstand:
 *
 *  1. **Held is not counted, and held is not deleted.** Every pending row
 *     says so, and the header says how many riders are being held.
 *  2. **A decision needs a reason.** The note field is required by this form,
 *     by the API and by a database CHECK constraint. There is no blank-note
 *     path anywhere, and no "count it anyway" shortcut.
 *  3. **Deciding does not move a number.** Saving records a decision; the
 *     ridership figure changes when the figures are worked out again. That
 *     sentence appears at the moment of deciding, not in a footnote, and the
 *     screen links straight to the room where figures are computed.
 *
 * Classifying requires the data-steward role or above — the check here is UX
 * only, exactly as on the data-quality queue; the API enforces it, and it
 * refuses outright for any period whose ridership figure is already
 * certified.
 *
 * Paging is keyset, on the server, like the DQ queue (handoff 0030): the
 * queue grows with the feed, so no screen may ever ask for all of it, and the
 * header counts are the server's whole-queue tallies rather than a count of
 * the rows on screen.
 */

const PAGE_SIZE = 25;

type QueueStatus = "pending" | "classified";

export function RevenueReviewView() {
  const session = useSession();
  const mayClassify = canResolveDqIssues(session);

  const [status, setStatus] = useState<QueueStatus>("pending");
  const [page, setPage] = useState<BoardingReviewPage | null>(null);
  const [counts, setCounts] = useState<BoardingReviewCounts | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
  // cursors[n] is the cursor that FETCHES page n (undefined for page 0), so
  // Previous rewinds through positions the server issued rather than
  // guessing one — the DqView pattern.
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const [pageLoading, setPageLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let live = true;
    setPageLoading(true);
    listBoardingReviews({
      status,
      limit: PAGE_SIZE,
      cursor: cursors[pageIndex],
    })
      .then((result) => {
        if (!live) return;
        setPage(result);
        setError(null);
        if (result.next_cursor) {
          setCursors((prev) => {
            const next = [...prev];
            next[pageIndex + 1] = result.next_cursor ?? undefined;
            return next;
          });
        }
      })
      .catch((err: unknown) => {
        if (!live) return;
        setPage(null);
        setError(
          err instanceof ApiError ? err.message : copy.revenueReview.loadFailed,
        );
      })
      .finally(() => {
        if (live) setPageLoading(false);
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, pageIndex, reload]);

  useEffect(() => {
    let live = true;
    getBoardingReviewCounts()
      .then((result) => {
        if (live) setCounts(result);
      })
      .catch(() => {
        // A missing tally must never blank the work itself. The rows below
        // still render; the cards simply do not appear.
        if (live) setCounts(null);
      });
    return () => {
      live = false;
    };
  }, [reload]);

  function changeStatus(next: QueueStatus) {
    setStatus(next);
    setPageIndex(0);
    setCursors([undefined]);
    setPage(null);
  }

  function afterDecision(boarding: BoardingReview) {
    pushToast(copy.revenueReview.success(vehicleName(boarding)));
    // Re-read from the server rather than patching the row in place: the
    // decided boarding leaves the pending queue, and the header counts move
    // with it. A screen that edited itself would drift from the truth.
    setReload((n) => n + 1);
  }

  const shown = page?.boardings ?? [];
  const rangeFrom = page === null || shown.length === 0 ? 0 : pageIndex * PAGE_SIZE + 1;
  const rangeTo = page === null ? 0 : pageIndex * PAGE_SIZE + shown.length;
  const queueEmpty =
    status === "pending" && page !== null && page.total === 0 && !error;

  return (
    <section aria-labelledby="revenue-review-heading">
      <h1 id="revenue-review-heading">{copy.revenueReview.heading}</h1>
      <p>{copy.revenueReview.intro}</p>

      {error && (
        <div role="alert" className="alert">
          <p>{error}</p>
          <button type="button" onClick={() => setReload((n) => n + 1)}>
            {copy.revenueReview.retry}
          </button>
        </div>
      )}

      {counts === null && page === null && !error && (
        <Skeleton variant="cards" count={3} />
      )}

      {counts !== null && (
        <section aria-label={copy.revenueReview.filterLabel}>
          {/* The cards ARE the filter (the /dq pattern): count + label,
              aria-pressed, never color alone. They count the WHOLE queue on
              the server — a card can never disagree with the rows below it,
              and the line under them says which is which. */}
          <SummaryCards
            label={copy.revenueReview.filterLabel}
            cards={[
              {
                key: "pending",
                label: copy.revenueReview.cards.pending,
                count: formatCount(counts.pending),
                tone: "warning",
                pressed: status === "pending",
              },
              {
                key: "classified",
                label: copy.revenueReview.cards.classified,
                count: formatCount(counts.classified),
                tone: "success",
                pressed: status === "classified",
              },
            ]}
            onToggle={(key) => changeStatus(key as QueueStatus)}
          />
          <ul className="dq-chips">
            <li className="chip">
              {copy.revenueReview.cards.pendingBoardings}:{" "}
              <span className="figure">
                {formatCount(counts.pending_boardings)}
              </span>
            </li>
            <li className="chip">
              {copy.revenueReview.cards.classifiedRevenue}:{" "}
              <span className="figure">
                {formatCount(counts.classified_revenue_boardings)}
              </span>
            </li>
            <li className="chip">
              {copy.revenueReview.cards.classifiedNonRevenue}:{" "}
              <span className="figure">
                {formatCount(counts.classified_non_revenue_boardings)}
              </span>
            </li>
          </ul>
          <p className="dq-showing">
            {copy.revenueReview.cardsScope(
              formatCount(counts.pending + counts.classified),
            )}
          </p>
        </section>
      )}

      {status === "classified" && (
        <p className="field-hint">
          {copy.revenueReview.decidedRecomputeNote}
        </p>
      )}

      {page === null && !error && <Skeleton variant="table" count={3} />}

      {queueEmpty && (
        <section className="card" aria-labelledby="revenue-review-empty">
          <h2 id="revenue-review-empty">
            {copy.revenueReview.empty.heading}
          </h2>
          <p>{copy.revenueReview.empty.body}</p>
          <p className="field-hint">{copy.revenueReview.empty.hint}</p>
        </section>
      )}

      {page !== null && shown.length > 0 && (
        <>
          <p className="dq-showing">
            {copy.revenueReview.showingRange(
              formatCount(rangeFrom),
              formatCount(rangeTo),
              formatCount(page.total),
            )}
          </p>
          <ul className="issue-list">
            {shown.map((boarding) => (
              <BoardingCard
                key={boarding.passenger_event_id}
                boarding={boarding}
                mayClassify={mayClassify}
                onDecided={afterDecision}
              />
            ))}
          </ul>
          <nav className="dq-pager" aria-label={copy.revenueReview.pageNavLabel}>
            <button
              type="button"
              onClick={() => setPageIndex((n) => Math.max(0, n - 1))}
              disabled={pageIndex === 0 || pageLoading}
            >
              {copy.revenueReview.pagePrevious}
            </button>{" "}
            <button
              type="button"
              onClick={() => setPageIndex((n) => n + 1)}
              disabled={!page.has_more || pageLoading}
            >
              {copy.revenueReview.pageNext}
            </button>
            <span role="status">
              {pageLoading ? copy.revenueReview.pageLoading : ""}
            </span>
          </nav>
        </>
      )}
    </section>
  );
}

/** The agency's own word for the bus, or an honest absence. */
function vehicleName(boarding: BoardingReview): string {
  return boarding.vehicle_id === null
    ? copy.revenueReview.vehicleUnknown
    : copy.revenueReview.vehicleLabel(boarding.vehicle_id);
}

function formatCount(count: number): string {
  return count.toLocaleString("en-US");
}

/** ISO timestamps read back as a person says them; never re-derived. */
function formatWhen(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function formatDay(iso: string): string {
  const at = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleDateString("en-US", { dateStyle: "medium" });
}

interface BoardingCardProps {
  boarding: BoardingReview;
  mayClassify: boolean;
  onDecided: (boarding: BoardingReview) => void;
}

function BoardingCard({
  boarding,
  mayClassify,
  onDecided,
}: BoardingCardProps) {
  const decided = boarding.verdict !== null;
  const vehicle = vehicleName(boarding);
  const when = formatWhen(boarding.event_timestamp);
  return (
    <li>
      <article className="card">
        <h2>{copy.revenueReview.rowHeading(vehicle, when)}</h2>
        <dl>
          <dt>{copy.revenueReview.ridersLabel}</dt>
          <dd className="figure">
            {copy.revenueReview.ridersValue(String(boarding.event_count))}
          </dd>
          <dt>{copy.revenueReview.serviceDayLabel}</dt>
          <dd className="figure">{formatDay(boarding.service_date)}</dd>
          <dt>{copy.revenueReview.recordedAtLabel}</dt>
          <dd className="figure">{when}</dd>
          <dt>{copy.revenueReview.routeLabel}</dt>
          <dd>{copy.revenueReview.routeNone}</dd>
          <dt>{copy.revenueReview.whyLabel}</dt>
          <dd>{boarding.suggested_reason}</dd>
          <dt>{copy.revenueReview.suggestionLabel}</dt>
          <dd>{copy.revenueReview.suggestionPending}</dd>
          <dt>{copy.revenueReview.flaggedByLabel}</dt>
          <dd className="figure">
            {copy.revenueReview.flaggedByValue(
              boarding.calc_name,
              boarding.calc_version,
              formatWhen(boarding.first_seen_at),
            )}
          </dd>
        </dl>

        {decided ? (
          <div>
            <p>
              <strong>
                {boarding.verdict === "revenue"
                  ? copy.revenueReview.decidedRevenue
                  : copy.revenueReview.decidedNonRevenue}
              </strong>
            </p>
            <dl>
              <dt>{copy.revenueReview.decidedByLabel}</dt>
              <dd className="figure">
                {copy.revenueReview.decidedByValue(
                  boarding.classified_by ?? "",
                  formatWhen(boarding.classified_at ?? ""),
                )}
              </dd>
              <dt>{copy.revenueReview.decidedWhyLabel}</dt>
              <dd>{boarding.justification}</dd>
              <dt>{copy.revenueReview.decidedFindingLabel}</dt>
              <dd>
                {boarding.dq_issue_id === null ? (
                  copy.revenueReview.decidedFindingNone
                ) : (
                  <Link to={`/dq?issue=${boarding.dq_issue_id}`}>
                    {boarding.dq_issue_id}
                  </Link>
                )}
              </dd>
            </dl>
          </div>
        ) : (
          <>
            <p className="banner">{copy.revenueReview.heldNote}</p>
            {mayClassify && (
              <DecisionForm boarding={boarding} onDecided={onDecided} />
            )}
          </>
        )}

        <details>
          <summary>{copy.revenueReview.technicalToggle}</summary>
          <p className="field-hint">{copy.revenueReview.technicalIntro}</p>
          <dl>
            <dt>{copy.revenueReview.technicalEventLabel}</dt>
            <dd className="figure">{boarding.passenger_event_id}</dd>
            <dt>{copy.revenueReview.technicalSourceLabel}</dt>
            <dd className="figure">
              <Link
                to={`/raw/records/${encodeURIComponent(boarding.source_record_id)}`}
              >
                {boarding.source_record_id}
              </Link>
            </dd>
            <dt>{copy.revenueReview.periodLabel}</dt>
            <dd className="figure">
              {formatDay(boarding.period_start)} – {formatDay(boarding.period_end)}
            </dd>
          </dl>
        </details>
      </article>
    </li>
  );
}

interface DecisionFormProps {
  boarding: BoardingReview;
  onDecided: (boarding: BoardingReview) => void;
}

/**
 * The decision. Two buttons and a required note — and the note is genuinely
 * required: an empty one never reaches the network, and the API and the
 * database refuse it too. Three independent refusals, because "you must say
 * why" is the whole reason this feature is worth having.
 */
function DecisionForm({ boarding, onDecided }: DecisionFormProps) {
  const [open, setOpen] = useState(false);
  const [verdict, setVerdict] = useState<string>("");
  const [justification, setJustification] = useState("");
  const [validation, setValidation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const noteId = useId();
  const verdictName = useId();
  const vehicle = vehicleName(boarding);
  const when = formatWhen(boarding.event_timestamp);

  if (!open) {
    return (
      <button
        type="button"
        className="primary"
        onClick={() => setOpen(true)}
      >
        {copy.revenueReview.decideButton(vehicle, when)}
      </button>
    );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (verdict === "") {
      setValidation(copy.revenueReview.verdictRequired);
      return;
    }
    if (justification.trim() === "") {
      setValidation(copy.revenueReview.justificationRequired);
      return;
    }
    setValidation(null);
    setSaving(true);
    classifyBoarding(boarding.passenger_event_id, {
      verdict,
      justification: justification.trim(),
    })
      .then((result) => {
        onDecided({
          ...boarding,
          verdict: result.verdict,
          justification: result.justification,
          classified_by: result.classified_by,
          classified_at: result.classified_at,
          dq_issue_id: result.dq_issue_id,
        });
      })
      .catch((err: unknown) => {
        // The API's own words, verbatim — including the certified-period
        // refusal, which explains itself far better than any generic
        // message this screen could substitute.
        setError(
          err instanceof ApiError ? err.message : copy.revenueReview.failed,
        );
      })
      .finally(() => setSaving(false));
  }

  return (
    <form onSubmit={submit}>
      <fieldset>
        <legend>{copy.revenueReview.decideHeading}</legend>
        <div role="radiogroup" aria-label={copy.revenueReview.verdictLabel}>
          <label>
            <input
              type="radio"
              name={verdictName}
              value="revenue"
              checked={verdict === "revenue"}
              onChange={() => setVerdict("revenue")}
            />{" "}
            {copy.revenueReview.verdictRevenue}
          </label>
          <p className="field-hint">{copy.revenueReview.verdictRevenueHint}</p>
          <label>
            <input
              type="radio"
              name={verdictName}
              value="non_revenue"
              checked={verdict === "non_revenue"}
              onChange={() => setVerdict("non_revenue")}
            />{" "}
            {copy.revenueReview.verdictNonRevenue}
          </label>
          <p className="field-hint">
            {copy.revenueReview.verdictNonRevenueHint}
          </p>
        </div>
      </fieldset>
      <label htmlFor={noteId}>{copy.revenueReview.justificationLabel}</label>
      <p className="field-hint" id={`${noteId}-hint`}>
        {copy.revenueReview.justificationHint}
      </p>
      <textarea
        id={noteId}
        aria-describedby={`${noteId}-hint`}
        required
        value={justification}
        onChange={(event) => setJustification(event.target.value)}
      />
      {validation && (
        <p role="alert" className="alert">
          {validation}
        </p>
      )}
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {/* Said at the moment of deciding, never as a footnote. */}
      <p className="banner">
        {copy.revenueReview.recomputeWarning}{" "}
        <Link to="/calc-runs">{copy.revenueReview.recomputeLink}</Link>
      </p>
      <button type="submit" className="primary" disabled={saving}>
        {copy.revenueReview.submit}
      </button>{" "}
      <button type="button" onClick={() => setOpen(false)} disabled={saving}>
        {copy.revenueReview.cancel}
      </button>
    </form>
  );
}
