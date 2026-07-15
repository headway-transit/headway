/**
 * Statistician attestations (/attestations — handoff 0019, design A): the
 * room that records a qualified statistician's approval of a factoring
 * method. The suite pins: the verbatim p. 146 rule on the page (never a
 * paraphrase standing alone), the hard-limits list, the role-gated entry
 * form with the house disabled-with-reason pattern, the POST body, the
 * re-read after recording, revoked attestations staying VISIBLE and
 * labeled, and the attested-figure receipt callout (the justified-exception
 * rendering, visually distinct without reading as an error).
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
import {
  attestationRecord,
  attestedUptValue,
  revokedAttestationRecord,
} from "./fixtures";

/** The p. 146 statistician sentence (quotes.json upt_v0), verbatim. */
const P146_STATISTICIAN_SNIPPET =
  "agencies must have a qualified statistician approve the factoring " +
  "method used to account for the missing percentage";

describe("/attestations (statistician attestations)", () => {
  it("shows the verbatim p. 146 rule, the behavior note, and the hard-limits list to every signed-in role", async () => {
    signInAs("viewer");
    mockApi({
      "GET /attestations": { status: 200, body: [] },
    });
    renderApp("/attestations");

    expect(
      await screen.findByRole("heading", { name: "Statistician attestations" }),
    ).toBeInTheDocument();

    // The rule itself is the verbatim manual quote with its citation —
    // the plain-language intro never stands alone.
    const quote = screen.getByText(new RegExp(P146_STATISTICIAN_SNIPPET));
    expect(quote.closest("figure")).toHaveClass("fta-quote");
    expect(
      screen.getByText(/100% counts \/ missing-trip rule — 2026 NTD Policy Manual, Full Reporting, p\. 146/),
    ).toBeInTheDocument();

    // What an attestation can never do, stated plainly.
    const limits = screen
      .getByRole("heading", { name: "What an attestation can never do" })
      .closest("section") as HTMLElement;
    expect(limits).toHaveTextContent(
      "It never unblocks an undersampled PMT sampling plan.",
    );
    expect(limits).toHaveTextContent(
      "It never touches the simulated-data flag.",
    );
    expect(limits).toHaveTextContent(
      "It never applies outside its declared scope",
    );
    expect(limits).toHaveTextContent("It never affects operations metrics.");
    // The undersampling hard limit in the manual's own words (p. 149) —
    // the plain-language list never stands alone as a paraphrase.
    expect(limits).toHaveTextContent(
      "agencies must not collect a smaller sample than the chosen sampling plan prescribes",
    );

    // The empty record is stated — and the refusal behavior with it.
    expect(
      screen.getByText(/No attestations are on record/),
    ).toBeInTheDocument();

    // A viewer sees no entry form and no revoke control — stated plainly,
    // not hidden (the API enforces the same rule).
    expect(
      screen.getByText(/Only a certifying official can record an attestation/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Record attestation" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Revoke attestation/ }),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("lists every attestation on record — revoked ones VISIBLE and labeled with who and why, never hidden", async () => {
    signInAs("data_steward");
    mockApi({
      "GET /attestations": {
        status: 200,
        body: [attestationRecord, revokedAttestationRecord],
      },
    });
    renderApp("/attestations");

    // The standing attestation, with statistician, method, scope, document
    // pointer, and entry provenance.
    const standing = (
      await screen.findByRole("heading", { name: "Attestation #att-3" })
    ).closest("li") as HTMLElement;
    expect(standing).toHaveTextContent(
      "Approved by Dr. Maria Chen — PhD, Statistics — State University; independent consultant",
    );
    expect(standing).toHaveTextContent(
      "Factor up by route-level average boardings from the surrounding four weeks.",
    );
    expect(standing).toHaveTextContent(
      "Metric: Unlinked Passenger Trips (UPT)",
    );
    expect(standing).toHaveTextContent("Applies to: agency");
    expect(standing).toHaveTextContent("Period: 2026-03-01 to 2026-07-01");
    expect(standing).toHaveTextContent(
      "Approval document: records://agency/approvals/2026-014.pdf (Headway stores this pointer, never the document itself)",
    );
    expect(standing).toHaveTextContent(
      "Recorded by certifier, 2026-03-05T15:00:00Z",
    );

    // The revoked one stays on the page, labeled — an append-only record
    // that names who revoked it and why.
    const revoked = screen
      .getByRole("heading", { name: /Attestation #att-2/ })
      .closest("li") as HTMLElement;
    expect(within(revoked).getByText("Revoked")).toBeInTheDocument();
    expect(revoked).toHaveTextContent(
      "Revoked 2026-02-20T09:00:00Z by certifier. Revoked attestations stay on record — nothing here is ever deleted.",
    );
    expect(revoked).toHaveTextContent(
      "Reason: Superseded by a route-level method.",
    );
    // A data steward reads the record but cannot revoke (UX mirror of the
    // API's certifying_official rule).
    expect(
      screen.queryByRole("button", { name: /Revoke attestation/ }),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  // Explicit timeout: seven typed fields + axe sit at the 5 s default's
  // edge under full-suite load on this box (the house 15 s precedent).
  it("gates the entry form with the disabled-with-reason pattern, POSTs exactly the typed record, and re-reads the list", { timeout: 15_000 }, async () => {
    signInAs("certifying_official");
    let listCalls = 0;
    const calls = mockApi({
      "GET /attestations": () => {
        listCalls += 1;
        return {
          status: 200,
          body: listCalls === 1 ? [] : [attestationRecord],
        };
      },
      "POST /attestations": {
        status: 201,
        body: { ...attestationRecord, audit_event_id: 55 },
      },
    });
    const user = userEvent.setup();
    renderApp("/attestations");

    const button = await screen.findByRole("button", {
      name: "Record attestation",
    });
    // The statistician fieldset carries the p. 150 qualifications rule
    // verbatim — who counts as qualified is the manual's text, not ours.
    expect(
      screen.getByText(/FTA does not prescribe specific statistician qualifications/),
    ).toBeInTheDocument();
    // Every empty field is a stated reason at the (aria-disabled, still
    // perceivable) button.
    expect(button).toHaveAttribute("aria-disabled", "true");
    const reason = screen.getByRole("status", {
      name: "Why the record button is off",
    });
    expect(button).toHaveAttribute("aria-describedby", reason.id);
    expect(reason).toHaveTextContent("Fill in “Statistician's full name”.");
    expect(reason).toHaveTextContent("Fill in “Method description”.");
    expect(reason).toHaveTextContent("Fill in “Covers periods from”.");
    // A click on the off button is refused — no POST, no silent swallow.
    await user.click(button);
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    // Fill the form (the scope pattern defaults to "agency").
    await user.type(
      screen.getByLabelText("Statistician's full name"),
      "Dr. Maria Chen",
    );
    await user.type(
      screen.getByLabelText("Credentials"),
      "PhD, Statistics — State University; independent consultant",
    );
    await user.type(
      screen.getByLabelText("Method description"),
      "Factor up by route-level average boardings from the surrounding four weeks.",
    );
    await user.type(
      screen.getByLabelText("Approval document reference"),
      "records://agency/approvals/2026-014.pdf",
    );
    await user.selectOptions(screen.getByLabelText("Metric"), "upt");
    await user.type(
      screen.getByLabelText("Covers periods from"),
      "2026-03-01",
    );
    await user.type(
      screen.getByLabelText("Up to (not including)"),
      "2026-07-01",
    );

    expect(button).not.toHaveAttribute("aria-disabled");
    await expectNoAxeViolations(); // the completed form, pre-submit
    await user.click(button);

    // The POST carries exactly what was typed.
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      statistician_name: "Dr. Maria Chen",
      statistician_credentials:
        "PhD, Statistics — State University; independent consultant",
      method_description:
        "Factor up by route-level average boardings from the surrounding four weeks.",
      document_reference: "records://agency/approvals/2026-014.pdf",
      metric: "upt",
      scope_pattern: "agency",
      period_start: "2026-03-01",
      period_end: "2026-07-01",
    });
    expect(post?.headers["Authorization"]).toBe("Bearer test-token");

    // The durable identifiers verbatim, the toast confirmation, and the
    // list RE-READ from the API — never assumed.
    expect(
      await screen.findByText("Attestation #att-3 recorded. Audit event 55."),
    ).toBeInTheDocument();
    expect(screen.getByRole("log")).toHaveTextContent(
      "Attestation recorded and audit-logged. It appears in the list below.",
    );
    await waitFor(() => {
      expect(listCalls).toBe(2);
    });
    expect(
      screen.getByRole("heading", { name: "Attestation #att-3" }),
    ).toBeInTheDocument();
  });

  it("revokes with a required reason — the record stays visible, the API is re-read, nothing is deleted", async () => {
    signInAs("certifying_official");
    let listCalls = 0;
    const calls = mockApi({
      "GET /attestations": () => {
        listCalls += 1;
        return {
          status: 200,
          body:
            listCalls === 1
              ? [attestationRecord]
              : [
                  {
                    ...attestationRecord,
                    revoked_at: "2026-07-15T16:00:00Z",
                    revoked_by: "test.user",
                    revocation_reason: "Entered against the wrong period.",
                  },
                ],
        };
      },
      "POST /attestations/att-3/revoke": {
        status: 200,
        body: {
          ...attestationRecord,
          revoked_at: "2026-07-15T16:00:00Z",
          revoked_by: "test.user",
          revocation_reason: "Entered against the wrong period.",
          audit_event_id: 77,
        },
      },
    });
    const user = userEvent.setup();
    renderApp("/attestations");

    // The revoke act needs a stated reason: the button is off (but
    // perceivable) until one is written, and says why.
    const button = await screen.findByRole("button", {
      name: "Revoke attestation #att-3",
    });
    expect(button).toHaveAttribute("aria-disabled", "true");
    await user.click(button);
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    expect(
      screen.getByText(
        "Write the reason for revoking. It is kept in the record and the audit log.",
      ),
    ).toBeInTheDocument();

    await user.type(
      screen.getByLabelText("Reason for revoking attestation #att-3"),
      "Entered against the wrong period.",
    );
    expect(button).not.toHaveAttribute("aria-disabled");
    await user.click(button);

    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe("/attestations/att-3/revoke");
    expect(post?.body).toEqual({ reason: "Entered against the wrong period." });

    // The list is re-read; the record stays, now labeled revoked.
    await waitFor(() => {
      expect(listCalls).toBe(2);
    });
    const card = screen
      .getByRole("heading", { name: /Attestation #att-3/ })
      .closest("li") as HTMLElement;
    expect(within(card).getByText("Revoked")).toBeInTheDocument();
    expect(card).toHaveTextContent(
      "Reason: Entered against the wrong period.",
    );
    expect(screen.getByRole("log")).toHaveTextContent(
      "Attestation revoked and audit-logged. It stays on record below.",
    );

    await expectNoAxeViolations();
  });

  it("shows an API refusal verbatim (the server enforces the role and the record's validity)", async () => {
    signInAs("certifying_official");
    mockApi({
      "GET /attestations": { status: 200, body: [] },
      "POST /attestations": {
        status: 403,
        body: {
          detail:
            "Recording an attestation requires the certifying_official role.",
        },
      },
    });
    const user = userEvent.setup();
    renderApp("/attestations");

    await screen.findByRole("button", { name: "Record attestation" });
    await user.type(screen.getByLabelText("Statistician's full name"), "A");
    await user.type(screen.getByLabelText("Credentials"), "B");
    await user.type(screen.getByLabelText("Method description"), "C");
    await user.type(screen.getByLabelText("Approval document reference"), "D");
    await user.type(screen.getByLabelText("Covers periods from"), "2026-03-01");
    await user.type(screen.getByLabelText("Up to (not including)"), "2026-07-01");
    await user.click(
      screen.getByRole("button", { name: "Record attestation" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Recording an attestation requires the certifying_official role.",
    );
  });
});

describe("attested-figure receipt callout (handoff 0019, design 2)", () => {
  it("renders the justified-exception callout: the handoff's statement, the verbatim p. 146 quote, the method, and the attestations link — without the danger styling of an error", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [attestedUptValue] },
    });
    renderApp("/metrics");
    const user = userEvent.setup();

    // Open the figure's receipt from the metrics table.
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /^Details/ }));
    const receipt = await screen.findByRole("region", {
      name: /^Receipt for Unlinked Passenger Trips/,
    });

    // The labeled exception tag + the handoff's statement, attestation
    // number included.
    const callout = within(receipt)
      .getByText("Statistician-approved exception")
      .closest(".attested-callout") as HTMLElement;
    expect(callout).not.toBeNull();
    expect(callout).toHaveTextContent(
      "This figure was factored beyond the 2% threshold under a statistician-approved method — attestation #att-3.",
    );

    // The p. 146 rule, verbatim with its citation, INSIDE the callout.
    expect(callout).toHaveTextContent(
      /agencies must have a qualified statistician approve the factoring method/,
    );
    expect(callout).toHaveTextContent(
      /100% counts \/ missing-trip rule — 2026 NTD Policy Manual, Full Reporting, p\. 146/,
    );

    // WHO approved and WHAT method, verbatim from the figure's own
    // provenance (detail.attestation — carried permanently).
    expect(callout).toHaveTextContent("Approved by Dr. Maria Chen.");
    expect(callout).toHaveTextContent(
      "The approved method: Factor up by route-level average boardings from the surrounding four weeks.",
    );

    // The door to the full attestation record.
    expect(
      within(callout).getByRole("link", {
        name: "Read attestation #att-3 on the Attestations page",
      }),
    ).toHaveAttribute("href", "/attestations");

    // A justified exception, not an error: nothing in the callout renders
    // with the alert styling, and no role="alert" fires for it.
    expect(callout.querySelector(".alert")).toBeNull();
    expect(within(callout).queryByRole("alert")).not.toBeInTheDocument();

    // The attestation provenance never double-renders in the generic
    // detail list (the callout is its one home on a receipt).
    const detailList = within(receipt).getByRole("list", {
      name: /Calculation details for/,
    });
    expect(detailList).not.toHaveTextContent(/Adjusted under statistician/);
    expect(detailList).not.toHaveTextContent("attestation_id");

    await expectNoAxeViolations();
  });
});
