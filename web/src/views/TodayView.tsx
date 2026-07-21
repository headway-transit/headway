/**
 * /today — the role-aware briefing home (handoff 0021, design point 1).
 * The product greets you with YOUR situation, composed CLIENT-SIDE from
 * existing endpoints — including the handoff-0017 counts endpoints
 * (/dq/issues/counts, /safety/events/counts), consumed here for the first
 * time so no card ever downloads a whole queue just to count it.
 *
 * Composition per role (the lead cards differ; everyone gets the KPI and
 * ops sections):
 *   certifying_official → certification state + safety deadlines first;
 *   data_steward        → DQ queue + safety first;
 *   report_preparer     → report readiness + sampling progress first;
 *   viewer              → straight to the figures.
 *
 * BINDING rules (the handoff's letter):
 * - EVERY number keeps its receipt door: a FIGURE opens its full Receipt
 *   inline (the number is the button) and carries its lineage link; a
 *   WORKFLOW TALLY links to exactly the list it was counted over (the
 *   counts endpoints count over exactly the rows those lists serve).
 * - Cards never invent urgency: a card with nothing to say says so warmly
 *   (copy.today.*.empty) — no red, no exclamation, no fake countdowns.
 * - Deltas are SERVER-computed (GET /metrics/compare, exact Decimal,
 *   signed strings) and sign-neutral unless the metric registry defines a
 *   direction — this view never subtracts two figures.
 * - Performance: every independent request fires in parallel on mount and
 *   each card shows a skeleton until ITS data lands; errors render
 *   verbatim, without animation, in place of the card.
 *
 * NUMBERS STAY SACRED: figures are the API's strings verbatim; the only
 * client-side counting is of workflow rows (how many measures have a
 * figure), never arithmetic on figure values.
 */

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  getDqIssueCounts,
  getMetricsCompare,
  getSafetyDeadlines,
  getSafetyEventCounts,
  comparandToken,
  listCertifications,
  listMetricValues,
  listSamplingPlans,
  getSamplingProgress,
} from "../api/client";
import type {
  CertificationRecord,
  CompareResponse,
  DqIssueCounts,
  MetricValue,
  SafetyDeadlines,
  SafetyEventCounts,
  SamplingPlanProgress,
  SamplingPlanRecord,
} from "../api/types";
import { useSession } from "../auth/session";
import { DeltaFigure } from "../components/DeltaFigure";
import { RowProgress } from "../components/RowProgress";
import { OpsBadge } from "../components/OpsBadge";
import { Receipt } from "../components/Receipt";
import { SimulatedBadge } from "../components/SimulatedBadge";
import { Skeleton } from "../components/Skeleton";
import { copy } from "../copy";
import { isOps, isSimulated } from "../detail";
import { startTour, tourSeen, useTour } from "../tour";

/** One async slice of the briefing: skeleton → verbatim error | data. */
type Load<T> =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; data: T };

const LOADING = { state: "loading" } as const;

function toError(err: unknown): { state: "error"; message: string } {
  return {
    state: "error",
    message: err instanceof ApiError ? err.message : String(err),
  };
}

/** Workflow tallies for display (house precedent) — never figures. */
function formatCount(count: number): string {
  return count.toLocaleString("en-US");
}

/** Current UTC month, YYYY-MM — the same convention the API defaults to. */
function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

/** "2026-07" → "July 2026" (a workflow label, never a figure). */
function monthLabel(month: string): string {
  const date = new Date(`${month}-01T00:00:00Z`);
  return date.toLocaleString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

function unitLabel(code: string): string {
  return copy.unitLabels[code] ?? code;
}

/** The KPI metrics every role sees (the walking-skeleton trio). */
const KPI_METRICS = ["vrm", "vrh", "upt"] as const;

/** The MR-20 monthly measures for the readiness tally. */
const REPORT_MEASURES = ["vrm", "vrh", "upt", "voms"] as const;

/**
 * The newest figure of a metric for the briefing: NTD rows only, the
 * fleet/agency-wide scope preferred (a mode-sliced figure never silently
 * stands in for the whole), latest period wins. Selection only — no
 * arithmetic on values.
 */
function latestKpi(values: MetricValue[], metric: string): MetricValue | null {
  const rows = values.filter((v) => !isOps(v) && v.metric === metric);
  if (rows.length === 0) return null;
  const wide = rows.filter((v) => v.scope === "fleet" || v.scope === "agency");
  const pool = wide.length > 0 ? wide : rows;
  return pool.reduce((latest, v) =>
    v.period_end > latest.period_end ||
    (v.period_end === latest.period_end && v.computed_at > latest.computed_at)
      ? v
      : latest,
  );
}

/** The most recent figure BEFORE `latest` in the same metric + scope. */
function previousKpi(
  values: MetricValue[],
  latest: MetricValue,
): MetricValue | null {
  const earlier = values.filter(
    (v) =>
      !isOps(v) &&
      v.metric === latest.metric &&
      v.scope === latest.scope &&
      v.period_end <= latest.period_start,
  );
  if (earlier.length === 0) return null;
  return earlier.reduce((best, v) =>
    v.period_end > best.period_end ? v : best,
  );
}

/** Latest agency-wide ops figure of a metric (selection only). */
function latestOps(values: MetricValue[], metric: string): MetricValue | null {
  const rows = values.filter(
    (v) => isOps(v) && v.metric === metric && v.scope === "agency",
  );
  if (rows.length === 0) return null;
  return rows.reduce((latest, v) =>
    v.period_end > latest.period_end ? v : latest,
  );
}

/** One card's per-slice error: verbatim, plain, NEVER animated in. */
function CardError({ message }: { message: string }) {
  return (
    <div role="alert" className="alert">
      {message}
    </div>
  );
}

// ---------------------------------------------------------------- lead cards

function CertificationCard({
  month,
  values,
  certifications,
  dqOpen,
  dqOwned,
}: {
  month: string;
  values: Load<MetricValue[]>;
  certifications: Load<CertificationRecord[]>;
  dqOpen: Load<DqIssueCounts>;
  dqOwned: Load<DqIssueCounts>;
}) {
  const t = copy.today.certification;
  // The card renders as soon as the figures land; the blockers line keeps
  // its own one-line skeleton while the (slower) counts settle — every
  // slice paints the moment ITS data arrives.
  if (values.state === "loading" || certifications.state === "loading") {
    return <Skeleton variant="cards" count={1} />;
  }
  const label = monthLabel(month);
  return (
    <div className="card today-card anim-rise">
      <h2>{t.heading}</h2>
      {values.state === "error" ? (
        <CardError message={values.message} />
      ) : (
        (() => {
          const ready = values.data.filter(
            (v) =>
              !isOps(v) &&
              v.period_start.slice(0, 7) === month &&
              v.certification_status !== "certified",
          ).length;
          return ready === 0 ? (
            <p>{t.empty(label)}</p>
          ) : (
            <p className="today-line">
              {t.readyLine(label, formatCount(ready))}
            </p>
          );
        })()
      )}
      {dqOpen.state === "loading" || dqOwned.state === "loading" ? (
        <Skeleton variant="lines" count={1} />
      ) : dqOpen.state === "error" ? (
        <CardError message={dqOpen.message} />
      ) : dqOwned.state === "error" ? (
        <CardError message={dqOwned.message} />
      ) : (
        (() => {
          const blocking =
            (dqOpen.data.by_severity.blocking ?? 0) +
            (dqOwned.data.by_severity.blocking ?? 0);
          return blocking > 0 ? (
            <p>
              {t.blockersLine(formatCount(blocking))}{" "}
              <Link to="/dq">{t.blockersDoor}</Link>
            </p>
          ) : (
            <p>{t.noBlockersLine}</p>
          );
        })()
      )}
      {certifications.state === "error" ? (
        <CardError message={certifications.message} />
      ) : (
        <p>
          {t.certifiedLine(formatCount(certifications.data.length))}{" "}
          <Link to="/certifications">{t.recordDoor}</Link>
        </p>
      )}
      <p className="today-door">
        <Link to="/certify">{t.door}</Link>
      </p>
    </div>
  );
}

function DqCard({
  open,
  owned,
  attested,
  resolved,
}: {
  open: Load<DqIssueCounts>;
  owned: Load<DqIssueCounts>;
  attested: Load<DqIssueCounts>;
  resolved: Load<DqIssueCounts>;
}) {
  const t = copy.today.dq;
  if (open.state === "loading" || owned.state === "loading") {
    return <Skeleton variant="cards" count={1} />;
  }
  if (open.state === "error") {
    return (
      <div className="card today-card">
        <h2>{t.heading}</h2>
        <CardError message={open.message} />
      </div>
    );
  }
  const openCount = open.data.total;
  const ownedCount = owned.state === "ready" ? owned.data.total : 0;
  const resolvedCount = resolved.state === "ready" ? resolved.data.total : 0;
  const attestedCount = attested.state === "ready" ? attested.data.total : 0;
  const blocking =
    (open.data.by_severity.blocking ?? 0) +
    (owned.state === "ready" ? (owned.data.by_severity.blocking ?? 0) : 0);
  const blockingKnown = owned.state === "ready";
  const queueEmpty = openCount === 0 && ownedCount === 0;
  return (
    <div className="card today-card anim-rise">
      <h2>{t.heading}</h2>
      {queueEmpty ? (
        <p>{t.empty}</p>
      ) : (
        <>
          <p className="today-line">
            {t.openLine(formatCount(openCount), formatCount(ownedCount))}
          </p>
          {blockingKnown ? (
            blocking > 0 ? (
              <p>{t.blockingLine(formatCount(blocking))}</p>
            ) : (
              <p>{t.noBlockingLine}</p>
            )
          ) : (
            // A severity split that failed to load is stated, not guessed.
            <CardError
              message={owned.state === "error" ? owned.message : ""}
            />
          )}
        </>
      )}
      {attestedCount > 0 && (
        <p>{t.attestedLine(formatCount(attestedCount))}</p>
      )}
      {resolvedCount > 0 && (
        <p>{t.resolvedLine(formatCount(resolvedCount))}</p>
      )}
      <p className="today-door">
        <Link to="/dq">{t.door}</Link>
      </p>
    </div>
  );
}

function SafetyCard({
  month,
  counts,
  deadlines,
}: {
  month: string;
  counts: Load<SafetyEventCounts>;
  deadlines: Load<SafetyDeadlines>;
}) {
  const t = copy.today.safety;
  if (counts.state === "loading" || deadlines.state === "loading") {
    return <Skeleton variant="cards" count={1} />;
  }
  const label = monthLabel(month);
  return (
    <div className="card today-card anim-rise">
      <h2>{t.heading}</h2>
      {counts.state === "error" ? (
        <CardError message={counts.message} />
      ) : counts.data.total === 0 ? (
        <p>{t.monthNone(label)}</p>
      ) : (
        <p className="today-line">
          {t.monthCounts(
            label,
            formatCount(counts.data.total),
            formatCount(counts.data.by_classification.major ?? 0),
          )}
        </p>
      )}
      {deadlines.state === "error" ? (
        <CardError message={deadlines.message} />
      ) : (
        <>
          {deadlines.data.ss40.length > 0 && (
            <p>{t.ss40Line(formatCount(deadlines.data.ss40.length))}</p>
          )}
          {deadlines.data.ss50.length > 0 && (
            <p>
              {t.ss50Line(
                formatCount(deadlines.data.ss50.length),
                deadlines.data.ss50.reduce(
                  (min, d) => (d.due_date < min ? d.due_date : min),
                  deadlines.data.ss50[0].due_date,
                ),
              )}
            </p>
          )}
        </>
      )}
      <p className="today-door">
        <Link to="/safety">{t.door}</Link>
      </p>
    </div>
  );
}

function ReportCard({
  month,
  values,
}: {
  month: string;
  values: Load<MetricValue[]>;
}) {
  const t = copy.today.report;
  if (values.state === "loading") return <Skeleton variant="cards" count={1} />;
  const label = monthLabel(month);
  return (
    <div className="card today-card anim-rise">
      <h2>{t.heading}</h2>
      {values.state === "error" ? (
        <CardError message={values.message} />
      ) : (
        (() => {
          // A workflow tally over which measures have ANY figure for the
          // month — never a sum of figures.
          const have = REPORT_MEASURES.filter((m) =>
            values.data.some(
              (v) =>
                !isOps(v) &&
                v.metric === m &&
                v.period_start.slice(0, 7) === month,
            ),
          ).length;
          return have === 0 ? (
            <p>{t.empty(label)}</p>
          ) : (
            <p className="today-line">
              {t.readiness(
                label,
                formatCount(have),
                formatCount(REPORT_MEASURES.length),
              )}
            </p>
          );
        })()
      )}
      <p>{t.workbookNote}</p>
      <p className="today-door">
        <Link to="/reports/monthly">{t.door}</Link>
      </p>
    </div>
  );
}

function SamplingCard({
  plans,
  progress,
}: {
  plans: Load<SamplingPlanRecord[]>;
  progress: Record<string, Load<SamplingPlanProgress>>;
}) {
  const t = copy.today.sampling;
  if (plans.state === "loading") return <Skeleton variant="cards" count={1} />;
  if (plans.state === "error") {
    return (
      <div className="card today-card">
        <h2>{t.heading}</h2>
        <CardError message={plans.message} />
      </div>
    );
  }
  const newest = [...plans.data]
    .sort((a, b) => (a.created_at > b.created_at ? -1 : 1))
    .slice(0, 3);
  const more = plans.data.length - newest.length;
  return (
    <div className="card today-card anim-rise">
      <h2>{t.heading}</h2>
      {newest.length === 0 ? (
        <p>{t.empty}</p>
      ) : (
        newest.map((plan) => {
          const planName = `${plan.mode}/${plan.type_of_service} ${plan.report_year}`;
          const p = progress[plan.plan_id] ?? LOADING;
          return (
            <div className="today-plan" key={plan.plan_id}>
              <p className="today-line">{t.planLine(planName)}</p>
              {p.state === "loading" && <Skeleton variant="lines" count={1} />}
              {p.state === "error" && <CardError message={p.message} />}
              {p.state === "ready" && (
                <PlanProgressRow progress={p.data} planName={planName} />
              )}
            </div>
          );
        })
      )}
      {more > 0 && <p>{t.morePlans(formatCount(more))}</p>}
      <p className="today-door">
        <Link to="/sampling">{t.door}</Link>
      </p>
    </div>
  );
}

/** The in-row progress house pattern: text leads, bar echoes. */
function PlanProgressRow({
  progress,
  planName,
}: {
  progress: SamplingPlanProgress;
  planName: string;
}) {
  const t = copy.today.sampling;
  const ready =
    !progress.undersampled &&
    progress.units_measured >= progress.required_annual;
  return (
    <RowProgress
      done={progress.units_measured}
      required={progress.required_annual}
      text={t.progressText(
        formatCount(progress.units_measured),
        formatCount(progress.required_annual),
      )}
      label={t.meterLabel(planName)}
      ready={ready}
      readyLabel={t.readyTag}
    />
  );
}

// ------------------------------------------------------------- KPI section

function KpiCard({
  latest,
  previous,
  compare,
  first,
  open,
  onToggle,
}: {
  latest: MetricValue | null;
  /** The compared period, named in the delta line — periods of unlike
   *  lengths DO get compared, and the reader must see that. */
  previous: MetricValue | null;
  compare: Load<CompareResponse | null> | undefined;
  /** The tour's anchor card (the first KPI with a figure). */
  first: boolean;
  open: boolean;
  onToggle: () => void;
  metric: string;
}) {
  const t = copy.today.kpi;
  if (!latest) return null;
  const period = t.periodLine(latest.period_start, latest.period_end);
  const label = metricLabel(latest.metric);
  return (
    <li className="card today-card stat-tile anim-rise">
      <p className="stat-label">{label}</p>
      {/* THE RECEIPT DOOR: the figure itself is the button (aria-expanded
          discloses the full Receipt right here — never a dead number). */}
      <p className="stat-value">
        <button
          type="button"
          className="link-like figure-button"
          aria-expanded={open}
          onClick={onToggle}
          data-tour={first ? "kpi-figure" : undefined}
        >
          {latest.value}{" "}
          <span className="stat-unit">{unitLabel(latest.unit)}</span>
          <span className="visually-hidden">
            {` — ${t.receiptToggle(label, period)}`}
          </span>
        </button>
      </p>
      <p className="stat-period">{period}</p>
      <p className="stat-flags">
        <span className={`tag ${latest.certification_status}`}>
          {latest.certification_status}
        </span>
        {isSimulated(latest.detail) && <SimulatedBadge />}
      </p>
      {/* The SERVER-computed delta vs the previous period (sign-neutral
          unless the registry defines a direction); its absence is stated. */}
      {compare === undefined ? (
        <p className="kpi-delta-note">{t.firstFigure}</p>
      ) : compare.state === "loading" ? (
        <Skeleton variant="lines" count={1} />
      ) : compare.state === "error" ? (
        <p className="kpi-delta-note">{t.deltaUnavailable(compare.message)}</p>
      ) : compare.data === null || previous === null ? (
        <p className="kpi-delta-note">{t.firstFigure}</p>
      ) : (
        <p className="kpi-delta">
          <DeltaFigure
            delta={deltaVsPrevious(compare.data)}
            direction={compare.data.directions[latest.metric] ?? null}
            versus={t.vsPrevious(previous.period_start, previous.period_end)}
          />
        </p>
      )}
      {open && (
        <div data-tour={first ? "kpi-receipt" : undefined}>
          <Receipt value={latest} />
        </div>
      )}
    </li>
  );
}

/**
 * The latest comparand's delta against the baseline (the previous period)
 * for the card's scope row — the server's signed string or null, verbatim.
 */
function deltaVsPrevious(compare: CompareResponse): string | null {
  for (const row of compare.rows) {
    const cell = row.cells.find(
      (c) => c.comparand_index === 1 && c.value !== null,
    );
    if (cell) return cell.delta_vs_baseline ?? null;
  }
  return null;
}

// ------------------------------------------------------------- the view

export function TodayView() {
  const session = useSession();
  const tour = useTour();
  const role = session?.role ?? "viewer";
  const month = useMemo(currentMonth, []);

  const [values, setValues] = useState<Load<MetricValue[]>>(LOADING);
  const [certs, setCerts] = useState<Load<CertificationRecord[]>>(LOADING);
  const [dqOpen, setDqOpen] = useState<Load<DqIssueCounts>>(LOADING);
  const [dqOwned, setDqOwned] = useState<Load<DqIssueCounts>>(LOADING);
  const [dqAttested, setDqAttested] = useState<Load<DqIssueCounts>>(LOADING);
  const [dqResolved, setDqResolved] = useState<Load<DqIssueCounts>>(LOADING);
  const [safetyCounts, setSafetyCounts] =
    useState<Load<SafetyEventCounts>>(LOADING);
  const [deadlines, setDeadlines] = useState<Load<SafetyDeadlines>>(LOADING);
  const [plans, setPlans] = useState<Load<SamplingPlanRecord[]>>(LOADING);
  const [planProgress, setPlanProgress] = useState<
    Record<string, Load<SamplingPlanProgress>>
  >({});
  const [compares, setCompares] = useState<
    Record<string, Load<CompareResponse | null>>
  >({});
  const [openReceipts, setOpenReceipts] = useState<Set<string>>(new Set());

  const needsCertification = role === "certifying_official";
  const needsDq = role === "certifying_official" || role === "data_steward";
  const needsSafety = role === "certifying_official" || role === "data_steward";
  const needsSampling = role === "report_preparer";

  // Everything independent fires IN PARALLEL on mount (the <1s first-paint
  // budget): skeletons render immediately; each slice settles on its own.
  useEffect(() => {
    listMetricValues()
      .then((data) => setValues({ state: "ready", data }))
      .catch((err) => setValues(toError(err)));
    if (needsCertification) {
      listCertifications()
        .then((data) => setCerts({ state: "ready", data }))
        .catch((err) => setCerts(toError(err)));
    }
    if (needsDq) {
      // Per-status counts ONLY — never the unfiltered count and never the
      // list: each server-side count scales with its own rows (live
      // finding, 2026-07-20: an unfiltered count over a 41k-issue queue
      // costs ~5s; the owned/resolved/attested slices are milliseconds).
      getDqIssueCounts("open")
        .then((data) => setDqOpen({ state: "ready", data }))
        .catch((err) => setDqOpen(toError(err)));
      getDqIssueCounts("owned")
        .then((data) => setDqOwned({ state: "ready", data }))
        .catch((err) => setDqOwned(toError(err)));
    }
    if (role === "data_steward") {
      getDqIssueCounts("attested")
        .then((data) => setDqAttested({ state: "ready", data }))
        .catch((err) => setDqAttested(toError(err)));
      getDqIssueCounts("resolved")
        .then((data) => setDqResolved({ state: "ready", data }))
        .catch((err) => setDqResolved(toError(err)));
    }
    if (needsSafety) {
      getSafetyEventCounts({ month })
        .then((data) => setSafetyCounts({ state: "ready", data }))
        .catch((err) => setSafetyCounts(toError(err)));
      getSafetyDeadlines()
        .then((data) => setDeadlines({ state: "ready", data }))
        .catch((err) => setDeadlines(toError(err)));
    }
    if (needsSampling) {
      listSamplingPlans()
        .then((data) => {
          setPlans({ state: "ready", data });
          // Progress for the newest three plans, in parallel.
          const newest = [...data]
            .sort((a, b) => (a.created_at > b.created_at ? -1 : 1))
            .slice(0, 3);
          for (const plan of newest) {
            getSamplingProgress(plan.plan_id)
              .then((p) =>
                setPlanProgress((prev) => ({
                  ...prev,
                  [plan.plan_id]: { state: "ready", data: p },
                })),
              )
              .catch((err) =>
                setPlanProgress((prev) => ({
                  ...prev,
                  [plan.plan_id]: toError(err),
                })),
              );
          }
        })
        .catch((err) => setPlans(toError(err)));
    }
  }, [month, role, needsCertification, needsDq, needsSafety, needsSampling]);

  // The KPI cards' latest figures — selection only.
  const kpis = useMemo(() => {
    if (values.state !== "ready") return [];
    return KPI_METRICS.map((metric) => {
      const latest = latestKpi(values.data, metric);
      return {
        metric,
        latest,
        previous: latest ? previousKpi(values.data, latest) : null,
      };
    });
  }, [values]);

  // Deltas: one /metrics/compare call per KPI with a previous period,
  // fired in parallel the moment the values land. The compare response is
  // SERVER arithmetic — this view never subtracts.
  useEffect(() => {
    for (const { metric, latest, previous } of kpis) {
      if (!latest) continue;
      if (!previous) {
        setCompares((prev) => ({
          ...prev,
          [metric]: { state: "ready", data: null },
        }));
        continue;
      }
      getMetricsCompare({
        metric,
        comparands: [
          comparandToken(previous.period_start, previous.period_end),
          comparandToken(latest.period_start, latest.period_end),
        ],
        scopes: [latest.scope],
      })
        .then((data) =>
          setCompares((prev) => ({
            ...prev,
            [metric]: { state: "ready", data },
          })),
        )
        .catch((err) =>
          setCompares((prev) => ({ ...prev, [metric]: toError(err) })),
        );
    }
  }, [kpis]);

  // First-run tour offer (design point 3): auto-starts once, is skippable
  // at every step, and never re-offers after a finish OR a dismissal.
  useEffect(() => {
    if (!tourSeen()) startTour();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Tour coordination: when the tour reaches the receipt/quote steps, open
  // the first KPI's receipt so the overlay has real DOM to point at.
  const firstKpiId = kpis.find((k) => k.latest)?.latest?.metric_value_id;
  useEffect(() => {
    if (!tour.active) return;
    if ((tour.step === 1 || tour.step === 2) && firstKpiId) {
      setOpenReceipts((prev) =>
        prev.has(firstKpiId) ? prev : new Set(prev).add(firstKpiId),
      );
    }
  }, [tour.active, tour.step, firstKpiId]);

  const toggleReceipt = (id: string) => {
    setOpenReceipts((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const t = copy.today;
  const otp = values.state === "ready" ? latestOps(values.data, "otp") : null;
  const cvh =
    values.state === "ready"
      ? latestOps(values.data, "headway_adherence")
      : null;

  return (
    <>
      <h1>{t.heading}</h1>
      <p data-tour="today-intro">{t.intro}</p>

      {/* ---- role-aware lead cards ---- */}
      {(needsCertification || needsDq || needsSampling) && (
        <div className="today-grid">
          {needsCertification && (
            <CertificationCard
              month={month}
              values={values}
              certifications={certs}
              dqOpen={dqOpen}
              dqOwned={dqOwned}
            />
          )}
          {role === "data_steward" && (
            <DqCard
              open={dqOpen}
              owned={dqOwned}
              attested={dqAttested}
              resolved={dqResolved}
            />
          )}
          {needsSafety && (
            <SafetyCard
              month={month}
              counts={safetyCounts}
              deadlines={deadlines}
            />
          )}
          {needsSampling && (
            <>
              <ReportCard month={month} values={values} />
              <SamplingCard plans={plans} progress={planProgress} />
            </>
          )}
        </div>
      )}

      {/* ---- KPI cards (everyone) ---- */}
      <section aria-label={t.kpi.heading}>
        <h2>{t.kpi.heading}</h2>
        <p className="chart-desc">{t.kpi.intro}</p>
        {values.state === "loading" && <Skeleton variant="cards" count={3} />}
        {values.state === "error" && <CardError message={values.message} />}
        {values.state === "ready" &&
          (kpis.every((k) => k.latest === null) ? (
            <div className="card today-card">
              {/* The teaching empty state: warm + the concrete command. */}
              <p>{t.kpi.emptyAll}</p>
              <p>
                <code>{t.kpi.emptyAllCommand}</code>
              </p>
            </div>
          ) : (
            <>
              <ul className="stat-grid">
                {kpis.map(({ metric, latest, previous }) => (
                  <KpiCard
                    key={metric}
                    metric={metric}
                    latest={latest}
                    previous={previous}
                    compare={
                      latest ? (compares[metric] ?? LOADING) : undefined
                    }
                    first={latest?.metric_value_id === firstKpiId}
                    open={
                      latest ? openReceipts.has(latest.metric_value_id) : false
                    }
                    onToggle={() =>
                      latest && toggleReceipt(latest.metric_value_id)
                    }
                  />
                ))}
              </ul>
              {kpis.some((k) => k.latest === null) &&
                kpis
                  .filter((k) => k.latest === null)
                  .map((k) => (
                    <p className="kpi-delta-note" key={k.metric}>
                      {t.kpi.empty(metricLabel(k.metric))}
                    </p>
                  ))}
              <p>
                <Link to="/metrics">{t.kpi.metricsDoor}</Link>
              </p>
            </>
          ))}
      </section>

      {/* ---- ops cards (everyone; always badged) ---- */}
      <section aria-label={t.ops.heading}>
        <h2>{t.ops.heading}</h2>
        <p className="chart-desc">{t.ops.intro}</p>
        {values.state === "loading" && <Skeleton variant="cards" count={2} />}
        {values.state === "ready" &&
          (otp === null && cvh === null ? (
            <div className="card today-card">
              <p>{t.ops.empty}</p>
            </div>
          ) : (
            <>
              <ul className="stat-grid">
                {otp && (
                  <OpsCard
                    value={otp}
                    line={t.ops.otpLine(otp.value)}
                    open={openReceipts.has(otp.metric_value_id)}
                    onToggle={() => toggleReceipt(otp.metric_value_id)}
                  />
                )}
                {cvh && (
                  <OpsCard
                    value={cvh}
                    line={t.ops.cvhLine(cvh.value)}
                    open={openReceipts.has(cvh.metric_value_id)}
                    onToggle={() => toggleReceipt(cvh.metric_value_id)}
                  />
                )}
              </ul>
              <p>
                <Link to="/dashboard">{t.ops.door}</Link>
              </p>
            </>
          ))}
      </section>
    </>
  );
}

/** One ops pulse card: badge + the figure (its receipt door) + the line. */
function OpsCard({
  value,
  line,
  open,
  onToggle,
}: {
  value: MetricValue;
  line: string;
  open: boolean;
  onToggle: () => void;
}) {
  const t = copy.today.kpi;
  const label = metricLabel(value.metric);
  const period = t.periodLine(value.period_start, value.period_end);
  return (
    <li className="card today-card stat-tile anim-rise">
      <p className="stat-label">{label}</p>
      <p className="stat-flags">
        <OpsBadge />
      </p>
      <p className="stat-value">
        <button
          type="button"
          className="link-like figure-button"
          aria-expanded={open}
          onClick={onToggle}
        >
          {value.value}
          <span className="visually-hidden">
            {` — ${t.receiptToggle(label, period)}`}
          </span>
        </button>
      </p>
      <p className="stat-period">{period}</p>
      <p>{line}</p>
      {open && <Receipt value={value} />}
    </li>
  );
}
