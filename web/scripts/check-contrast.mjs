// WCAG 2.1 contrast checker for the Headway color tokens.
//
// jsdom cannot compute color contrast (no layout engine), so the axe checks in
// the test suite disable the color-contrast rule and THIS script is the
// verification for WCAG 2.1 SC 1.4.3 (text, >= 4.5:1) and SC 1.4.11
// (non-text UI parts, >= 3:1). Run with:  npm run check:contrast
//
// The pairs below MUST match the tokens in src/styles.css. If you change a
// token, change it here too — the script exits non-zero on any failure.

function srgbChannel(v) {
  const c = v / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function luminance(hex) {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return 0.2126 * srgbChannel(r) + 0.7152 * srgbChannel(g) + 0.0722 * srgbChannel(b);
}

export function contrastRatio(fg, bg) {
  const l1 = luminance(fg);
  const l2 = luminance(bg);
  const [hi, lo] = l1 >= l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
}

// [description, foreground, background, minimum ratio]
//
// LIGHT theme pairs first, then the DARK theme set (handoff 0008 pillar A —
// both themes are deliberately selected token sets and BOTH must pass).
// Chart SERIES colors (--series-*) are NOT here: they are data encodings
// validated by the dataviz palette validator (lightness band, chroma floor,
// CVD separation, contrast vs the chart surface) per mode. Chart STATUS
// fills are here as non-text marks (3:1) because they always ride with an
// icon + label.
const PAIRS = [
  ["body text on page background", "#1f2328", "#ffffff", 4.5],
  ["body text on raised surface", "#1f2328", "#f6f8fa", 4.5],
  ["muted text on page background", "#57606a", "#ffffff", 4.5],
  ["link / accent text on page background", "#0b57d0", "#ffffff", 4.5],
  ["primary button text on accent", "#ffffff", "#0b57d0", 4.5],
  ["blocking (danger) text on danger background", "#9f1b1b", "#fdeaea", 4.5],
  ["warning text on warning background", "#664b00", "#fff3d1", 4.5],
  ["info text on info background", "#1d4e89", "#e7f0fa", 4.5],
  ["certified (success) text on success background", "#1c632f", "#e8f5eb", 4.5],
  ["banner text on notice background", "#664b00", "#fff3d1", 4.5],
  // Non-text (SC 1.4.11): focus indicator and control borders against white.
  ["focus outline on page background (non-text, 3:1)", "#0b57d0", "#ffffff", 3.0],
  ["input border on page background (non-text, 3:1)", "#57606a", "#ffffff", 3.0],
  ["blocking icon on danger background (non-text, 3:1)", "#9f1b1b", "#fdeaea", 3.0],
  ["warning icon on warning background (non-text, 3:1)", "#664b00", "#fff3d1", 3.0],
  ["info icon on info background (non-text, 3:1)", "#1d4e89", "#e7f0fa", 3.0],
  // Receipt + lineage graph (handoff 0007): text and links on the surface
  // panel, and the meter/graph strokes as non-text UI parts.
  ["muted text on raised surface (receipt cite, graph line2)", "#57606a", "#f6f8fa", 4.5],
  ["link / accent text on raised surface (receipt, graph button)", "#0b57d0", "#f6f8fa", 4.5],
  ["meter fill / metric node stroke on surface track (non-text, 3:1)", "#0b57d0", "#f6f8fa", 3.0],
  ["graph node + meter track border on surface (non-text, 3:1)", "#57606a", "#f6f8fa", 3.0],
  // 2026-07-11 click-through fixes: the aria-disabled certify button keeps a
  // readable label; the at-button reason line (warning tokens) carries its
  // /dq link in the same warning-text color.
  ["aria-disabled certify button label on surface", "#57606a", "#f6f8fa", 4.5],
  ["certify reason text + link on warning background", "#664b00", "#fff3d1", 4.5],

  // Handoff 0008 pillar B: chart status fills (severity marks on the light
  // chart surface — non-text, always paired with icon + label + table view).
  ["chart status blocking fill on light chart surface (non-text, 3:1)", "#9f1b1b", "#ffffff", 3.0],
  ["chart status warning fill on light chart surface (non-text, 3:1)", "#946300", "#ffffff", 3.0],
  ["chart status info fill on light chart surface (non-text, 3:1)", "#1d4e89", "#ffffff", 3.0],
  // Handoff 0008 pillar C: the DEFAULT brand chrome values (migration 0015
  // seeds). Non-default brand colors are contrast-gated server-side
  // (services/api branding.py refuses any color under 4.5:1 on either light
  // surface), so every accepted override at least matches these checks.
  ["default brand primary header bar on header (non-text, 3:1)", "#1a5fb4", "#ffffff", 3.0],
  ["default brand accent as link on page background", "#0b57d0", "#ffffff", 4.5],
  ["default brand accent as link on raised surface", "#0b57d0", "#f6f8fa", 4.5],

  // Handoff 0013 (Demand Response): the DR mode/TOS badge reuses the info
  // text/background pair (already checked above); the rule-callout border
  // is a non-text mark against the receipt's page background.
  ["DR callout border on receipt background (non-text, 3:1)", "#1d4e89", "#ffffff", 3.0],

  // Handoff 0014 (Operations metrics): the ops badge + Headway-owned label
  // reuse the info text/background pair (text checked above); their 2px
  // border and the ops-owned DASHED rule are non-text marks on the card /
  // receipt background, and the formula block is body text on the raised
  // surface with its border as a non-text mark.
  ["ops badge border / ops-owned dashed rule on card background (non-text, 3:1)", "#1d4e89", "#ffffff", 3.0],
  ["ops badge icon on info background (non-text, 3:1)", "#1d4e89", "#e7f0fa", 3.0],
  ["ops formula text on raised surface", "#1f2328", "#f6f8fa", 4.5],

  // ---- DARK theme (handoff 0008 pillar A) ----
  // Card/content surface #161b22, page plane #0d1117. Brand color overrides
  // are NOT applied to dark text/controls (server guardrail covers light
  // surfaces only) — the dark accent below is pinned in styles.css.
  ["dark: body text on card surface", "#e6edf3", "#161b22", 4.5],
  ["dark: body text on page plane", "#e6edf3", "#0d1117", 4.5],
  ["dark: muted text on card surface", "#9ea7b3", "#161b22", 4.5],
  ["dark: muted text on page plane", "#9ea7b3", "#0d1117", 4.5],
  ["dark: link / accent text on card surface", "#58a6ff", "#161b22", 4.5],
  ["dark: link / accent text on page plane", "#58a6ff", "#0d1117", 4.5],
  ["dark: primary button text on accent", "#0d1117", "#58a6ff", 4.5],
  ["dark: blocking (danger) text on danger background", "#ffb3ab", "#3a1d1f", 4.5],
  ["dark: warning text on warning background", "#e8c06c", "#332711", 4.5],
  ["dark: info text on info background", "#a8c7f0", "#172439", 4.5],
  ["dark: certified (success) text on success background", "#8ddaa4", "#12291a", 4.5],
  ["dark: focus outline on card surface (non-text, 3:1)", "#58a6ff", "#161b22", 3.0],
  ["dark: focus outline on page plane (non-text, 3:1)", "#58a6ff", "#0d1117", 3.0],
  ["dark: input border on card surface (non-text, 3:1)", "#8b949e", "#161b22", 3.0],
  ["dark: input border on page plane (non-text, 3:1)", "#8b949e", "#0d1117", 3.0],
  ["dark: aria-disabled certify button label on page-plane fill", "#9ea7b3", "#0d1117", 4.5],
  ["dark: meter fill / metric node stroke on page-plane track (non-text, 3:1)", "#58a6ff", "#0d1117", 3.0],
  ["dark: chart status blocking fill on dark chart surface (non-text, 3:1)", "#f2827f", "#161b22", 3.0],
  ["dark: chart status warning fill on dark chart surface (non-text, 3:1)", "#d4a72c", "#161b22", 3.0],
  ["dark: chart status info fill on dark chart surface (non-text, 3:1)", "#6cb6ff", "#161b22", 3.0],
  ["dark: DR callout border on receipt background (non-text, 3:1)", "#a8c7f0", "#161b22", 3.0],
  ["dark: ops badge border / ops-owned dashed rule on card background (non-text, 3:1)", "#a8c7f0", "#161b22", 3.0],
  ["dark: ops badge icon on info background (non-text, 3:1)", "#a8c7f0", "#172439", 3.0],
  ["dark: ops formula text on raised surface (page plane)", "#e6edf3", "#0d1117", 4.5],
];

let failed = false;
for (const [label, fg, bg, min] of PAIRS) {
  const ratio = contrastRatio(fg, bg);
  const ok = ratio >= min;
  if (!ok) failed = true;
  console.log(
    `${ok ? "PASS" : "FAIL"}  ${ratio.toFixed(2)}:1 (min ${min}:1)  ${fg} on ${bg}  ${label}`,
  );
}
if (failed) {
  console.error("\nContrast check FAILED — fix the tokens before shipping.");
  process.exit(1);
}
console.log("\nAll token pairs meet WCAG 2.1 AA.");
