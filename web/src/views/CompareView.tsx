/**
 * The comparison surface (/compare — handoff 0017, design point 1): pick a
 * metric and 2–4 comparands (calculation versions of the same figure, or
 * one calculation across periods) → a card row (big value, delta vs the
 * baseline comparand and vs the previous one, per-mode subline) and a
 * detail matrix (rows = scopes, columns = comparands).
 *
 * BINDING RULES (handoff 0017):
 * - Every cell keeps its receipt affordance: the cell's button opens the
 *   same Receipt every other surface uses (in a focus-trapped dialog).
 * - Deltas are SERVER-computed decimal strings and rendered SIGN-NEUTRALLY
 *   (glyph + magnitude) unless the response's registry `direction` defines
 *   better/worse (coverage only today) — see DeltaFigure.
 * - Simulated / ops / DR badges carry through every comparison surface.
 * - A comparison mixing certified and uncertified figures labels BOTH: a
 *   banner states the mix and every figure carries its own status tag.
 *
 * THE PAGE NEVER COMPUTES A FIGURE. The comparand VOCABULARY (which
 * calcs/periods exist) is enumerated client-side from the metric list —
 * a workflow enumeration, not arithmetic; values and deltas are rendered
 * verbatim from GET /metrics/compare.
 */

import { useEffect, useId, useState } from "react";
import {
  ApiError,
  comparandToken,
  getMetricsCompare,
  listMetricValues,
} from "../api/client";
import type {
  CompareCell,
  CompareResponse,
  MetricValue,
} from "../api/types";
import { copy } from "../copy";
import { isOps, isPreVerification, isSimulated } from "../detail";
import { DeltaFigure } from "../components/DeltaFigure";
import { DrScopeBadge } from "../components/DrScopeBadge";
import { Modal } from "../components/Modal";
import { OpsBadge } from "../components/OpsBadge";
import { Receipt } from "../components/Receipt";
import { SimulatedBadge } from "../components/SimulatedBadge";

const c = copy.compare;

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

/**
 * A comparand column's display label (presentation only): the pinned calc
 * and the period, e.g. "vrh_v0 0.4.0 — 2026-06-01 to 2026-07-01".
 */
function comparandLabel(comparand: CompareResponse["comparands"][number]): string {
  const period = `${comparand.period_start} to ${comparand.period_end}`;
  return comparand.calc_name
    ? `${comparand.calc_name} ${comparand.calc_version ?? ""} — ${period}`
    : period;
}

/** "agency" → "Agency-wide"; "mode:bus" → "Mode: Bus"; unknown → raw. */
function scopeLabel(scope: string): string {
  const known = c.scopeLabels[scope];
  if (known) return known;
  if (scope.startsWith("mode:")) {
    const rest = scope.slice("mode:".length);
    const modeCode = rest.split(":")[0];
    const label =
      copy.safety.modeLabels[modeCode] ??
      copy.report.mr20.modeLabels[modeCode] ??
      modeCode;
    // A TOS-qualified DR scope keeps its qualifier visible, raw.
    return rest.includes(":") ? `${c.modeScope(label)} (${rest})` : c.modeScope(label);
  }
  return scope;
}

/** A period key "start..end" for the vocabulary selects. */
function periodKey(value: MetricValue): string {
  return `${value.period_start}..${value.period_end}`;
}

function calcKey(value: MetricValue): string {
  return `${value.calc_name}@${value.calc_version}`;
}

/** The certification tag (the /metrics pattern). */
function StatusTag({ status }: { status: string }) {
  return (
    <span className={`tag ${status === "certified" ? "certified" : "uncertified"}`}>
      {status}
    </span>
  );
}

/** The badges a figure carries EVERYWHERE (binding: they carry through). */
function CellBadges({ value }: { value: MetricValue }) {
  return (
    <>
      {isSimulated(value.detail ?? {}) && <SimulatedBadge />}
      {isOps(value) && <OpsBadge />}
      <DrScopeBadge scope={value.scope} />
      {isPreVerification(value) && (
        <span className="tag pre-verification">
          {copy.metrics.preVerificationTag}
        </span>
      )}
    </>
  );
}

/**
 * One matrix/card cell's value with its receipt affordance: a button that
 * opens the figure's full Receipt in a dialog.
 */
function CellValue({
  cell,
  receiptName,
}: {
  cell: CompareCell;
  receiptName: string;
}) {
  const titleId = useId();
  const [open, setOpen] = useState(false);
  if (cell.value == null) {
    // A stated absence, never a blank cell.
    return <span>{cell.missing_reason ?? c.cellMissing}</span>;
  }
  const value = cell.value;
  return (
    <>
      <button
        type="button"
        className="link-like cell-receipt"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
      >
        <span className="figure">{value.value}</span>
        <span className="visually-hidden"> — {receiptName}</span>
      </button>
      {open && (
        <Modal titleId={titleId} onClose={() => setOpen(false)}>
          <h2 id={titleId}>{c.receiptModalHeading}</h2>
          <Receipt value={value} />
          <div className="modal-actions">
            <button type="button" onClick={() => setOpen(false)}>
              {c.closeReceipt}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

// ------------------------------------------------------------- card row

function ComparisonCards({ result }: { result: CompareResponse }) {
  // The headline row: the agency/fleet scope when present, else the first.
  const headlineRow =
    result.rows.find((row) => row.scope === "agency" || row.scope === "fleet") ??
    result.rows[0];
  const modeRows = result.rows.filter(
    (row) => row !== headlineRow && row.scope.startsWith("mode:"),
  );
  const mixed = result.mixed_certification;
  const unitLabel = result.unit
    ? (copy.unitLabels[result.unit] ?? result.unit)
    : "";
  return (
    <section aria-label={c.cardsHeading}>
      <h2>{c.cardsHeading}</h2>
      <ul className="compare-cards">
        {result.comparands.map((comparand, index) => {
          const cell = headlineRow?.cells[index];
          const value = cell?.value ?? null;
          const label = comparandLabel(comparand);
          return (
            <li key={comparand.key}>
              <article
                className="card compare-card"
                aria-label={c.cardLabel(label)}
              >
                <p className="compare-card-label">
                  {label}{" "}
                  {comparand.baseline && (
                    <span className="tag baseline">{c.baselineTag}</span>
                  )}
                </p>
                {cell && value ? (
                  <>
                    <p className="compare-card-value">
                      <CellValue
                        cell={cell}
                        receiptName={c.cellReceipt(
                          metricLabel(result.metric),
                          scopeLabel(headlineRow.scope),
                          label,
                        )}
                      />{" "}
                      <span className="stat-unit">{unitLabel}</span>
                    </p>
                    <p className="compare-card-badges">
                      {/* Certified-vs-uncertified: label both (always when
                          mixed; harmless context otherwise). */}
                      {mixed && <StatusTag status={value.certification_status} />}
                      <CellBadges value={value} />
                    </p>
                  </>
                ) : (
                  <p>{cell?.missing_reason ?? c.noFleetFigure}</p>
                )}
                {index > 0 && (
                  <p className="compare-card-delta">
                    <DeltaFigure
                      delta={cell?.delta_vs_baseline ?? null}
                      direction={result.directions[result.metric] ?? null}
                      versus={c.vsBaseline}
                    />
                  </p>
                )}
                {index > 1 && (
                  <p className="compare-card-delta">
                    <DeltaFigure
                      delta={cell?.delta_vs_previous ?? null}
                      direction={result.directions[result.metric] ?? null}
                      versus={c.vsPrevious}
                    />
                  </p>
                )}
                {modeRows.length > 0 && (
                  <>
                    <h3>{c.perModeHeading}</h3>
                    <ul className="compare-card-modes">
                      {modeRows.map((row) => (
                        <li key={row.scope}>
                          {scopeLabel(row.scope)}:{" "}
                          {row.cells[index]?.value != null ? (
                            <span className="figure">
                              {row.cells[index].value!.value}
                            </span>
                          ) : (
                            (row.cells[index]?.missing_reason ?? c.cellMissing)
                          )}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </article>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// ---------------------------------------------------------- detail matrix

function ComparisonMatrix({ result }: { result: CompareResponse }) {
  const mixed = result.mixed_certification;
  return (
    <section aria-label={c.matrixHeading}>
      <h2>{c.matrixHeading}</h2>
      {/* The server's own delta + direction provenance notes, verbatim. */}
      <p className="field-hint">{result.delta_note}</p>
      <p className="field-hint">{result.direction_note}</p>
      <div className="table-wrap">
        <table className="compare-matrix">
          <caption>{c.matrixCaption(metricLabel(result.metric))}</caption>
          <thead>
            <tr>
              <th scope="col">{c.scopeColumn}</th>
              {result.comparands.map((comparand) => (
                <th scope="col" key={comparand.key}>
                  {comparandLabel(comparand)}
                  {comparand.baseline && (
                    <>
                      {" "}
                      <span className="tag baseline">{c.baselineTag}</span>
                    </>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows.map((row) => (
              <tr key={row.scope}>
                <th scope="row">{scopeLabel(row.scope)}</th>
                {row.cells.map((cell, index) => (
                  <td className="figure" key={result.comparands[index].key}>
                    <CellValue
                      cell={cell}
                      receiptName={c.cellReceipt(
                        metricLabel(result.metric),
                        scopeLabel(row.scope),
                        comparandLabel(result.comparands[index]),
                      )}
                    />
                    {cell.value && (
                      <span className="compare-cell-meta">
                        {mixed && (
                          <StatusTag status={cell.value.certification_status} />
                        )}
                        <CellBadges value={cell.value} />
                      </span>
                    )}
                    {index > 0 && (
                      <span className="compare-cell-delta">
                        <DeltaFigure
                          delta={cell.delta_vs_baseline ?? null}
                          direction={result.directions[result.metric] ?? null}
                          versus={c.vsBaseline}
                        />
                      </span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// -------------------------------------------------------------------- view

export function CompareView() {
  const ids = {
    metric: useId(),
    mode: useId(),
    period: useId(),
    calc: useId(),
    reason: useId(),
    comparands: useId(),
  };
  const [values, setValues] = useState<MetricValue[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [metric, setMetric] = useState("");
  const [mode, setMode] = useState<"versions" | "periods">("versions");
  const [period, setPeriod] = useState("");
  const [calc, setCalc] = useState("");
  /** Tick ORDER matters: the first ticked comparand is the baseline. */
  const [picked, setPicked] = useState<string[]>([]);
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [comparing, setComparing] = useState(false);

  useEffect(() => {
    listMetricValues()
      .then(setValues)
      .catch((err) =>
        setLoadError(err instanceof ApiError ? err.message : String(err)),
      );
  }, []);

  const all = values ?? [];
  const metrics = [...new Set(all.map((v) => v.metric))];
  const ofMetric = all.filter((v) => v.metric === metric);
  const periods = [...new Set(ofMetric.map(periodKey))].sort().reverse();
  const calcs = [...new Set(ofMetric.map(calcKey))].sort();

  // The comparand vocabulary for the current picks (a workflow enumeration
  // of what exists — never arithmetic).
  const options: { key: string; label: string }[] =
    mode === "versions"
      ? [
          ...new Set(
            ofMetric.filter((v) => periodKey(v) === period).map(calcKey),
          ),
        ]
          .sort()
          .map((key) => ({ key, label: key.replace("@", " ") }))
      : [...new Set(ofMetric.filter((v) => calcKey(v) === calc).map(periodKey))]
          .sort()
          .reverse()
          .map((key) => ({ key, label: key.replace("..", " to ") }));

  const togglePick = (key: string) => {
    setPicked((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  };

  const selectionOk = picked.length >= 2 && picked.length <= 4;
  const runDisabled = !selectionOk || comparing;

  const handleCompare = async () => {
    // aria-disabled house pattern: the click lands and is refused while the
    // reason line beside the button says why.
    if (runDisabled) return;
    setComparing(true);
    setCompareError(null);
    try {
      const tokens = picked.map((key) => {
        if (mode === "versions") {
          const [calcName, calcVersion] = key.split("@");
          const [start, end] = period.split("..");
          return comparandToken(start, end, calcName, calcVersion);
        }
        const [calcName, calcVersion] = calc.split("@");
        const [start, end] = key.split("..");
        return comparandToken(start, end, calcName, calcVersion);
      });
      setResult(await getMetricsCompare({ metric, comparands: tokens }));
    } catch (err) {
      setCompareError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setComparing(false);
    }
  };

  return (
    <>
      <h1>{c.heading}</h1>
      <p>{c.intro}</p>
      {loadError && (
        <div role="alert" className="alert">
          {loadError}
        </div>
      )}
      {!values && !loadError && <p>{c.loading}</p>}
      {values && values.length === 0 && <p>{c.empty}</p>}
      {values && values.length > 0 && (
        <section className="card compare-picker" aria-label={c.pickerHeading}>
          <h2>{c.pickerHeading}</h2>
          <label htmlFor={ids.metric}>{c.metricLabel}</label>
          <select
            id={ids.metric}
            value={metric}
            onChange={(e) => {
              setMetric(e.target.value);
              setPeriod("");
              setCalc("");
              setPicked([]);
            }}
          >
            <option value="">{c.metricUnselected}</option>
            {metrics.map((code) => (
              <option key={code} value={code}>
                {metricLabel(code)}
              </option>
            ))}
          </select>

          {metric && (
            <>
              <label htmlFor={ids.mode}>{c.modeLabel}</label>
              <select
                id={ids.mode}
                value={mode}
                onChange={(e) => {
                  setMode(e.target.value as "versions" | "periods");
                  setPicked([]);
                }}
              >
                <option value="versions">{c.modeVersions}</option>
                <option value="periods">{c.modePeriods}</option>
              </select>

              {mode === "versions" ? (
                <>
                  <label htmlFor={ids.period}>{c.periodLabel}</label>
                  <select
                    id={ids.period}
                    value={period}
                    onChange={(e) => {
                      setPeriod(e.target.value);
                      setPicked([]);
                    }}
                  >
                    <option value="">{c.periodUnselected}</option>
                    {periods.map((key) => (
                      <option key={key} value={key}>
                        {key.replace("..", " to ")}
                      </option>
                    ))}
                  </select>
                </>
              ) : (
                <>
                  <label htmlFor={ids.calc}>{c.calcLabel}</label>
                  <select
                    id={ids.calc}
                    value={calc}
                    onChange={(e) => {
                      setCalc(e.target.value);
                      setPicked([]);
                    }}
                  >
                    <option value="">{c.calcUnselected}</option>
                    {calcs.map((key) => (
                      <option key={key} value={key}>
                        {key.replace("@", " ")}
                      </option>
                    ))}
                  </select>
                </>
              )}

              {options.length > 0 && (
                <fieldset className="compare-comparands">
                  <legend>
                    {mode === "versions"
                      ? c.comparandsVersionsLabel
                      : c.comparandsPeriodsLabel}
                  </legend>
                  <p className="field-hint">{c.baselineHint}</p>
                  {options.map((option) => (
                    <div className="safety-checkbox" key={option.key}>
                      <input
                        id={`${ids.comparands}-${option.key}`}
                        type="checkbox"
                        checked={picked.includes(option.key)}
                        onChange={() => togglePick(option.key)}
                      />
                      <label htmlFor={`${ids.comparands}-${option.key}`}>
                        {option.label}
                        {picked[0] === option.key && (
                          <>
                            {" "}
                            <span className="tag baseline">{c.baselineTag}</span>
                          </>
                        )}
                      </label>
                    </div>
                  ))}
                </fieldset>
              )}

              <p>
                <button
                  type="button"
                  className="primary"
                  aria-disabled={runDisabled || undefined}
                  aria-describedby={!selectionOk ? ids.reason : undefined}
                  onClick={handleCompare}
                >
                  {comparing ? c.comparing : c.run}
                </button>
              </p>
              {!selectionOk && (
                <div
                  id={ids.reason}
                  className="certify-reason"
                  aria-label={c.reasonLabel}
                >
                  <p>{c.reasonCount}</p>
                </div>
              )}
            </>
          )}
        </section>
      )}

      {compareError && (
        <div role="alert" className="alert">
          {compareError}
        </div>
      )}
      {result && (
        <>
          {result.mixed_certification && (
            // The server's own label-both note, verbatim (with this
            // catalog's wording as the fallback for a null note).
            <p className="banner">
              {result.mixed_certification_note ?? c.mixedBanner}
            </p>
          )}
          <ComparisonCards result={result} />
          <ComparisonMatrix result={result} />
        </>
      )}
    </>
  );
}
