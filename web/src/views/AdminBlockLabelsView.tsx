/**
 * /admin/block-labels — name blocks the way the run board names them.
 *
 * WHY THIS IS A SCREEN. The derivation has existed as a command-line tool
 * since handoff 0038 and was never run once, because running it means a
 * terminal, a database password and a Python invocation. The person who needs
 * it is an ITS manager who was one week into Linux when this started. A
 * one-time load that decides how every future finding READS is not a good
 * reason to hand somebody a shell.
 *
 * TWO STEPS, AND THE FILE IS UPLOADED TWICE. "Check this file" reports what
 * would happen; "Save these block names" derives again from the same file and
 * writes. Nothing is cached on either side. A cached preview would let the
 * approval and the write describe different bytes.
 *
 * WHAT THIS SCREEN REFUSES TO SMOOTH OVER. A partial result is the expected
 * result — the join key is route plus first departure, which does not
 * separate every block. So the counts are shown whole, the leftovers are
 * shown with their reasons, and the page says plainly that an unnamed block
 * keeps its feed id. Reporting only the good number would leave someone
 * believing every block was named.
 */

import { useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  loadBlockLabels,
  previewBlockLabels,
  type BlockLabelPreview,
  type BlockLabelProblemRow,
  type ServiceDayNote,
} from "../api/client";
import { canCertify, useSession } from "../auth/session";
import { Breadcrumbs } from "../components/Breadcrumbs";
import { copy } from "../copy";

const t = copy.admin.blockLabels;

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}

/** One complete count. Never a percentage — a share of an unknown whole is
 *  not a fact anyone can act on. */
function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="block-label-count">
      <dt>{label}</dt>
      <dd>{value.toLocaleString("en-US")}</dd>
    </div>
  );
}

function ProblemTable({
  heading,
  rows,
}: {
  heading: string;
  rows: BlockLabelProblemRow[];
}) {
  if (rows.length === 0) return null;
  return (
    <>
      <h4>{heading}</h4>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">{t.columnLine}</th>
              <th scope="col">{t.columnTrip}</th>
              <th scope="col">{t.columnBlock}</th>
              <th scope="col">{t.columnReason}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.line}-${row.trip_name}`}>
                <td>{row.line}</td>
                <td>{row.trip_name}</td>
                <td>{row.block_name}</td>
                <td>{row.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/**
 * What each service day in the file was used for. This is shown whether or
 * not it helped, because a narrowing nobody can inspect is a narrowing
 * nobody should trust — and a reader who sees only the improved counts would
 * assume every service day was separated when some were left alone.
 */
function ServiceDays({ notes }: { notes: ServiceDayNote[] }) {
  if (notes.length === 0) return null;
  return (
    <>
      <h4>{t.serviceDaysHeading}</h4>
      <p>{t.serviceDaysIntro}</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">{t.columnServiceDay}</th>
              <th scope="col">{t.columnUsed}</th>
              <th scope="col">{t.columnTripsNamed}</th>
              <th scope="col">{t.columnWhy}</th>
            </tr>
          </thead>
          <tbody>
            {notes.map((n) => (
              <tr key={n.service_day}>
                <td>{n.service_day}</td>
                {/* Text, never colour alone — WCAG AA. */}
                <td>{n.used ? t.serviceDayUsed : t.serviceDayNotUsed}</td>
                <td>{t.serviceDayTrips(n.trips_named)}</td>
                <td>{n.explanation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/**
 * The last mile, shown only after a save actually wrote something.
 *
 * Saving changes nothing a person can see until a calculation runs AND they
 * open Data Quality. The first operator to use this screen went looking on
 * the certification screen, where block names do not appear and never will —
 * `block_label` is rendered in exactly one view. "Findings raised from here
 * on" was true and useless: it named neither the screen nor the step.
 */
function NextSteps({ derived }: { derived: number }) {
  if (derived === 0) return null;
  return (
    <section className="card">
      <h3>{t.nextStepsHeading}</h3>
      <ol>
        {t.nextSteps.map((step) => (
          <li key={step.slice(0, 24)}>{step}</li>
        ))}
      </ol>
      <p className="block-label-actions">
        <Link to="/calc-runs">{t.nextStepsCalcLink}</Link>
        <Link to="/dq">{t.nextStepsDqLink}</Link>
      </p>
      {/* Ingestion is upstream of all of it: a name can only reach a finding
          that something raised. Worth saying here rather than leaving an
          operator to conclude the upload failed. */}
      <p className="field-hint">{t.nextStepsNoData}</p>
    </section>
  );
}

function Result({
  result,
  saved,
}: {
  result: BlockLabelPreview;
  saved: boolean;
}) {
  const problems =
    result.ambiguous_examples.length +
    result.unmatched_examples.length +
    result.unparseable_examples.length;

  return (
    <section className="card">
      <h3>{t.resultHeading}</h3>
      {/* The server's own sentence, verbatim. It is the one place that knows
          whether anything was written. */}
      <p role="status" className={saved ? "status" : "banner"}>
        {result.note}
      </p>

      <dl className="block-label-counts">
        <Count label={t.readLabel} value={result.rows_read} />
        <Count label={t.matchedLabel} value={result.matched} />
        <Count label={t.ambiguousLabel} value={result.ambiguous} />
        <Count label={t.unmatchedLabel} value={result.unmatched} />
        <Count label={t.unparseableLabel} value={result.unparseable} />
        <Count
          label={saved ? t.derivedLabelSaved : t.derivedLabel}
          value={result.labels_derived}
        />
        <Count label={t.conflictsLabel} value={result.conflicts} />
      </dl>

      {result.labels_derived === 0 ? (
        <p className="banner">{t.nothingToSave}</p>
      ) : (
        // Said on every result, not only bad ones: a partial mapping is the
        // normal outcome of this join, and someone who is not told that will
        // read the leftover count as a failure.
        <p>{t.partialNote(result.labels_derived, result.rows_read)}</p>
      )}

      {result.service_days.some((n) => !n.used) && (
        // Shown only when a period would actually have helped. An always-on
        // nudge is noise; this one names a problem the reader can see above.
        <p className="banner">{t.scheduleDateNudge}</p>
      )}
      <ServiceDays notes={result.service_days} />

      {result.conflict_notes.length > 0 && (
        <>
          <h4>{t.conflictsHeading}</h4>
          <p>{t.conflictsIntro}</p>
          <ul>
            {result.conflict_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </>
      )}

      {problems > 0 && (
        <>
          <h4>{t.problemsHeading}</h4>
          <p className="field-hint">{t.capNote(result.examples_capped_at)}</p>
          <ProblemTable
            heading={t.unmatchedLabel}
            rows={result.unmatched_examples}
          />
          <ProblemTable
            heading={t.ambiguousLabel}
            rows={result.ambiguous_examples}
          />
          <ProblemTable
            heading={t.unparseableLabel}
            rows={result.unparseable_examples}
          />
        </>
      )}
    </section>
  );
}

export function AdminBlockLabelsView() {
  const session = useSession();
  const allowed = canCertify(session);
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<BlockLabelPreview | null>(null);
  const [saved, setSaved] = useState<BlockLabelPreview | null>(null);
  const [scheduleDate, setScheduleDate] = useState("");
  const [busy, setBusy] = useState<null | "preview" | "load">(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const fileId = useId();
  const fileHintId = useId();
  const dateId = useId();
  const dateHintId = useId();

  if (!allowed) {
    return (
      <>
        <Breadcrumbs
          trail={[{ label: copy.admin.heading, to: "/admin" }, { label: t.heading }]}
        />
        <h1>{t.heading}</h1>
        <p>{t.notAllowed}</p>
      </>
    );
  }

  const chooseFile = (next: File | null) => {
    setFile(next);
    // A new file invalidates the old verdict. Leaving a stale preview on
    // screen beside a new file is how someone approves the wrong thing.
    setPreview(null);
    setSaved(null);
    setErrorMessage(null);
  };

  const run = (which: "preview" | "load") => {
    if (busy) return;
    if (!file) {
      setErrorMessage(t.chooseFirst);
      return;
    }
    setBusy(which);
    setErrorMessage(null);
    void (async () => {
      try {
        // The same File object goes up again for the load. The server derives
        // from these exact bytes rather than trusting the preview.
        const result =
          which === "preview"
            ? await previewBlockLabels(file, scheduleDate || undefined)
            : await loadBlockLabels(file, scheduleDate || undefined);
        if (which === "preview") setPreview(result);
        else setSaved(result);
      } catch (err) {
        // Server refusals verbatim: the 413, the "only one column" 422, the
        // 503 when the installation carries no trip-name rules.
        setErrorMessage(`${t.loadError} ${errorText(err)}`);
      } finally {
        setBusy(null);
      }
    })();
  };

  const startOver = () => {
    chooseFile(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <>
      <Breadcrumbs
        trail={[{ label: copy.admin.heading, to: "/admin" }, { label: t.heading }]}
      />
      <h1>{t.heading}</h1>
      <p>{t.intro}</p>

      <section className="card">
        <h2>{t.howToHeading}</h2>
        <ol>
          {t.howTo.map((step) => (
            <li key={step.slice(0, 24)}>{step}</li>
          ))}
        </ol>
        {/* The warning is an alert, not a hint. Excel mangled 21 of the
            partner agency's block names on the way to us, and a mangled name
            is indistinguishable from a real one once it is in the file. */}
        <p role="alert" className="alert">
          {t.excelWarning}
        </p>
      </section>

      <section className="card">
        <label htmlFor={fileId}>{t.fileLabel}</label>
        <p className="field-hint" id={fileHintId}>
          {t.fileHint}
        </p>
        <input
          id={fileId}
          ref={fileRef}
          type="file"
          accept=".csv,text/csv,text/plain"
          aria-describedby={fileHintId}
          onChange={(e) => chooseFile(e.target.files?.[0] ?? null)}
        />

        <label htmlFor={dateId}>{t.scheduleDateLabel}</label>
        <p className="field-hint" id={dateHintId}>
          {t.scheduleDateHint}
        </p>
        <input
          id={dateId}
          type="date"
          aria-describedby={dateHintId}
          value={scheduleDate}
          onChange={(e) => setScheduleDate(e.target.value)}
        />

        {errorMessage && (
          <div role="alert" className="alert">
            {errorMessage}
          </div>
        )}

        <div className="block-label-actions">
          <button
            type="button"
            onClick={() => run("preview")}
            aria-disabled={busy !== null || undefined}
          >
            {busy === "preview" ? t.previewBusy : t.previewButton}
          </button>

          {/* Only offered once a preview exists and has something to write.
              Saving is never the first thing a person can click. */}
          {preview && preview.labels_derived > 0 && !saved && (
            <button
              type="button"
              onClick={() => run("load")}
              aria-disabled={busy !== null || undefined}
            >
              {busy === "load" ? t.loadBusy : t.loadButton}
            </button>
          )}

          {(preview || saved) && (
            <button type="button" onClick={startOver}>
              {t.startOver}
            </button>
          )}
        </div>

        {preview && !saved && <p>{t.whatHappensNext}</p>}
      </section>

      {saved ? (
        <>
          <Result result={saved} saved />
          <NextSteps derived={saved.labels_derived} />
        </>
      ) : (
        preview && <Result result={preview} saved={false} />
      )}
    </>
  );
}
