import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import type { DqIssue } from "../api/types";
import {
  attestationRecord,
  attestedBlockingIssue,
  blockingIssue,
  resolvedIssue,
  revokedAttestationRecord,
  warningIssue,
} from "./fixtures";

function mockIssues() {
  return mockApi({
    "GET /dq/issues": {
      status: 200,
      body: [blockingIssue, warningIssue, resolvedIssue],
    },
  });
}

/**
 * An OPEN p. 146 refusal issue — the one class with a statistician cure
 * (the attestedBlockingIssue fixture is the same class already closed).
 */
const openRefusalIssue: DqIssue = {
  ...attestedBlockingIssue,
  issue_id: "dq-att-open",
  status: "open",
  resolved_at: null,
  resolution: null,
};

describe("/dq", () => {
  it("treats an ATTESTED blocking issue as closed (migration 0029): visible with its resolution story, not counted open, no resolve form, no blocking note", async () => {
    signInAs("data_steward");
    mockApi({
      "GET /dq/issues": {
        status: 200,
        body: [attestedBlockingIssue, blockingIssue],
      },
    });
    renderApp("/dq");

    // The open count matches the API's certification rule: the attested
    // issue is CLOSED, so only the open one counts.
    expect(
      await screen.findByRole("button", { name: /Blocking open/ }),
    ).toHaveTextContent("1");

    // The attested issue stays fully visible — status labeled, its
    // resolution story shown, no blocking prominence, no resolve form.
    const card = screen
      .getByRole("heading", { name: /412 of 9123 operated trips/ })
      .closest("article") as HTMLElement;
    expect(card).toHaveTextContent("attested");
    expect(card).toHaveTextContent(
      "Closed under statistician attestation #att-3 (p. 146): the factoring method was approved.",
    );
    expect(card).not.toHaveTextContent(
      "Must be resolved before any figure can be certified.",
    );
    expect(
      within(card).queryByRole("button", { name: /^Resolve:/ }),
    ).not.toBeInTheDocument();
    // The still-open blocking issue keeps its resolve form and note.
    const openCard = screen
      .getByRole("heading", { name: /Bus 1207 sent no location data/ })
      .closest("article") as HTMLElement;
    expect(openCard).toHaveTextContent(
      "Must be resolved before any figure can be certified.",
    );
    expect(
      within(openCard).getByRole("button", { name: /^Resolve:/ }),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });
  it("lists issues with severity as text (not color alone), status, owner, and blocking prominence", async () => {
    signInAs("viewer");
    mockIssues();
    renderApp("/dq");

    expect(
      await screen.findByRole("heading", { name: "Data-quality issues" }),
    ).toBeInTheDocument();

    // Severity is conveyed by TEXT on each card (plus icon and color in CSS).
    const blockingCard = screen
      .getByRole("heading", {
        name: "Bus 1207 sent no location data for 42 minutes on March 3",
      })
      .closest("article") as HTMLElement;
    const warningCard = screen
      .getByRole("heading", { name: /GPS miles and odometer miles disagree/ })
      .closest("article") as HTMLElement;
    const infoCard = screen
      .getByRole("heading", { name: /new optional field/ })
      .closest("article") as HTMLElement;
    expect(within(blockingCard).getByText("Blocking")).toBeInTheDocument();
    expect(within(warningCard).getByText("Warning")).toBeInTheDocument();
    expect(within(infoCard).getByText("Info")).toBeInTheDocument();

    // The blocking issue is explicit about its consequence.
    expect(blockingCard.className).toContain("blocking");
    expect(blockingCard).toHaveTextContent(
      "Must be resolved before any figure can be certified.",
    );

    // A resolved issue shows its permanent resolution note; an unresolved one
    // is never presented as resolved.
    expect(
      screen.getByText(
        "Confirmed the new field is informational only; mapping updated.",
      ),
    ).toBeInTheDocument();
    expect(blockingCard).toHaveTextContent("open");

    // Viewers can read the queue but get no resolve controls (API enforces
    // the same rule server-side; hiding is UX, not security).
    expect(
      screen.queryByRole("button", { name: /^Resolve:/ }),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("summarizes the queue with summary-card filter toggles (colored top border, aria-pressed, keyboard operable)", async () => {
    signInAs("viewer");
    mockIssues();
    const user = userEvent.setup();
    renderApp("/dq");

    await screen.findByRole("heading", { name: "Data-quality issues" });

    // Queue-at-a-glance SUMMARY CARDS (handoff 0017 #2), computed from the
    // loaded list (the endpoint returns the whole queue): 1 blocking open,
    // 1 warning open ("owned" still counts as open — it is not resolved),
    // 0 info open, 1 resolved. Each card IS a filter toggle.
    const summary = screen.getByRole("region", { name: "Queue at a glance" });
    const cardRow = within(summary).getByRole("list", {
      name: "Show issues by severity",
    });
    const blockingToggle = within(cardRow).getByRole("button", {
      name: /Blocking open/,
    });
    const warningToggle = within(cardRow).getByRole("button", {
      name: /Warnings open/,
    });
    const infoToggle = within(cardRow).getByRole("button", {
      name: /Info open/,
    });
    const resolvedToggle = within(cardRow).getByRole("button", {
      name: /Resolved/,
    });
    expect(blockingToggle).toHaveTextContent("1");
    expect(warningToggle).toHaveTextContent("1");
    expect(infoToggle).toHaveTextContent("0");
    expect(resolvedToggle).toHaveTextContent("1");
    // The colored top border rides a tone class (color is never alone:
    // the label carries the meaning).
    expect(blockingToggle.className).toContain("tone-danger");
    expect(resolvedToggle.className).toContain("tone-success");

    // Blocking-only in ONE click, state conveyed via aria-pressed.
    expect(blockingToggle).toHaveAttribute("aria-pressed", "false");
    await user.click(blockingToggle);
    expect(blockingToggle).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("heading", { name: /Bus 1207/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /GPS miles/ }),
    ).not.toBeInTheDocument();
    // Filtering hides nothing silently: the held-back count is stated and
    // the cards above keep covering the whole queue.
    expect(summary).toHaveTextContent(
      "Showing 1 of 3 issues. The counts above always cover the whole queue.",
    );
    expect(resolvedToggle).toHaveTextContent("1");

    // Combining filters down to nothing states so plainly — an issue is
    // never made to look resolved (or gone) by a filter.
    await user.click(resolvedToggle);
    expect(
      screen.getByText(/No issues match these filters/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show all issues" }));
    expect(screen.getAllByRole("article")).toHaveLength(3);

    // Full keyboard path: a card toggle is focusable and operable with Enter.
    warningToggle.focus();
    await user.keyboard("{Enter}");
    expect(warningToggle).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("heading", { name: /GPS miles/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /Bus 1207/ }),
    ).not.toBeInTheDocument();
    // Pressing the same card again clears it.
    await user.keyboard("{Enter}");
    expect(warningToggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.getAllByRole("article")).toHaveLength(3);

    await expectNoAxeViolations();
  });

  it("lets a data steward resolve an issue by keyboard with a required note", async () => {
    signInAs("data_steward");
    const calls = mockApi({
      "GET /dq/issues": { status: 200, body: [blockingIssue] },
      "POST /dq/issues/dq-1/resolve": {
        status: 200,
        body: {
          issue_id: "dq-1",
          status: "resolved",
          resolved_at: "2026-03-05T10:00:00Z",
          resolution: "Radio outage confirmed; miles verified against odometer.",
          audit_event_id: 11,
        },
      },
    });
    const user = userEvent.setup();
    renderApp("/dq");

    const resolveButton = await screen.findByRole("button", {
      name: "Resolve: Bus 1207 sent no location data for 42 minutes on March 3",
    });
    resolveButton.focus();
    await user.keyboard("{Enter}");

    // Submitting without a note is refused with an announced explanation.
    const submit = screen.getByRole("button", { name: "Mark as resolved" });
    await user.click(submit);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Please describe how the issue was resolved before submitting.",
    );

    const noteField = screen.getByLabelText("How was this issue resolved?");
    await user.type(
      noteField,
      "Radio outage confirmed; miles verified against odometer.",
    );
    await user.click(submit);

    // Success is confirmed in the shell's toast region (aria-live polite,
    // handoff 0017 #4) and the card now shows the resolved state + note.
    expect(await screen.findByRole("log")).toHaveTextContent(
      "is now resolved",
    );
    const card = screen
      .getByRole("heading", {
        name: "Bus 1207 sent no location data for 42 minutes on March 3",
      })
      .closest("article") as HTMLElement;
    expect(card).toHaveTextContent("resolved");
    expect(card).toHaveTextContent(
      "Radio outage confirmed; miles verified against odometer.",
    );

    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe("/dq/issues/dq-1/resolve");
    expect(post?.body).toEqual({
      resolution: "Radio outage confirmed; miles verified against odometer.",
    });

    await expectNoAxeViolations();
  });

  it("records optional time spent (whole minutes), shows it on the resolved card, and totals documented effort in the header", async () => {
    signInAs("data_steward");
    const calls = mockApi({
      "GET /dq/issues": { status: 200, body: [blockingIssue, resolvedIssue] },
      "POST /dq/issues/dq-1/resolve": {
        status: 200,
        body: {
          issue_id: "dq-1",
          status: "resolved",
          resolved_at: "2026-03-05T10:00:00Z",
          resolution: "Radio outage confirmed.",
          resolution_minutes: 30,
          audit_event_id: 12,
        },
      },
    });
    const user = userEvent.setup();
    renderApp("/dq");

    // The fixture's 90 recorded minutes already show as ≈1.5 hours — UI
    // arithmetic on effort metadata (workflow minutes), never a figure.
    const summary = await screen.findByRole("region", {
      name: "Queue at a glance",
    });
    expect(summary).toHaveTextContent(
      "≈1.5 hours of documented data-quality work",
    );

    await user.click(screen.getByRole("button", { name: /^Resolve:/ }));

    // The effort field is labeled in plain language, with the why.
    const minutesField = screen.getByLabelText(
      "Time spent resolving (minutes)",
    );
    expect(
      screen.getByText(
        "Optional. A whole number of minutes, like 45. Recording it helps show the work behind data quality.",
      ),
    ).toBeInTheDocument();

    // A non-numeric entry is refused with an announced explanation and the
    // issue stays unresolved.
    await user.type(
      screen.getByLabelText("How was this issue resolved?"),
      "Radio outage confirmed.",
    );
    await user.type(minutesField, "twenty");
    await user.click(screen.getByRole("button", { name: "Mark as resolved" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Time spent must be a whole number of minutes (like 45), or left blank.",
    );
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    // A whole number is accepted and sent as an integer.
    await user.clear(minutesField);
    await user.type(minutesField, "30");
    await user.click(screen.getByRole("button", { name: "Mark as resolved" }));
    expect(await screen.findByRole("log")).toHaveTextContent(
      "is now resolved",
    );
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      resolution: "Radio outage confirmed.",
      resolution_minutes: 30,
    });

    // The resolved card displays the recorded effort…
    const card = screen
      .getByRole("heading", { name: /Bus 1207/ })
      .closest("article") as HTMLElement;
    expect(card).toHaveTextContent("Time spent resolving");
    expect(card).toHaveTextContent("30 minutes");
    // …and the header total now covers 90 + 30 minutes = 2.0 hours.
    expect(summary).toHaveTextContent(
      "≈2.0 hours of documented data-quality work",
    );

    await expectNoAxeViolations();
  });

  it("keeps the effort field optional: a blank field sends no resolution_minutes and shows no total when none are recorded", async () => {
    signInAs("data_steward");
    const calls = mockApi({
      "GET /dq/issues": { status: 200, body: [blockingIssue] },
      "POST /dq/issues/dq-1/resolve": {
        status: 200,
        body: {
          issue_id: "dq-1",
          status: "resolved",
          resolved_at: "2026-03-05T10:00:00Z",
          resolution: "Checked and settled.",
          resolution_minutes: null,
          audit_event_id: 13,
        },
      },
    });
    const user = userEvent.setup();
    renderApp("/dq");

    // No recorded minutes anywhere: no effort total is claimed.
    const summary = await screen.findByRole("region", {
      name: "Queue at a glance",
    });
    expect(summary).not.toHaveTextContent("documented data-quality work");

    await user.click(screen.getByRole("button", { name: /^Resolve:/ }));
    await user.type(
      screen.getByLabelText("How was this issue resolved?"),
      "Checked and settled.",
    );
    await user.click(screen.getByRole("button", { name: "Mark as resolved" }));

    expect(await screen.findByRole("log")).toHaveTextContent(
      "is now resolved",
    );
    // The body carries NO resolution_minutes key — blank means unstated.
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({ resolution: "Checked and settled." });
    // The card claims no effort it does not have.
    const card = screen
      .getByRole("heading", { name: /Bus 1207/ })
      .closest("article") as HTMLElement;
    expect(card).not.toHaveTextContent("Time spent resolving");
  });

  it("shows a resolve refusal from the API verbatim", async () => {
    signInAs("data_steward");
    const refusal =
      "This data-quality issue is already resolved. It cannot be resolved " +
      "again — reopening and re-resolving would need a new issue so the " +
      "history stays honest.";
    mockApi({
      "GET /dq/issues": { status: 200, body: [blockingIssue] },
      "POST /dq/issues/dq-1/resolve": {
        status: 409,
        body: { detail: refusal },
      },
    });
    const user = userEvent.setup();
    renderApp("/dq");

    await user.click(await screen.findByRole("button", { name: /^Resolve:/ }));
    await user.type(
      screen.getByLabelText("How was this issue resolved?"),
      "Checked it.",
    );
    await user.click(screen.getByRole("button", { name: "Mark as resolved" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(refusal);
    // The issue is still shown as open — a failed resolution never looks done.
    const card = screen
      .getByRole("heading", { name: /Bus 1207/ })
      .closest("article") as HTMLElement;
    expect(card).toHaveTextContent("open");
  });

  it("closes a p. 146 refusal issue under a recorded attestation: dialog with the verbatim rule, standing attestations only, POST, toast, the attested chip", async () => {
    signInAs("data_steward");
    const calls = mockApi({
      "GET /dq/issues": {
        status: 200,
        body: [openRefusalIssue, blockingIssue],
      },
      "GET /attestations": {
        status: 200,
        body: [attestationRecord, revokedAttestationRecord],
      },
      [`POST /dq/issues/${openRefusalIssue.issue_id}/attest`]: {
        status: 200,
        body: {
          issue_id: openRefusalIssue.issue_id,
          status: "attested",
          resolved_at: "2026-07-15T18:00:00Z",
          resolution:
            "Closed under statistician attestation #att-3 (p. 146): the factoring method was approved.",
          attestation_id: "att-3",
          audit_event_id: 901,
        },
      },
    });
    const user = userEvent.setup();
    renderApp("/dq");

    // The attest action is offered ONLY on the p. 146 refusal class: the
    // telemetry_gap blocking issue takes no attest button — no other gap
    // has a statistician cure (the server enforces the same wall).
    const attestButton = await screen.findByRole("button", {
      name: `Attest: ${openRefusalIssue.title}`,
    });
    expect(
      screen.queryByRole("button", { name: /^Attest:.*Bus 1207/ }),
    ).not.toBeInTheDocument();
    // Both blocking issues are open before the closure.
    expect(
      screen.getByRole("button", { name: /Blocking open/ }),
    ).toHaveTextContent("2");

    await user.click(attestButton);
    const dialog = await screen.findByRole("dialog", {
      name: "Close this issue under a statistician attestation",
    });
    // The p. 146 rule renders VERBATIM via the existing quote map — the
    // plain-language framing never stands alone.
    expect(dialog).toHaveTextContent(
      "qualified statistician approve the factoring method",
    );
    // Only STANDING attestations are offered; the revoked one (att-2)
    // stays on the /attestations record but is never offered here.
    const picker = within(dialog).getByLabelText(
      "Which recorded attestation covers this gap?",
    );
    expect(
      within(picker).getByRole("option", { name: /#att-3 — Dr. Maria Chen/ }),
    ).toBeInTheDocument();
    expect(
      within(picker).queryByRole("option", { name: /att-2/ }),
    ).not.toBeInTheDocument();

    // Submitting without a pick is refused with an announced explanation.
    await user.click(
      within(dialog).getByRole("button", {
        name: "Close this issue as attested",
      }),
    );
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Pick the recorded attestation that covers this issue.",
    );
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    // Zero axe violations WITH the dialog open.
    await expectNoAxeViolations();

    await user.selectOptions(picker, "att-3");
    await user.click(
      within(dialog).getByRole("button", {
        name: "Close this issue as attested",
      }),
    );

    // The POST carries only the reference — the server builds the story.
    expect(await screen.findByRole("log")).toHaveTextContent(
      "is closed as attested",
    );
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(`/dq/issues/${openRefusalIssue.issue_id}/attest`);
    expect(post?.body).toEqual({ attestation_id: "att-3" });

    // The card now wears the attested state (the existing chip vocabulary)
    // with the server-built resolution story, and takes no further action.
    const card = screen
      .getByRole("heading", { name: openRefusalIssue.title })
      .closest("article") as HTMLElement;
    expect(card).toHaveTextContent("attested");
    expect(card).toHaveTextContent(
      "Closed under statistician attestation #att-3 (p. 146): the factoring method was approved.",
    );
    expect(
      within(card).queryByRole("button", { name: /^Resolve:/ }),
    ).not.toBeInTheDocument();
    expect(
      within(card).queryByRole("button", { name: /^Attest:/ }),
    ).not.toBeInTheDocument();
    // The attested issue no longer counts open — screen and server tell
    // the same story as the certification gate.
    expect(
      screen.getByRole("button", { name: /Blocking open/ }),
    ).toHaveTextContent("1");

    await expectNoAxeViolations();
  }, 15000);

  it("offers no attest action to a viewer (UX mirror of the API's data_steward+ rule)", async () => {
    signInAs("viewer");
    mockApi({ "GET /dq/issues": { status: 200, body: [openRefusalIssue] } });
    renderApp("/dq");

    await screen.findByRole("heading", { name: openRefusalIssue.title });
    expect(
      screen.queryByRole("button", { name: /^Attest:/ }),
    ).not.toBeInTheDocument();
  });

  it("states plainly when no standing attestation exists — the dialog references approvals, it never creates one", async () => {
    signInAs("data_steward");
    mockApi({
      "GET /dq/issues": { status: 200, body: [openRefusalIssue] },
      // Only a REVOKED attestation on record: nothing standing to offer.
      "GET /attestations": { status: 200, body: [revokedAttestationRecord] },
    });
    const user = userEvent.setup();
    renderApp("/dq");

    await user.click(
      await screen.findByRole("button", {
        name: `Attest: ${openRefusalIssue.title}`,
      }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      "No standing attestation is on record, so this issue cannot be closed this way yet.",
    );
    expect(
      within(dialog).getByRole("link", { name: "Go to the Attestations page" }),
    ).toHaveAttribute("href", "/attestations");
    expect(
      within(dialog).queryByRole("button", {
        name: "Close this issue as attested",
      }),
    ).not.toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("shows an attest refusal from the API verbatim and keeps the issue open", async () => {
    signInAs("data_steward");
    const refusal =
      "The attestation att-3 was revoked on 2026-07-14 and can no longer " +
      "close issues. Record a new attestation if a statistician has " +
      "approved a method.";
    mockApi({
      "GET /dq/issues": { status: 200, body: [openRefusalIssue] },
      "GET /attestations": { status: 200, body: [attestationRecord] },
      [`POST /dq/issues/${openRefusalIssue.issue_id}/attest`]: {
        status: 409,
        body: { detail: refusal },
      },
    });
    const user = userEvent.setup();
    renderApp("/dq");

    await user.click(
      await screen.findByRole("button", {
        name: `Attest: ${openRefusalIssue.title}`,
      }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(
      within(dialog).getByLabelText(
        "Which recorded attestation covers this gap?",
      ),
      "att-3",
    );
    await user.click(
      within(dialog).getByRole("button", {
        name: "Close this issue as attested",
      }),
    );

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      refusal,
    );
    // A failed closure never looks done.
    const card = screen
      .getByRole("heading", { name: openRefusalIssue.title })
      .closest("article") as HTMLElement;
    expect(card).toHaveTextContent("open");
  });

  it("caps the number of drawn issue cards LOUDLY (counts still cover the whole queue) — the 2026-07-14 live-scale finding", async () => {
    signInAs("viewer");
    // 250 open info issues: over the 200-card render cap.
    const many = Array.from({ length: 250 }, (_, i) => ({
      ...warningIssue,
      issue_id: `dq-bulk-${i}`,
      severity: "info",
      status: "open",
      title: `Bulk issue ${i}`,
    }));
    mockApi({ "GET /dq/issues": { status: 200, body: many } });
    renderApp("/dq");

    await screen.findByRole("heading", { name: "Data-quality issues" });
    // The cap is STATED, with both numbers.
    expect(
      screen.getByText(/Only the first 200 of 250 matching issues are drawn/),
    ).toBeInTheDocument();
    // Exactly the cap's worth of cards is drawn…
    expect(screen.getAllByRole("article")).toHaveLength(200);
    // …and the summary counts still cover the WHOLE queue.
    const summary = screen.getByRole("region", { name: "Queue at a glance" });
    expect(
      within(summary).getByRole("button", { name: /Info open/ }),
    ).toHaveTextContent("250");
  });
});
