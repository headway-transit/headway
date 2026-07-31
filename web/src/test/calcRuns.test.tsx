/**
 * The calculations room (/calc-runs — handoff 0026): starting a run, the
 * single-flight 409 verbatim at the control, refusals as first-class
 * outcomes with links to the exact DQ findings, the honest live state (no
 * fake progress), staleness verbatim, and the viewer's read-only surface.
 */

import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import {
  halfOpenMonthPeriod,
  recentMonthOptions,
} from "../reports/period";

const REFUSED_RUN = {
  run_id: "0e0d61cc-0000-4000-8000-000000000001",
  requested_by: "dsteward",
  requested_at: "2026-07-28T18:00:00Z",
  period_start: "2026-06-01",
  period_end: "2026-07-01",
  status: "refused",
  started_at: "2026-07-28T18:00:01Z",
  finished_at: "2026-07-28T18:02:31Z",
  runner_pid: 4242,
  summary: {
    runner: "python -m headway_calc.runner (default NTD calc set)",
    period_start: "2026-06-01",
    period_end: "2026-07-01",
    period_convention: "half-open [period_start, period_end), UTC",
    persisted_count: 0,
    blocked_count: 4,
    routed_blocking_count: 4,
    routed_warning_count: 2,
    routed_info_count: 0,
    coverage_threshold: "0.95",
    threshold_sources: { coverage_threshold: "settings" },
    positions_loaded: 3096786,
    passenger_events_loaded: 0,
    operated_trips_loaded: 61535,
    dr_trips_loaded: 0,
    metrics: [
      {
        calc_name: "vrm_v0",
        calc_version: "0.2.0",
        metric: "vrm",
        unit: "miles",
        scope: "agency",
        outcome: "refused",
        value: null,
        metric_value_id: null,
        coverage: "0.9126",
        blocking_issue_ids: ["11111111-aaaa-4000-8000-000000000001"],
        warning_issue_ids: [],
        info_issue_ids: [],
      },
      {
        calc_name: "upt_v0",
        calc_version: "0.1.0",
        metric: "upt",
        unit: "unlinked_passenger_trips",
        scope: "agency",
        outcome: "refused",
        value: null,
        metric_value_id: null,
        coverage: null,
        blocking_issue_ids: ["11111111-aaaa-4000-8000-000000000002"],
        warning_issue_ids: [],
        info_issue_ids: [],
      },
    ],
  },
  stdout_tail: '--- stdout (tail) ---\n{"period_start": "2026-06-01"}',
  duration_seconds: 150.0,
  stale: false,
  stale_note: null,
};

const SUCCEEDED_RUN = {
  ...REFUSED_RUN,
  run_id: "0e0d61cc-0000-4000-8000-000000000002",
  requested_at: "2026-06-15T09:00:00Z",
  started_at: "2026-06-15T09:00:01Z",
  finished_at: "2026-06-15T09:01:41Z",
  period_start: "2026-05-01",
  period_end: "2026-06-01",
  status: "succeeded",
  duration_seconds: 100.0,
  summary: {
    ...REFUSED_RUN.summary,
    period_start: "2026-05-01",
    period_end: "2026-06-01",
    persisted_count: 1,
    blocked_count: 0,
    routed_blocking_count: 0,
    metrics: [
      {
        calc_name: "vrm_v0",
        calc_version: "0.2.0",
        metric: "vrm",
        unit: "miles",
        scope: "agency",
        outcome: "persisted",
        value: "1832041.174",
        metric_value_id: "22222222-bbbb-4000-8000-000000000001",
        coverage: "0.9612",
        blocking_issue_ids: [],
        warning_issue_ids: [],
        info_issue_ids: [],
      },
    ],
  },
};

const RUNNING_RUN = {
  ...REFUSED_RUN,
  run_id: "0e0d61cc-0000-4000-8000-000000000003",
  status: "running",
  started_at: "2026-07-28T18:30:05Z",
  finished_at: null,
  summary: null,
  stdout_tail: null,
  duration_seconds: null,
};

const LIVE_409 =
  "A calculation run is already in progress: run " +
  "0e0d61cc-0000-4000-8000-000000000003 over 2026-06-01 to 2026-07-01, " +
  "requested by dsteward, running since 18:30:05 UTC. Headway runs one " +
  "calculation at a time in this version — when it finishes, start yours " +
  "from this page.";

describe("the calculations room (/calc-runs)", () => {
  it("month helpers build half-open periods (calendar labels, not figures)", () => {
    expect(halfOpenMonthPeriod("2026-06")).toEqual({
      period_start: "2026-06-01",
      period_end: "2026-07-01",
    });
    expect(halfOpenMonthPeriod("2026-12")).toEqual({
      period_start: "2026-12-01",
      period_end: "2027-01-01",
    });
    const options = recentMonthOptions(new Date("2026-07-28T12:00:00Z"));
    expect(options[0]).toEqual({ value: "2026-07", label: "July 2026" });
    expect(options[1]).toEqual({ value: "2026-06", label: "June 2026" });
    expect(options).toHaveLength(12);
  });

  it("renders a refused run as first-class: reasons linked, teaching block, no alarm theater", async () => {
    signInAs("data_steward");
    mockApi({ "GET /calc/runs": { status: 200, body: [REFUSED_RUN] } });
    renderApp("/calc-runs");

    expect(
      await screen.findByRole("heading", {
        name: "Refused — figures withheld",
      }),
    ).toBeInTheDocument();
    // The refusal explanation in plain words.
    expect(
      screen.getByText(/Every calculation withheld its figure/),
    ).toBeInTheDocument();
    // Links to the EXACT blocking findings (one per refused calc here).
    const links = screen.getAllByRole("link", {
      name: "Open blocking finding 1",
    });
    expect(links.map((l) => l.getAttribute("href"))).toEqual([
      "/dq?issue=11111111-aaaa-4000-8000-000000000001",
      "/dq?issue=11111111-aaaa-4000-8000-000000000002",
    ]);
    // Coverage served verbatim (the runner's string).
    expect(screen.getAllByText(/Coverage: 0\.9126/).length).toBeGreaterThan(0);
    // The teaching moment, house voice, walking to the DQ queue.
    expect(
      screen.getByText("This refusal is Headway working as designed"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Go to the data-quality queue" }),
    ).toHaveAttribute("href", "/dq");
    // Duration is the timestamps' difference in plain words.
    expect(screen.getByText("Took 2 minutes 30 seconds.")).toBeInTheDocument();
    // A finished refusal is NOT an alert (refusals arrive plainly) — the
    // page has no alert at all in this state.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("renders a succeeded run with the figure verbatim and its receipt links", async () => {
    signInAs("data_steward");
    mockApi({ "GET /calc/runs": { status: 200, body: [SUCCEEDED_RUN] } });
    renderApp("/calc-runs");

    expect(
      await screen.findByRole("heading", { name: "Figures produced" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/1832041\.174/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "How this number was made" }),
    ).toHaveAttribute(
      "href",
      "/metrics/22222222-bbbb-4000-8000-000000000001/lineage",
    );
    expect(
      screen.getByRole("link", { name: "See it on the metrics page" }),
    ).toHaveAttribute("href", "/metrics");
    // No refusal teaching block on a succeeded run.
    expect(
      screen.queryByText("This refusal is Headway working as designed"),
    ).not.toBeInTheDocument();
    // A first run carries no already-on-record note.
    expect(
      screen.queryByText(/not duplicated/),
    ).not.toBeInTheDocument();
  });

  it("an identical re-run says the figure was not duplicated", async () => {
    // The persist dedupe (identical figure already on record): the outcome
    // still shows the figure verbatim with its receipt links, PLUS the
    // plain-words note — a re-run must never read as a second figure.
    signInAs("data_steward");
    const rerun = {
      ...SUCCEEDED_RUN,
      summary: {
        ...SUCCEEDED_RUN.summary,
        metrics: [
          {
            ...SUCCEEDED_RUN.summary.metrics[0],
            already_on_record: true,
          },
        ],
      },
    };
    mockApi({ "GET /calc/runs": { status: 200, body: [rerun] } });
    renderApp("/calc-runs");

    expect(await screen.findByText(/1832041\.174/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "Same result as the figure already on record — not duplicated",
      ),
    ).toBeInTheDocument();
    // The receipt links still point at the (one) existing row.
    expect(
      screen.getByRole("link", { name: "How this number was made" }),
    ).toHaveAttribute(
      "href",
      "/metrics/22222222-bbbb-4000-8000-000000000001/lineage",
    );
  });

  it("starts a run with the picked custom period and confirms plainly", async () => {
    signInAs("data_steward");
    const calls = mockApi({
      "GET /calc/runs": { status: 200, body: [] },
      "POST /calc/runs": {
        status: 202,
        body: {
          run_id: "0e0d61cc-0000-4000-8000-000000000009",
          status: "queued",
          requested_by: "dsteward",
          requested_at: "2026-07-28T19:00:00Z",
          period_start: "2026-06-01",
          period_end: "2026-07-01",
          note: "queued",
          audit_event_id: 99,
        },
      },
    });
    renderApp("/calc-runs");
    const user = userEvent.setup();

    await screen.findByText(/No calculation runs yet/);
    await user.selectOptions(
      screen.getByLabelText("Calendar month"),
      "custom",
    );
    await user.type(
      screen.getByLabelText("First day (included)"),
      "2026-06-01",
    );
    await user.type(
      screen.getByLabelText("Day after the last day (not included)"),
      "2026-07-01",
    );
    await user.click(
      screen.getByRole("button", { name: "Compute figures for this period" }),
    );

    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.path === "/calc/runs",
      );
      expect(post?.body).toEqual({
        period_start: "2026-06-01",
        period_end: "2026-07-01",
      });
    });
    // The shell confirmation (aria-live region), plainly worded.
    expect(
      await screen.findByText("Calculation run started."),
    ).toBeInTheDocument();
  });

  it("renders the single-flight 409 VERBATIM at the control and shows the live run without fake progress", async () => {
    signInAs("data_steward");
    let posted = false;
    mockApi({
      "GET /calc/runs": () => ({
        status: 200,
        body: posted ? [RUNNING_RUN] : [],
      }),
      "POST /calc/runs": () => {
        posted = true;
        return { status: 409, body: { detail: LIVE_409 } };
      },
    });
    renderApp("/calc-runs");
    const user = userEvent.setup();

    await screen.findByText(/No calculation runs yet/);
    // Default period = the previous calendar month, so the button is armed.
    await user.click(
      screen.getByRole("button", { name: "Compute figures for this period" }),
    );

    // The server's words, verbatim, as an alert at the control.
    expect(await screen.findByRole("alert")).toHaveTextContent(LIVE_409);
    // The refresh picked up the live run: honest liveness only — a real
    // start time, no progress bar, no percentage.
    expect(
      await screen.findByText("Running since 18:30:05 UTC."),
    ).toBeInTheDocument();
    expect(document.querySelector("progress")).toBeNull();
    // The button now carries the live-run reason at the control.
    const button = screen.getByRole("button", {
      name: "A run is in progress…",
    });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(
      screen.getByText(/Headway runs one at a time — when it finishes/),
    ).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("renders a stale run's server note verbatim", async () => {
    signInAs("data_steward");
    const staleNote =
      "This run has been marked as started for more than 2 hours without " +
      "finishing — far longer than a run takes. The server was most likely " +
      "restarted while it was running, so its real state is unknown.";
    mockApi({
      "GET /calc/runs": {
        status: 200,
        body: [{ ...RUNNING_RUN, stale: true, stale_note: staleNote }],
      },
    });
    renderApp("/calc-runs");

    expect(
      await screen.findByRole("heading", { name: /Running — State unknown/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(staleNote)).toBeInTheDocument();
    // A stale run does not disable the form: the reason line is absent and
    // the run button is armed (the server reconciles on POST).
    expect(
      screen.getByRole("button", { name: "Compute figures for this period" }),
    ).not.toHaveAttribute("aria-disabled");
  });

  it("gives viewers the read-only surface: history yes, run button no", async () => {
    signInAs("viewer");
    mockApi({ "GET /calc/runs": { status: 200, body: [REFUSED_RUN] } });
    renderApp("/calc-runs");

    expect(
      await screen.findByRole("heading", {
        name: "Refused — figures withheld",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Starting a run is done by a data steward/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Compute figures for this period",
      }),
    ).not.toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("failed runs state the recorded reason and tuck the output tail behind a disclosure", async () => {
    signInAs("data_steward");
    mockApi({
      "GET /calc/runs": {
        status: 200,
        body: [
          {
            ...REFUSED_RUN,
            run_id: "0e0d61cc-0000-4000-8000-000000000004",
            status: "failed",
            summary: {
              error:
                "The calculation runner stopped with an error (exit code 1) " +
                "before it could finish. No figure was invented to cover " +
                "the gap; the output tail below says what happened.",
              exit_code: 1,
            },
            stdout_tail: "--- stderr (tail) ---\nTraceback: boom",
          },
        ],
      },
    });
    renderApp("/calc-runs");

    expect(
      await screen.findByRole("heading", { name: "Failed" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      /No figure was invented to cover the gap/,
    );
    const disclosure = screen.getByText("Show the runner's output (technical)");
    expect(disclosure).toBeInTheDocument();
    expect(screen.getByText(/Traceback: boom/)).toBeInTheDocument();
  });

  it("polls while a run is live and stops reporting it once terminal", { timeout: 20_000 }, async () => {
    signInAs("data_steward");
    let requests = 0;
    mockApi({
      "GET /calc/runs": () => {
        requests += 1;
        return {
          status: 200,
          body: requests >= 3 ? [REFUSED_RUN] : [RUNNING_RUN],
        };
      },
    });
    renderApp("/calc-runs");

    expect(
      await screen.findByText("Running since 18:30:05 UTC."),
    ).toBeInTheDocument();
    // The poll (5 s cadence) eventually lands the terminal state; the
    // refused outcome replaces the live line with no animation in between.
    await waitFor(
      () =>
        expect(
          screen.getByRole("heading", { name: "Refused — figures withheld" }),
        ).toBeInTheDocument(),
      { timeout: 15_000 },
    );
    expect(requests).toBeGreaterThanOrEqual(3);
  });
});
