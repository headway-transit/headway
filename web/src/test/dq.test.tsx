import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import { blockingIssue, resolvedIssue, warningIssue } from "./fixtures";

function mockIssues() {
  return mockApi({
    "GET /dq/issues": {
      status: 200,
      body: [blockingIssue, warningIssue, resolvedIssue],
    },
  });
}

describe("/dq", () => {
  it("lists issues with severity as text (not color alone), status, owner, and blocking prominence", async () => {
    signInAs("viewer");
    mockIssues();
    renderApp("/dq");

    expect(
      await screen.findByRole("heading", { name: "Data-quality issues" }),
    ).toBeInTheDocument();

    // Severity is conveyed by TEXT (plus icon and color in CSS).
    expect(screen.getByText("Blocking")).toBeInTheDocument();
    expect(screen.getByText("Warning")).toBeInTheDocument();
    expect(screen.getByText("Info")).toBeInTheDocument();

    // The blocking issue is explicit about its consequence.
    const blockingCard = screen
      .getByRole("heading", {
        name: "Bus 1207 sent no location data for 42 minutes on March 3",
      })
      .closest("article") as HTMLElement;
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

    // Success is announced and the card now shows the resolved state + note.
    expect(await screen.findByRole("status")).toHaveTextContent(
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
});
