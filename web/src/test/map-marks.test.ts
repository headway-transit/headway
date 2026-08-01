/**
 * The mode-mark gate (handoff 0043, design point 4).
 *
 * The first half of this wave established the rule for this map: a colour
 * ships when it has been MEASURED, and the measurement re-runs against the
 * palette that actually ships rather than against a table somebody typed
 * once. This file is that rule applied to the overlay:
 *
 *   - every mode colour clears WCAG 2.1 SC 1.4.11 (3:1) against BOTH
 *     grounds its palette can be drawn on, and against its own halo;
 *   - and over EVERY surface the matching basemap style can put underneath
 *     it — parks, woods, buildings, runways, street ink, place labels —
 *     either the mark or its halo clears the same bar. That generated
 *     sweep exists because the first half found, by measuring a rendered
 *     frame, that a check against bare `earth` alone passes things that are
 *     not actually legible;
 *   - every pair of modes drawn with the SAME glyph — the only pairs colour
 *     alone has to separate — survives a protanopia and a deuteranopia
 *     simulation AND is separated by relative luminance, the channel no
 *     colour-vision deficiency removes;
 *   - every glyph the map draws is really in the vendored font, read off
 *     the actual .pbf, so the no-sprite decision cannot rot silently;
 *   - and the two colours borrowed from the shipped token set still equal
 *     their values in `src/styles.css`, which this wave never edits.
 *
 * `npm run check:map-marks` runs exactly this file with the tables visible.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  CANONICAL_MODES,
  FAMILY_GLYPH,
  FAMILY_SIZE,
  FINDING_GLYPH,
  MARK_CONTRAST_MIN,
  MARK_GROUNDS,
  MARK_HALO,
  MODE_DIM_OPACITY,
  MODE_MARKS,
  TOKEN_MARK_COLORS,
  colorAtLuminance,
  markColor,
  markContrastResults,
  markFamily,
  markPalette,
  markSurfaceResults,
  markSurfaces,
  modeColorExpression,
  modeFilterOpacityExpression,
  modeGlyphExpression,
  modeLuminanceSeparation,
  modeSizeExpression,
  routeColorExpression,
  routeOpacityExpression,
  routeWidthExpression,
  sameShapePairs,
  type MarkGround,
} from "../map/marks";
import { cvdSeparation, simulateCvd } from "../map/cvd";
import { luminance, ratio } from "../map/contrast";
import { BASEMAP_STYLES } from "../map/basemapStyle.ts";
import { PULSE_PERIOD_MS, PULSE_RADIUS, PULSE_STATIC, pulseFrame } from "../map/pulse";

const GROUNDS: MarkGround[] = ["light", "dark"];

/**
 * The bars, stated where they are used.
 *
 * ΔE 15 in CIE76 is comfortably past "clearly a different colour" while
 * staying achievable for four hues inside one glyph family; the luminance
 * bar of 1.35:1 is the backstop that carries the pairs a simulation puts
 * close together (and covers tritanopia, which the palette separates by
 * brightness rather than by hue).
 */
const CVD_DELTA_E_MIN = 15;
const CVD_LUMINANCE_MIN = 1.35;

/** The evidence table, printed per ground (see file header). */
function contrastReport(): string[] {
  const lines = [``, `── mode marks — measured contrast (WCAG 2.1 SC 1.4.11, ${MARK_CONTRAST_MIN}:1) ──`];
  for (const result of markContrastResults()) {
    const against = result.against
      .map((a) => `${a.key} ${a.color} ${a.ratio.toFixed(2)}:1`)
      .join("  |  ");
    lines.push(
      `   ${result.pass ? "PASS" : "FAIL"} ${result.worst.toFixed(2).padStart(6)}:1` +
        `  ${result.what.padEnd(38)} ${result.color}  ·  ${against}`,
    );
  }
  return lines;
}

function cvdReport(): string[] {
  const lines = [
    ``,
    `── same-shape mode pairs — colour separation under dichromacy ──`,
    `   bars: ΔE ≥ ${CVD_DELTA_E_MIN} (protan + deutan) AND luminance ≥ ${CVD_LUMINANCE_MIN}:1`,
  ];
  for (const ground of GROUNDS) {
    for (const [a, b] of sameShapePairs()) {
      const palette = markPalette(ground);
      const sep = cvdSeparation(palette[a], palette[b]);
      const lum = modeLuminanceSeparation(a, b, ground);
      const pass =
        sep.protan >= CVD_DELTA_E_MIN &&
        sep.deutan >= CVD_DELTA_E_MIN &&
        lum >= CVD_LUMINANCE_MIN;
      lines.push(
        `   ${pass ? "PASS" : "FAIL"} ${ground.padEnd(5)} ${`${a}/${b}`.padEnd(26)}` +
          ` ΔE protan ${String(sep.protan).padStart(5)}` +
          `  deutan ${String(sep.deutan).padStart(5)}` +
          `  tritan ${String(sep.tritan).padStart(5)}` +
          `  luminance ${lum.toFixed(2)}:1`,
      );
    }
  }
  return lines;
}

describe("mode marks — the palette generator", () => {
  it("lands a hue anchor on the exact relative luminance it was asked for", () => {
    for (const target of [0.01, 0.08, 0.27, 0.7]) {
      for (const anchor of ["#0072B2", "#F0E442", "#009E73", "#6E7781"]) {
        // Within 8-bit sRGB quantization of the target: the generator
        // bisects exactly, and the residual is the rounding to a hex value
        // an actual display can show — a step that is worth more luminance
        // near white than near black, hence the proportional tolerance.
        expect(
          Math.abs(luminance(colorAtLuminance(anchor, target)) - target),
          `${anchor} → ${target}`,
        ).toBeLessThan(Math.max(0.0015, target * 0.01));
      }
    }
  });

  it("produces a colour for every canonical mode, on both grounds", () => {
    for (const ground of GROUNDS) {
      const palette = markPalette(ground);
      for (const mode of CANONICAL_MODES) {
        expect(palette[mode], mode).toMatch(/^#[0-9A-F]{6}$/);
      }
    }
  });

  it("INVERTS between the grounds: dark marks on the light ground, light marks on the dark one", () => {
    const lightGround = luminance(String(BASEMAP_STYLES.light.theme.earth));
    const darkGround = luminance(String(BASEMAP_STYLES.dark.theme.earth));
    for (const mode of CANONICAL_MODES) {
      expect(luminance(markColor(mode, "light"))).toBeLessThan(lightGround);
      expect(luminance(markColor(mode, "dark"))).toBeGreaterThan(darkGround);
    }
  });

  it("shares no colour between the two palettes — neither is a tint of the other", () => {
    const light = new Set(Object.values(markPalette("light")));
    const dark = new Set(Object.values(markPalette("dark")));
    for (const color of dark) expect(light.has(color)).toBe(false);
  });
});

describe("mode marks — contrast against every ground they can land on", () => {
  it("clears 3:1 against both of its grounds and against its own halo", () => {
    const results = markContrastResults();
    console.log(contrastReport().join("\n"));
    // Every mode plus the two token-sourced marks, on both grounds.
    expect(results.length).toBe((CANONICAL_MODES.length + 2) * 2);
    expect(results.filter((r) => !r.pass).map((r) => r.what)).toEqual([]);
  });

  it("sweeps EVERY surface the basemap can draw underneath a mark, not just the bare earth", () => {
    // The sweep is generated from the authored palettes, so a ground colour
    // added to a style later is gated the day it appears.
    expect(markSurfaces("light").length).toBeGreaterThan(40);
    expect(markSurfaces("dark").length).toBeGreaterThan(40);
    const results = markSurfaceResults();
    expect(results.length).toBeGreaterThan(1000);
    const failures = results
      .filter((r) => !r.pass)
      .map(
        (r) =>
          `${r.mode} on ${r.ground}: ${r.surface} (${r.surfaceColor}) ink ${r.inkRatio.toFixed(2)} halo ${r.haloRatio.toFixed(2)}`,
      );
    expect(failures).toEqual([]);
  });

  it("keeps the halo a REAL edge — mark ink separates from its own halo on both grounds", () => {
    for (const ground of GROUNDS) {
      const palette = markPalette(ground);
      for (const mode of CANONICAL_MODES) {
        expect(
          ratio(palette[mode], MARK_HALO[ground]),
          `${mode} on ${ground}`,
        ).toBeGreaterThanOrEqual(MARK_CONTRAST_MIN);
      }
    }
  });

  it("measures against the AUTHORED style grounds, so re-tuning a basemap re-measures the marks", () => {
    expect(MARK_GROUNDS.light["light basemap earth"]).toBe(
      BASEMAP_STYLES.light.theme.earth,
    );
    expect(MARK_GROUNDS.dark["dark basemap earth"]).toBe(
      BASEMAP_STYLES.dark.theme.earth,
    );
  });
});

describe("mode marks — colour-vision deficiency", () => {
  it("simulates dichromacy for real: red and green collapse together under deuteranopia", () => {
    // The control. If the simulation were a no-op this pair would stay far
    // apart and every CVD assertion below would be worthless.
    const plain = cvdSeparation("#FF0000", "#00FF00");
    expect(plain.deutan).toBeLessThan(35);
    expect(simulateCvd("#FF0000", "deutan")).not.toBe("#FF0000");
    // And a pair that differs only in brightness must SURVIVE it.
    expect(cvdSeparation("#111111", "#DDDDDD").deutan).toBeGreaterThan(60);
  });

  it("separates every pair of modes drawn with the SAME glyph, by hue AND by brightness", () => {
    console.log(cvdReport().join("\n"));
    const pairs = sameShapePairs();
    // road (1 pair) + rail (6) + cable (3): the families where colour has
    // to do the work. Water and unknown have one mode each.
    expect(pairs.length).toBe(10);
    const failures: string[] = [];
    for (const ground of GROUNDS) {
      const palette = markPalette(ground);
      for (const [a, b] of pairs) {
        const sep = cvdSeparation(palette[a], palette[b]);
        const lum = modeLuminanceSeparation(a, b, ground);
        if (sep.protan < CVD_DELTA_E_MIN || sep.deutan < CVD_DELTA_E_MIN) {
          failures.push(`${ground} ${a}/${b}: ΔE ${sep.protan}/${sep.deutan}`);
        }
        if (lum < CVD_LUMINANCE_MIN) {
          failures.push(`${ground} ${a}/${b}: luminance ${lum.toFixed(2)}:1`);
        }
      }
    }
    expect(failures).toEqual([]);
  });

  it("gives every mode inside a glyph family its OWN brightness tier — the channel no deficiency removes", () => {
    const byFamily = new Map<string, number[]>();
    for (const mode of CANONICAL_MODES) {
      const spec = MODE_MARKS[mode];
      byFamily.set(spec.family, [
        ...(byFamily.get(spec.family) ?? []),
        spec.tier,
      ]);
    }
    for (const [family, tiers] of byFamily) {
      expect(new Set(tiers).size, family).toBe(tiers.length);
    }
  });
});

describe("mode marks — the shapes, and the sprite decision", () => {
  /**
   * Parse the vendored SDF glyph range and list the codepoints it holds.
   * glyphs.proto: glyphs{1: fontstack{3: glyph{1: id}}}.
   */
  function vendoredCodepoints(range: string): Set<number> {
    const data = readFileSync(
      resolve(process.cwd(), `public/basemap-fonts/Noto Sans Regular/${range}.pbf`),
    );
    const readVarint = (at: number): [number, number] => {
      let result = 0;
      let shift = 0;
      let i = at;
      for (;;) {
        const byte = data[i++];
        result |= (byte & 0x7f) << shift;
        if ((byte & 0x80) === 0) return [result, i];
        shift += 7;
      }
    };
    const fields = function* (
      start: number,
      end: number,
    ): Generator<[number, number, number]> {
      let i = start;
      while (i < end) {
        const [key, next] = readVarint(i);
        i = next;
        const field = key >> 3;
        const wire = key & 7;
        if (wire === 2) {
          const [len, after] = readVarint(i);
          yield [field, after, after + len];
          i = after + len;
        } else if (wire === 0) {
          const [value, after] = readVarint(i);
          yield [field, value, -1];
          i = after;
        } else if (wire === 5) {
          yield [field, i, i + 4];
          i += 4;
        } else if (wire === 1) {
          yield [field, i, i + 8];
          i += 8;
        } else {
          throw new Error(`unexpected wire type ${wire}`);
        }
      }
    };
    const ids = new Set<number>();
    for (const [f1, s1, e1] of fields(0, data.length)) {
      if (f1 !== 1 || e1 < 0) continue;
      for (const [f2, s2, e2] of fields(s1, e1)) {
        if (f2 !== 3 || e2 < 0) continue;
        for (const [f3, v3, e3] of fields(s2, e2)) {
          if (f3 === 1 && e3 < 0) ids.add(v3);
        }
      }
    }
    return ids;
  }

  it("draws every mark with a glyph the vendored font ACTUALLY contains — no sprite, and no silent erasure of the fleet", () => {
    const present = vendoredCodepoints("9472-9727");
    const drawn = [...Object.values(FAMILY_GLYPH), FINDING_GLYPH];
    expect(drawn.length).toBeGreaterThan(4);
    for (const glyph of drawn) {
      const codepoint = glyph.codePointAt(0)!;
      // Every mark glyph lives in Unicode "Geometric Shapes" (U+25A0-25FF),
      // which is exactly the range parsed above.
      expect(codepoint, glyph).toBeGreaterThanOrEqual(0x25a0);
      expect(codepoint, glyph).toBeLessThanOrEqual(0x25ff);
      expect(present.has(codepoint), `${glyph} (U+${codepoint.toString(16)})`)
        .toBe(true);
    }
  });

  it("keeps the recorded no-sprite posture: neither authored style declares one", () => {
    for (const ground of GROUNDS) {
      expect(
        (BASEMAP_STYLES[ground] as unknown as Record<string, unknown>).sprite,
      ).toBeUndefined();
    }
  });

  it("reserves ▲ for findings — it is never a mode's shape", () => {
    expect(Object.values(FAMILY_GLYPH)).not.toContain(FINDING_GLYPH);
    for (const mode of CANONICAL_MODES) {
      expect(FAMILY_GLYPH[markFamily(mode)]).not.toBe(FINDING_GLYPH);
    }
  });

  it("draws a mode it has never heard of, rather than dropping it", () => {
    expect(markFamily("hyperloop")).toBe("unknown");
    expect(markColor("hyperloop", "light")).toBe(markColor("unknown", "light"));
  });

  it("gives every family a glyph and a size", () => {
    for (const mode of CANONICAL_MODES) {
      const family = markFamily(mode);
      expect(FAMILY_GLYPH[family]).toBeTruthy();
      expect(FAMILY_SIZE[family]).toBeGreaterThan(0);
    }
  });
});

describe("mode marks — the token colours are quoted, not forked", () => {
  const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

  /**
   * Read one custom property out of a specific theme block.
   *
   * The selectors are matched at the START of a line, because the file
   * opens with a long comment that mentions both of them — a slice keyed on
   * the first textual occurrence silently reads the wrong region.
   */
  function token(name: string, theme: "light" | "dark"): string {
    const lightAt = css.search(/^:root \{/m);
    const darkAt = css.search(/^:root\[data-theme="dark"\] \{/m);
    expect(lightAt).toBeGreaterThan(-1);
    expect(darkAt).toBeGreaterThan(lightAt);
    const block =
      theme === "light" ? css.slice(lightAt, darkAt) : css.slice(darkAt);
    const match = new RegExp(`${name}:\\s*([^;]+);`).exec(block);
    if (!match) throw new Error(`no ${name} in the ${theme} block`);
    return match[1].trim();
  }

  it("uses the SHIPPED --status-alert for the flagged mark, one value per ground", () => {
    expect(TOKEN_MARK_COLORS.alert.light).toBe(token("--status-alert", "light"));
    expect(TOKEN_MARK_COLORS.alert.dark).toBe(token("--status-alert", "dark"));
  });

  it("uses the SHIPPED --signal for 'this is what you are pointing at'", () => {
    expect(TOKEN_MARK_COLORS.signal.light).toBe(token("--signal", "light"));
    expect(TOKEN_MARK_COLORS.signal.dark).toBe(token("--signal", "dark"));
  });

  it("measures the no-basemap canvas against the SHIPPED --map-bg", () => {
    expect(MARK_GROUNDS.light["canvas ground, no basemap (--map-bg)"]).toBe(
      token("--map-bg", "light"),
    );
    expect(MARK_GROUNDS.dark["canvas ground, no basemap (--map-bg)"]).toBe(
      token("--map-bg", "dark"),
    );
  });
});

describe("mode marks — the data-driven expressions", () => {
  it("encodes shape, colour and size as ONE match over `mode` each, never per-feature", () => {
    for (const expression of [
      modeGlyphExpression(),
      modeColorExpression("light"),
      modeSizeExpression(),
    ]) {
      const parts = expression as unknown[];
      expect(parts[0]).toBe("match");
      expect(parts[1]).toEqual(["get", "mode"]);
      // Every canonical mode except 'unknown' is a case; 'unknown' is the
      // fallback, which is also what an unrecognised mode falls through to.
      expect(parts.length).toBe(3 + (CANONICAL_MODES.length - 1) * 2);
    }
  });

  it("names every canonical mode in the colour expression, with the ring as the fallback", () => {
    const parts = modeColorExpression("dark") as unknown[];
    const palette = markPalette("dark");
    for (const mode of CANONICAL_MODES) {
      if (mode === "unknown") continue;
      const at = parts.indexOf(mode);
      expect(at, mode).toBeGreaterThan(1);
      expect(parts[at + 1]).toBe(palette[mode]);
    }
    expect(parts[parts.length - 1]).toBe(palette.unknown);
  });

  it("DIMS rather than hides when a mode is highlighted — nothing leaves the map", () => {
    expect(modeFilterOpacityExpression(null)).toBe(1);
    const parts = modeFilterOpacityExpression("bus") as unknown[];
    expect(parts[0]).toBe("case");
    expect(parts[1]).toEqual(["==", ["get", "mode"], "bus"]);
    expect(parts[2]).toBe(1);
    // The dim is a real reduction but never zero: a dimmed vehicle is still
    // on the map, which is the whole difference between highlight and filter.
    expect(parts[3]).toBe(MODE_DIM_OPACITY);
    expect(MODE_DIM_OPACITY).toBeGreaterThan(0);
  });

  it("thickens the highlighted mode's routes and lets a related route win", () => {
    const plain = routeWidthExpression(null) as unknown[];
    expect(plain[1]).toEqual(["boolean", ["feature-state", "related"], false]);
    expect(plain[3]).toBe(1.5);
    const filtered = routeWidthExpression("bus") as unknown[];
    const modeCase = filtered[3] as unknown[];
    expect(modeCase[0]).toBe("case");
    // selected mode thicker than the rest
    expect(Number(modeCase[2])).toBeGreaterThan(Number(modeCase[3]));
  });

  it("lights a related route with the identity accent for the ground it is on", () => {
    for (const ground of GROUNDS) {
      const parts = routeColorExpression("#123456", ground) as unknown[];
      expect(parts[2]).toBe(TOKEN_MARK_COLORS.signal[ground]);
      expect(parts[3]).toBe("#123456");
    }
    const opacity = routeOpacityExpression("bus") as unknown[];
    expect(opacity[1]).toEqual(["boolean", ["feature-state", "related"], false]);
    expect(opacity[2]).toBe(1);
  });
});

describe("the attention pulse", () => {
  it("breathes the FRAME only, seamlessly, and never past its bounds", () => {
    const start = pulseFrame(0);
    expect(start.radius).toBeCloseTo(PULSE_RADIUS.min, 6);
    expect(pulseFrame(PULSE_PERIOD_MS / 2).radius).toBeCloseTo(
      PULSE_RADIUS.max,
      6,
    );
    // Seamless loop: one full period returns to the first frame.
    expect(pulseFrame(PULSE_PERIOD_MS).radius).toBeCloseTo(start.radius, 6);
    for (let ms = 0; ms < PULSE_PERIOD_MS * 2; ms += 37) {
      const frame = pulseFrame(ms);
      expect(frame.radius).toBeGreaterThanOrEqual(PULSE_RADIUS.min - 1e-9);
      expect(frame.radius).toBeLessThanOrEqual(PULSE_RADIUS.max + 1e-9);
      // Never fades out entirely — the ring is part of the mark.
      expect(frame.strokeOpacity).toBeGreaterThan(0.35);
      expect(frame.strokeOpacity).toBeLessThanOrEqual(1);
    }
  });

  it("collapses to a static ring at FULL strength, not to nothing", () => {
    expect(PULSE_STATIC.radius).toBe(PULSE_RADIUS.min);
    expect(PULSE_STATIC.strokeOpacity).toBe(1);
  });
});
