/**
 * The PMT sampling module (/sampling — handoff 0012, design point 3),
 * typed against services/api routers/sampling.py exactly (the backend was
 * built in parallel against the same handoff).
 *
 * Four rooms on one page:
 *  1. Plan wizard (POST /sampling/plans, data_steward+): vocabulary
 *     served by GET /sampling/options (modes, the units Table 41.01
 *     allows per mode, which efficiency options are creatable,
 *     frequencies) with the calc's §41.01/§41.03 eligibility guidance
 *     rendered VERBATIM and the manual's §41.07(c) options quoted beside
 *     the radios (APTL requires a 100% UPT count and SAYS so; Base
 *     estimation and route grouping are stated deferred) — ending in the
 *     required per-period AND annual sizes served verbatim from the
 *     manual's tables with their citation, rendered as a receipt.
 *  2. Drawn-sample worksheets: one seeded, without-replacement draw per
 *     period (POST /sampling/plans/{id}/draws — the seed is recorded, or
 *     generated server-side from a cryptographic source) and, per draw,
 *     the ride checker's printable list with the seed and the verbatim
 *     §63.03 rule on the sheet.
 *  3. Measurement entry (POST /sampling/plans/{id}/measurements): per
 *     drawn unit the observed UPT (whole count) and PMT (decimal STRING,
 *     never parsed), with the API-computed progress
 *     (GET /sampling/plans/{id}/progress) as a meter. Under target, the
 *     API's own no-undersampling citation is shown verbatim and the
 *     estimate button stays off with the reason stated AT the button.
 *  4. Estimate receipt (POST /sampling/plans/{id}/estimate,
 *     report_preparer+): the §83 figures VERBATIM — expansion factor (the
 *     100% UPT count) × sample APTL — with the §83.01/§83.05/§83.07 rules
 *     quoted, the calc's citations and caveats verbatim, and the
 *     sampled-estimate provenance label kept clearly distinct from
 *     computed PMT figures.
 *
 * THE PAGE NEVER COMPUTES. Required sizes, drawn units, progress counts,
 * the undersampled verdict, and every estimate figure are the
 * deterministic sampling_v0 calc's output served by the API, shown
 * verbatim. The only arithmetic here is the progress meter's position
 * (integer workflow counts, presentation only — the displayed counts are
 * the API's).
 *
 * Honest v0 gap: the API's measurement-supersede endpoint has no UI room
 * yet; a duplicate measurement's 409 (which names that endpoint) is
 * surfaced verbatim. Recorded in the handoff evidence.
 */

import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import { useMeter } from "react-aria";
import {
  ApiError,
  createSamplingPlan,
  drawSamplingPeriod,
  estimateSamplingPmt,
  getSamplingOptions,
  getSamplingProgress,
  listSamplingDraws,
  listSamplingMeasurements,
  listSamplingPlans,
  recordSamplingMeasurement,
} from "../api/client";
import type {
  SamplingDrawCreated,
  SamplingDrawRecord,
  SamplingEstimateBlock,
  SamplingEstimateResponse,
  SamplingMeasurementRecord,
  SamplingOptions,
  SamplingPlanCreated,
  SamplingPlanProgress,
  SamplingPlanRecord,
} from "../api/types";
import {
  canManageSampling,
  canRunSamplingEstimate,
  useSession,
} from "../auth/session";
import { QuoteFigure } from "../components/QuoteFigure";
import { copy } from "../copy";
import { quoteContaining } from "../regulatory/quotes";
import type { RegulatoryQuote } from "../regulatory/quotes";
import {
  EXPANSION_FACTOR_QUOTE_SNIPPET,
  MULTIPLY_QUOTE_SNIPPET,
  OPTIONS_QUOTE_SNIPPET,
  PRECISION_FLOOR_QUOTE_SNIPPET,
  RATIO_OF_TOTALS_QUOTE_SNIPPET,
  SELECTION_QUOTE_SNIPPET,
} from "../regulatory/samplingRules";

const s = copy.sampling;

function modeLabel(code: string): string {
  return s.modeLabels[code] ?? code;
}

function unitLabel(code: string): string {
  return s.unitLabels[code] ?? code;
}

function optionLabel(code: string): string {
  return s.optionLabels[code] ?? code;
}

function frequencyLabel(code: string): string {
  return s.frequencyLabels[code] ?? code;
}

/** "2026 — Bus (MB), one-way trips — Averaging option …, monthly" */
function planLabel(plan: SamplingPlanRecord): string {
  return s.planLabel(
    String(plan.report_year),
    modeLabel(plan.mode),
    unitLabel(plan.unit),
    optionLabel(plan.efficiency_option),
    frequencyLabel(plan.frequency),
  );
}

/** A verbatim manual quote + citation, or the stated absence — never blank
 *  (the shared QuoteFigure, bound to this page's missing-rule copy). */
function ManualQuote({ quote }: { quote: RegulatoryQuote | null }) {
  return <QuoteFigure quote={quote} missingMessage={s.ruleMissing} />;
}

// ------------------------------------------------------------ plan receipt

/**
 * The plan receipt: the required per-period AND annual sizes VERBATIM
 * (both are the manual's own table rows, served by the calc) with the
 * calc's citation for the cell, the selector version, the calc's
 * guidance (creation response only), and the p. 149 estimation floor the
 * ready-to-use sizes are designed to meet, quoted.
 */
function PlanReceipt({
  plan,
  guidance,
  isNew = false,
}: {
  plan: SamplingPlanRecord;
  /** The calc's eligibility/caveat guidance (creation response only). */
  guidance?: string[];
  /** true in the wizard (distinct landmark name from the card's copy). */
  isNew?: boolean;
}) {
  const floorQuote = quoteContaining("pmt_v0", PRECISION_FLOOR_QUOTE_SNIPPET);
  return (
    <section
      className="receipt"
      aria-label={
        isNew
          ? s.planReceipt.newLabel(planLabel(plan))
          : s.planReceipt.label(planLabel(plan))
      }
    >
      <p className="receipt-story">
        {/* Both sizes are the API's verbatim table rows. */}
        {s.planReceipt.requiredLine(String(plan.required_annual))}{" "}
        {s.planReceipt.perPeriodLine(
          String(plan.required_per_period),
          frequencyLabel(plan.frequency),
        )}
      </p>
      <p>{s.planReceipt.citationIntro}</p>
      {/* The calc's own citation text for the table cell, verbatim. */}
      <p className="sampling-citation">
        <cite>{plan.table_citation}</cite>
      </p>
      {/* selector_version verbatim — never split or parsed. */}
      <p className="field-hint">
        {s.planReceipt.lookedUpBy(plan.selector_version)}
      </p>
      {guidance && guidance.length > 0 && (
        <>
          <h3>{s.planReceipt.guidanceHeading}</h3>
          <ul className="sampling-guidance">
            {guidance.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </>
      )}
      <p>{s.planReceipt.floorIntro}</p>
      <ManualQuote quote={floorQuote} />
    </section>
  );
}

// ------------------------------------------------------------------ wizard

interface WizardDraft {
  reportYear: string;
  mode: string;
  typeOfService: string;
  unit: string;
  option: string;
  frequency: string;
}

function emptyDraft(): WizardDraft {
  return {
    // Presentational default the user edits — the API validates the year.
    reportYear: String(new Date().getFullYear()),
    mode: "",
    typeOfService: "",
    unit: "",
    // APTL is preselected (the option Headway carries end-to-end).
    option: "aptl",
    frequency: "",
  };
}

function validateWizard(draft: WizardDraft): string[] {
  const w = s.wizard;
  const messages: string[] = [];
  if (!/^\d{4}$/.test(draft.reportYear.trim())) {
    messages.push(w.reportYearInvalid);
  }
  if (draft.mode === "") messages.push(w.modeRequired);
  if (draft.typeOfService === "") messages.push(w.tosRequired);
  if (draft.unit === "") messages.push(w.unitRequired);
  if (draft.frequency === "") messages.push(w.frequencyRequired);
  return messages;
}

function PlanWizard({
  options,
  onCreated,
}: {
  options: SamplingOptions;
  onCreated: (created: SamplingPlanCreated) => void;
}) {
  const w = s.wizard;
  const formId = useId();
  const ids = {
    reportYear: `${formId}-year`,
    reportYearHint: `${formId}-year-hint`,
    mode: `${formId}-mode`,
    tos: `${formId}-tos`,
    unit: `${formId}-unit`,
    unitHint: `${formId}-unit-hint`,
    frequency: `${formId}-frequency`,
    frequencyHint: `${formId}-frequency-hint`,
  };
  const [draft, setDraft] = useState<WizardDraft>(emptyDraft);
  const [errors, setErrors] = useState<string[] | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const optionsQuote = quoteContaining("sampling_v0", OPTIONS_QUOTE_SNIPPET);

  /** The plain-language explanation per efficiency-option token. */
  const optionExplanations: Record<string, string> = {
    aptl: w.optionAptlExplanation,
    base: w.optionBaseExplanation,
    aptl_grouped: w.optionGroupedExplanation,
  };

  // The units the API's vocabulary allows for the picked mode
  // (Table 41.01 via the calc selector — never a client-side guess).
  const unitOptions = options.units_by_mode[draft.mode] ?? [];

  const handleModeChange = (mode: string) => {
    const allowed = options.units_by_mode[mode] ?? [];
    setDraft((prev) => ({
      ...prev,
      mode,
      // A single-unit mode selects its only Table 41.01 unit; otherwise a
      // stale unit the new mode does not allow is cleared rather than
      // silently submitted.
      unit:
        allowed.length === 1
          ? allowed[0]
          : allowed.includes(prev.unit)
            ? prev.unit
            : "",
    }));
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const messages = validateWizard(draft);
    if (messages.length > 0) {
      setErrors(messages);
      setApiError(null);
      return;
    }
    setErrors(null);
    setApiError(null);
    setSubmitting(true);
    try {
      const created = await createSamplingPlan({
        // A year a person typed (validated above) — workflow entry, not a
        // served figure, so converting it for the JSON body is fine.
        report_year: Number(draft.reportYear.trim()),
        mode: draft.mode,
        type_of_service: draft.typeOfService,
        unit: draft.unit,
        efficiency_option: draft.option,
        frequency: draft.frequency,
      });
      onCreated(created);
      setDraft(emptyDraft());
    } catch (err) {
      setApiError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="sampling-form">
      {errors && (
        <div role="alert" className="alert">
          <p>{w.validationHeading}</p>
          <ul>
            {errors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      )}
      {apiError && (
        // The API's plain-language refusal, verbatim.
        <div role="alert" className="alert">
          {apiError}
        </div>
      )}

      <h3>{w.eligibilityHeading}</h3>
      <p>{w.eligibilityIntro}</p>
      {/* The calc's guidance strings VERBATIM (§41.01/§41.03 quoted inside). */}
      <ul className="sampling-guidance">
        {options.eligibility_guidance.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>

      <label htmlFor={ids.reportYear}>{w.reportYear}</label>
      <p id={ids.reportYearHint} className="field-hint">
        {w.reportYearHint}
      </p>
      <input
        id={ids.reportYear}
        type="text"
        inputMode="numeric"
        className="count-input"
        aria-describedby={ids.reportYearHint}
        value={draft.reportYear}
        onChange={(e) =>
          setDraft((prev) => ({ ...prev, reportYear: e.target.value }))
        }
      />

      <label htmlFor={ids.mode}>{w.mode}</label>
      <select
        id={ids.mode}
        value={draft.mode}
        onChange={(e) => handleModeChange(e.target.value)}
      >
        <option value="">{w.modeUnselected}</option>
        {Object.keys(options.modes).map((code) => (
          <option key={code} value={code}>
            {modeLabel(code)}
          </option>
        ))}
      </select>

      <label htmlFor={ids.tos}>{w.tos}</label>
      <select
        id={ids.tos}
        value={draft.typeOfService}
        onChange={(e) =>
          setDraft((prev) => ({ ...prev, typeOfService: e.target.value }))
        }
      >
        <option value="">{w.tosUnselected}</option>
        {Object.entries(s.tosLabels).map(([code, label]) => (
          <option key={code} value={code}>
            {label}
          </option>
        ))}
      </select>

      <label htmlFor={ids.unit}>{w.unit}</label>
      <p id={ids.unitHint} className="field-hint">
        {w.unitHint}
      </p>
      <select
        id={ids.unit}
        aria-describedby={ids.unitHint}
        value={draft.unit}
        onChange={(e) =>
          setDraft((prev) => ({ ...prev, unit: e.target.value }))
        }
      >
        <option value="">{w.unitUnselected}</option>
        {unitOptions.map((code) => (
          <option key={code} value={code}>
            {unitLabel(code)}
          </option>
        ))}
      </select>

      <fieldset className="sampling-options">
        <legend>{w.option}</legend>
        {options.efficiency_options.map((option) => {
          const creatable = options.creatable_options.includes(option);
          return (
            <div key={option}>
              <div className="sampling-option">
                <input
                  id={`${formId}-${option}`}
                  type="radio"
                  name={`${formId}-option`}
                  aria-describedby={`${formId}-${option}-hint`}
                  checked={draft.option === option}
                  disabled={!creatable}
                  onChange={() => setDraft((prev) => ({ ...prev, option }))}
                />
                <label htmlFor={`${formId}-${option}`}>
                  {optionLabel(option)}
                </label>
              </div>
              <p id={`${formId}-${option}-hint`} className="field-hint">
                {optionExplanations[option] ?? option}
              </p>
            </div>
          );
        })}
        <p>{w.optionsRuleIntro}</p>
        <ManualQuote quote={optionsQuote} />
      </fieldset>

      <label htmlFor={ids.frequency}>{w.frequency}</label>
      <p id={ids.frequencyHint} className="field-hint">
        {w.frequencyHint}
      </p>
      <select
        id={ids.frequency}
        aria-describedby={ids.frequencyHint}
        value={draft.frequency}
        onChange={(e) =>
          setDraft((prev) => ({ ...prev, frequency: e.target.value }))
        }
      >
        <option value="">{w.frequencyUnselected}</option>
        {options.frequencies.map((code) => (
          <option key={code} value={code}>
            {frequencyLabel(code)}
          </option>
        ))}
      </select>

      <p>
        <button type="submit" className="primary" disabled={submitting}>
          {w.submit}
        </button>
      </p>
    </form>
  );
}

// -------------------------------------------------------------------- draw

function DrawForm({
  plan,
  onDrawn,
}: {
  plan: SamplingPlanRecord;
  onDrawn: (created: SamplingDrawCreated) => void;
}) {
  const d = s.draw;
  const ids = {
    period: useId(),
    periodHint: useId(),
    units: useId(),
    unitsHint: useId(),
    seed: useId(),
    seedHint: useId(),
    oversample: useId(),
    oversampleHint: useId(),
  };
  const [period, setPeriod] = useState("");
  const [unitsText, setUnitsText] = useState("");
  const [seed, setSeed] = useState("");
  const [oversample, setOversample] = useState("0");
  const [errors, setErrors] = useState<string[] | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const units = unitsText
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line !== "");
    const messages: string[] = [];
    if (period.trim() === "") messages.push(d.periodRequired);
    if (units.length === 0) messages.push(d.unitsRequired);
    if (seed.trim() !== "" && seed.trim().length < 8) {
      messages.push(d.seedTooShort);
    }
    if (!/^\d+$/.test(oversample.trim())) messages.push(d.oversampleInvalid);
    if (messages.length > 0) {
      setErrors(messages);
      setApiError(null);
      return;
    }
    setErrors(null);
    setApiError(null);
    setSubmitting(true);
    try {
      const extra = Number(oversample.trim());
      const created = await drawSamplingPeriod(plan.plan_id, {
        period_label: period.trim(),
        service_units: units,
        // Blank seed = the API generates one from a cryptographic source
        // and records it; a typed seed is sent (and recorded) verbatim.
        ...(seed.trim() !== "" && { seed: seed.trim() }),
        ...(extra > 0 && { oversample_units: extra }),
      });
      onDrawn(created);
      setPeriod("");
      setUnitsText("");
      setSeed("");
      setOversample("0");
    } catch (err) {
      setApiError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="sampling-draw no-print" aria-label={d.heading}>
      <h4>{d.heading}</h4>
      <p>{d.intro}</p>
      <form onSubmit={handleSubmit} className="sampling-form">
        {errors && (
          <div role="alert" className="alert">
            <p>{d.validationHeading}</p>
            <ul>
              {errors.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </div>
        )}
        {apiError && (
          <div role="alert" className="alert">
            {apiError}
          </div>
        )}
        <label htmlFor={ids.period}>{d.periodLabel}</label>
        <p id={ids.periodHint} className="field-hint">
          {d.periodHint}
        </p>
        <input
          id={ids.period}
          type="text"
          className="count-input"
          aria-describedby={ids.periodHint}
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
        />
        <label htmlFor={ids.units}>{d.unitsLabel}</label>
        <p id={ids.unitsHint} className="field-hint">
          {d.unitsHint}
        </p>
        <textarea
          id={ids.units}
          aria-describedby={ids.unitsHint}
          value={unitsText}
          onChange={(e) => setUnitsText(e.target.value)}
        />
        <label htmlFor={ids.seed}>{d.seedLabel}</label>
        <p id={ids.seedHint} className="field-hint">
          {d.seedHint}
        </p>
        <input
          id={ids.seed}
          type="text"
          aria-describedby={ids.seedHint}
          value={seed}
          onChange={(e) => setSeed(e.target.value)}
        />
        <label htmlFor={ids.oversample}>{d.oversampleLabel}</label>
        <p id={ids.oversampleHint} className="field-hint">
          {d.oversampleHint}
        </p>
        <input
          id={ids.oversample}
          type="text"
          inputMode="numeric"
          className="count-input"
          aria-describedby={ids.oversampleHint}
          value={oversample}
          onChange={(e) => setOversample(e.target.value)}
        />
        <p>
          <button type="submit" className="primary" disabled={submitting}>
            {d.submit}
          </button>
        </p>
      </form>
    </section>
  );
}

// --------------------------------------------------------------- worksheet

/**
 * One period's ride-checker worksheet: the drawn units IN DRAW ORDER with
 * the recorded seed, the sampling-frame size, and the verbatim §63.03
 * rule on the sheet. Printable — the print stylesheet keeps worksheets
 * and drops the app chrome and forms.
 */
function Worksheet({
  draw,
  measurementsByUnit,
}: {
  draw: SamplingDrawRecord;
  measurementsByUnit: Map<string, SamplingMeasurementRecord>;
}) {
  const ws = s.worksheet;
  const selectionQuote = quoteContaining(
    "sampling_v0",
    SELECTION_QUOTE_SNIPPET,
  );
  return (
    <section
      className="sampling-worksheet"
      aria-label={ws.heading(draw.period_label)}
    >
      <h4>{ws.heading(draw.period_label)}</h4>
      <p className="no-print">{ws.intro}</p>
      {/* The recorded seed (§63.03 reproducibility), on the sheet. */}
      <p className="sampling-seed">{ws.seedLine(draw.seed)}</p>
      <p>{ws.frameLine(String(draw.frame_size))}</p>
      {draw.oversample_units > 0 && (
        <p>{ws.oversampleLine(String(draw.oversample_units))}</p>
      )}
      <p>{ws.ruleIntro}</p>
      <ManualQuote quote={selectionQuote} />
      <div className="table-wrap">
        <table>
          <caption>{ws.heading(draw.period_label)}</caption>
          <thead>
            <tr>
              <th scope="col">{ws.columns.position}</th>
              <th scope="col">{ws.columns.unit}</th>
              <th scope="col">{ws.columns.upt}</th>
              <th scope="col">{ws.columns.pmt}</th>
              <th scope="col">{ws.columns.recorded}</th>
            </tr>
          </thead>
          <tbody>
            {draw.selected_units.map((unitId, index) => {
              const measurement = measurementsByUnit.get(unitId);
              return (
                <tr key={unitId}>
                  <td>{index + 1}</td>
                  <td>{unitId}</td>
                  {/* Observed figures verbatim; unmeasured cells are left
                      blank for the checker's pencil. */}
                  <td className="figure">
                    {measurement !== undefined
                      ? String(measurement.observed_upt)
                      : ""}
                  </td>
                  <td className="figure">
                    {measurement !== undefined ? measurement.observed_pmt : ""}
                  </td>
                  <td>
                    {measurement !== undefined
                      ? ws.measuredLine(
                          measurement.entered_by,
                          measurement.entered_at,
                        )
                      : ws.notMeasured}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="sampling-created">
        {ws.drawnLine(draw.drawn_by, draw.drawn_at, draw.drawer_version)}
      </p>
    </section>
  );
}

// ------------------------------------------------------ measurement + meter

/**
 * Sample progress, as the API computed it: measured vs required as TEXT
 * first (the API's counts, verbatim) with a meter for the visual, plus
 * the per-draw lines. The meter position is the ONE piece of arithmetic
 * on this page — integer workflow counts, presentation only, never
 * displayed as a figure. Under target, the API's own no-undersampling
 * citation is shown verbatim where the gap is.
 */
function ProgressPanel({
  progress,
  label,
}: {
  progress: SamplingPlanProgress;
  label: string;
}) {
  const m = s.measure;
  const measured = progress.units_measured;
  const required = progress.required_annual;
  const meterValue =
    required > 0 ? Math.min(100, Math.floor((measured / required) * 100)) : 0;
  const { meterProps } = useMeter({
    value: meterValue,
    minValue: 0,
    maxValue: 100,
    valueLabel: m.progressLine(String(measured), String(required)),
    "aria-label": m.meterLabel(label),
  });
  return (
    <div className="sampling-progress no-print">
      <h4>{m.progressHeading}</h4>
      <div {...meterProps} role="meter" className="coverage-meter">
        <span className="coverage-meter-value">
          {m.progressLine(String(measured), String(required))}
        </span>
        <span className="meter-track">
          <span className="meter-fill" style={{ width: `${meterValue}%` }} />
        </span>
      </div>
      {progress.draws.length > 0 && (
        <ul className="sampling-draw-progress">
          {progress.draws.map((draw) => (
            <li key={draw.period_label}>
              {m.perDrawLine(
                draw.period_label,
                String(draw.measured),
                String(draw.selected),
              )}
            </li>
          ))}
        </ul>
      )}
      {/* The API's verdict and its own regulatory wording, verbatim. */}
      {progress.undersampled && (
        <div className="sampling-under-target">
          <p>{m.underTargetIntro}</p>
          <p className="sampling-citation">
            {progress.undersampling_citation}
          </p>
        </div>
      )}
      {!progress.undersampled && measured > required && (
        <div className="sampling-under-target">
          <p>{m.oversampledIntro}</p>
          <p className="sampling-citation">
            {progress.oversampling_citation}
          </p>
        </div>
      )}
    </div>
  );
}

function MeasurementForm({
  plan,
  progress,
  dayTypes,
  onRecorded,
}: {
  plan: SamplingPlanRecord;
  progress: SamplingPlanProgress;
  dayTypes: string[];
  onRecorded: (unitId: string) => void;
}) {
  const m = s.measure;
  const ids = {
    unit: useId(),
    upt: useId(),
    uptHint: useId(),
    pmt: useId(),
    pmtHint: useId(),
    dayType: useId(),
    dayTypeHint: useId(),
    date: useId(),
    notes: useId(),
  };
  const [unitId, setUnitId] = useState("");
  const [upt, setUpt] = useState("");
  const [pmt, setPmt] = useState("");
  const [dayType, setDayType] = useState("");
  const [serviceDate, setServiceDate] = useState("");
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState<string[] | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (progress.units_unmeasured.length === 0) {
    return (
      <section className="sampling-measure no-print" aria-label={m.heading}>
        <h4>{m.heading}</h4>
        <p>{m.allMeasured}</p>
      </section>
    );
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const messages: string[] = [];
    if (unitId === "") messages.push(m.unitRequired);
    if (!/^\d+$/.test(upt.trim())) messages.push(m.uptInvalid);
    if (!/^\d+(\.\d+)?$/.test(pmt.trim())) messages.push(m.pmtInvalid);
    if (messages.length > 0) {
      setErrors(messages);
      setApiError(null);
      return;
    }
    setErrors(null);
    setApiError(null);
    setSubmitting(true);
    try {
      await recordSamplingMeasurement(plan.plan_id, {
        unit_id: unitId,
        // A whole count a person typed (validated above) — workflow entry,
        // not a served figure, so converting it for the JSON body is fine.
        observed_upt: Number(upt.trim()),
        // The observed miles stay a decimal STRING end to end.
        observed_pmt: pmt.trim(),
        ...(dayType !== "" && { service_day_type: dayType }),
        ...(serviceDate !== "" && { service_date: serviceDate }),
        ...(notes.trim() !== "" && { notes: notes.trim() }),
      });
      onRecorded(unitId);
      setUnitId("");
      setUpt("");
      setPmt("");
      setDayType("");
      setServiceDate("");
      setNotes("");
    } catch (err) {
      setApiError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="sampling-measure no-print" aria-label={m.heading}>
      <h4>{m.heading}</h4>
      <p>{m.intro}</p>
      <form onSubmit={handleSubmit} className="sampling-form">
        {errors && (
          <div role="alert" className="alert">
            <p>{m.validationHeading}</p>
            <ul>
              {errors.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </div>
        )}
        {apiError && (
          // The API's plain-language refusal (e.g. the duplicate-
          // measurement 409, which names the supersede endpoint), verbatim.
          <div role="alert" className="alert">
            {apiError}
          </div>
        )}
        <label htmlFor={ids.unit}>{m.unitLabel}</label>
        <select
          id={ids.unit}
          value={unitId}
          onChange={(e) => setUnitId(e.target.value)}
        >
          <option value="">{m.unitUnselected}</option>
          {progress.units_unmeasured.map((unit) => (
            <option key={unit} value={unit}>
              {unit}
            </option>
          ))}
        </select>
        <label htmlFor={ids.upt}>{m.uptLabel}</label>
        <p id={ids.uptHint} className="field-hint">
          {m.uptHint}
        </p>
        <input
          id={ids.upt}
          type="text"
          inputMode="numeric"
          className="count-input"
          aria-describedby={ids.uptHint}
          value={upt}
          onChange={(e) => setUpt(e.target.value)}
        />
        <label htmlFor={ids.pmt}>{m.pmtLabel}</label>
        <p id={ids.pmtHint} className="field-hint">
          {m.pmtHint}
        </p>
        <input
          id={ids.pmt}
          type="text"
          inputMode="decimal"
          className="count-input"
          aria-describedby={ids.pmtHint}
          value={pmt}
          onChange={(e) => setPmt(e.target.value)}
        />
        <label htmlFor={ids.dayType}>{m.dayTypeLabel}</label>
        <p id={ids.dayTypeHint} className="field-hint">
          {m.dayTypeHint}
        </p>
        <select
          id={ids.dayType}
          aria-describedby={ids.dayTypeHint}
          value={dayType}
          onChange={(e) => setDayType(e.target.value)}
        >
          <option value="">{m.dayTypeUnselected}</option>
          {dayTypes.map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </select>
        <label htmlFor={ids.date}>{m.dateLabel}</label>
        <input
          id={ids.date}
          type="date"
          value={serviceDate}
          onChange={(e) => setServiceDate(e.target.value)}
        />
        <label htmlFor={ids.notes}>{m.notesLabel}</label>
        <input
          id={ids.notes}
          type="text"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
        <p>
          <button type="submit" className="primary" disabled={submitting}>
            {m.submit}
          </button>
        </p>
      </form>
    </section>
  );
}

// ---------------------------------------------------------------- estimate

/** One §83 estimate block's figures, every one the calc's value verbatim. */
function EstimateComponents({ block }: { block: SamplingEstimateBlock }) {
  const r = s.estimate.receipt;
  return (
    <dl>
      <dt>{r.expansionTerm}</dt>
      <dd className="figure">{block.expansion_factor_upt}</dd>
      <dt>{r.aptlTerm}</dt>
      <dd className="figure">{block.sample_aptl}</dd>
      <dt>{r.sampleUptTerm}</dt>
      <dd className="figure">{String(block.sample_total_upt)}</dd>
      <dt>{r.samplePmtTerm}</dt>
      <dd className="figure">{block.sample_total_pmt}</dd>
    </dl>
  );
}

/**
 * The estimate receipt: every figure the calc served, VERBATIM — the
 * expansion factor (the 100% UPT count, §83.01) and the sample APTL
 * (ratio of totals, §83.05) that produced the estimate — with the
 * §83.01/§83.05/§83.07 rules quoted, the calc's citations and caveats
 * verbatim, and the sampled-estimate provenance label kept clearly
 * distinct from computed PMT figures.
 */
function EstimateReceipt({
  response,
  label,
}: {
  response: SamplingEstimateResponse;
  label: string;
}) {
  const r = s.estimate.receipt;
  const estimate = response.estimate;
  const expansionQuote = quoteContaining(
    "sampling_v0",
    EXPANSION_FACTOR_QUOTE_SNIPPET,
  );
  const ratioQuote = quoteContaining(
    "sampling_v0",
    RATIO_OF_TOTALS_QUOTE_SNIPPET,
  );
  const multiplyQuote = quoteContaining("sampling_v0", MULTIPLY_QUOTE_SNIPPET);
  return (
    <section className="receipt" aria-label={r.label(label)}>
      <p className="receipt-story">
        <span className="tag estimate">{r.estimateTag}</span>{" "}
        {r.estimateLine(estimate.estimated_pmt)}
      </p>
      <p className="sampling-distinct-note">{r.distinctNote}</p>
      <p>{r.methodIntro}</p>
      {/* The calc's fixed provenance label for a sampled estimate. */}
      <p className="sampling-citation">
        <cite>{estimate.method}</cite>
      </p>

      <h5>{r.componentsHeading}</h5>
      <EstimateComponents block={estimate} />
      <dl>
        <dt>{r.unitsTerm}</dt>
        <dd>
          {r.unitsValue(
            String(response.units_measured),
            String(response.required_annual),
          )}
        </dd>
        {response.oversampled_by > 0 && (
          <>
            <dt>{r.oversampleTerm}</dt>
            <dd>{r.oversampleValue(String(response.oversampled_by))}</dd>
          </>
        )}
      </dl>

      {/* BOTH sides of "expansion factor × sample APTL", quoted. */}
      <p>{r.expansionRuleIntro}</p>
      <ManualQuote quote={expansionQuote} />
      <p>{r.ratioRuleIntro}</p>
      <ManualQuote quote={ratioQuote} />
      <p>{r.multiplyRuleIntro}</p>
      <ManualQuote quote={multiplyQuote} />

      {/* Day-type blocks, if the API served them — never hidden. */}
      {response.by_service_day !== null &&
        response.by_service_day.length > 0 && (
          <>
            <h5>{r.byDayHeading}</h5>
            {response.by_service_day.map((block) => (
              <div key={block.scope}>
                <h6>{r.byDayBlockLabel(block.scope)}</h6>
                <p className="receipt-story">
                  <span className="tag estimate">{r.estimateTag}</span>{" "}
                  <span className="figure">{block.estimated_pmt}</span>
                </p>
                <EstimateComponents block={block} />
              </div>
            ))}
          </>
        )}

      <h5>{r.citationsHeading}</h5>
      <ul>
        {response.citations.map((citation) => (
          <li key={citation}>
            <cite>{citation}</cite>
          </li>
        ))}
      </ul>

      <h5>{r.caveatsHeading}</h5>
      <ul>
        {response.caveats.map((caveat) => (
          <li key={caveat}>{caveat}</li>
        ))}
      </ul>
    </section>
  );
}

function EstimatePanel({
  plan,
  progress,
  onEstimated,
}: {
  plan: SamplingPlanRecord;
  progress: SamplingPlanProgress;
  onEstimated: (response: SamplingEstimateResponse) => void;
}) {
  const e = s.estimate;
  const ids = {
    expansion: useId(),
    expansionHint: useId(),
    reason: useId(),
  };
  const [expansionUpt, setExpansionUpt] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const baseOption = plan.efficiency_option !== "aptl";
  const underTarget = progress.undersampled;
  const expansionMissing = expansionUpt.trim() === "";
  const estimateDisabled =
    baseOption || underTarget || expansionMissing || submitting;

  const handleClick = async () => {
    // aria-disabled (never the native disabled attribute) keeps the button
    // focusable and clickable, so the refusal is PERCEIVABLE: the click
    // lands here and is refused while the always-visible reason line beside
    // the button says why. Nothing is silently swallowed.
    if (estimateDisabled) return;
    if (!/^\d+(\.\d+)?$/.test(expansionUpt.trim())) {
      setFormError(e.expansionInvalid);
      return;
    }
    setFormError(null);
    setApiError(null);
    setSubmitting(true);
    try {
      const result = await estimateSamplingPmt(plan.plan_id, {
        // The 100% UPT count stays a decimal STRING end to end.
        annual_upt_100pct: expansionUpt.trim(),
      });
      onEstimated(result);
    } catch (err) {
      setApiError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="sampling-estimate no-print" aria-label={e.heading}>
      <h4>{e.heading}</h4>
      <p>{e.intro}</p>
      {formError && (
        <div role="alert" className="alert">
          {formError}
        </div>
      )}
      {apiError && (
        // The API's plain-language refusal (undersampled / Base-option
        // plans are refused server-side too), verbatim.
        <div role="alert" className="alert">
          {apiError}
        </div>
      )}
      <label htmlFor={ids.expansion}>{e.expansionLabel}</label>
      <p id={ids.expansionHint} className="field-hint">
        {e.expansionHint}
      </p>
      <input
        id={ids.expansion}
        type="text"
        inputMode="decimal"
        className="count-input"
        aria-describedby={ids.expansionHint}
        value={expansionUpt}
        onChange={(ev) => setExpansionUpt(ev.target.value)}
      />
      <p>
        <button
          type="button"
          className="primary"
          aria-disabled={estimateDisabled || undefined}
          aria-describedby={estimateDisabled ? ids.reason : undefined}
          onClick={handleClick}
        >
          {e.submit}
        </button>
      </p>
      {/* Reason-at-button (house pattern): EVERY disabled cause is stated
          in an always-visible line exactly where the user is looking. */}
      {estimateDisabled && !submitting && (
        <div
          id={ids.reason}
          className="certify-reason"
          aria-label={e.reasonLabel}
        >
          {baseOption && <p>{e.reasonBase}</p>}
          {!baseOption && underTarget && (
            <p>
              {e.reasonUnderTarget(
                String(progress.units_measured),
                String(progress.required_annual),
              )}
            </p>
          )}
          {!baseOption && !underTarget && expansionMissing && (
            <p>{e.reasonExpansionMissing}</p>
          )}
        </div>
      )}
    </section>
  );
}

// --------------------------------------------------------------- plan card

function PlanCard({
  plan,
  mayManage,
  mayEstimate,
  dayTypes,
  onAnnounce,
}: {
  plan: SamplingPlanRecord;
  mayManage: boolean;
  mayEstimate: boolean;
  dayTypes: string[];
  onAnnounce: (message: string) => void;
}) {
  const headingId = useId();
  const label = planLabel(plan);
  const statusLabel = s.statusLabels[plan.status];
  const [progress, setProgress] = useState<SamplingPlanProgress | null>(null);
  const [draws, setDraws] = useState<SamplingDrawRecord[] | null>(null);
  const [measurements, setMeasurements] = useState<
    SamplingMeasurementRecord[] | null
  >(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [lastDraw, setLastDraw] = useState<SamplingDrawCreated | null>(null);
  const [estimate, setEstimate] = useState<SamplingEstimateResponse | null>(
    null,
  );

  const loadDetail = () =>
    Promise.all([
      getSamplingProgress(plan.plan_id),
      listSamplingDraws(plan.plan_id),
      listSamplingMeasurements(plan.plan_id),
    ])
      .then(([p, d, m]) => {
        setProgress(p);
        setDraws(d);
        setMeasurements(m);
        setDetailError(null);
      })
      .catch((err) =>
        setDetailError(err instanceof ApiError ? err.message : String(err)),
      );

  useEffect(() => {
    void loadDetail();
    // Reload only when the card is for a different plan; writes reload
    // explicitly via the handlers below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan.plan_id]);

  // The ACTIVE observation per unit (append-only history: a superseded
  // record stays in the list; the standing one is the record that counts).
  const measurementsByUnit = new Map<string, SamplingMeasurementRecord>();
  for (const m of measurements ?? []) {
    if (m.superseded_by === null) measurementsByUnit.set(m.unit_id, m);
  }

  return (
    <li>
      <article className="sampling-plan card" aria-labelledby={headingId}>
        <h3 id={headingId}>
          {label} <span className="chip">{statusLabel ?? plan.status}</span>
        </h3>
        {/* An unknown status is stated raw — never hidden. */}
        {statusLabel === undefined && (
          <p className="alert">{s.plans.statusUnknown(plan.status)}</p>
        )}
        <p className="sampling-created no-print">
          {s.plans.createdLine(plan.created_by, plan.created_at)}
        </p>

        <PlanReceipt plan={plan} />

        {detailError && (
          <div role="alert" className="alert">
            {s.plans.detailError(detailError)}
          </div>
        )}

        {draws?.map((draw) => (
          <Worksheet
            key={draw.draw_id}
            draw={draw}
            measurementsByUnit={measurementsByUnit}
          />
        ))}
        {draws && draws.length > 0 && (
          <p className="no-print">
            <button type="button" onClick={() => window.print()}>
              {s.worksheet.printButton}
            </button>
          </p>
        )}

        {/* The drawer's documented procedure, verbatim, after a draw. */}
        {lastDraw && (
          <div className="no-print">
            <p>{s.draw.methodIntro}</p>
            <p className="sampling-citation">
              <cite>{lastDraw.method}</cite>
            </p>
            {lastDraw.oversampling_note !== null && (
              <p className="sampling-citation">
                {lastDraw.oversampling_note}
              </p>
            )}
          </div>
        )}

        {mayManage && (
          <DrawForm
            plan={plan}
            onDrawn={(created) => {
              setLastDraw(created);
              onAnnounce(
                s.draw.drawn(
                  String(created.draw.selected_units.length),
                  created.draw.period_label,
                ),
              );
              void loadDetail();
            }}
          />
        )}

        {progress && draws && draws.length > 0 && (
          <>
            <ProgressPanel progress={progress} label={label} />
            {mayManage && (
              <MeasurementForm
                plan={plan}
                progress={progress}
                dayTypes={dayTypes}
                onRecorded={(unitId) => {
                  onAnnounce(s.measure.recorded(unitId));
                  void loadDetail();
                }}
              />
            )}
            {mayEstimate ? (
              <EstimatePanel
                plan={plan}
                progress={progress}
                onEstimated={(response) => {
                  setEstimate(response);
                  onAnnounce(s.estimate.done);
                }}
              />
            ) : (
              <p className="no-print">{s.estimate.notAllowed}</p>
            )}
            {estimate && (
              <div className="no-print">
                <EstimateReceipt response={estimate} label={label} />
              </div>
            )}
          </>
        )}
      </article>
    </li>
  );
}

// -------------------------------------------------------------------- view

export function SamplingView() {
  const session = useSession();
  const [options, setOptions] = useState<SamplingOptions | null>(null);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [plans, setPlans] = useState<SamplingPlanRecord[] | null>(null);
  const [plansError, setPlansError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState<string | null>(null);
  const [lastCreated, setLastCreated] = useState<SamplingPlanCreated | null>(
    null,
  );

  const mayManage = canManageSampling(session);
  const mayEstimate = canRunSamplingEstimate(session);

  const loadPlans = () =>
    listSamplingPlans()
      .then((list) => {
        setPlans(list);
        setPlansError(null);
      })
      .catch((err) =>
        setPlansError(err instanceof ApiError ? err.message : String(err)),
      );

  useEffect(() => {
    getSamplingOptions()
      .then((o) => {
        setOptions(o);
        setOptionsError(null);
      })
      .catch((err) =>
        setOptionsError(err instanceof ApiError ? err.message : String(err)),
      );
    void loadPlans();
  }, []);

  const handleCreated = (created: SamplingPlanCreated) => {
    setLastCreated(created);
    setAnnouncement(s.wizard.created(String(created.plan.required_annual)));
    // The API is the record: re-read the plans rather than patching state.
    void loadPlans();
  };

  return (
    <>
      <h1>{s.heading}</h1>
      <p className="no-print">{s.intro}</p>
      {/* Honest scope, on every visit (handoff 0012, design point 4). */}
      <p className="banner no-print">{s.alphaBanner}</p>
      {/* The ≥3-year retention rule (design point 2): the calc's own
          note, served by the API and shown verbatim. */}
      {options && <p className="banner no-print">{options.retention_note}</p>}

      {announcement && (
        <div role="status" className="status no-print">
          {announcement}
        </div>
      )}

      <section
        className="card sampling-panel no-print"
        aria-label={s.wizard.heading}
      >
        <h2>{s.wizard.heading}</h2>
        {mayManage ? (
          <>
            <p>{s.wizard.intro}</p>
            {optionsError && (
              <>
                <div role="alert" className="alert">
                  {optionsError}
                </div>
                <p>{s.optionsError}</p>
              </>
            )}
            {!options && !optionsError && <p>{s.optionsLoading}</p>}
            {options && (
              <PlanWizard options={options} onCreated={handleCreated} />
            )}
            {lastCreated && (
              <PlanReceipt
                plan={lastCreated.plan}
                guidance={lastCreated.guidance}
                isNew
              />
            )}
          </>
        ) : (
          <p>{s.wizard.notAllowed}</p>
        )}
      </section>

      <section className="sampling-plans" aria-label={s.plans.heading}>
        <h2 className="no-print">{s.plans.heading}</h2>
        {plansError && (
          <div role="alert" className="alert">
            {plansError}
          </div>
        )}
        {!plans && !plansError && <p>{s.plans.loading}</p>}
        {plans && plans.length === 0 && <p>{s.plans.empty}</p>}
        {plans && plans.length > 0 && (
          <ul className="plan-list">
            {plans.map((plan) => (
              <PlanCard
                key={plan.plan_id}
                plan={plan}
                mayManage={mayManage}
                mayEstimate={mayEstimate}
                dayTypes={options?.service_day_types ?? []}
                onAnnounce={setAnnouncement}
              />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
