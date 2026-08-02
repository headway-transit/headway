/**
 * The "as computed" stamp in the command bar (handoff 0044, output 1).
 *
 * The study's control-room header carries a run stamp on the right, and the
 * honest version of that is not a decorative clock: it is WHEN THIS
 * INSTALLATION LAST COMPUTED, read from the calculation-run record
 * (GET /calc-runs, newest first). It is a stamp, never a figure.
 *
 * Fail loudly, in miniature: if the run record cannot be read it says so; if
 * no run has ever been recorded it says that instead of showing a blank; a
 * run that is queued or running is named as in-progress rather than being
 * back-dated to its request time.
 */

import { useEffect, useState } from "react";
import { ApiError, listCalcRuns } from "../api/client";
import type { CalcRunRecord } from "../api/types";
import { copy } from "../copy";

type StampState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "none" }
  | { kind: "run"; run: CalcRunRecord };

/** The stamp's own words for a run — the server's timestamp, verbatim. */
function stampText(state: StampState): string {
  const t = copy.shell.stamp;
  switch (state.kind) {
    case "loading":
      return t.checking;
    case "error":
      return t.unavailable;
    case "none":
      return t.none;
    case "run": {
      const { run } = state;
      if (run.stale) return `${t.statusLabels.running ?? run.status} · stale`;
      const finished = run.finished_at;
      if (!finished) return t.inProgress;
      const status = t.statusLabels[run.status] ?? run.status;
      return `${finished} · ${status}`;
    }
  }
}

export function RunStamp() {
  const [state, setState] = useState<StampState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    listCalcRuns(1)
      .then((runs) => {
        if (cancelled) return;
        setState(
          runs.length === 0
            ? { kind: "none" }
            : { kind: "run", run: runs[0] },
        );
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // The message itself belongs on the calculation-runs page; the bar
        // only says the record could not be read — never a silent blank.
        void (err instanceof ApiError ? err.message : String(err));
        setState({ kind: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const text = stampText(state);
  return (
    <span className="run-stamp">
      <span className="run-stamp-label">{copy.shell.stamp.label}</span>
      <span className="run-stamp-value mono">{text}</span>
      <span className="visually-hidden">
        {` (${copy.shell.stamp.describe(text)})`}
      </span>
    </span>
  );
}

export default RunStamp;
