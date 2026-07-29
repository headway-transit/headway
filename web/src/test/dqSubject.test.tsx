import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import type { DqIssue, DqIssueCounts } from "../api/types";
import type { RouteHandler } from "./helpers";
import { blockingIssue, subjectContextIssue } from "./fixtures";

/**
 * "Which trips this affects" — the finding's subject rendered in the
 * agency's own vocabulary (handoff 0029, migration 0035).
 *
 * The UAT sentence these tests answer: *"staff/users will need an easier way
 * to know what exact block they are looking for that had the issue."*
 * So the assertions are about what a DISPATCHER can read — blocks, trip
 * counts, routes, times of day — plus the two things that make it
 * trustworthy: nothing is ever invented, and nothing that used to render
 * stops rendering.
 */

function countsFor(issues: DqIssue[], status: string | null): DqIssueCounts {
  const rows = status ? issues.filter((i) => i.status === status) : issues;
  const tally = (pick: (i: DqIssue) => string) => {
    const out: Record<string, number> = {};
    for (const i of rows) out[pick(i)] = (out[pick(i)] ?? 0) + 1;
    return out;
  };
  return {
    total: rows.length,
    by_severity: tally((i) => i.severity),
    by_status: tally((i) => i.status),
  };
}

function dqRoutes(issues: DqIssue[]): Record<string, RouteHandler> {
  return {
    "GET /dq/issues": { status: 200, body: issues },
    "GET /dq/issues/counts": (call) => {
      const status = new URL(call.url, "http://test").searchParams.get(
        "status",
      );
      return { status: 200, body: countsFor(issues, status) };
    },
  };
}

async function subjectCard(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", {
    name: /No passenger counts arrived for any operated trip/,
  });
  return heading.closest("article") as HTMLElement;
}

/** Every string the subject panel can put on screen. */
const SUBJECT_MARKERS = [
  "Which trips this affects",
  "Affected trips grouped by block",
  "Technical detail: trip identifiers",
  "No block in the schedule feed",
  "Trips not in the schedule feed",
];

describe("/dq — the finding's subject in the agency's vocabulary", () => {
  it("leads with blocks, trip counts, routes and times of day — not a wall of ids", async () => {
    signInAs("viewer");
    mockApi(dqRoutes([subjectContextIssue]));
    renderApp("/dq");

    const card = await subjectCard();
    expect(
      within(card).getByRole("heading", { name: "Which trips this affects" }),
    ).toBeInTheDocument();
    // The count and the grouping, said plainly.
    expect(card).toHaveTextContent(
      "2,307 affected trips, grouped into 660 blocks",
    );

    // The dispatcher's row: a block they can look up, with route and time.
    const table = within(card).getByRole("table", {
      name: "Affected trips grouped by block",
    });
    const row = within(table)
      .getByRole("rowheader", { name: "L455-173" })
      .closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("4 trips");
    expect(row).toHaveTextContent("442");
    expect(row).toHaveTextContent("455");
    expect(row).toHaveTextContent("19:05–22:59");

    // The identifiers are NOT the headline: they are inside the collapsed
    // disclosure, and the visible table shows none of them.
    expect(table).not.toHaveTextContent("t-442-a");

    await expectNoAxeViolations();
  });

  it("states the after-midnight schedule convention instead of silently wrapping it", async () => {
    signInAs("viewer");
    mockApi(dqRoutes([subjectContextIssue]));
    renderApp("/dq");

    const card = await subjectCard();
    // 24:31 is 00:31 the next morning of the SAME service day. Wrapping it
    // would move the trip to the wrong day.
    expect(card).toHaveTextContent("18:10–24:31");
    expect(card).toHaveTextContent(
      "an hour of 24 or more means after midnight",
    );
  });

  it("never invents a label: absent block, absent route name and absent times are said in words", async () => {
    signInAs("viewer");
    mockApi(dqRoutes([subjectContextIssue]));
    renderApp("/dq");

    const card = await subjectCard();
    const table = within(card).getByRole("table", {
      name: "Affected trips grouped by block",
    });

    // No block in the feed: stated as a fact, with the reason.
    const noBlockRow = within(table)
      .getByRole("rowheader", { name: /No block in the schedule feed/ })
      .closest("tr") as HTMLElement;
    expect(noBlockRow).toHaveTextContent("83 trips");
    expect(noBlockRow).toHaveTextContent("rather than guessing one");

    // A route with no short name shows its id LABELLED as an id — the id is
    // the only thing that exists, so it is not dressed up as a name. (This
    // fixture's route has a long name, which is a real label and wins.)
    expect(noBlockRow).toHaveTextContent("Fairmount Line");
    // 12 routes exist, 1 is materialised: the truncation is stated.
    expect(noBlockRow).toHaveTextContent("1 of 12 routes");

    // No scheduled departure at all: said, never rendered as 00:00.
    const noTimeRow = within(table)
      .getByRole("rowheader", { name: "C01-28" })
      .closest("tr") as HTMLElement;
    expect(noTimeRow).toHaveTextContent("No scheduled time in the feed");
    expect(noTimeRow).not.toHaveTextContent("00:00");
  });

  it("states the group cap instead of quietly showing a short list", async () => {
    signInAs("viewer");
    mockApi(dqRoutes([subjectContextIssue]));
    renderApp("/dq");

    const card = await subjectCard();
    expect(card).toHaveTextContent("Showing the first 3 of 660 blocks");
    expect(card).toHaveTextContent("Nothing is dropped");
  });

  it("gives trips missing from the schedule feed their own honest bucket", async () => {
    signInAs("viewer");
    mockApi(dqRoutes([subjectContextIssue]));
    renderApp("/dq");

    const card = await subjectCard();
    expect(
      within(card).getByRole("heading", {
        name: "Trips not in the schedule feed",
      }),
    ).toBeInTheDocument();
    expect(card).toHaveTextContent(
      "211 affected trips are not in the published schedule",
    );
    // Never folded into a block they do not belong to.
    const table = within(card).getByRole("table", {
      name: "Affected trips grouped by block",
    });
    expect(within(table).queryByText(/added-trip-1/)).not.toBeInTheDocument();
  });

  it("keeps the raw identifiers copyable behind a collapsed disclosure", async () => {
    signInAs("viewer");
    mockApi(dqRoutes([subjectContextIssue]));
    renderApp("/dq");

    const card = await subjectCard();
    const disclosure = within(card).getByText(
      "Technical detail: trip identifiers",
    );
    const details = disclosure.closest("details") as HTMLDetailsElement;
    // Collapsed by default — forensic on demand, never the headline.
    expect(details.open).toBe(false);

    await userEvent.click(disclosure);
    expect(details.open).toBe(true);
    expect(details).toHaveTextContent("t-442-a, t-455-b");
    expect(details).toHaveTextContent("NorthBase-825706-274");
    // Including the ids of trips that are not in the feed.
    expect(details).toHaveTextContent("added-trip-1");
    // The cap is stated where the truncation happens.
    expect(details).toHaveTextContent(
      "Up to 20 identifiers are listed per block",
    );

    await expectNoAxeViolations();
  });

  it("renders a finding WITHOUT a subject exactly as it did before migration 0035", async () => {
    // 97,067 rows in the live queue carry no context. Not one of them may
    // crash, blank out, or grow a placeholder panel.
    signInAs("data_steward");
    mockApi(dqRoutes([blockingIssue]));
    renderApp("/dq");

    const card = (
      await screen.findByRole("heading", {
        name: "Bus 1207 sent no location data for 42 minutes on March 3",
      })
    ).closest("article") as HTMLElement;

    for (const marker of SUBJECT_MARKERS) {
      expect(card).not.toHaveTextContent(marker);
    }
    // Everything it always showed still shows.
    expect(card).toHaveTextContent("Blocking");
    expect(card).toHaveTextContent(
      "Must be resolved before any figure can be certified.",
    );
    expect(card).toHaveTextContent(
      "Headway received no position reports from Bus 1207",
    );
    expect(card).toHaveTextContent("Not yet assigned");
    expect(card).toHaveTextContent("sha256:aaaa1111");
    expect(
      within(card).getByRole("button", { name: /^Resolve:/ }),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("renders a context whose version it does not understand as if it were absent", async () => {
    // A shape this UI cannot read is worse than none: the finding's prose
    // still says what happened, so fall back to exactly that.
    signInAs("viewer");
    mockApi(
      dqRoutes([
        {
          ...subjectContextIssue,
          subject_context: {
            ...subjectContextIssue.subject_context!,
            version: 99,
          },
        },
      ]),
    );
    renderApp("/dq");

    const card = await subjectCard();
    for (const marker of SUBJECT_MARKERS) {
      expect(card).not.toHaveTextContent(marker);
    }
    expect(card).toHaveTextContent("Every operated trip in this period");
  });

  it("shows the subject on a finding opened by deep link, not only in the queue", async () => {
    signInAs("viewer");
    mockApi({
      ...dqRoutes([]),
      "GET /dq/issues/dq-subject-1": {
        status: 200,
        body: subjectContextIssue,
      },
    });
    renderApp("/dq?issue=dq-subject-1");

    const card = await subjectCard();
    expect(
      within(card).getByRole("table", {
        name: "Affected trips grouped by block",
      }),
    ).toBeInTheDocument();
  });
});
