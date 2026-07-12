/**
 * /safety (handoff 0010, design point 5) — mock-based verification, typed
 * against services/api routers/safety.py's request/response models exactly
 * (the backend was built in parallel; these mocks mirror its router).
 *
 * Held lines:
 * - plain-language entry with PROGRESSIVE DISCLOSURE of rail-only questions;
 * - client-side validation mirrors the contract and never calls the API on
 *   an invalid form; API refusals surface verbatim;
 * - the classifier's verdict is DISPLAYED, never computed here, as a receipt
 *   carrying the classifier's sentences verbatim plus the VERBATIM manual
 *   quote + page citation per token (the extract-quotes pattern);
 * - corrections are append-only (with their required audit reason): the
 *   original stays visible, struck and linked — never hidden;
 * - deadlines show urgency as text + icon + color (never color alone), and
 *   zero-event rows are stated as still due, with the manual's own words.
 */

import { describe, expect, it } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SafetyDeadlines } from "../api/types";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import type { RouteHandler } from "./helpers";
import {
  safetyAssaultCreated,
  safetyCorrectionEvent,
  safetyMajorCreated,
  safetyMajorEvent,
  safetyMajorResult,
  safetyNonMajorEvent,
  safetyNotReportableEvent,
  safetySupersededEvent,
  safetySupersededResponse,
} from "./fixtures";

/**
 * An ISO date `offset` days from today, built from LOCAL date components —
 * the same calendar the view's daysUntil uses — so urgency assertions never
 * shift with the clock or timezone.
 */
function isoDateFromToday(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const SS40_NOTE =
  "Headway v0 has no NTD submission tracking: every major event that has " +
  "not been superseded is listed as open.";

/** Deadlines with one S&S-40 due soon, one overdue, and an S&S-50 month
 *  where two of three mode rows have zero events. */
function makeDeadlines(): SafetyDeadlines {
  return {
    month: "2026-06",
    ss40: [
      {
        event_id: safetyMajorEvent.event_id,
        occurred_at: safetyMajorEvent.occurred_at,
        mode: "bus",
        event_category: "collision",
        due_date: isoDateFromToday(3),
      },
      {
        event_id: "ev-major-late",
        occurred_at: "2026-06-01T08:00:00Z",
        mode: "subway",
        event_category: "derailment",
        due_date: isoDateFromToday(-2),
      },
    ],
    ss40_citation:
      "The S&S-40 Major Event Report is 'due no later than 30 days after " +
      "the date of the event.' (2026 S&S Policy Manual, Exhibit 2, p. 4)",
    ss40_note: SS40_NOTE,
    ss50: [
      {
        month: "2026-06",
        mode: "bus",
        due_date: isoDateFromToday(19),
        non_major_event_count: 2,
        zero_event: false,
      },
      {
        month: "2026-06",
        mode: "ferry",
        due_date: isoDateFromToday(19),
        non_major_event_count: 0,
        zero_event: true,
      },
      {
        month: "2026-06",
        mode: "tram",
        due_date: isoDateFromToday(19),
        non_major_event_count: 0,
        zero_event: true,
      },
    ],
    ss50_citation:
      "The S&S-50 Non-Major Monthly Summary is submitted 'for each mode " +
      "and TOS … every month, even if no event occurs'. (2026 S&S Policy " +
      "Manual, p. 4 + Exhibit 3, p. 5)",
  };
}

function mockSafety(overrides: Record<string, RouteHandler> = {}) {
  return mockApi({
    "GET /safety/events": {
      status: 200,
      body: [
        safetyMajorEvent,
        safetyNonMajorEvent,
        safetyNotReportableEvent,
      ],
    },
    "GET /safety/deadlines": { status: 200, body: makeDeadlines() },
    ...overrides,
  });
}

describe("/safety", () => {
  it("shows the honest-scope banner, urgency-stated deadlines, and the zero-event month rule with its verbatim citation", async () => {
    signInAs("viewer");
    mockSafety();
    renderApp("/safety");

    expect(
      await screen.findByRole("heading", { name: "Safety & security" }),
    ).toBeInTheDocument();

    // Honest scope: alpha, no e-filing — on every visit.
    expect(
      screen.getByText(/Alpha preview — not certified for submission/),
    ).toBeInTheDocument();
    expect(screen.getByText(/does not e-file/)).toBeInTheDocument();

    const deadlines = await screen.findByRole("region", {
      name: "Reporting deadlines",
    });

    // S&S-40: the 30-day rule quoted word for word, with its citation, and
    // the API's openness caveat verbatim.
    expect(deadlines).toHaveTextContent(
      "due no later than 30 days after the date of the event.",
    );
    expect(deadlines).toHaveTextContent(
      "S&S-40 timing — 2026 Safety & Security Policy Manual V1, Exhibit 2, p. 4",
    );
    expect(deadlines).toHaveTextContent(SS40_NOTE);
    // Urgency is TEXT (plus icon and color in CSS — never color alone).
    expect(deadlines).toHaveTextContent("Due in 3 days");
    expect(deadlines).toHaveTextContent("Overdue by 2 days");
    expect(deadlines).toHaveTextContent(
      `S&S-40 for Collision on 2026-07-02 (Bus) (${safetyMajorEvent.event_id})`,
    );
    expect(deadlines).toHaveTextContent(
      "S&S-40 for Derailment on 2026-06-01 (Subway or metro) (ev-major-late)",
    );

    // S&S-50: the month line counts its zero-event modes, each zero row is
    // stated as still due, and the manual's trap is quoted verbatim.
    expect(deadlines).toHaveTextContent("S&S-50 for June 2026");
    expect(deadlines).toHaveTextContent("includes 2 modes with zero events");
    expect(deadlines).toHaveTextContent(
      "for each mode and TOS … every month, even if no event occurs",
    );
    expect(deadlines).toHaveTextContent(
      "S&S-50 timing — 2026 Safety & Security Policy Manual V1, p. 4 + Exhibit 3, p. 5",
    );
    const zeroLines = within(deadlines).getAllByText(
      /0 events — the summary is still due/,
    );
    expect(zeroLines).toHaveLength(2);

    await expectNoAxeViolations();
  });

  it("lists events with classification chips and keeps reading open to viewers while entry and correction stay data_steward+", async () => {
    signInAs("viewer");
    mockSafety();
    const user = userEvent.setup();
    renderApp("/safety");

    await screen.findByRole("heading", { name: "Safety & security" });

    // Classification is conveyed by TEXT on each card (plus icon + color).
    const events = await screen.findByRole("region", {
      name: "Recorded events",
    });
    expect(within(events).getByText("Major event")).toBeInTheDocument();
    expect(within(events).getByText("Non-major event")).toBeInTheDocument();
    expect(within(events).getByText("Not reportable")).toBeInTheDocument();

    // The damage estimate renders VERBATIM (trailing zeros preserved).
    expect(within(events).getByText("$18000.00")).toBeInTheDocument();

    // A record's receipt opens with aria-expanded and shows the token's
    // verified quote + citation (the list serves tokens, not prose).
    const toggle = within(events).getByRole("button", {
      name: "Why this classification — Collision on 2026-07-02 (Bus)",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const receipt = within(events).getByRole("region", {
      name: "Classification receipt for Collision on 2026-07-02 (Bus)",
    });
    expect(receipt).toHaveTextContent(
      "Someone was taken directly from the scene for medical care",
    );
    expect(receipt).toHaveTextContent(
      "Immediate transport away from the scene for medical attention for one or more persons.",
    );
    expect(receipt).toHaveTextContent(
      "Major-event thresholds — 2026 Safety & Security Policy Manual V1, Exhibit 5, p. 16",
    );

    // Viewers read everything but get no entry form and no correct buttons
    // (UX only — the API enforces data_steward+ on every safety write).
    expect(
      screen.getByText(/Only a data steward or above can record/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Record this event" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Correct this event/ }),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("asks plain-language questions and discloses the rail-only questions (and the derailment category) only for rail modes", async () => {
    signInAs("data_steward");
    mockSafety();
    const user = userEvent.setup();
    renderApp("/safety");

    await screen.findByRole("heading", { name: "Record an event" });

    // The injury question is the plain-language form of the threshold.
    expect(
      screen.getByLabelText(
        "Was anyone taken directly from the scene for medical care? How many people?",
      ),
    ).toBeInTheDocument();

    // No rail questions and no derailment option before a rail mode is picked.
    expect(
      screen.queryByRole("group", { name: "Rail-only questions" }),
    ).not.toBeInTheDocument();
    const category = screen.getByLabelText("What kind of event was it?");
    expect(
      within(category).queryByRole("option", { name: "Derailment" }),
    ).not.toBeInTheDocument();

    // Picking a rail mode (the classifier's own rail set) discloses them.
    const mode = screen.getByLabelText("Which mode of service was involved?");
    await user.selectOptions(mode, "subway");
    expect(
      screen.getByRole("group", { name: "Rail-only questions" }),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(
        "Did anyone have a serious injury under the rail criteria?",
      ),
    ).toBeInTheDocument();
    // The migration-0018 capture fields (contract closing round): runaway
    // train and evacuation to the rail right-of-way are rail-only too.
    expect(
      screen.getByLabelText("Did a rail vehicle move on its own (a runaway)?"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Did people evacuate onto the rail right-of-way?"),
    ).toBeInTheDocument();
    expect(
      within(category).getByRole("option", { name: "Derailment" }),
    ).toBeInTheDocument();
    await user.selectOptions(category, "derailment");

    // Leaving rail hides them again and clears the rail-only category
    // rather than silently submitting it for a bus.
    await user.selectOptions(mode, "bus");
    expect(
      screen.queryByRole("group", { name: "Rail-only questions" }),
    ).not.toBeInTheDocument();
    expect(
      within(category).queryByRole("option", { name: "Derailment" }),
    ).not.toBeInTheDocument();
    expect((category as HTMLSelectElement).value).toBe("");

    await expectNoAxeViolations();
  });

  it("refuses an invalid form client-side, in plain language, without calling the API", async () => {
    signInAs("data_steward");
    const calls = mockSafety();
    const user = userEvent.setup();
    renderApp("/safety");

    await screen.findByRole("heading", { name: "Record an event" });
    await user.type(
      screen.getByLabelText(
        "Was anyone taken directly from the scene for medical care? How many people?",
      ),
      " two",
    );
    await user.click(screen.getByRole("button", { name: "Record this event" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The event was not recorded.");
    expect(alert).toHaveTextContent("Enter when the event happened.");
    expect(alert).toHaveTextContent("Pick which mode of service was involved.");
    expect(alert).toHaveTextContent("Pick what kind of event it was.");
    expect(alert).toHaveTextContent(
      "Describe what happened — the narrative is required.",
    );
    expect(alert).toHaveTextContent("needs a whole number, 0 or more.");

    // No POST left the browser: the refusal was client-side.
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    await expectNoAxeViolations();
  });

  it("records an event, sends the contract body (damage stays a string; rail answers omitted for a bus), and shows the returned verdict as a receipt with the verbatim quote + citation", async () => {
    signInAs("data_steward");
    const calls = mockSafety({
      "POST /safety/events": { status: 201, body: safetyMajorCreated },
    });
    const user = userEvent.setup();
    renderApp("/safety");

    await screen.findByRole("heading", { name: "Record an event" });

    fireEvent.change(screen.getByLabelText("When did the event happen?"), {
      target: { value: "2026-07-02T14:30" },
    });
    await user.selectOptions(
      screen.getByLabelText("Which mode of service was involved?"),
      "bus",
    );
    await user.selectOptions(
      screen.getByLabelText("What kind of event was it?"),
      "collision",
    );
    await user.type(
      screen.getByLabelText("Describe what happened"),
      "A bus collided with a car; two passengers went to the hospital.",
    );
    const injuries = screen.getByLabelText(
      "Was anyone taken directly from the scene for medical care? How many people?",
    );
    await user.clear(injuries);
    await user.type(injuries, "2");
    await user.type(
      screen.getByLabelText(
        "Estimated property damage, in dollars (optional)",
      ),
      "18000.00",
    );
    await user.click(
      screen.getByLabelText("Did the event involve a transit vehicle?"),
    );
    await user.click(screen.getByRole("button", { name: "Record this event" }));

    // Success is announced with the classifier's verdict.
    expect(await screen.findByRole("status")).toHaveTextContent(
      "The event is recorded. The classifier's verdict: Major event.",
    );

    // The POST body matches the router's SafetyEventCreate exactly: the
    // occurred_at carries a timezone, the damage estimate is a decimal
    // STRING, and no rail-only field is sent for a bus.
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe("/safety/events");
    expect(post?.body).toEqual({
      occurred_at: new Date("2026-07-02T14:30").toISOString(),
      mode: "bus",
      event_category: "collision",
      narrative:
        "A bus collided with a car; two passengers went to the hospital.",
      fatalities: 0,
      injuries: 2,
      property_damage_usd: "18000.00",
      towed: false,
      evacuation_life_safety: false,
      assault_on_worker: false,
      involves_transit_vehicle: true,
    });

    // The receipt: verdict chip, the classifier named with its version, the
    // classifier's summary and per-threshold sentence VERBATIM, and the
    // threshold's verbatim manual quote with its page citation (the
    // extract-quotes pattern).
    const receipt = screen.getByRole("region", {
      name: "Classification receipt for Collision on 2026-07-02 (Bus)",
    });
    expect(within(receipt).getByText("Major event")).toBeInTheDocument();
    expect(receipt).toHaveTextContent(
      "Decided by classifier sscls_v0 0.1.1",
    );
    expect(receipt).toHaveTextContent(safetyMajorResult.summary);
    expect(receipt).toHaveTextContent(
      "2 person(s) were taken directly from the scene for medical care.",
    );
    expect(receipt).toHaveTextContent(
      "Immediate transport away from the scene for medical attention for one or more persons.",
    );
    expect(receipt).toHaveTextContent(
      "Major-event thresholds — 2026 Safety & Security Policy Manual V1, Exhibit 5, p. 16",
    );
    expect(receipt).toHaveTextContent(
      "thresholds never multiply reports (2026 S&S Policy Manual, p. 14)",
    );

    // The page re-reads the record: events and deadlines are fetched again
    // rather than patched locally (a new major event changes the S&S-40s).
    const eventGets = calls.filter(
      (c) => c.method === "GET" && c.path === "/safety/events",
    );
    const deadlineGets = calls.filter(
      (c) => c.method === "GET" && c.path === "/safety/deadlines",
    );
    expect(eventGets.length).toBe(2);
    expect(deadlineGets.length).toBe(2);

    await expectNoAxeViolations();
  });

  it("shows a non-major verdict's S&S-50 basis: the classifier's sentence verbatim plus the verified quote", async () => {
    signInAs("data_steward");
    mockSafety({
      "POST /safety/events": { status: 201, body: safetyAssaultCreated },
    });
    const user = userEvent.setup();
    renderApp("/safety");

    await screen.findByRole("heading", { name: "Record an event" });
    fireEvent.change(screen.getByLabelText("When did the event happen?"), {
      target: { value: "2026-06-14T09:10" },
    });
    await user.selectOptions(
      screen.getByLabelText("Which mode of service was involved?"),
      "bus",
    );
    await user.selectOptions(
      screen.getByLabelText("What kind of event was it?"),
      "assault",
    );
    await user.type(
      screen.getByLabelText("Describe what happened"),
      "A passenger spat on the bus operator. No injury.",
    );
    await user.click(
      screen.getByLabelText("Was a transit worker assaulted?"),
    );
    await user.click(screen.getByRole("button", { name: "Record this event" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "The classifier's verdict: Non-major event.",
    );
    const receipt = screen.getByRole("region", {
      name: "Classification receipt for Assault on 2026-06-14 (Bus)",
    });
    expect(receipt).toHaveTextContent(
      "The classifier reported no federal major-event threshold met by this event.",
    );
    expect(receipt).toHaveTextContent(
      "Why this belongs on the S&S-50 monthly summary",
    );
    expect(receipt).toHaveTextContent(
      "A transit worker was assaulted; no injury is required for this to belong on the S&S-50.",
    );
    // The verified rule, word for word, with its citation.
    expect(receipt).toHaveTextContent(
      "Assaults on a transit worker do not require an injury to be reportable on the S&S-50.",
    );
    expect(receipt).toHaveTextContent(
      "Non-major — 2026 Safety & Security Policy Manual V1, S&S-50 scope, p. 3",
    );

    await expectNoAxeViolations();
  });

  it("expands nothing silently: unknown threshold tokens are shown raw with the missing quote stated", async () => {
    signInAs("viewer");
    mockSafety({
      "GET /safety/events": {
        status: 200,
        body: [
          {
            ...safetyNotReportableEvent,
            classification: "major",
            thresholds_met: ["mystery_token"],
          },
        ],
      },
    });
    const user = userEvent.setup();
    renderApp("/safety");

    const toggle = await screen.findByRole("button", {
      name: /^Why this classification/,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    // The unrecognized token is stated raw, and so is the missing quote —
    // nothing is hidden, nothing is paraphrased in place of the rule.
    expect(
      screen.getByText(/does not label yet \(“mystery_token”\)/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No verified manual quote is mapped to “mystery_token”/),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("corrects an event through the supersede endpoint (with its required audit reason) and keeps the original visible — struck and linked, never hidden", async () => {
    signInAs("data_steward");
    let eventsBody = [safetyMajorEvent];
    const calls = mockSafety({
      "GET /safety/events": () => ({ status: 200, body: eventsBody }),
      [`POST /safety/events/${safetyMajorEvent.event_id}/supersede`]: () => {
        eventsBody = [safetySupersededEvent, safetyCorrectionEvent];
        return { status: 201, body: safetySupersededResponse };
      },
    });
    const user = userEvent.setup();
    renderApp("/safety");

    await user.click(
      await screen.findByRole("button", { name: /^Correct this event/ }),
    );

    // The correction form is PREFILLED from the original record and states
    // the append-only rule.
    expect(
      screen.getByText(/A correction never edits or deletes the original/),
    ).toBeInTheDocument();
    const narratives = screen.getAllByLabelText("Describe what happened");
    expect(narratives[narratives.length - 1]).toHaveValue(
      safetyMajorEvent.narrative,
    );
    const injuries = screen.getAllByLabelText(
      "Was anyone taken directly from the scene for medical care? How many people?",
    );
    const correctionInjuries = injuries[injuries.length - 1];
    expect(correctionInjuries).toHaveValue("2");

    await user.clear(correctionInjuries);
    await user.type(correctionInjuries, "1");

    // The audit reason is REQUIRED: submitting without one is refused
    // client-side, in plain language, with no API call.
    await user.click(
      screen.getByRole("button", { name: "Record the correction" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Say why this entry is being corrected — the reason is the permanent audit record.",
    );
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    await user.type(
      screen.getByLabelText("Why is this entry being corrected?"),
      "The second passenger declined care at the scene.",
    );
    await user.click(
      screen.getByRole("button", { name: "Record the correction" }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "The correction is recorded and the original is marked as corrected — both stay in the record.",
    );
    const post = calls.find((c) => c.method === "POST");
    expect(post).toBeDefined();
    expect(post?.path).toBe(
      `/safety/events/${safetyMajorEvent.event_id}/supersede`,
    );
    const body = post!.body as { injuries: number; reason: string };
    expect(body.injuries).toBe(1);
    expect(body.reason).toBe(
      "The second passenger declined care at the scene.",
    );

    // The audit story, visually: the ORIGINAL is still on the page — struck
    // through, tagged, and linked to its replacement — and the correction
    // is present as its own record.
    const original = document.getElementById(
      `event-${safetyMajorEvent.event_id}`,
    ) as HTMLElement;
    expect(original).toBeInTheDocument();
    expect(original.querySelector("s")).toHaveTextContent(
      /^Collision on 2026-07-02/,
    );
    expect(
      within(original).getByText("Corrected — see the replacement"),
    ).toBeInTheDocument();
    expect(
      within(original).getByRole("link", {
        name: `Corrected by event ${safetyCorrectionEvent.event_id}`,
      }),
    ).toHaveAttribute("href", `#event-${safetyCorrectionEvent.event_id}`);
    // A superseded record cannot be corrected again from here; the standing
    // replacement can.
    const correctButtons = screen.getAllByRole("button", {
      name: /^Correct this event/,
    });
    expect(correctButtons).toHaveLength(1);
    expect(
      document.getElementById(`event-${safetyCorrectionEvent.event_id}`),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("shows an API refusal verbatim and leaves the form standing", async () => {
    signInAs("data_steward");
    const refusal =
      "Enter when the event happened as a date and time with a time zone. " +
      "Headway cannot place an event in a reporting month without one.";
    mockSafety({
      "POST /safety/events": { status: 422, body: { detail: refusal } },
    });
    const user = userEvent.setup();
    renderApp("/safety");

    await screen.findByRole("heading", { name: "Record an event" });
    fireEvent.change(screen.getByLabelText("When did the event happen?"), {
      target: { value: "2026-07-02T14:30" },
    });
    await user.selectOptions(
      screen.getByLabelText("Which mode of service was involved?"),
      "bus",
    );
    await user.selectOptions(
      screen.getByLabelText("What kind of event was it?"),
      "other",
    );
    await user.type(
      screen.getByLabelText("Describe what happened"),
      "Test narrative.",
    );
    await user.click(screen.getByRole("button", { name: "Record this event" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(refusal);
    // No success receipt appears for a refused event.
    expect(
      screen.queryByRole("region", { name: /^Classification receipt/ }),
    ).not.toBeInTheDocument();
  });
});
