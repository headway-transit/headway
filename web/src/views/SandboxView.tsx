/**
 * The settings sandbox (/sandbox — handoff 0017, design point 6): the
 * adapted what-if surface, behind Headway's honesty walls. Typed against
 * services/api routers/sandbox.py EXACTLY (reconciled 2026-07-14).
 *
 * HARD WALLS (binding, restated where the user reads):
 * - "Modeling preview — changes nothing" is the page's prominent banner —
 *   rendered on EVERY visit, plus the server's own banner verbatim on
 *   every preview result. The backend's preview entry points perform NO
 *   writes; previews are EPHEMERAL (`persisted` is a constant false), so
 *   no certification path can ever reach one — and, being unpersisted,
 *   preview figures have no receipt/lineage door: the impact table names
 *   the calc + version instead, and every would-be finding is listed.
 * - There is NO apply button anywhere on this surface, by design. The
 *   server's own settings_flow_note (PUT /settings/{key} — certifying
 *   official only, audited) is rendered verbatim; this page adds its own
 *   plain-language statement of the same rule.
 * - Both variants are computed by the deterministic calc library over the
 *   SAME canonical inputs; the delta is the server's exact Decimal string.
 *   Rendered sign-neutrally — a preview is a model, never a verdict.
 *
 * The knobs offered are the API's previewable knob set (the four NTD
 * calc-policy knobs + the two OTP-window ops knobs); current values,
 * descriptions, and provenance come from GET /settings verbatim.
 */

import { useEffect, useId, useState } from "react";
import { ApiError, listSettings, runSandboxPreview } from "../api/client";
import type {
  PreviewSection,
  PreviewSide,
  SandboxPreviewResponse,
  Setting,
} from "../api/types";
import { copy } from "../copy";
import { isSimulated } from "../detail";
import { DeltaFigure } from "../components/DeltaFigure";
import { OpsBadge } from "../components/OpsBadge";
import { SimulatedBadge } from "../components/SimulatedBadge";
import { pushToast } from "../toasts";

const sb = copy.sandbox;

/**
 * The previewable knob set — mirrors the API's PREVIEWABLE_KNOBS
 * (routers/sandbox.py: POLICY_SETTING_TYPES + OPS_POLICY_SETTING_TYPES).
 * An unknown proposed key is refused server-side with a plain-language
 * 422, surfaced verbatim; this list only decides which settings rows get
 * an input.
 */
const SANDBOX_KNOB_KEYS = [
  "coverage_threshold",
  "gap_threshold_seconds",
  "layover_max_seconds",
  "missing_trip_threshold",
  "otp_early_tolerance_seconds",
  "otp_late_tolerance_seconds",
];

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

/** The /compare scope labeling, reused. */
function scopeLabel(scope: string): string {
  const known = copy.compare.scopeLabels[scope];
  if (known) return known;
  if (scope.startsWith("mode:")) {
    const modeCode = scope.slice("mode:".length).split(":")[0];
    return copy.compare.modeScope(
      copy.safety.modeLabels[modeCode] ??
        copy.report.mr20.modeLabels[modeCode] ??
        modeCode,
    );
  }
  return scope;
}

/** One knob's editor: today's value verbatim + a proposed-value input. */
function KnobField({
  setting,
  proposed,
  onChange,
}: {
  setting: Setting;
  proposed: string;
  onChange: (value: string) => void;
}) {
  const inputId = useId();
  const hintId = useId();
  return (
    <div className="sandbox-knob">
      <label htmlFor={inputId}>{sb.proposedLabel(setting.setting_key)}</label>
      <p id={hintId} className="field-hint">
        {sb.currentValue(setting.setting_value)}
      </p>
      <input
        id={inputId}
        type="text"
        inputMode="decimal"
        className="count-input"
        aria-describedby={hintId}
        value={proposed}
        onChange={(e) => onChange(e.target.value)}
      />
      {/* The setting's own recorded description, verbatim, disclosed. */}
      <details>
        <summary>{sb.descriptionToggle}</summary>
        <p className="field-hint">{setting.description}</p>
      </details>
    </div>
  );
}

/**
 * One variant's outcome: the would-be figure verbatim (with the preview
 * tag and any simulated flag), or the honest refusal with every would-be
 * finding stated — never a blank cell.
 */
function SideCell({ side }: { side: PreviewSide }) {
  const findingTitles = side.findings
    .map((finding) =>
      typeof finding.title === "string"
        ? finding.title
        : JSON.stringify(finding),
    )
    .filter((title) => title.length > 0);
  return (
    <>
      {side.value !== null ? (
        <>
          <span className="figure">{side.value}</span>{" "}
          <span className="tag estimate">{sb.previewTag}</span>
          {isSimulated(side.detail ?? {}) && (
            <>
              {" "}
              <SimulatedBadge />
            </>
          )}
        </>
      ) : (
        <span>{sb.previewRefused}</span>
      )}
      {/* Every would-be finding is shown, never hidden — refusals AND
          standing-figure warnings alike (titles verbatim). */}
      {findingTitles.length > 0 && (
        <ul className="sandbox-findings">
          {findingTitles.map((title) => (
            <li key={title}>{title}</li>
          ))}
        </ul>
      )}
    </>
  );
}

/** One knob family's what-if section (NTD figures, or ops metrics). */
function SectionTable({
  section,
  heading,
  ops,
}: {
  section: PreviewSection;
  heading: string;
  ops: boolean;
}) {
  const knobKeys = Object.keys(section.proposed_thresholds);
  return (
    <section className="sandbox-section" aria-label={heading}>
      <h3>
        {heading}
        {ops && (
          <>
            {" "}
            <OpsBadge />
          </>
        )}
      </h3>
      {/* The knobs BOTH variants ran under: today's audited value (with
          its recorded provenance) beside the proposed value, verbatim. */}
      <ul>
        {knobKeys.map((key) => (
          <li key={key}>
            {sb.settingUsedLine(
              key,
              section.baseline_thresholds[key] ?? "?",
              section.proposed_thresholds[key] ?? "?",
            )}
            {section.baseline_threshold_sources[key] && (
              <span className="field-hint">
                {" "}
                ({section.baseline_threshold_sources[key]})
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="field-hint">
        {sb.inputsLine(
          Object.entries(section.inputs)
            .map(([name, count]) => `${name}: ${count}`)
            .join(" · "),
        )}
      </p>
      <div className="table-wrap">
        <table>
          <caption>{heading}</caption>
          <thead>
            <tr>
              <th scope="col">{sb.columns.figure}</th>
              <th scope="col">{sb.columns.current}</th>
              <th scope="col">{sb.columns.preview}</th>
              <th scope="col">{sb.columns.change}</th>
            </tr>
          </thead>
          <tbody>
            {section.metrics.map((impact) => (
              <tr key={`${impact.calc_name}:${impact.scope}`}>
                <th scope="row">
                  {metricLabel(impact.metric)} — {scopeLabel(impact.scope)}
                  <span className="field-hint">
                    {" "}
                    ({impact.calc_name} {impact.calc_version})
                  </span>
                </th>
                <td className="figure">
                  <SideCell side={impact.baseline} />
                </td>
                <td className="figure">
                  <SideCell side={impact.proposed} />
                </td>
                <td>
                  {/* Sign-neutral ALWAYS here: a preview delta is a model,
                      never a judged outcome. */}
                  <DeltaFigure
                    delta={impact.delta}
                    direction={null}
                    versus={sb.versus}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** The impact rail: what would change, verbatim, changes nothing. */
function ImpactRail({ result }: { result: SandboxPreviewResponse }) {
  return (
    <section className="sandbox-rail" aria-label={sb.railHeading}>
      <h2>{sb.railHeading}</h2>
      {/* The server's own changes-nothing banner, verbatim. */}
      <p className="banner">{result.banner}</p>
      <p>{sb.railIntro}</p>
      <p className="field-hint">
        {sb.railCaption(result.period_start, result.period_end)}{" "}
        {result.period_convention}
      </p>
      {result.ntd && (
        <SectionTable
          section={result.ntd}
          heading={sb.ntdHeading}
          ops={false}
        />
      )}
      {result.ops && (
        <SectionTable section={result.ops} heading={sb.opsHeading} ops />
      )}
      {/* The server's pointer at the audited settings flow, verbatim. */}
      <p className="sandbox-apply-note">{result.settings_flow_note}</p>
    </section>
  );
}

// -------------------------------------------------------------------- view

export function SandboxView() {
  const ids = {
    from: useId(),
    to: useId(),
    reason: useId(),
  };
  const [settings, setSettings] = useState<Setting[] | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [proposed, setProposed] = useState<Record<string, string>>({});
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [result, setResult] = useState<SandboxPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    listSettings()
      .then(setSettings)
      .catch((err) =>
        setSettingsError(err instanceof ApiError ? err.message : String(err)),
      );
  }, []);

  const knobs = (settings ?? []).filter((setting) =>
    SANDBOX_KNOB_KEYS.includes(setting.setting_key),
  );

  const proposedEntries = Object.entries(proposed).filter(
    ([, value]) => value.trim() !== "",
  );
  const nothingProposed = proposedEntries.length === 0;
  const periodMissing = periodStart === "" || periodEnd === "";
  const runDisabled = nothingProposed || periodMissing || running;

  const handleRun = async () => {
    // aria-disabled house pattern: the refusal is perceivable — the click
    // lands here and the always-visible reason line says why.
    if (runDisabled) return;
    setRunning(true);
    setPreviewError(null);
    try {
      const response = await runSandboxPreview({
        period_start: periodStart,
        period_end: periodEnd,
        // Values stay strings end to end (the app.settings discipline).
        proposed: Object.fromEntries(
          proposedEntries.map(([key, value]) => [key, value.trim()]),
        ),
      });
      setResult(response);
      pushToast(sb.previewDone);
    } catch (err) {
      setPreviewError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <h1>{sb.heading}</h1>
      {/* The prominent changes-nothing statement — on EVERY visit. */}
      <p className="banner sandbox-banner">{sb.banner}</p>
      <p>{sb.intro}</p>
      {/* NO apply button anywhere on this surface; the audited flow named. */}
      <p className="sandbox-apply-note">{sb.applyNote}</p>

      <section className="card sandbox-panel" aria-label={sb.settingsHeading}>
        <h2>{sb.settingsHeading}</h2>
        <p>{sb.settingsIntro}</p>
        {settingsError && (
          <>
            <div role="alert" className="alert">
              {settingsError}
            </div>
            <p>{sb.settingsError}</p>
          </>
        )}
        {!settings && !settingsError && <p>{sb.settingsLoading}</p>}
        {settings && knobs.length === 0 && <p>{sb.noKnobs}</p>}
        {knobs.map((setting) => (
          <KnobField
            key={setting.setting_key}
            setting={setting}
            proposed={proposed[setting.setting_key] ?? ""}
            onChange={(value) =>
              setProposed((prev) => ({ ...prev, [setting.setting_key]: value }))
            }
          />
        ))}

        {knobs.length > 0 && (
          <>
            <h3>{sb.periodHeading}</h3>
            <div className="chart-filters">
              <div className="date-range-field">
                <label htmlFor={ids.from}>
                  {copy.dashboard.filters.fromLabel}
                </label>
                <input
                  id={ids.from}
                  type="date"
                  value={periodStart}
                  onChange={(e) => setPeriodStart(e.target.value)}
                />
              </div>
              <div className="date-range-field">
                <label htmlFor={ids.to}>{copy.dashboard.filters.toLabel}</label>
                <input
                  id={ids.to}
                  type="date"
                  value={periodEnd}
                  onChange={(e) => setPeriodEnd(e.target.value)}
                />
              </div>
            </div>

            <p>
              <button
                type="button"
                className="primary"
                aria-disabled={runDisabled || undefined}
                aria-describedby={
                  runDisabled && !running ? ids.reason : undefined
                }
                onClick={handleRun}
              >
                {running ? sb.running : sb.run}
              </button>
            </p>
            {runDisabled && !running && (
              <div
                id={ids.reason}
                className="certify-reason"
                aria-label={sb.reasonLabel}
              >
                {nothingProposed && <p>{sb.reasonNothingProposed}</p>}
                {!nothingProposed && periodMissing && (
                  <p>{sb.reasonPeriodMissing}</p>
                )}
              </div>
            )}
          </>
        )}
      </section>

      {previewError && (
        <div role="alert" className="alert">
          {previewError}
        </div>
      )}
      {result && <ImpactRail result={result} />}
    </>
  );
}
