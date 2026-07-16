/**
 * The certifications index (/certifications — the "list → certificate"
 * follow-up recorded in handoff 0019's frontend evidence). Pinned: every
 * record renders verbatim (signed ones with signer + fingerprint, legacy
 * ones with the honest no-signature line — never a blank), each entry
 * links to its certificate view, the signature-state SummaryCards act as
 * filter toggles whose counts always cover the whole record, the nav
 * links the room for every signed-in role, errors render verbatim, and
 * axe reports zero violations.
 */

import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import {
  legacyCertificationRecord,
  signedCertificationRecord,
} from "./fixtures";

function mockRecords(body: unknown) {
  return mockApi({ "GET /certifications": { status: 200, body } });
}

describe("/certifications (the index room)", () => {
  it("lists signed and legacy records honestly, links each certificate, and is linked from the nav for any signed-in role", async () => {
    signInAs("viewer");
    const calls = mockRecords([
      legacyCertificationRecord,
      signedCertificationRecord,
    ]);
    renderApp("/certifications");

    expect(
      await screen.findByRole("heading", { name: "Certifications" }),
    ).toBeInTheDocument();

    // The read is the authenticated list endpoint.
    const dataCall = calls.find((c) => c.path === "/certifications");
    expect(dataCall?.headers.Authorization).toBe("Bearer test-token");

    // The signed record: typed signer, timestamp, fingerprint VERBATIM.
    const signedCard = screen
      .getByRole("heading", { name: /Certification cert-42/ })
      .closest("article") as HTMLElement;
    expect(signedCard).toHaveTextContent(
      "Signed by Alex Rivera, NTD Certifying Official",
    );
    expect(signedCard).toHaveTextContent("2026-07-02T15:00:00Z");
    expect(signedCard).toHaveTextContent(
      signedCertificationRecord.key_fingerprint as string,
    );
    expect(within(signedCard).getByText("Signed")).toBeInTheDocument();
    expect(signedCard).toHaveTextContent("Covers 2 figures.");
    expect(
      within(signedCard).getByRole("link", {
        name: "Open certificate cert-42",
      }),
    ).toHaveAttribute("href", "/certifications/cert-42");

    // The legacy record: the honest absence, never a blank or a backfill.
    const legacyCard = screen
      .getByRole("heading", { name: /Certification cert-7/ })
      .closest("article") as HTMLElement;
    expect(
      within(legacyCard).getByText("No digital signature"),
    ).toBeInTheDocument();
    expect(legacyCard).toHaveTextContent(
      "Recorded before digital signatures existed in Headway — no signature fingerprint. Honest history, never backfilled.",
    );
    expect(legacyCard).toHaveTextContent(
      "Certified by the account certifier.",
    );
    expect(
      within(legacyCard).getByRole("link", {
        name: "Open certificate cert-7",
      }),
    ).toHaveAttribute("href", "/certifications/cert-7");

    // The nav links the room beside Certify's territory — for EVERY
    // signed-in role (a viewer here), like the API's any-role GET.
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(
      within(nav).getByRole("link", { name: "Certifications" }),
    ).toHaveAttribute("href", "/certifications");

    await expectNoAxeViolations();
  });

  it("filters by signature state through the summary cards — counts always cover the whole record, held-back records are stated", async () => {
    signInAs("data_steward");
    mockRecords([legacyCertificationRecord, signedCertificationRecord]);
    const user = userEvent.setup();
    renderApp("/certifications");

    await screen.findByRole("heading", { name: "Certifications" });

    const cardRow = screen.getByRole("list", {
      name: "Certifications at a glance — filter by signature state",
    });
    const signedToggle = within(cardRow).getByRole("button", {
      name: /Digitally signed/,
    });
    const legacyToggle = within(cardRow).getByRole("button", {
      name: /Recorded before signatures/,
    });
    expect(signedToggle).toHaveTextContent("1");
    expect(legacyToggle).toHaveTextContent("1");

    // Pressing "Digitally signed" narrows the list, states the held-back
    // count, and keeps both counts covering the whole record.
    await user.click(signedToggle);
    expect(signedToggle).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("heading", { name: /Certification cert-42/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /Certification cert-7/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        /1 certification record is outside the pressed filter — out of view here, never off the record/,
      ),
    ).toBeInTheDocument();
    expect(legacyToggle).toHaveTextContent("1");

    // Pressing again shows everything.
    await user.click(signedToggle);
    expect(screen.getAllByRole("article")).toHaveLength(2);

    await expectNoAxeViolations();
  });

  it("states the empty record plainly", async () => {
    signInAs("viewer");
    mockRecords([]);
    renderApp("/certifications");

    expect(
      await screen.findByText(
        "No certifications are on record yet. One appears here the moment a certifying official signs figures on the Certify page.",
      ),
    ).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("shows an API error verbatim", async () => {
    signInAs("viewer");
    mockApi({
      "GET /certifications": {
        status: 500,
        body: { detail: "The certifications record could not be read." },
      },
    });
    renderApp("/certifications");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The certifications record could not be read.",
    );
  });
});
