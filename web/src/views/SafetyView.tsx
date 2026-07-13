/**
 * The Safety & Security module (/safety — handoff 0010, design point 5),
 * typed against services/api routers/safety.py's response models exactly.
 *
 * Three rooms on one page:
 *  1. Reporting deadlines (GET /safety/deadlines): the API-computed S&S-40
 *     due date per open major event and the S&S-50 rows per operated mode
 *     for the month — INCLUDING zero-event rows, with the manual's own
 *     words ("even if no event occurs") quoted beside them. The only date
 *     math this page does is days-between-today-and-the-served-due-date, a
 *     presentation urgency — the due dates themselves come from the API.
 *  2. Event entry (POST /safety/events, data_steward+): plain-language
 *     questions ("Was anyone taken directly from the scene for medical
 *     care?", never "injury threshold"), rail-only questions disclosed only
 *     when the picked mode is rail, client-side validation mirroring the
 *     API contract, and the returned verdict shown as a classification
 *     receipt: the classifier's summary and per-threshold sentences
 *     VERBATIM plus the verified manual quote + page citation per token
 *     (the extract-quotes pattern).
 *  3. Recorded events (GET /safety/events): classification chips (text +
 *     icon + color — never color alone), a thresholds-met receipt per
 *     event, and the append-only correction flow
 *     (POST /safety/events/{id}/supersede, with its required audit reason)
 *     — the original is shown struck and linked, NEVER hidden: hiding it
 *     would break the audit story.
 *
 * THE PAGE NEVER CLASSIFIES. The verdict, thresholds_met, explanations,
 * and summary are the deterministic sscls_v0 classifier's output, shown
 * verbatim. property_damage_usd is a decimal string end to end — never
 * parsed.
 */

import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  createSafetyEvent,
  getSafetyDeadlines,
  listSafetyEvents,
  supersedeSafetyEvent,
} from "../api/client";
import type {
  SafetyClassificationResult,
  SafetyDeadlines,
  SafetyEventRecord,
  SafetyEventRequest,
  ThresholdExplanation,
} from "../api/types";
import { canEnterSafetyEvents, useSession } from "../auth/session";
import { QuoteFigure } from "../components/QuoteFigure";
import { SeverityIcon } from "../components/SeverityIcon";
import { copy } from "../copy";
import { quoteContaining } from "../regulatory/quotes";
import type { RegulatoryQuote } from "../regulatory/quotes";
import {
  SS40_QUOTE_SNIPPET,
  SS50_QUOTE_SNIPPET,
  THRESHOLD_QUOTE_SNIPPETS,
} from "../regulatory/safetyRules";

/**
 * Rail-running modes, mirroring headway_calc/sscls.py RAIL_MODES (the
 * transform's GTFS route_type→mode vocabulary — route_types 0, 1, 2, 5, 7,
 * 12). Rail-only questions are disclosed for these modes only, so the form
 * and the classifier agree on what "rail" means.
 */
const RAIL_MODES = new Set([
  "tram",
  "subway",
  "rail",
  "cable_tram",
  "funicular",
  "monorail",
]);

function isRailMode(mode: string): boolean {
  return RAIL_MODES.has(mode);
}

function modeLabel(code: string): string {
  return copy.safety.modeLabels[code] ?? code;
}

function categoryLabel(code: string): string {
  return copy.safety.form.categoryLabels[code] ?? code;
}

function classificationLabel(code: string): string {
  return copy.safety.classification.labels[code] ?? code;
}

/** "Collision on 2026-07-02 (Bus)" — an event's name everywhere. */
function eventLabelFor(
  category: string,
  occurredAt: string,
  mode: string,
): string {
  return copy.safety.events.eventLabel(
    categoryLabel(category),
    occurredAt.slice(0, 10),
    modeLabel(mode),
  );
}

function eventLabel(event: SafetyEventRecord): string {
  return eventLabelFor(event.event_category, event.occurred_at, event.mode);
}

/**
 * Whole days from today to an ISO due DATE (positive = still ahead).
 * PRESENTATION calendar arithmetic on the API-served due date — the due
 * date itself is the regulatory fact and is always displayed verbatim.
 * UTC component math so the result never shifts with the local timezone.
 */
function daysUntil(dueDate: string, now: Date): number {
  const [y, m, d] = dueDate.split("-").map((part) => Number(part));
  const due = Date.UTC(y, m - 1, d);
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((due - today) / 86_400_000);
}

type Urgency = "overdue" | "due-soon" | "upcoming";

function urgencyFor(days: number): Urgency {
  if (days < 0) return "overdue";
  if (days <= 7) return "due-soon";
  return "upcoming";
}

/** Urgency badge: text + distinct icon shape + color — never color alone. */
function UrgencyBadge({ days }: { days: number }) {
  const urgency = urgencyFor(days);
  const text =
    days < 0
      ? copy.safety.deadlines.overdueBy(String(-days))
      : days === 0
        ? copy.safety.deadlines.dueToday
        : copy.safety.deadlines.dueIn(String(days));
  const iconSeverity =
    urgency === "overdue" ? "blocking" : urgency === "due-soon" ? "warning" : "info";
  return (
    <span className={`deadline-urgency ${urgency}`}>
      <SeverityIcon severity={iconSeverity} />
      {text}
    </span>
  );
}

/** A verbatim manual quote + citation, or the stated absence — never blank
 *  (the shared QuoteFigure, bound to this page's missing-rule copy). */
function ManualQuote({ quote }: { quote: RegulatoryQuote | null }) {
  return (
    <QuoteFigure quote={quote} missingMessage={copy.safety.deadlines.ruleMissing} />
  );
}

/** "2026-06" → "June 2026" (presentation of the API's month key). */
function monthName(month: string): string {
  const [year, m] = month.split("-");
  const name = copy.report.monthNames[Number(m) - 1];
  return name ? `${name} ${year}` : month;
}

// ---------------------------------------------------------------- deadlines

function DeadlinesPanel({ deadlines }: { deadlines: SafetyDeadlines }) {
  const now = new Date();
  const ss40Quote = quoteContaining("sscls_v0", SS40_QUOTE_SNIPPET);
  const ss50Quote = quoteContaining("sscls_v0", SS50_QUOTE_SNIPPET);
  const zeroModes = deadlines.ss50.filter((row) => row.zero_event).length;

  return (
    <section
      className="card safety-panel"
      aria-label={copy.safety.deadlines.heading}
    >
      <h2>{copy.safety.deadlines.heading}</h2>
      <p>{copy.safety.deadlines.intro}</p>

      <h3>{copy.safety.deadlines.ss40Heading}</h3>
      <p>{copy.safety.deadlines.ss40Intro}</p>
      <ManualQuote quote={ss40Quote} />
      {/* The API's own openness caveat (v0 has no submission tracking),
          shown verbatim — semantics the reader must not have to guess. */}
      <p className="field-hint">{deadlines.ss40_note}</p>
      {deadlines.ss40.length === 0 ? (
        <p>{copy.safety.deadlines.ss40None}</p>
      ) : (
        <ul className="deadline-list">
          {deadlines.ss40.map((item) => (
            <li key={item.event_id} className="deadline-item">
              <UrgencyBadge days={daysUntil(item.due_date, now)} />
              <span>
                {copy.safety.deadlines.ss40Item(
                  `${eventLabelFor(item.event_category, item.occurred_at, item.mode)} (${item.event_id})`,
                  item.due_date,
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3>{copy.safety.deadlines.ss50Heading}</h3>
      <p>{copy.safety.deadlines.ss50Intro}</p>
      <ManualQuote quote={ss50Quote} />
      {deadlines.ss50.length === 0 ? (
        <p>{copy.safety.deadlines.ss50None}</p>
      ) : (
        <ul className="deadline-list">
          <li className="deadline-item deadline-month">
            <UrgencyBadge
              days={daysUntil(deadlines.ss50[0].due_date, now)}
            />
            <div>
              <span>
                {copy.safety.deadlines.ss50MonthLine(
                  monthName(deadlines.month),
                  deadlines.ss50[0].due_date,
                )}
                {zeroModes > 0 && (
                  <>
                    {" — "}
                    {copy.safety.deadlines.ss50ZeroModes(String(zeroModes))}
                  </>
                )}
              </span>
              <ul className="deadline-modes">
                {deadlines.ss50.map((row) => (
                  <li key={row.mode}>
                    {modeLabel(row.mode)}
                    {": "}
                    {row.zero_event
                      ? copy.safety.deadlines.ss50ModeZero
                      : copy.safety.deadlines.ss50ModeCount(
                          String(row.non_major_event_count),
                        )}
                  </li>
                ))}
              </ul>
            </div>
          </li>
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------- classification receipt

/** Text + distinct icon shape + color per verdict — never color alone. */
function ClassificationChip({ classification }: { classification: string }) {
  const known =
    classification === "major" ||
    classification === "non_major" ||
    classification === "not_reportable";
  const iconSeverity =
    classification === "major"
      ? "blocking"
      : classification === "non_major"
        ? "warning"
        : "info";
  return (
    <span
      className={`chip classification ${known ? classification : "not_reportable"}`}
    >
      <SeverityIcon severity={iconSeverity} />
      {classificationLabel(classification)}
    </span>
  );
}

/** The verified quote for a classifier token, or the stated gap. */
function TokenQuote({ token }: { token: string }) {
  const snippet = THRESHOLD_QUOTE_SNIPPETS[token];
  const quote = snippet ? quoteContaining("sscls_v0", snippet) : null;
  // variant="gap" — the MUTED stated absence, deliberately not an alert:
  // some tokens (safetyRules.ts — today only non_major_fire) have NO
  // verbatim quote in the tracker BY DESIGN, so they'd otherwise raise a
  // loud alert on every single receipt that meets them. The gap is still
  // stated in words — never a paraphrase in the rule's place, never blank.
  return (
    <QuoteFigure
      quote={quote}
      missingMessage={copy.safety.classification.quoteMissing(token)}
      variant="gap"
    />
  );
}

/**
 * What a receipt renders, from either source: the rich entry response
 * (summary + per-token explanations) or a flat list record (tokens only —
 * the list endpoint serves no explanation text).
 */
interface ReceiptData {
  classification: string;
  thresholds_met: string[];
  explanations: ThresholdExplanation[];
  non_major_basis: ThresholdExplanation[];
  summary: string | null;
  classifier_version: string | null;
}

function receiptFromResult(result: SafetyClassificationResult): ReceiptData {
  return { ...result, summary: result.summary };
}

function receiptFromRecord(event: SafetyEventRecord): ReceiptData | null {
  if (event.classification === null) return null;
  return {
    classification: event.classification,
    thresholds_met: event.thresholds_met ?? [],
    explanations: [],
    non_major_basis: [],
    summary: null,
    classifier_version: event.classifier_version,
  };
}

/**
 * The classification receipt: the verdict, the classifier's plain-language
 * summary and per-threshold sentences VERBATIM (when the response carried
 * them), and — per token — the verified manual quote with its page citation
 * (extract-quotes pattern). Unknown tokens and unmapped quotes are stated,
 * never hidden.
 */
function ClassificationReceipt({
  data,
  label,
}: {
  data: ReceiptData;
  label: string;
}) {
  // Explanations whose token is NOT a met threshold are classifier NOTES
  // (e.g. Scenario E: an assault with vehicle contact is evaluated as a
  // collision) — shown verbatim, never dropped.
  const noteExplanations = data.explanations.filter(
    (e) => !data.thresholds_met.includes(e.threshold),
  );
  return (
    <section
      className="receipt"
      aria-label={copy.safety.classification.receiptLabel(label)}
    >
      <p className="receipt-story">
        <ClassificationChip classification={data.classification} />
      </p>
      {data.classifier_version !== null && (
        <p>{copy.safety.classification.decidedBy(data.classifier_version)}</p>
      )}

      {data.summary !== null && (
        <>
          {/* h3 keeps the heading order clean in BOTH hosts: after the
              entry form's h2 and after an event card's h3 (axe
              heading-order). The summary is the classifier's, verbatim. */}
          <h3>{copy.safety.classification.explanationHeading}</h3>
          <p>{data.summary}</p>
        </>
      )}

      <h3>{copy.safety.classification.thresholdsHeading}</h3>
      {data.thresholds_met.length === 0 ? (
        <p>{copy.safety.classification.thresholdsNone}</p>
      ) : (
        <>
          <ul className="threshold-list">
            {data.thresholds_met.map((token) => {
              const label2 = copy.safety.classification.thresholdLabels[token];
              const explanation = data.explanations.find(
                (e) => e.threshold === token,
              );
              return (
                <li key={token}>
                  {label2 ? (
                    <strong>{label2}</strong>
                  ) : (
                    // FAIL LOUDLY: an unrecognized token is shown raw.
                    <strong>
                      {copy.safety.classification.thresholdUnknown(token)}
                    </strong>
                  )}
                  {explanation && (
                    // The classifier's own sentence + citation, verbatim.
                    <p className="threshold-explanation">
                      {explanation.plain_language}{" "}
                      <cite>{explanation.citation}</cite>
                    </p>
                  )}
                  <TokenQuote token={token} />
                </li>
              );
            })}
          </ul>
          <p className="threshold-one-report">
            {copy.safety.classification.oneReportNote}
          </p>
        </>
      )}

      {noteExplanations.length > 0 && (
        <>
          <h3>{copy.safety.classification.notesHeading}</h3>
          <ul className="threshold-list">
            {noteExplanations.map((note) => (
              <li key={note.threshold}>
                {/* The classifier's own sentence + citation, verbatim. */}
                <p className="threshold-explanation">
                  {note.plain_language} <cite>{note.citation}</cite>
                </p>
                {THRESHOLD_QUOTE_SNIPPETS[note.threshold] && (
                  <TokenQuote token={note.threshold} />
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {data.non_major_basis.length > 0 && (
        <>
          <h3>{copy.safety.classification.nonMajorBasisHeading}</h3>
          <ul className="threshold-list">
            {data.non_major_basis.map((basis) => (
              <li key={basis.threshold}>
                {/* The classifier's own sentence + citation, verbatim. */}
                <p className="threshold-explanation">
                  {basis.plain_language} <cite>{basis.citation}</cite>
                </p>
                {THRESHOLD_QUOTE_SNIPPETS[basis.threshold] && (
                  <TokenQuote token={basis.threshold} />
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

// ------------------------------------------------------------- entry form

interface EventFormProps {
  /** When set, the form is a CORRECTION of this event (prefilled). */
  correcting?: SafetyEventRecord;
  onCancel?: () => void;
  /** Called with the verdict and the recorded event's context on a 2xx. */
  onRecorded: (
    result: SafetyClassificationResult,
    label: string,
    wasCorrection: boolean,
  ) => void;
}

interface Draft {
  occurredAt: string;
  mode: string;
  typeOfService: string;
  category: string;
  narrative: string;
  location: string;
  fatalities: string;
  injuries: string;
  propertyDamage: string;
  towed: boolean;
  evacuationLifeSafety: boolean;
  assaultOnWorker: boolean;
  involvesTransitVehicle: boolean;
  seriousInjury: boolean;
  substantialDamage: boolean;
  involvesSecondRailVehicle: boolean;
  gradeCrossing: boolean;
  runawayTrain: boolean;
  evacuationToRailRow: boolean;
  /** The supersede body's required audit reason (corrections only). */
  reason: string;
}

function draftFrom(event?: SafetyEventRecord): Draft {
  return {
    // datetime-local wants "YYYY-MM-DDTHH:MM".
    occurredAt: event ? event.occurred_at.slice(0, 16) : "",
    mode: event?.mode ?? "",
    typeOfService: event?.type_of_service ?? "",
    category: event?.event_category ?? "",
    narrative: event?.narrative ?? "",
    location: event?.location ?? "",
    fatalities: event ? String(event.fatalities) : "0",
    injuries: event ? String(event.injuries) : "0",
    propertyDamage: event?.property_damage_usd ?? "",
    towed: event?.towed ?? false,
    evacuationLifeSafety: event?.evacuation_life_safety ?? false,
    assaultOnWorker: event?.assault_on_worker ?? false,
    involvesTransitVehicle: event?.involves_transit_vehicle ?? false,
    seriousInjury: event?.serious_injury ?? false,
    substantialDamage: event?.substantial_damage ?? false,
    involvesSecondRailVehicle: event?.involves_second_rail_vehicle ?? false,
    gradeCrossing: event?.grade_crossing ?? false,
    runawayTrain: event?.runaway_train ?? false,
    evacuationToRailRow: event?.evacuation_to_rail_row ?? false,
    reason: "",
  };
}

/**
 * Client-side validation MIRRORS the API contract (required fields with a
 * timezone-carrying timestamp, whole counts, decimal damage, a required
 * correction reason); the API's own refusals still surface verbatim.
 */
function validate(draft: Draft, isCorrection: boolean): string[] {
  const f = copy.safety.form;
  const messages: string[] = [];
  if (draft.occurredAt.trim() === "") messages.push(f.occurredAtRequired);
  if (draft.mode === "") messages.push(f.modeRequired);
  if (draft.category === "") messages.push(f.categoryRequired);
  if (draft.narrative.trim() === "") messages.push(f.narrativeRequired);
  if (isCorrection && draft.reason.trim() === "") {
    messages.push(f.reasonRequired);
  }
  if (!/^\d+$/.test(draft.fatalities.trim())) {
    messages.push(f.countInvalid(f.fatalities));
  }
  if (!/^\d+$/.test(draft.injuries.trim())) {
    messages.push(f.countInvalid(f.injuries));
  }
  const damage = draft.propertyDamage.trim();
  if (damage !== "" && !/^\d+(\.\d{1,2})?$/.test(damage)) {
    messages.push(f.damageInvalid);
  }
  return messages;
}

/** The request body — rail-only answers are sent only for rail modes. */
function toRequest(draft: Draft): SafetyEventRequest {
  const rail = isRailMode(draft.mode);
  const damage = draft.propertyDamage.trim();
  return {
    // toISOString gives the timezone-carrying timestamp the API requires.
    occurred_at: new Date(draft.occurredAt).toISOString(),
    mode: draft.mode,
    ...(draft.typeOfService !== "" && {
      type_of_service: draft.typeOfService,
    }),
    event_category: draft.category,
    narrative: draft.narrative,
    ...(draft.location.trim() !== "" && { location: draft.location.trim() }),
    // Workflow-entered whole counts a person typed (validated above) — not
    // served figures, so converting them for the JSON body is fine.
    fatalities: Number(draft.fatalities.trim()),
    injuries: Number(draft.injuries.trim()),
    // The damage estimate stays a decimal STRING end to end.
    ...(damage !== "" && { property_damage_usd: damage }),
    towed: draft.towed,
    evacuation_life_safety: draft.evacuationLifeSafety,
    assault_on_worker: draft.assaultOnWorker,
    involves_transit_vehicle: draft.involvesTransitVehicle,
    ...(rail && {
      serious_injury: draft.seriousInjury,
      substantial_damage: draft.substantialDamage,
      involves_second_rail_vehicle: draft.involvesSecondRailVehicle,
      grade_crossing: draft.gradeCrossing,
      runaway_train: draft.runawayTrain,
      evacuation_to_rail_row: draft.evacuationToRailRow,
    }),
  };
}

function EventForm({ correcting, onCancel, onRecorded }: EventFormProps) {
  const f = copy.safety.form;
  const ids = {
    occurredAt: useId(),
    mode: useId(),
    modeHint: useId(),
    typeOfService: useId(),
    category: useId(),
    categoryHint: useId(),
    narrative: useId(),
    narrativeHint: useId(),
    location: useId(),
    fatalities: useId(),
    fatalitiesHint: useId(),
    injuries: useId(),
    injuriesHint: useId(),
    propertyDamage: useId(),
    propertyDamageHint: useId(),
    assaultHint: useId(),
    transitVehicleHint: useId(),
    seriousInjuryHint: useId(),
    substantialDamageHint: useId(),
    secondRailHint: useId(),
    towedHint: useId(),
    runawayHint: useId(),
    evacRowHint: useId(),
    reason: useId(),
    reasonHint: useId(),
  };
  const [draft, setDraft] = useState<Draft>(() => draftFrom(correcting));
  const [errors, setErrors] = useState<string[] | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const rail = isRailMode(draft.mode);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  const handleModeChange = (mode: string) => {
    setDraft((prev) => ({
      ...prev,
      mode,
      // Derailment is a rail-only category: leaving rail clears it rather
      // than silently submitting a rail category for a non-rail mode.
      category:
        !isRailMode(mode) && prev.category === "derailment"
          ? ""
          : prev.category,
    }));
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const messages = validate(draft, correcting !== undefined);
    if (messages.length > 0) {
      setErrors(messages);
      setApiError(null);
      return;
    }
    setErrors(null);
    setApiError(null);
    setSubmitting(true);
    try {
      const body = toRequest(draft);
      const label = eventLabelFor(
        body.event_category,
        body.occurred_at,
        body.mode,
      );
      const result = correcting
        ? (
            await supersedeSafetyEvent(correcting.event_id, {
              ...body,
              reason: draft.reason.trim(),
            })
          ).result
        : (await createSafetyEvent(body)).result;
      onRecorded(result, label, correcting !== undefined);
      if (!correcting) setDraft(draftFrom());
    } catch (err) {
      setApiError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const categories = Object.entries(f.categoryLabels).filter(
    ([code]) => code !== "derailment" || rail,
  );

  return (
    <form onSubmit={handleSubmit} className="safety-form">
      {errors && (
        <div role="alert" className="alert">
          <p>{f.validationHeading}</p>
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

      <label htmlFor={ids.occurredAt}>{f.occurredAt}</label>
      <input
        id={ids.occurredAt}
        type="datetime-local"
        value={draft.occurredAt}
        onChange={(e) => set("occurredAt", e.target.value)}
      />

      <label htmlFor={ids.mode}>{f.mode}</label>
      <p id={ids.modeHint} className="field-hint">
        {f.modeHint}
      </p>
      <select
        id={ids.mode}
        aria-describedby={ids.modeHint}
        value={draft.mode}
        onChange={(e) => handleModeChange(e.target.value)}
      >
        <option value="">{f.modeUnselected}</option>
        {Object.entries(copy.safety.modeLabels).map(([code, label]) => (
          <option key={code} value={code}>
            {label}
          </option>
        ))}
      </select>

      <label htmlFor={ids.typeOfService}>{f.typeOfService}</label>
      <select
        id={ids.typeOfService}
        value={draft.typeOfService}
        onChange={(e) => set("typeOfService", e.target.value)}
      >
        {Object.entries(f.typeOfServiceOptions).map(([code, label]) => (
          <option key={code} value={code}>
            {label}
          </option>
        ))}
      </select>

      <label htmlFor={ids.category}>{f.category}</label>
      <p id={ids.categoryHint} className="field-hint">
        {f.cyberHint}
      </p>
      <select
        id={ids.category}
        aria-describedby={ids.categoryHint}
        value={draft.category}
        onChange={(e) => set("category", e.target.value)}
      >
        <option value="">{f.categoryUnselected}</option>
        {categories.map(([code, label]) => (
          <option key={code} value={code}>
            {label}
          </option>
        ))}
      </select>

      <label htmlFor={ids.narrative}>{f.narrative}</label>
      <p id={ids.narrativeHint} className="field-hint">
        {f.narrativeHint}
      </p>
      <textarea
        id={ids.narrative}
        aria-describedby={ids.narrativeHint}
        value={draft.narrative}
        onChange={(e) => set("narrative", e.target.value)}
      />

      <label htmlFor={ids.location}>{f.location}</label>
      <input
        id={ids.location}
        type="text"
        value={draft.location}
        onChange={(e) => set("location", e.target.value)}
      />

      <label htmlFor={ids.fatalities}>{f.fatalities}</label>
      <p id={ids.fatalitiesHint} className="field-hint">
        {f.fatalitiesHint}
      </p>
      <input
        id={ids.fatalities}
        type="text"
        inputMode="numeric"
        className="count-input"
        aria-describedby={ids.fatalitiesHint}
        value={draft.fatalities}
        onChange={(e) => set("fatalities", e.target.value)}
      />

      <label htmlFor={ids.injuries}>{f.injuries}</label>
      <p id={ids.injuriesHint} className="field-hint">
        {f.injuriesHint}
      </p>
      <input
        id={ids.injuries}
        type="text"
        inputMode="numeric"
        className="count-input"
        aria-describedby={ids.injuriesHint}
        value={draft.injuries}
        onChange={(e) => set("injuries", e.target.value)}
      />

      <label htmlFor={ids.propertyDamage}>{f.propertyDamage}</label>
      <p id={ids.propertyDamageHint} className="field-hint">
        {f.propertyDamageHint}
      </p>
      <input
        id={ids.propertyDamage}
        type="text"
        inputMode="decimal"
        className="count-input"
        aria-describedby={ids.propertyDamageHint}
        value={draft.propertyDamage}
        onChange={(e) => set("propertyDamage", e.target.value)}
      />

      <div className="safety-checkbox">
        <input
          id={`${ids.occurredAt}-towed`}
          type="checkbox"
          aria-describedby={ids.towedHint}
          checked={draft.towed}
          onChange={(e) => set("towed", e.target.checked)}
        />
        <label htmlFor={`${ids.occurredAt}-towed`}>{f.towed}</label>
      </div>
      <p id={ids.towedHint} className="field-hint">
        {f.towedHint}
      </p>

      <div className="safety-checkbox">
        <input
          id={`${ids.occurredAt}-evac`}
          type="checkbox"
          checked={draft.evacuationLifeSafety}
          onChange={(e) => set("evacuationLifeSafety", e.target.checked)}
        />
        <label htmlFor={`${ids.occurredAt}-evac`}>
          {f.evacuationLifeSafety}
        </label>
      </div>

      <div className="safety-checkbox">
        <input
          id={`${ids.occurredAt}-assault`}
          type="checkbox"
          aria-describedby={ids.assaultHint}
          checked={draft.assaultOnWorker}
          onChange={(e) => set("assaultOnWorker", e.target.checked)}
        />
        <label htmlFor={`${ids.occurredAt}-assault`}>{f.assaultOnWorker}</label>
      </div>
      <p id={ids.assaultHint} className="field-hint">
        {f.assaultOnWorkerHint}
      </p>

      <div className="safety-checkbox">
        <input
          id={`${ids.occurredAt}-vehicle`}
          type="checkbox"
          aria-describedby={ids.transitVehicleHint}
          checked={draft.involvesTransitVehicle}
          onChange={(e) => set("involvesTransitVehicle", e.target.checked)}
        />
        <label htmlFor={`${ids.occurredAt}-vehicle`}>
          {f.involvesTransitVehicle}
        </label>
      </div>
      <p id={ids.transitVehicleHint} className="field-hint">
        {f.involvesTransitVehicleHint}
      </p>

      {/* Rail-only questions — disclosed only when the mode is rail. */}
      {rail && (
        <fieldset className="rail-fields">
          <legend>{f.railHeading}</legend>
          <p className="field-hint">{f.railIntro}</p>

          <div className="safety-checkbox">
            <input
              id={`${ids.occurredAt}-serious`}
              type="checkbox"
              aria-describedby={ids.seriousInjuryHint}
              checked={draft.seriousInjury}
              onChange={(e) => set("seriousInjury", e.target.checked)}
            />
            <label htmlFor={`${ids.occurredAt}-serious`}>
              {f.seriousInjury}
            </label>
          </div>
          <p id={ids.seriousInjuryHint} className="field-hint">
            {f.seriousInjuryHint}
          </p>

          <div className="safety-checkbox">
            <input
              id={`${ids.occurredAt}-substantial`}
              type="checkbox"
              aria-describedby={ids.substantialDamageHint}
              checked={draft.substantialDamage}
              onChange={(e) => set("substantialDamage", e.target.checked)}
            />
            <label htmlFor={`${ids.occurredAt}-substantial`}>
              {f.substantialDamage}
            </label>
          </div>
          <p id={ids.substantialDamageHint} className="field-hint">
            {f.substantialDamageHint}
          </p>

          <div className="safety-checkbox">
            <input
              id={`${ids.occurredAt}-second-rail`}
              type="checkbox"
              aria-describedby={ids.secondRailHint}
              checked={draft.involvesSecondRailVehicle}
              onChange={(e) =>
                set("involvesSecondRailVehicle", e.target.checked)
              }
            />
            <label htmlFor={`${ids.occurredAt}-second-rail`}>
              {f.involvesSecondRailVehicle}
            </label>
          </div>
          <p id={ids.secondRailHint} className="field-hint">
            {f.involvesSecondRailVehicleHint}
          </p>

          <div className="safety-checkbox">
            <input
              id={`${ids.occurredAt}-crossing`}
              type="checkbox"
              checked={draft.gradeCrossing}
              onChange={(e) => set("gradeCrossing", e.target.checked)}
            />
            <label htmlFor={`${ids.occurredAt}-crossing`}>
              {f.gradeCrossing}
            </label>
          </div>

          <div className="safety-checkbox">
            <input
              id={`${ids.occurredAt}-runaway`}
              type="checkbox"
              aria-describedby={ids.runawayHint}
              checked={draft.runawayTrain}
              onChange={(e) => set("runawayTrain", e.target.checked)}
            />
            <label htmlFor={`${ids.occurredAt}-runaway`}>
              {f.runawayTrain}
            </label>
          </div>
          <p id={ids.runawayHint} className="field-hint">
            {f.runawayTrainHint}
          </p>

          <div className="safety-checkbox">
            <input
              id={`${ids.occurredAt}-evac-row`}
              type="checkbox"
              aria-describedby={ids.evacRowHint}
              checked={draft.evacuationToRailRow}
              onChange={(e) => set("evacuationToRailRow", e.target.checked)}
            />
            <label htmlFor={`${ids.occurredAt}-evac-row`}>
              {f.evacuationToRailRow}
            </label>
          </div>
          <p id={ids.evacRowHint} className="field-hint">
            {f.evacuationToRailRowHint}
          </p>
        </fieldset>
      )}

      {/* The required audit reason — corrections only. */}
      {correcting && (
        <>
          <label htmlFor={ids.reason}>{f.reason}</label>
          <p id={ids.reasonHint} className="field-hint">
            {f.reasonHint}
          </p>
          <textarea
            id={ids.reason}
            aria-describedby={ids.reasonHint}
            value={draft.reason}
            onChange={(e) => set("reason", e.target.value)}
          />
        </>
      )}

      <p>
        <button type="submit" className="primary" disabled={submitting}>
          {correcting ? f.submitCorrection : f.submit}
        </button>{" "}
        {correcting && onCancel && (
          <button type="button" onClick={onCancel}>
            {f.cancelCorrection}
          </button>
        )}
      </p>
    </form>
  );
}

// ------------------------------------------------------------- event card

interface EventCardProps {
  event: SafetyEventRecord;
  mayEnter: boolean;
  onRecorded: (
    result: SafetyClassificationResult,
    label: string,
    wasCorrection: boolean,
  ) => void;
}

function EventCard({ event, mayEnter, onRecorded }: EventCardProps) {
  const headingId = useId();
  const [receiptOpen, setReceiptOpen] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const label = eventLabel(event);
  const superseded = event.superseded_by !== null;
  const e = copy.safety.events;
  const receipt = receiptFromRecord(event);

  const circumstances = Object.entries(e.circumstances)
    .filter(([key]) => event[key as keyof SafetyEventRecord] === true)
    .map(([, phrase]) => phrase);

  return (
    <li>
      <article
        id={`event-${event.event_id}`}
        className={`safety-event card${superseded ? " superseded" : ""}`}
        aria-labelledby={headingId}
      >
        <h3 id={headingId}>
          {/* A corrected original is struck AND labeled — never hidden. */}
          {superseded ? <s>{label}</s> : label}{" "}
          {event.classification !== null && (
            <ClassificationChip classification={event.classification} />
          )}{" "}
          {superseded && (
            <span className="tag pre-verification">{e.supersededTag}</span>
          )}
        </h3>
        {/* A record with no classification is a LOUD gap, never blank. */}
        {event.classification === null && (
          <p className="alert">{copy.safety.classification.missing}</p>
        )}
        {superseded && (
          <p className="superseded-note">
            {e.supersededNote}{" "}
            <a href={`#event-${event.superseded_by}`}>
              {e.supersededBy(event.superseded_by ?? "")}
            </a>
          </p>
        )}
        <p className="safety-narrative">{event.narrative}</p>
        <dl>
          <dt>{e.occurredLabel}</dt>
          <dd>{event.occurred_at}</dd>
          <dt>{e.modeLabel}</dt>
          <dd>{modeLabel(event.mode)}</dd>
          {event.type_of_service && (
            <>
              <dt>{e.typeOfServiceLabel}</dt>
              <dd>
                {copy.safety.form.typeOfServiceOptions[event.type_of_service] ??
                  event.type_of_service}
              </dd>
            </>
          )}
          {event.location && (
            <>
              <dt>{e.locationLabel}</dt>
              <dd>{event.location}</dd>
            </>
          )}
          <dt>{e.fatalitiesLabel}</dt>
          <dd>{event.fatalities}</dd>
          <dt>{e.injuriesLabel}</dt>
          <dd>{event.injuries}</dd>
          {event.property_damage_usd != null && (
            <>
              <dt>{e.damageLabel}</dt>
              {/* The decimal string verbatim — never parsed or reformatted. */}
              <dd>{e.damageValue(event.property_damage_usd)}</dd>
            </>
          )}
          {circumstances.length > 0 && (
            <>
              <dt>{e.circumstancesLabel}</dt>
              <dd>{circumstances.join("; ")}</dd>
            </>
          )}
        </dl>
        <p className="safety-entered">
          {e.enteredLine(event.entered_by, event.entered_at)}
        </p>

        {receipt && (
          <button
            type="button"
            aria-expanded={receiptOpen}
            onClick={() => setReceiptOpen((open) => !open)}
          >
            {e.receiptToggle(label)}
          </button>
        )}
        {receipt && receiptOpen && (
          <ClassificationReceipt data={receipt} label={label} />
        )}

        {/* Correcting a record that still stands; a superseded record is
            corrected via its replacement, so it gets no button. */}
        {mayEnter && !superseded && !correcting && (
          <p>
            <button type="button" onClick={() => setCorrecting(true)}>
              {e.correctButton(label)}
            </button>
          </p>
        )}
        {correcting && (
          <section
            aria-label={copy.safety.form.correctionHeading(label)}
            className="correction-form"
          >
            <h4>{copy.safety.form.correctionHeading(label)}</h4>
            <p>{copy.safety.form.correctionIntro}</p>
            <EventForm
              correcting={event}
              onCancel={() => setCorrecting(false)}
              onRecorded={(result, recordedLabel, wasCorrection) => {
                setCorrecting(false);
                onRecorded(result, recordedLabel, wasCorrection);
              }}
            />
          </section>
        )}
      </article>
    </li>
  );
}

// ------------------------------------------------------------------ view

export function SafetyView() {
  const session = useSession();
  const [events, setEvents] = useState<SafetyEventRecord[] | null>(null);
  const [deadlines, setDeadlines] = useState<SafetyDeadlines | null>(null);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [deadlinesError, setDeadlinesError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState<string | null>(null);
  const [lastRecorded, setLastRecorded] = useState<{
    result: SafetyClassificationResult;
    label: string;
  } | null>(null);

  const mayEnter = canEnterSafetyEvents(session);

  const loadEvents = () =>
    listSafetyEvents()
      .then((list) => {
        setEvents(list);
        setEventsError(null);
      })
      .catch((err) =>
        setEventsError(err instanceof ApiError ? err.message : String(err)),
      );

  const loadDeadlines = () =>
    getSafetyDeadlines()
      .then((d) => {
        setDeadlines(d);
        setDeadlinesError(null);
      })
      .catch((err) =>
        setDeadlinesError(err instanceof ApiError ? err.message : String(err)),
      );

  useEffect(() => {
    void loadEvents();
    void loadDeadlines();
  }, []);

  const handleRecorded = (
    result: SafetyClassificationResult,
    label: string,
    wasCorrection: boolean,
  ) => {
    setLastRecorded({ result, label });
    setAnnouncement(
      wasCorrection
        ? copy.safety.form.correctionRecorded(
            classificationLabel(result.classification),
          )
        : copy.safety.form.recorded(
            classificationLabel(result.classification),
          ),
    );
    // The API is the record: re-read events and deadlines rather than
    // patching local state (a new major event changes the S&S-40 list).
    void loadEvents();
    void loadDeadlines();
  };

  return (
    <>
      <h1>{copy.safety.heading}</h1>
      <p>{copy.safety.intro}</p>
      {/* Honest scope, on every visit — alpha, no e-filing. */}
      <p className="banner">{copy.safety.alphaBanner}</p>

      {announcement && (
        <div role="status" className="status">
          {announcement}
        </div>
      )}

      {deadlinesError && (
        <div role="alert" className="alert">
          {deadlinesError}
        </div>
      )}
      {!deadlines && !deadlinesError && (
        <p>{copy.safety.deadlines.loading}</p>
      )}
      {deadlines && <DeadlinesPanel deadlines={deadlines} />}

      <section
        className="card safety-panel"
        aria-label={copy.safety.form.heading}
      >
        <h2>{copy.safety.form.heading}</h2>
        {mayEnter ? (
          <>
            <p>{copy.safety.form.intro}</p>
            <EventForm onRecorded={handleRecorded} />
            {lastRecorded && (
              <ClassificationReceipt
                data={receiptFromResult(lastRecorded.result)}
                label={lastRecorded.label}
              />
            )}
          </>
        ) : (
          <p>{copy.safety.form.notAllowed}</p>
        )}
      </section>

      <section
        className="safety-events"
        aria-label={copy.safety.events.heading}
      >
        <h2>{copy.safety.events.heading}</h2>
        {eventsError && (
          <div role="alert" className="alert">
            {eventsError}
          </div>
        )}
        {!events && !eventsError && <p>{copy.safety.events.loading}</p>}
        {events && events.length === 0 && <p>{copy.safety.events.empty}</p>}
        {events && events.length > 0 && (
          <ul className="event-list">
            {events.map((event) => (
              <EventCard
                key={event.event_id}
                event={event}
                mayEnter={mayEnter}
                onRecorded={handleRecorded}
              />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
