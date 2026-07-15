/**
 * The certificate view (/certifications/:id — handoff 0019, designs 5–8):
 * the signature block front and center, the SERVER's verification verdict
 * rendered verbatim on load AND on the verify button's re-check (verified /
 * FAILED / key-mismatch / unsigned legacy — every message the server's
 * own, never softened), the covered figures with receipt hashes from the
 * signed canonical document, and the honest-scope statement exactly as it
 * was signed — with its absence on a signed record stated loudly (this UI
 * never substitutes its own description of what a signature means).
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
  certificateFixture,
  unsignedCertificateFixture,
  verifiedResultFixture,
} from "./fixtures";

const FAILED_RESULT = {
  ...verifiedResultFixture,
  verified: false,
  verdict: "failed",
  message:
    "VERIFICATION FAILED: the stored certification record does not match " +
    "its signature (the signed bytes or the signature were altered). The " +
    "record has been tampered with since signing, or is corrupt.",
};

const MISMATCH_RESULT = {
  ...verifiedResultFixture,
  verified: false,
  verdict: "key_mismatch",
  message:
    "This certification was signed by key SHA256:old, but this " +
    "installation currently holds key SHA256:new. Treat this as " +
    "UNVERIFIED, not as proof of tampering.",
};

describe("/certifications/:id (certificate view)", () => {
  it("renders the signature block front and center — signer, title, timestamp, fingerprint, the on-load verified verdict verbatim — with the covered figures and their receipt hashes from the signed document", async () => {
    signInAs("viewer");
    mockApi({
      "GET /certifications/cert-42": { status: 200, body: certificateFixture },
    });
    renderApp("/certifications/cert-42");

    expect(
      await screen.findByRole("heading", { name: "Certification certificate" }),
    ).toBeInTheDocument();

    // The signature block: signer identity, timestamp, key fingerprint.
    const signature = screen
      .getByRole("heading", { name: "Signature" })
      .closest("section") as HTMLElement;
    expect(signature).toHaveTextContent(
      "Signed by Alex Rivera, NTD Certifying Official",
    );
    expect(signature).toHaveTextContent("Signed at 2026-07-02T15:00:00Z");
    expect(signature).toHaveTextContent(
      "SHA256:9wL2xkq8vX0FZm3n1p5r7t9u1w3y5a7c9e1g3i5k7m0",
    );

    // The server verifies on every read: the on-load verdict renders
    // verbatim in a status region without any click.
    const verdict = within(signature).getByText(/Signature verified\./);
    expect(verdict.closest("[role='status']")).not.toBeNull();
    expect(verdict.closest("[role='status']")).toHaveTextContent(
      verifiedResultFixture.message,
    );

    // The covered figures from the signed document: values and hashes
    // verbatim, provenance one step away.
    const covered = screen
      .getByRole("heading", { name: "Figures this signature covers" })
      .closest("section") as HTMLElement;
    expect(covered).toHaveTextContent(
      "Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31: 12345.60 miles — calculated by vrm_v0 1.0.0",
    );
    expect(covered).toHaveTextContent(
      "Receipt hash: aa11bb22cc33dd44ee55ff66aa77bb88cc99dd00ee11ff22aa33bb44cc55dd66",
    );
    expect(
      within(covered).getAllByRole("link", { name: "How this number was made" }),
    ).toHaveLength(2);

    // The statistician attestations recorded in the signed document.
    expect(
      screen.getByText("Attestation #att-3 — Dr. Maria Chen"),
    ).toBeInTheDocument();

    // The recorded intent statement, verbatim.
    expect(
      screen.getByText(certificateFixture.attestation),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("renders the honest-scope statement exactly as it was signed — verbatim, never paraphrased", async () => {
    signInAs("viewer");
    mockApi({
      "GET /certifications/cert-42": { status: 200, body: certificateFixture },
    });
    renderApp("/certifications/cert-42");

    const scope = (
      await screen.findByRole("heading", {
        name: "What this signature covers — and what it does not",
      })
    ).closest("section") as HTMLElement;
    // The signed document's exact sentence — including the not-PKI half,
    // which must never be weakened or dropped.
    expect(scope).toHaveTextContent(
      certificateFixture.document?.scope_statement as string,
    );
    expect(scope).toHaveTextContent(
      "It is not a personal public-key-infrastructure signature",
    );
  });

  it("states LOUDLY when a signed record carries no scope statement, instead of substituting one", async () => {
    signInAs("viewer");
    mockApi({
      "GET /certifications/cert-42": {
        status: 200,
        // A signed record whose document could not be parsed: the server
        // serves document=null and a failed verification.
        body: { ...certificateFixture, document: null, verification: FAILED_RESULT },
      },
    });
    renderApp("/certifications/cert-42");

    const scope = (
      await screen.findByRole("heading", {
        name: "What this signature covers — and what it does not",
      })
    ).closest("section") as HTMLElement;
    expect(scope).toHaveTextContent(
      "The signed record does not contain the server's statement of what this signature covers.",
    );
    // And the failed verification is an alert, verbatim.
    expect(screen.getByRole("alert")).toHaveTextContent(
      "SIGNATURE VERIFICATION FAILED.",
    );

    await expectNoAxeViolations();
  });

  it("verify button: re-verifies on demand and renders a verified verdict verbatim in a status region", async () => {
    signInAs("viewer");
    const calls = mockApi({
      "GET /certifications/cert-42": { status: 200, body: certificateFixture },
      "GET /certifications/cert-42/verify": {
        status: 200,
        body: verifiedResultFixture,
      },
    });
    const user = userEvent.setup();
    renderApp("/certifications/cert-42");

    await user.click(
      await screen.findByRole("button", { name: "Verify this signature" }),
    );

    // Two verified verdicts now: on-load and the re-check.
    const verdicts = await screen.findAllByText(/Signature verified\./);
    expect(verdicts).toHaveLength(2);
    expect(
      calls.filter((c) => c.path === "/certifications/cert-42/verify"),
    ).toHaveLength(1);

    await expectNoAxeViolations();
  });

  it("verify button: a FAILED re-check is an alert with the server's verdict verbatim — never softened", async () => {
    signInAs("viewer");
    mockApi({
      "GET /certifications/cert-42": { status: 200, body: certificateFixture },
      "GET /certifications/cert-42/verify": {
        status: 200,
        body: FAILED_RESULT,
      },
    });
    const user = userEvent.setup();
    renderApp("/certifications/cert-42");

    await user.click(
      await screen.findByRole("button", { name: "Verify this signature" }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("SIGNATURE VERIFICATION FAILED.");
    expect(alert).toHaveTextContent(FAILED_RESULT.message);

    await expectNoAxeViolations();
  });

  it("renders a key-mismatch verdict as honestly inconclusive — an alert with the server's message verbatim, distinct from tampering", async () => {
    signInAs("viewer");
    mockApi({
      "GET /certifications/cert-42": {
        status: 200,
        body: { ...certificateFixture, verification: MISMATCH_RESULT },
      },
    });
    renderApp("/certifications/cert-42");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("SIGNATURE NOT CHECKABLE.");
    expect(alert).toHaveTextContent(
      "Treat this as UNVERIFIED, not as proof of tampering.",
    );
    expect(alert).not.toHaveTextContent("VERIFICATION FAILED");

    await expectNoAxeViolations();
  });

  it("verify button: a verification ERROR (e.g. the endpoint refused) is also a loud failure, verbatim", async () => {
    signInAs("viewer");
    mockApi({
      "GET /certifications/cert-42": { status: 200, body: certificateFixture },
      "GET /certifications/cert-42/verify": {
        status: 503,
        body: { detail: "The verification service is unavailable." },
      },
    });
    const user = userEvent.setup();
    renderApp("/certifications/cert-42");

    await user.click(
      await screen.findByRole("button", { name: "Verify this signature" }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("SIGNATURE VERIFICATION FAILED.");
    expect(alert).toHaveTextContent(
      "The verification service is unavailable.",
    );
  });

  it("renders a pre-signature certification honestly: the server's unsigned-legacy message verbatim, no verify button, history never backfilled", async () => {
    signInAs("viewer");
    mockApi({
      "GET /certifications/cert-7": {
        status: 200,
        body: unsignedCertificateFixture,
      },
    });
    renderApp("/certifications/cert-7");

    // The server's own legacy statement, verbatim — a banner, not an error.
    expect(
      await screen.findByText(
        /recorded before digital signatures existed in Headway/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Verify this signature" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    // Only ids were recorded: stated, with provenance links kept.
    expect(
      screen.getByText(/This record holds only the identifiers/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "How this number was made" }),
    ).toHaveAttribute("href", "/metrics/mv-vrm-0/lineage");
    // The account that certified is still named.
    expect(
      screen.getByText("Certified by the account certifier."),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("shows a load failure verbatim (e.g. no certification with that id)", async () => {
    signInAs("viewer");
    mockApi({
      "GET /certifications/cert-42": {
        status: 404,
        body: { detail: "No certification with that id exists." },
      },
    });
    renderApp("/certifications/cert-42");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Headway could not load this certificate. The server said:",
    );
    expect(alert).toHaveTextContent("No certification with that id exists.");

    await expectNoAxeViolations();
  });
});
