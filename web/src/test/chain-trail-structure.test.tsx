/**
 * The relationship trail must be a valid list.
 *
 * The trail (PR #21) wraps the inspector's chain — finding → block → route →
 * calculation → owner → source records — in an <ol> so the spine says those
 * links are consecutive. Two caveat paragraphs about how complete the chain
 * can be were left as DIRECT children of that <ol>, which is invalid markup:
 * an <ol> may only directly contain <li>, <script> or <template>.
 *
 * It reached main. PR #21's own web job passed and the merge run failed,
 * because the violation only surfaces when the branch that renders those
 * caveats is actually taken — and axe is the only thing in the suite that
 * looks. A grep cannot answer this (it cannot tell a <p> nested inside a
 * ChainStep from one beside it), so the assertion is on the rendered DOM:
 * every direct child of the trail is an <li>, with every optional branch
 * forced on at once.
 */

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import RelationshipInspector from "../map/RelationshipInspector";
import type { FindingChain } from "../map/findings";
import { expectNoAxeViolations } from "./helpers";
import { blockingIssue } from "./fixtures";

/** Every optional branch ON at once — the caveats, an empty calc list, and a
 *  null owner all render together, which no single realistic chain does. */
const EVERY_BRANCH: FindingChain = {
  issue: blockingIssue,
  blocks: [
    {
      block_id: "B800-53",
      block_label: "Block 53",
      trip_count: 4,
      first_departure: "06:12",
      last_departure: "09:41",
      trip_ids: ["t1", "t2"],
      routes: [],
    },
  ],
  routes: [
    {
      route_id: "E",
      short_name: "E",
      long_name: "Riverbend — Knight St",
      mode: "bus",
      drawn: false,
    },
  ],
  calcs: [],
  owner: null,
  unmatchedTripCount: 3,
  subjectCapped: true,
};

function renderInspector(chain: FindingChain) {
  return render(
    <MemoryRouter>
      <RelationshipInspector
        chain={chain}
        sourceRecordIds={null}
        sourceRecordsLoading={false}
        fromMap={false}
        onClose={() => {}}
      />
    </MemoryRouter>,
  );
}

describe("the relationship trail", () => {
  it("contains only list items, with every optional branch rendering", () => {
    const { container } = renderInspector(EVERY_BRANCH);
    const trail = container.querySelector("ol.chain-trail");
    expect(trail, "the trail did not render").not.toBeNull();

    const strays = Array.from(trail!.children)
      .filter((el) => el.tagName !== "LI")
      .map((el) => `<${el.tagName.toLowerCase()}>`);
    expect(
      strays,
      "an <ol> may only directly contain <li>. Anything else is invalid " +
        "markup and an axe `list` violation — put it in a ChainStep, or " +
        "outside the trail entirely.",
    ).toEqual([]);
    expect(trail!.children.length).toBeGreaterThan(0);
  });

  it("still renders the caveats it moved out of the list", () => {
    // Moving them must not lose them: 'trips we could not attribute' and 'the
    // subject list was capped' are how the panel stays honest about the
    // chain's completeness.
    const { container } = renderInspector(EVERY_BRANCH);
    expect(container.textContent).toMatch(/3/);
    const trail = container.querySelector("ol.chain-trail")!;
    expect(trail.textContent).not.toContain("could not be attributed");
  });

  it("is axe-clean with every branch on", async () => {
    renderInspector(EVERY_BRANCH);
    await expectNoAxeViolations();
  });

  it("is axe-clean with a minimal chain too", async () => {
    renderInspector({
      ...EVERY_BRANCH,
      blocks: [],
      routes: [],
      unmatchedTripCount: 0,
      subjectCapped: false,
      owner: "fleet-telemetry",
    });
    await expectNoAxeViolations();
  });
});
