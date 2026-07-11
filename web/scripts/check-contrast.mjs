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
  ["meter fill / metric node stroke on white track (non-text, 3:1)", "#0b57d0", "#ffffff", 3.0],
  ["graph node + meter track border on surface (non-text, 3:1)", "#57606a", "#f6f8fa", 3.0],
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
