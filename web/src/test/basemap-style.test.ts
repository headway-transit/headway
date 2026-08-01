/**
 * The basemap legibility gate (handoff 0043, design point 1 + 3).
 *
 * "The dark map does not ship until a street reads." This file is that
 * sentence in executable form: it measures every road, water and label
 * pair each authored style declares, prints the numbers as the recorded
 * evidence table, and FAILS the suite if any pair drops under its bar.
 * `npm run check:map-contrast` runs exactly this file with the table
 * visible.
 *
 * It also pins the reason the styles exist at all — the stock Protomaps
 * flavors this project shipped in handoff 0027 are measured here too, and
 * they fail. That test is not a swipe at an excellent upstream project
 * (its flavors are tuned for reference maps, not for an ops console where
 * the street network is the subject); it is the regression pin. If anyone
 * ever swaps our authored palettes back out for a stock flavor to save a
 * file, the numbers say no.
 */

import { describe, expect, it } from "vitest";
import { labels, namedTheme, noLabels } from "protomaps-themes-base";
import type { LayerSpecification } from "maplibre-gl";
import {
  BASEMAP_FONT,
  BASEMAP_LAYER_PREFIX,
  BASEMAP_STYLES,
  basemapLayerSpecs,
  scaleLineWidth,
  type BasemapStyleId,
} from "../map/basemapStyle.ts";
import {
  contrastRatio,
  luminance,
  measureCheck,
  measureStyle,
  ratio,
} from "../map/contrast.ts";

const STYLE_IDS: BasemapStyleId[] = ["light", "dark"];

/** The evidence table, printed once per style (see file header). */
function report(id: BasemapStyleId): string[] {
  const style = BASEMAP_STYLES[id];
  const lines = [
    ``,
    `── ${style.name} — measured contrast (WCAG 2.1) ──`,
    `   bars: roads/water ${style.contrastTargets.road}:1 (SC 1.4.11 non-text)` +
      ` · labels ${style.contrastTargets.label}:1 (SC 1.4.3 text)`,
    `   ground: ${String(style.theme.earth)}   label halo: ${style.labelHalo.width}px`,
  ];
  for (const r of measureStyle(style)) {
    const strokes = r.measured
      .map((m) => `${m.key} ${m.color} ${m.ratio.toFixed(2)}:1`)
      .join("  |  ");
    lines.push(
      `   ${r.pass ? "PASS" : "FAIL"} ${r.best.toFixed(2).padStart(6)}:1` +
        ` (min ${r.min})  ${r.what}  ·  on ${r.bg.key} ${r.bg.color}  ·  ${strokes}`,
    );
  }
  return lines;
}

describe("basemap styles — WCAG math", () => {
  it("computes the reference values from WCAG 2.1 (white/black = 21:1, identical = 1:1)", () => {
    expect(ratio("#ffffff", "#000000")).toBe(21);
    expect(ratio("#123456", "#123456")).toBe(1);
    expect(luminance("#ffffff")).toBeCloseTo(1, 10);
    expect(luminance("#000000")).toBeCloseTo(0, 10);
    // A known third-party value: #767676 is the classic "smallest grey that
    // still clears 4.5:1 on white".
    expect(contrastRatio("#767676", "#ffffff")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio("#777777", "#ffffff")).toBeLessThan(4.5);
  });

  it("refuses a color it cannot measure instead of scoring it 1:1 (fail loudly)", () => {
    expect(() => luminance("rgb(1,2,3)")).toThrow();
    expect(() =>
      measureCheck(
        { what: "x", kind: "road", min: 3, bg: "earth", fg: ["nope"] },
        { earth: "#000000" },
      ),
    ).toThrow(/no theme color "nope"/);
  });
});

describe.each(STYLE_IDS)("basemap style: %s", (id) => {
  const style = BASEMAP_STYLES[id];

  it("EVERY declared road, water and label pair clears its WCAG bar — the gate that lets this style ship", () => {
    const results = measureStyle(style);
    // The table goes to the run output: these are the recorded numbers.
    console.log(report(id).join("\n"));
    expect(results.length).toBeGreaterThan(20);
    const failures = results
      .filter((r) => !r.pass)
      .map((r) => `${r.what}: ${r.best.toFixed(2)}:1 < ${r.min}:1`);
    expect(failures).toEqual([]);
  });

  it("holds roads to 3:1 and labels to 4.5:1 — the bars are the WCAG ones, not a softened house rule", () => {
    expect(style.contrastTargets.road).toBe(3);
    expect(style.contrastTargets.water).toBe(3);
    expect(style.contrastTargets.label).toBe(4.5);
    for (const check of style.contrastChecks) {
      expect(check.min).toBe(style.contrastTargets[check.kind]);
    }
  });

  it("covers every road class, water and label kind — a pair nobody measured is a pair nobody fixed", () => {
    const what = style.contrastChecks.map((c) => c.what.toLowerCase());
    for (const needle of [
      "highway",
      "major road",
      "link",
      "minor street",
      "service road",
      "bridge",
      "tunnel",
      "railway",
      "water vs ground",
      "street name",
      "city / town name",
      "neighborhood name",
    ]) {
      expect(
        what.some((w) => w.includes(needle)),
        `no contrast check mentions "${needle}"`,
      ).toBe(true);
    }
    expect(style.contrastChecks.filter((c) => c.kind === "road").length)
      .toBeGreaterThanOrEqual(12);
    expect(style.contrastChecks.filter((c) => c.kind === "label").length)
      .toBeGreaterThanOrEqual(12);
  });

  it("defines every color the vendored tile schema asks for — no key falls through to undefined", () => {
    const required = Object.keys(namedTheme("light"));
    const missing = required.filter((k) => !(k in style.theme));
    expect(missing).toEqual([]);
    // And every scalar entry is a real #rrggbb we can measure.
    for (const [key, value] of Object.entries(style.theme)) {
      if (typeof value !== "string") continue;
      if (key === "regular" || key === "bold" || key === "italic") {
        expect(value).toBe(BASEMAP_FONT);
        continue;
      }
      expect(value, `theme.${key}`).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it("puts a HALO under every single label layer — the failure mode was names dissolving into the ground", () => {
    const specs = basemapLayerSpecs(id);
    const symbols = specs.filter((l) => l.type === "symbol");
    expect(symbols.length).toBeGreaterThan(5);
    for (const layer of symbols) {
      const paint = (layer.paint ?? {}) as Record<string, unknown>;
      expect(paint["text-halo-color"], `${layer.id} halo color`).toMatch(
        /^#[0-9A-Fa-f]{6}$/,
      );
      expect(paint["text-halo-width"], `${layer.id} halo width`).toBe(
        style.labelHalo.width,
      );
      expect(paint["text-halo-blur"], `${layer.id} halo blur`).toBe(
        style.labelHalo.blur,
      );
      // Upstream ships a flat 1px halo; both our styles raise it.
      expect(style.labelHalo.width).toBeGreaterThan(1);
      // Every label text color is measurably separated from its own halo.
      const text = paint["text-color"];
      if (typeof text === "string") {
        expect(
          contrastRatio(text, paint["text-halo-color"] as string),
          `${layer.id} text vs its halo`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("makes ZERO external requests possible: one vendored glyph stack, no icon-image, no sprite, no POI layer, no URL in any layer", () => {
    const specs = basemapLayerSpecs(id);
    expect(specs.length).toBeGreaterThan(40);
    for (const layer of specs) {
      expect(layer.id.startsWith(BASEMAP_LAYER_PREFIX)).toBe(true);
      const layout = (layer.layout ?? {}) as Record<string, unknown>;
      expect(layout["icon-image"]).toBeUndefined();
      if (layout["text-font"]) {
        expect(layout["text-font"]).toEqual([BASEMAP_FONT]);
      }
    }
    // Nothing anywhere in the produced style resembles an off-box URL.
    const serialized = JSON.stringify(specs);
    expect(serialized).not.toMatch(/https?:\/\//);
    expect(serialized).not.toMatch(/\/\/[a-z0-9-]+\.[a-z]{2,}/i);
    expect(specs.some((l) => l.id === `${BASEMAP_LAYER_PREFIX}pois`)).toBe(
      false,
    );
    expect(specs.some((l) => l.type === "background")).toBe(false);
  });

  /**
   * Found by MEASURING A RENDERED FRAME, not by reading the style file.
   *
   * The declared checks above all measure against `earth`, and the first
   * screenshot of the dark style (a wooded stretch of the Boston extract)
   * came back with the modal color of the frame being `wood_b`, not
   * `earth` — a third of the visible ground was land cover. Water over
   * that green measured 2.80:1 and would have shipped as a pass. A street
   * or a shoreline does not care which polygon it happens to be crossing,
   * so the bar has to hold over EVERY surface the map can put underneath
   * it. This sweep is generated from the palette, so a new ground color
   * added later is gated the day it appears.
   */
  it("holds the bar over EVERY ground surface the map can draw — parks, woods, buildings, runways, land cover — not just the bare earth", () => {
    const t = style.theme as Record<string, string>;
    const landcover = (style.theme.landcover ?? {}) as Record<string, string>;
    const grounds: [string, string][] = [
      ...[
        "earth",
        "park_a",
        "park_b",
        "hospital",
        "industrial",
        "school",
        "wood_a",
        "wood_b",
        "pedestrian",
        "scrub_a",
        "scrub_b",
        "glacier",
        "sand",
        "beach",
        "aerodrome",
        "zoo",
        "military",
        "buildings",
        "runway",
        "pier",
      ].map((k) => [k, t[k]] as [string, string]),
      ...Object.entries(landcover).map(
        ([k, v]) => [`landcover.${k}`, v] as [string, string],
      ),
    ];
    expect(grounds.length).toBeGreaterThan(24);

    const failures: string[] = [];
    for (const [name, ground] of grounds) {
      expect(ground, `no color for ground ${name}`).toMatch(
        /^#[0-9A-Fa-f]{6}$/,
      );
      const best = (...keys: string[]) =>
        Math.max(...keys.map((k) => contrastRatio(t[k], ground)));
      const pairs: [string, number, number][] = [
        ["minor street", best("minor_b", "minor_casing"), 3],
        ["highway", best("highway", "highway_casing_early"), 3],
        ["service road", best("minor_service", "minor_service_casing"), 3],
        ["water", best("water"), 3],
        ["street name", best("roads_label_minor"), 4.5],
      ];
      for (const [what, got, min] of pairs) {
        if (got < min) {
          failures.push(`${what} over ${name} (${ground}): ${got.toFixed(2)}:1 < ${min}:1`);
        }
      }
    }
    expect(failures).toEqual([]);
  });

  it("never mutates the vendored layer specs it borrows structure from", () => {
    const before = JSON.stringify(noLabels("basemap", "light"));
    basemapLayerSpecs(id);
    basemapLayerSpecs(id);
    expect(JSON.stringify(noLabels("basemap", "light"))).toBe(before);
  });
});

describe("basemap styles — the two are authored, not one filtered from the other", () => {
  it("inverts the contrast direction: dark draws BRIGHT streets on a near-black ground, light draws DARK-CASED streets on paper", () => {
    const dark = BASEMAP_STYLES.dark.theme as Record<string, string>;
    const light = BASEMAP_STYLES.light.theme as Record<string, string>;

    // Dark: the street fill is lighter than the ground it sits on.
    const darkGround = luminance(dark.earth);
    for (const key of ["highway", "major", "minor_a", "minor_b", "other"]) {
      expect(luminance(dark[key]), `dark ${key}`).toBeGreaterThan(darkGround);
    }
    // Light: the street CASING is darker than the ground (the fill is
    // white-on-cream by cartographic convention, so the casing is what
    // makes the street visible at all).
    const lightGround = luminance(light.earth);
    for (const key of [
      "highway_casing_early",
      "major_casing_early",
      "minor_casing",
      "minor_service_casing",
    ]) {
      expect(luminance(light[key]), `light ${key}`).toBeLessThan(lightGround);
    }
    // A near-black warm ground, in the control-room family the app settled
    // on (~#07090E–#0F131B), not a blue-grey slate.
    expect(darkGround).toBeLessThan(0.02);
  });

  it("shares no palette entry between the styles — neither is a tint of the other", () => {
    const dark = BASEMAP_STYLES.dark.theme as Record<string, unknown>;
    const light = BASEMAP_STYLES.light.theme as Record<string, unknown>;
    const colorKeys = Object.keys(dark).filter(
      (k) =>
        typeof dark[k] === "string" &&
        !["regular", "bold", "italic"].includes(k),
    );
    const shared = colorKeys.filter((k) => dark[k] === light[k]);
    expect(shared).toEqual([]);
  });

  it("keeps the land cover QUIET so the network dominates the frame (under 1.6:1 against the ground, both styles)", () => {
    for (const id of STYLE_IDS) {
      const theme = BASEMAP_STYLES[id].theme as Record<string, string>;
      for (const key of [
        "park_a",
        "wood_a",
        "buildings",
        "industrial",
        "school",
        "pedestrian",
      ]) {
        expect(
          contrastRatio(theme[key], theme.earth),
          `${id} ${key} must not compete with the street network`,
        ).toBeLessThan(1.6);
      }
    }
  });

  it("scales road widths per style without mangling the zoom expressions", () => {
    expect(scaleLineWidth(2, 1.15)).toBe(2.3);
    expect(scaleLineWidth(2, 1)).toBe(2);
    expect(
      scaleLineWidth(
        ["interpolate", ["exponential", 1.6], ["zoom"], 11, 0, 12.5, 0.5, 15, 2],
        2,
      ),
    ).toEqual([
      "interpolate",
      ["exponential", 1.6],
      ["zoom"],
      11,
      0,
      12.5,
      1,
      15,
      4,
    ]);
    // Anything that is not a width we understand is passed through, never
    // silently rewritten.
    expect(scaleLineWidth(["get", "width"], 2)).toEqual(["get", "width"]);
    expect(scaleLineWidth(undefined, 2)).toBeUndefined();

    // The dark style really does widen: bright hairlines on a dark ground
    // read thinner than dark ones on a light ground.
    expect(BASEMAP_STYLES.dark.roadWidthScale).toBeGreaterThan(1);
    expect(BASEMAP_STYLES.light.roadWidthScale).toBe(1);
    const widthOf = (specs: LayerSpecification[], id: string) =>
      ((specs.find((l) => l.id === id)?.paint ?? {}) as Record<string, unknown>)[
        "line-width"
      ];
    expect(
      JSON.stringify(widthOf(basemapLayerSpecs("dark"), "basemap-roads_minor")),
    ).not.toBe(
      JSON.stringify(widthOf(basemapLayerSpecs("light"), "basemap-roads_minor")),
    );
  });
});

/**
 * The regression pin. These are the numbers the ITS manager was looking
 * at. They are recorded here so the complaint stays legible in code, and
 * so a future "just use the stock flavor" change fails loudly.
 */
describe("the stock Protomaps flavors — why we authored our own", () => {
  it("stock DARK buries the street network: roads, water and street names all miss the WCAG bars", () => {
    const t = namedTheme("dark") as unknown as Record<string, string>;
    const ground = t.earth;
    // Roads: the complaint, in numbers. Dark grey on a dark ground.
    expect(ratio(t.minor_b, ground)).toBeLessThan(3);
    expect(ratio(t.major, ground)).toBeLessThan(3);
    expect(ratio(t.highway, ground)).toBeLessThan(3);
    // ...and the casing under them is no help either.
    expect(ratio(t.minor_casing, ground)).toBeLessThan(3);
    // Water is nearly indistinguishable from land.
    expect(ratio(t.water, ground)).toBeLessThan(2);
    // Street names miss the 4.5:1 text bar by a wide margin.
    expect(ratio(t.roads_label_minor, ground)).toBeLessThan(4.5);
    expect(ratio(t.roads_label_major, ground)).toBeLessThan(4.5);
  });

  it("stock LIGHT is no better by measurement — its road casing is 1.01:1 against the earth", () => {
    const t = namedTheme("light") as unknown as Record<string, string>;
    const ground = t.earth;
    expect(ratio(t.minor_casing, ground)).toBeLessThan(1.1);
    expect(ratio(t.minor_b, ground)).toBeLessThan(3);
    expect(ratio(t.water, ground)).toBeLessThan(3);
    expect(ratio(t.roads_label_minor, ground)).toBeLessThan(4.5);
  });

  it("and our authored styles beat the stock flavor they replace, class for class", () => {
    for (const id of STYLE_IDS) {
      const stock = namedTheme(id) as unknown as Record<string, string>;
      const ours = BASEMAP_STYLES[id].theme as Record<string, string>;
      const best = (t: Record<string, string>, fill: string, casing: string) =>
        Math.max(ratio(t[fill], t.earth), ratio(t[casing], t.earth));
      for (const [fill, casing] of [
        ["highway", "highway_casing_early"],
        ["major", "major_casing_early"],
        ["minor_b", "minor_casing"],
      ] as const) {
        expect(
          best(ours, fill, casing),
          `${id} ${fill} must beat the stock flavor`,
        ).toBeGreaterThan(best(stock, fill, casing));
      }
      expect(ratio(ours.roads_label_minor, ours.earth)).toBeGreaterThan(
        ratio(stock.roads_label_minor, stock.earth),
      );
      expect(ratio(ours.water, ours.earth)).toBeGreaterThan(
        ratio(stock.water, stock.earth),
      );
    }
  });

  it("the stock flavors would FAIL our gate — proving the gate is not trivially satisfiable", () => {
    for (const id of STYLE_IDS) {
      const stock = namedTheme(id) as unknown as Record<string, unknown>;
      const results = BASEMAP_STYLES[id].contrastChecks.map((c) =>
        measureCheck(c, stock),
      );
      const failures = results.filter((r) => !r.pass);
      expect(
        failures.length,
        `stock ${id} unexpectedly passed the Headway gate`,
      ).toBeGreaterThan(5);
    }
  });

  it("still borrows the vendored LAYER STRUCTURE verbatim — same layers, our paint", () => {
    const stockIds = [
      ...noLabels("basemap", "light"),
      ...labels("basemap", "light", "en"),
    ]
      .map((l) => l.id)
      .filter((l) => l !== "background" && l !== "pois")
      .sort();
    for (const id of STYLE_IDS) {
      const ourIds = basemapLayerSpecs(id)
        .map((l) => l.id.slice(BASEMAP_LAYER_PREFIX.length))
        .sort();
      expect(ourIds).toEqual(stockIds);
    }
  });
});
