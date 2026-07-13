/**
 * The shared QuoteFigure (src/components/QuoteFigure.tsx — extracted
 * 2026-07-13 from the four per-view copies). Pins the three states every
 * migrated call site relies on:
 *   1. a quote on file renders the fta-quote figure (blockquote + cite);
 *   2. a missing quote renders the caller's message LOUDLY (class "alert")
 *      by default;
 *   3. variant="gap" renders the deliberately-muted stated absence
 *      ("threshold-quote-missing") for tokens the tracker knowingly has no
 *      verbatim quote for — stated, never blank, never a false alarm.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QuoteFigure } from "../components/QuoteFigure";
import { expectNoAxeViolations } from "./helpers";

const QUOTE = {
  quote:
    "Transit agencies must report accurate, true statistics for VRM (i.e., no estimates).",
  citation: "Accuracy requirement — 2026 NTD Policy Manual, Full Reporting, p. 135",
};

describe("QuoteFigure", () => {
  it("renders a verbatim quote as a blockquote with its citation", async () => {
    const { container } = render(
      <QuoteFigure quote={QUOTE} missingMessage="unused here" />,
    );
    const figure = container.querySelector("figure.fta-quote");
    expect(figure).not.toBeNull();
    expect(figure?.querySelector("blockquote")).toHaveTextContent(QUOTE.quote);
    expect(figure?.querySelector("figcaption cite")).toHaveTextContent(
      QUOTE.citation,
    );
    // The stated-absence message must not render when the quote is on file.
    expect(screen.queryByText("unused here")).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("states a missing quote loudly (alert) by default", async () => {
    const { container } = render(
      <QuoteFigure quote={null} missingMessage="The rule is not on file." />,
    );
    const message = screen.getByText("The rule is not on file.");
    expect(message).toHaveClass("alert");
    expect(container.querySelector("figure.fta-quote")).toBeNull();
    await expectNoAxeViolations(container);
  });

  it('mutes the stated absence for the deliberate-gap variant ("gap")', async () => {
    const { container } = render(
      <QuoteFigure
        quote={null}
        missingMessage="No verified quote is mapped to this token."
        variant="gap"
      />,
    );
    const message = screen.getByText(
      "No verified quote is mapped to this token.",
    );
    expect(message).toHaveClass("threshold-quote-missing");
    expect(message).not.toHaveClass("alert");
    await expectNoAxeViolations(container);
  });
});
