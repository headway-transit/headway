/**
 * /revenue-review — the human-in-the-loop revenue review queue (handoff 0040).
 *
 * What these tests hold in place is not the layout; it is the honesty of the
 * screen. A boarding held out of a ridership figure is a number an agency
 * cannot report yet, so the queue must say so in words, must refuse a
 * decision with no reason, and must never let anyone believe that deciding
 * one changed a figure that has already been worked out.
 */

import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import { uptValue } from "./fixtures";
import type { BoardingReview } from "../api/types";

const pending: BoardingReview = {
  passenger_event_id: "pe-1",
  source_record_id: "c".repeat(64),
  service_date: "2026-07-09",
  event_timestamp: "2026-07-09T15:12:00Z",
  vehicle_id: "3684",
  event_count: 4,
  suggested_verdict: "pending_review",
  suggested_reason:
    "no run assignment but WITHIN the day's revenue-service window — " +
    "ambiguous (could be a catch-up bus dispatched without a formal trip " +
    "assignment); held pending human review",
  calc_name: "upt_v0",
  calc_version: "0.4.0",
  period_start: "2026-07-01",
  period_end: "2026-08-01",
  first_seen_at: "2026-07-15T09:00:00Z",
  verdict: null,
  justification: null,
  classified_by: null,
  classified_at: null,
  dq_issue_id: null,
};

const decided: BoardingReview = {
  ...pending,
  passenger_event_id: "pe-2",
  vehicle_id: "1207",
  verdict: "non_revenue",
  justification: "Counter double-fired during layover, confirmed with dispatch.",
  classified_by: "stella",
  classified_at: "2026-07-16T10:00:00Z",
  dq_issue_id: "11111111-2222-3333-4444-555555555555",
};

function page(rows: BoardingReview[]) {
  return {
    boardings: rows,
    total: rows.length,
    limit: 25,
    next_cursor: null,
    has_more: false,
  };
}

function counts(overrides: Record<string, number> = {}) {
  return {
    pending: 1,
    pending_boardings: 4,
    classified: 0,
    classified_revenue: 0,
    classified_non_revenue: 0,
    classified_revenue_boardings: 0,
    classified_non_revenue_boardings: 0,
    ...overrides,
  };
}

function queueRoutes(rows: BoardingReview[], countOverrides = {}) {
  return {
    "GET /revenue-review/boardings": (call: { url: string }) => {
      const status =
        new URL(call.url, "http://test").searchParams.get("status") ?? "pending";
      return {
        status: 200,
        body: page(
          rows.filter((r) =>
            status === "pending" ? r.verdict === null : r.verdict !== null,
          ),
        ),
      };
    },
    "GET /revenue-review/boardings/counts": {
      status: 200,
      body: counts(countOverrides),
    },
  };
}

describe("/revenue-review", () => {
  it("says what the boarding was, in the agency's words, and that it is held out", async () => {
    signInAs("viewer");
    mockApi(queueRoutes([pending]));
    renderApp("/revenue-review");

    expect(
      await screen.findByRole("heading", { name: "Boardings to review" }),
    ).toBeInTheDocument();
    // The vehicle by its fleet number, not an internal identifier.
    const card = screen
      .getByRole("heading", { name: /Vehicle 3684/ })
      .closest("article") as HTMLElement;
    expect(within(card).getByText("4 riders")).toBeInTheDocument();
    // Held is neither counted nor discarded, and it says so.
    expect(
      within(card).getByText(/Held out of the ridership figure while it waits/),
    ).toBeInTheDocument();
    expect(
      within(card).getByText(/It is not counted, and it is not thrown away/),
    ).toBeInTheDocument();
    // No route/run — stated as an explanation, never as a blank.
    expect(
      within(card).getByText(/The bus was not logged into a run/),
    ).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("states that Headway made no suggestion rather than nudging the analyst", async () => {
    signInAs("data_steward");
    mockApi(queueRoutes([pending]));
    renderApp("/revenue-review");

    expect(
      await screen.findByText(/No suggestion\. Headway will not guess this one/),
    ).toBeInTheDocument();
  });

  it("shows how many riders the whole queue is holding, not the page", async () => {
    signInAs("viewer");
    mockApi(queueRoutes([pending]));
    renderApp("/revenue-review");

    expect(
      await screen.findByText(/Riders held out of the figure/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Counted across the whole queue/),
    ).toBeInTheDocument();
  });

  it("invites, rather than scolds, when nothing is waiting", async () => {
    signInAs("data_steward");
    mockApi(
      queueRoutes([], { pending: 0, pending_boardings: 0 }),
    );
    renderApp("/revenue-review");

    expect(
      await screen.findByRole("heading", { name: "Nothing is waiting on you" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/is not holding anything back for review/),
    ).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("records a decision with its justification note", async () => {
    signInAs("data_steward");
    let sent: unknown = null;
    mockApi({
      ...queueRoutes([pending]),
      "POST /revenue-review/boardings/pe-1/classify": (call: {
        body: unknown;
      }) => {
        sent = call.body;
        return {
          status: 200,
          body: {
            passenger_event_id: "pe-1",
            verdict: "revenue",
            justification: "Extra bus sent at 15:10; dispatch confirms riders.",
            classified_by: "test.user",
            classified_at: "2026-07-20T12:00:00Z",
            dq_issue_id: null,
            audit_event_id: 42,
            recompute_required: true,
          },
        };
      },
    });
    renderApp("/revenue-review");

    await userEvent.click(
      await screen.findByRole("button", { name: /^Decide: Vehicle 3684/ }),
    );
    await userEvent.click(
      screen.getByRole("radio", { name: /Real ridership — count them/ }),
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: /Why \(required\)/ }),
      "Extra bus sent at 15:10; dispatch confirms riders.",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Record this decision" }),
    );

    await waitFor(() =>
      expect(sent).toEqual({
        verdict: "revenue",
        justification: "Extra bus sent at 15:10; dispatch confirms riders.",
      }),
    );
  });

  it("refuses a decision with no reason, and never sends one", async () => {
    signInAs("data_steward");
    let posted = false;
    mockApi({
      ...queueRoutes([pending]),
      "POST /revenue-review/boardings/pe-1/classify": () => {
        posted = true;
        return { status: 200, body: {} };
      },
    });
    renderApp("/revenue-review");

    await userEvent.click(
      await screen.findByRole("button", { name: /^Decide: Vehicle 3684/ }),
    );
    await userEvent.click(
      screen.getByRole("radio", { name: /Not ridership — leave them out/ }),
    );
    // Whitespace is not a reason.
    await userEvent.type(
      screen.getByRole("textbox", { name: /Why \(required\)/ }),
      "   ",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Record this decision" }),
    );

    expect(
      await screen.findByText(/A decision with no reason cannot be defended/),
    ).toBeInTheDocument();
    expect(posted).toBe(false);
  });

  it("refuses a decision with no verdict", async () => {
    signInAs("data_steward");
    mockApi(queueRoutes([pending]));
    renderApp("/revenue-review");

    await userEvent.click(
      await screen.findByRole("button", { name: /^Decide: Vehicle 3684/ }),
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: /Why \(required\)/ }),
      "Real riders.",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Record this decision" }),
    );
    expect(
      await screen.findByText(/Choose one of the two decisions/),
    ).toBeInTheDocument();
  });

  it("says the figure does not move until the figures are worked out again", async () => {
    signInAs("data_steward");
    mockApi(queueRoutes([pending]));
    renderApp("/revenue-review");

    await userEvent.click(
      await screen.findByRole("button", { name: /^Decide: Vehicle 3684/ }),
    );
    expect(
      screen.getByText(/It does not change any figure that has already been worked out/),
    ).toBeInTheDocument();
    // ...and points at the room where that happens.
    expect(
      screen.getByRole("link", { name: "Go and work the figures out again" }),
    ).toHaveAttribute("href", "/calc-runs");
  });

  it("shows the API's refusal verbatim when the period is already certified", async () => {
    signInAs("data_steward");
    mockApi({
      ...queueRoutes([pending]),
      "POST /revenue-review/boardings/pe-1/classify": {
        status: 409,
        body: {
          detail:
            "This boarding is on 2026-07-09, which falls inside a reporting " +
            "period whose Unlinked Passenger Trips figure has already been " +
            "certified.",
        },
      },
    });
    renderApp("/revenue-review");

    await userEvent.click(
      await screen.findByRole("button", { name: /^Decide: Vehicle 3684/ }),
    );
    await userEvent.click(
      screen.getByRole("radio", { name: /Real ridership — count them/ }),
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: /Why \(required\)/ }),
      "Real riders.",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Record this decision" }),
    );

    expect(
      await screen.findByText(/has already been certified/),
    ).toBeInTheDocument();
  });

  it("gives a viewer the queue to read but no way to decide", async () => {
    signInAs("viewer");
    mockApi(queueRoutes([pending]));
    renderApp("/revenue-review");

    expect(
      await screen.findByRole("heading", { name: /Vehicle 3684/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Decide:/ }),
    ).not.toBeInTheDocument();
  });

  it("shows decided boardings with who decided, when, and why", async () => {
    signInAs("data_steward");
    mockApi(
      queueRoutes([decided], {
        pending: 0,
        pending_boardings: 0,
        classified: 1,
        classified_non_revenue: 1,
        classified_non_revenue_boardings: 4,
      }),
    );
    renderApp("/revenue-review");

    await userEvent.click(
      await screen.findByRole("button", { name: /Decided so far/ }),
    );
    const card = (
      await screen.findByRole("heading", { name: /Vehicle 1207/ })
    ).closest("article") as HTMLElement;
    expect(within(card).getByText("Ruled not ridership")).toBeInTheDocument();
    expect(within(card).getByText(/stella/)).toBeInTheDocument();
    expect(
      within(card).getByText(/Counter double-fired during layover/),
    ).toBeInTheDocument();
    // ...and the honesty note about figures computed before the decision.
    expect(
      screen.getByText(/a number never changes quietly under a signature/),
    ).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("states the load failure instead of showing an empty queue", async () => {
    signInAs("data_steward");
    mockApi({
      "GET /revenue-review/boardings": {
        status: 500,
        body: { detail: "The review queue is unavailable." },
      },
      "GET /revenue-review/boardings/counts": {
        status: 500,
        body: { detail: "unavailable" },
      },
    });
    renderApp("/revenue-review");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The review queue is unavailable.");
    // An empty state would be a lie here — nothing said the queue was empty.
    expect(
      screen.queryByRole("heading", { name: "Nothing is waiting on you" }),
    ).not.toBeInTheDocument();
  });
});

/**
 * The receipt side (handoff 0040, design point 2). A corrected number is only
 * defensible if the correction shows its work, so the judgment calls travel
 * INSIDE the figure — frozen at compute time, quoted verbatim, attributed.
 */
describe("Receipt — the judgment calls behind the number", () => {
  const classifiedUpt = {
    ...uptValue,
    metric_value_id: "mv-upt-reviewed",
    detail: {
      ...(uptValue.detail as Record<string, unknown>),
      revenue_classification: {
        revenue_boardings: 41000,
        excluded_non_revenue_boardings: 120,
        pending_review_boardings: 9,
        pending_review_policy: "exclude_until_classified",
        human_revenue_boardings: 14,
        human_non_revenue_boardings: 6,
        human_classifications: [
          {
            passenger_event_id: "pe-1",
            source_record_id: "c".repeat(64),
            service_date: "2026-03-11",
            event_timestamp: "2026-03-11T15:12:00+00:00",
            vehicle_id: "3684",
            event_count: 14,
            verdict: "revenue",
            justification:
              "Extra bus sent at 15:10 to recover the route; dispatch " +
              "confirms these are real riders.",
            classified_by: "stella",
            classified_at: "2026-03-20T10:00:00+00:00",
          },
          {
            passenger_event_id: "pe-2",
            source_record_id: "d".repeat(64),
            service_date: "2026-03-12",
            event_timestamp: "2026-03-12T05:40:00+00:00",
            vehicle_id: "1207",
            event_count: 6,
            verdict: "non_revenue",
            justification: "Counter double-fired during layover.",
            classified_by: "stella",
            classified_at: "2026-03-20T10:05:00+00:00",
          },
        ],
      },
    },
  };

  it("shows who decided, when, and why — verbatim", async () => {
    signInAs("viewer");
    mockApi({ "GET /metrics/values": { status: 200, body: [classifiedUpt] } });
    renderApp("/metrics");

    await screen.findByRole("table");
    await userEvent.click(
      screen.getByRole("button", { name: /^Details/ }),
    );

    expect(
      await screen.findByRole("heading", {
        name: "Judgment calls behind this number",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Counted as ridership")).toBeInTheDocument();
    expect(screen.getByText("Not ridership")).toBeInTheDocument();
    // The analyst's words, unedited.
    expect(
      screen.getByText(/Extra bus sent at 15:10 to recover the route/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Counter double-fired during layover/),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Decided by stella/).length).toBe(2);
    // ...and the honesty about what a later decision does to THIS number.
    expect(
      screen.getByText(/Decisions made since then apply to the next time/),
    ).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("says how many riders are still held out of the number", async () => {
    signInAs("viewer");
    mockApi({ "GET /metrics/values": { status: 200, body: [classifiedUpt] } });
    renderApp("/metrics");

    await screen.findByRole("table");
    await userEvent.click(
      screen.getByRole("button", { name: /^Details/ }),
    );

    expect(
      await screen.findByText(/9 still waiting on a decision, and held OUT/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/must never quietly inflate or deflate a number/),
    ).toBeInTheDocument();
  });

  it("draws no judgment section for a figure nobody had to judge", async () => {
    signInAs("viewer");
    mockApi({ "GET /metrics/values": { status: 200, body: [uptValue] } });
    renderApp("/metrics");

    await screen.findByRole("table");
    await userEvent.click(
      screen.getByRole("button", { name: /^Details/ }),
    );

    expect(
      screen.queryByRole("heading", {
        name: "Judgment calls behind this number",
      }),
    ).not.toBeInTheDocument();
  });
});
