/**
 * The design-forward pass (handoff 0041) — the rules that must not rot.
 *
 * These are deliberately assertions about the SOURCE tokens and the rendered
 * DOM, because the honesty rules of this direction are visual ones:
 *
 *   - honest attention: the halo rides the card FRAME (an edge-rail), never
 *     a figure — a glow behind a number would eat its contrast ratio, and
 *     glow says "look here", never "this is good";
 *   - the flag always ships a shape and a sentence, so the signal survives
 *     for a reader who perceives no glow at all;
 *   - there is no "all clear" glow: a clear queue gets no rail;
 *   - ALL motion lives inside `prefers-reduced-motion: no-preference`, so
 *     reduced motion means instant, never "slower";
 *   - executed FLAT: --shadow-1 is `none` in both themes, separation is a
 *     1px hairline etch;
 *   - identity-orange and the semantic status set are SEPARATE tokens.
 *
 * Contrast for every token pair is verified by scripts/check-contrast.mjs
 * (npm run check:contrast), which jsdom cannot do.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import { expectNoAxeViolations, mockApi, renderApp, signInAs } from "./helpers";
import {
  blockingIssue,
  dashboardValues,
  dqCountsFor,
  resolvedIssue,
  warningIssue,
} from "./fixtures";
import { copy } from "../copy";

const CSS = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

/** The body of the single prefers-reduced-motion block, and everything else. */
function splitMotion(css: string): { motion: string; rest: string } {
  const marker = "@media (prefers-reduced-motion: no-preference)";
  const start = css.indexOf(marker);
  expect(start).toBeGreaterThan(-1);
  let depth = 0;
  let i = css.indexOf("{", start);
  const open = i;
  for (; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}") {
      depth--;
      if (depth === 0) break;
    }
  }
  return {
    motion: css.slice(open, i + 1),
    rest: css.slice(0, start) + css.slice(i + 1),
  };
}

/** Every declaration block whose selector mentions `needle`. */
function blocksFor(css: string, needle: string): string[] {
  // Strip comments FIRST. The rule-matching regex below treats everything
  // between `}` and `{` as the selector, so a `/* … */` note sitting above
  // a rule gets swallowed into it — and this file's CSS is commented
  // heavily, by design. Without this, a comment that merely NAMES a class
  // makes every test here match on prose instead of on CSS.
  const source = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const out: string[] = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source)) !== null) {
    if (m[1].includes(needle)) out.push(m[2]);
  }
  return out;
}

describe("design tokens (handoff 0041)", () => {
  it("keeps ALL motion inside prefers-reduced-motion: no-preference", () => {
    const { motion, rest } = splitMotion(CSS);
    expect(rest).not.toMatch(/\banimation\s*:/);
    expect(rest).not.toMatch(/@keyframes/);
    // …and the attention rail's pulse is one of the things inside it, so
    // reduced motion leaves a STATIC rail rather than a slower one.
    expect(motion).toMatch(/hw-rail-pulse/);
  });

  it("never puts a glow behind a figure — the halo is on the frame only", () => {
    // No text glow anywhere: a figure's contrast ratio is not negotiable.
    expect(CSS).not.toMatch(/text-shadow/);
    for (const needle of [".stat-value", ".figure", "td.figure"]) {
      for (const block of blocksFor(CSS, needle)) {
        expect(block).not.toMatch(/box-shadow/);
        expect(block).not.toMatch(/filter\s*:/);
      }
    }
    // The rail is a ::before on the card frame, and it is the only thing
    // carrying the glow.
    expect(CSS).toMatch(/\.attn::before/);
    expect(blocksFor(CSS, ".attn-alert::before").join("")).toMatch(
      /box-shadow/,
    );
  });

  it("is FLAT: no elevation shadow on cards in either theme", () => {
    const shadows = [...CSS.matchAll(/--shadow-1:\s*([^;]+);/g)].map((m) =>
      m[1].trim(),
    );
    expect(shadows.length).toBe(2); // light + dark
    expect(shadows.every((s) => s === "none")).toBe(true);
  });

  it("keeps ONE identity accent, separate from the semantic status set", () => {
    const signals = [...CSS.matchAll(/^\s*--signal:\s*([^;]+);/gm)].map((m) =>
      m[1].trim(),
    );
    expect(signals).toEqual(["#a84400", "#ff7a1a"]); // light, dark
    const statuses = [
      ...CSS.matchAll(/--status-(ok|watch|alert):\s*([^;]+);/g),
    ].map((m) => m[2].trim());
    // Six values (three per theme) and the identity accent is none of them:
    // the accent must never be readable as a state.
    expect(statuses).toHaveLength(6);
    for (const signal of signals) expect(statuses).not.toContain(signal);
  });

  it("draws every figure in monospace tabular-nums", () => {
    const statValue = blocksFor(CSS, ".stat-value").join("\n");
    expect(statValue).toMatch(/font-family:\s*var\(--font-mono\)/);
    expect(statValue).toMatch(/font-variant-numeric:\s*tabular-nums/);
    expect(blocksFor(CSS, ".figure").join("\n")).toMatch(
      /font-variant-numeric:\s*tabular-nums/,
    );
  });

  it("right-aligns BARE numeric columns, and only those (handoff 0047)", () => {
    // tabular-nums equalises digit WIDTH; alignment is the other half. A
    // column of VRM read DOWN the page has to stack on the ones place.
    expect(blocksFor(CSS, ".numeric").join("\n")).toMatch(
      /text-align:\s*right/,
    );

    // …and the alignment is deliberately NOT folded into `.figure`. A
    // `.figure` cell may carry a figure PLUS a badge, or a whole phrase —
    // DqView renders "1,204 trips" — and right-aligning those aligns the
    // WORDS while scattering the digits. If someone moves `text-align:
    // right` onto `.figure` to save a class, this fails and says why.
    for (const block of blocksFor(CSS, ".figure")) {
      expect(block).not.toMatch(/text-align:\s*right/);
    }
  });
});

describe("honest attention on the dashboard", () => {
  async function renderWith(issues: typeof blockingIssue[]) {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: dashboardValues },
      "GET /dq/issues/counts": (call) => {
        const status = new URL(call.url, "http://test").searchParams.get(
          "status",
        );
        return { status: 200, body: dqCountsFor(issues, status) };
      },
    });
    renderApp("/dashboard");
    expect(
      await screen.findByRole("heading", { name: "Dashboard" }),
    ).toBeInTheDocument();
  }

  it("flags the card FRAME when a blocking issue is open — with a shape AND a sentence, never a rail alone", async () => {
    await renderWith([blockingIssue, warningIssue, resolvedIssue]);

    const dqCard = (await screen.findByRole("heading", {
      name: "Unresolved data-quality issues by severity",
    })).closest("section") as HTMLElement;

    // The rail is a class on the card frame…
    expect(dqCard.className).toContain("attn");
    expect(dqCard.className).toContain("attn-alert");
    // …and it never touches a figure: nothing inside the card carries it.
    expect(dqCard.querySelectorAll(".attn").length).toBe(0);

    // Shape + words, so the signal survives without perceiving any glow.
    const flag = dqCard.querySelector(".card-flag") as HTMLElement;
    expect(flag).not.toBeNull();
    expect(flag).toHaveTextContent(copy.dashboard.dq.blockingFlag("1"));
    expect(flag.querySelectorAll("svg").length).toBe(1);

    await expectNoAxeViolations();
  });

  it("gives a clear queue NO glow — there is no all-clear signal", async () => {
    await renderWith([resolvedIssue]);
    // findBy: the tallies land on their own counts request.
    const dqCard = (await screen.findByRole("heading", {
      name: "Unresolved data-quality issues by severity",
    })).closest("section") as HTMLElement;
    expect(await within(dqCard).findByText(copy.dashboard.dq.empty)).toBeInTheDocument();
    expect(dqCard.className).not.toContain("attn");
    expect(document.querySelectorAll(".card-flag").length).toBe(0);
  });
});
