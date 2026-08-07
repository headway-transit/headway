/**
 * The mobile layer targets classes that actually exist, and clears the
 * published touch-target floor.
 *
 * WHY THIS TEST EXISTS. Writing the mobile layer, I styled `.dq-subject-grid`
 * — a class that appears nowhere in the app. CSS fails silently: the rule
 * parses, the build passes, the contrast checker is happy, and the grid it
 * was supposed to collapse stays two columns on a phone. Nothing anywhere
 * would have said a word.
 *
 * So every class selector inside the mobile media blocks is checked against
 * the components. A rule for a class nobody renders is decoration with a
 * maintenance cost, and the next person to read it will assume it works.
 *
 * IT DOES NOT TEST LAYOUT. jsdom has no layout engine — it cannot tell you
 * whether something overflows. What it can do is hold the DECLARATIONS
 * honest, which is where this particular class of mistake lives.
 */

import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const ROOT = join(process.cwd(), ".");
const RAW_CSS = readFileSync(join(ROOT, "src/styles.css"), "utf8");
/**
 * Comments stripped before anything is matched. The .nav-strip rule EXPLAINS
 * the overflow trap in prose — it quotes `overflow-x: auto` in the comment
 * that says never to use it — so a naive scan flags the very warning that
 * prevents the bug. The first run of this test did exactly that.
 */
const CSS = RAW_CSS.replace(/\/\*[\s\S]*?\*\//g, "");

/** Every class name mentioned anywhere in the components. */
function renderedClasses(): Set<string> {
  const found = new Set<string>();
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name !== "test") walk(full);
        continue;
      }
      if (!/\.tsx?$/.test(entry.name)) continue;
      const src = readFileSync(full, "utf8");
      for (const m of src.matchAll(/className=\{?["'`]([^"'`]+)["'`]/g)) {
        for (const cls of m[1].split(/\s+/)) if (cls) found.add(cls);
      }
      // Template-literal and conditional class names, e.g. `card ${x}`.
      for (const m of src.matchAll(/["'`]([a-z][a-z0-9-]{2,})["'`]/g)) {
        found.add(m[1]);
      }
    }
  };
  walk(join(ROOT, "src"));
  return found;
}

/**
 * The widest breakpoint still describing a hand-held screen. Anything above
 * this is a tablet or a small window, not the case this layer exists for.
 * Bounded on purpose: a block at `max-width: 99999px` applies everywhere and
 * is not a mobile layer at all, but a naive scan counts it as one — which it
 * did, until this test was mutated to check.
 */
const PHONE_MAX_PX = 900;

/** The text inside the mobile-facing media blocks. */
function mobileBlocks(): string {
  const blocks: string[] = [];
  const re = /@media \(max-width: (\d+)px\) \{/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(CSS)) !== null) {
    if (Number(m[1]) > PHONE_MAX_PX) continue;
    let depth = 1;
    let i = re.lastIndex;
    while (i < CSS.length && depth > 0) {
      if (CSS[i] === "{") depth++;
      else if (CSS[i] === "}") depth--;
      i++;
    }
    blocks.push(CSS.slice(re.lastIndex, i));
  }
  return blocks.join("\n");
}

describe("the mobile layer", () => {
  it("exists at all", () => {
    // The app shipped 4,400 lines of CSS with one responsive rule. If this
    // ever drops back to nothing, that is a regression worth a red build.
    expect(mobileBlocks().length).toBeGreaterThan(400);
  });

  it("every class it styles is actually rendered somewhere", () => {
    const rendered = renderedClasses();
    const styled = new Set<string>();
    for (const m of mobileBlocks().matchAll(/\.([a-z][a-z0-9-]+)/g)) {
      styled.add(m[1]);
    }
    expect(styled.size).toBeGreaterThan(4);

    const orphans = [...styled].filter((c) => !rendered.has(c));
    expect(
      orphans,
      `these mobile rules target classes no component renders, so they do ` +
        `nothing and will quietly rot: ${orphans.join(", ")}`,
    ).toEqual([]);
  });

  it("clears the published touch-target floor", () => {
    // 44px is the floor in WCAG 2.5.5 and Apple's HIG; Material says 48dp.
    // The nav links were about 29px, which is what "bunched up" felt like.
    const mins = [...mobileBlocks().matchAll(/min-height:\s*(\d+)px/g)].map(
      (m) => Number(m[1]),
    );
    expect(mins.length, "no touch-target floor is declared at all").toBeGreaterThan(0);
    for (const value of mins) {
      expect(value, `${value}px is below the 44px touch-target floor`).toBeGreaterThanOrEqual(44);
    }
  });

  it("never puts a scroll container on the nav strip", () => {
    // The trap, found live on 2026-08-03: any non-visible overflow makes the
    // OTHER axis compute to auto (CSS Overflow 3 §3.2), which turned the
    // strip into a 20px-tall scroll box and clipped every open group menu.
    // The fix was to remove it; this is what stops it coming back.
    const strip = /\.nav-strip[^{]*\{([^}]*)\}/g;
    for (const m of CSS.matchAll(strip)) {
      expect(
        /overflow(-x|-y)?\s*:\s*(auto|scroll|hidden)/.test(m[1]),
        "overflow on .nav-strip clips the group menus — see the comment there",
      ).toBe(false);
    }
  });
});
