/**
 * The nav menus must not be trapped inside a scroll box.
 *
 * Found live on the UAT box, 2026-08-03: clicking Reports, Records or Tools
 * appeared to do nothing. The disclosure was working perfectly — it opened,
 * set aria-expanded, and rendered its links. It was clipped to about twenty
 * pixels, because `.nav-strip` carried `overflow-x: auto`.
 *
 * That is the trap: per CSS Overflow 3 §3.2, a box cannot scroll in one axis
 * only. Setting `overflow-x` to anything other than `visible` computes the
 * other axis to `auto` as well, so the strip became a scroll container in BOTH
 * directions and clipped its absolutely-positioned child to a nav row's
 * height. The giveaway was a vertical scrollbar appearing in the header.
 *
 * jsdom has no layout engine, so no rendering test can catch this — asking it
 * for the panel's height returns zero whether the bug is present or not. The
 * honest check is therefore on the stylesheet itself: the ancestor of an
 * absolutely-positioned panel must not establish a scroll container.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// process.cwd() is web/ under vitest — the same way map-marks.test.ts reaches
// its font fixtures.
const CSS = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

/** The body of one top-level rule, by exact selector. */
function ruleBody(selector: string): string {
  const start = CSS.indexOf(`\n${selector} {`);
  expect(start, `no rule for ${selector}`).toBeGreaterThan(-1);
  const open = CSS.indexOf("{", start);
  const close = CSS.indexOf("\n}", open);
  return CSS.slice(open + 1, close);
}

/** Declarations only — comments explaining the rule are not declarations. */
function declarations(body: string): string {
  return body.replace(/\/\*[\s\S]*?\*\//g, "");
}

describe("the nav strip", () => {
  it("does not establish a scroll container around the open menu", () => {
    const body = declarations(ruleBody(".nav-strip"));
    expect(
      body,
      "`.nav-strip` sets overflow again. Any non-visible overflow value " +
        "clips the nav-group panel to the strip's height — the menus open " +
        "and cannot be seen. If the row needs to fit a narrow window, let it " +
        "wrap; do not make it scroll.",
    ).not.toMatch(/overflow/);
  });

  it("lets the row wrap instead, so nothing needs to scroll", () => {
    const body = declarations(ruleBody(".nav-strip > ul"));
    expect(body).toMatch(/flex-wrap:\s*wrap/);
    expect(
      body,
      "nowrap forces the row to overflow, which is what invited the " +
        "scroll container that clipped the menus",
    ).not.toMatch(/flex-wrap:\s*nowrap/);
  });

  it("still positions the panel against the group, not the page", () => {
    // The other half of the contract: the panel is absolutely positioned, so
    // it needs `.nav-group` as its containing block. If that relative
    // positioning is ever dropped the panel escapes to the viewport corner.
    expect(declarations(ruleBody(".nav-group"))).toMatch(
      /position:\s*relative/,
    );
    expect(declarations(ruleBody(".nav-group-panel"))).toMatch(
      /position:\s*absolute/,
    );
  });
});
