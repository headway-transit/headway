"""Agency branding guardrail: WCAG 2.1 contrast math, computed server-side.

Agencies may brand Headway (handoff 0008, pillar C); they may not brand it
inaccessible. A brand color is accepted only if it measures at least 4.5:1
(WCAG 2.1 AA for normal text) against BOTH app surfaces it will sit on. The
check runs on every PUT of a brand color setting; a failing color is refused
with a plain-language message naming the failing surface and the measured
ratio.

FORMULA SOURCE — verified against the published W3C spec, never from memory:

- Relative luminance (WCAG 2.1, W3C Recommendation, definition "relative
  luminance", https://www.w3.org/TR/WCAG21/#dfn-relative-luminance, as
  reproduced in W3C technique G18,
  https://www.w3.org/WAI/WCAG21/Techniques/general/G18.html, fetched
  2026-07-11):

      L = 0.2126 * R + 0.7152 * G + 0.0722 * B

  where each 8-bit sRGB channel c (scaled to 0..1 by dividing by 255)
  linearizes as:

      c / 12.92                      if c <= 0.04045
      ((c + 0.055) / 1.055) ** 2.4   otherwise

  The 0.04045 threshold is the CORRECTED published value: the original WCAG
  2.x text carried 0.03928 from an obsolete sRGB draft, and the W3C errata
  (May 2021, noted in G18) fixed it to 0.04045. For 8-bit channel values the
  two thresholds are numerically indistinguishable (no c = n/255 falls
  between them), but we implement the corrected constant.

- Contrast ratio (WCAG 2.1, definition "contrast ratio",
  https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio):

      (L1 + 0.05) / (L2 + 0.05)

  where L1 is the lighter and L2 the darker relative luminance. The spec
  states the range is 1:1 to 21:1 (pure white on pure black).

- The 4.5:1 minimum is Success Criterion 1.4.3 Contrast (Minimum), Level AA.

Floating point is fine here: contrast ratios are display geometry, not
reported transit figures — the Decimal-only rule applies to figures.

THE SURFACES — cited from web/src/styles.css :root tokens (the web design
tokens are themselves AA-verified by web/scripts/check-contrast.mjs):

- LIGHT_SURFACE  = #ffffff — the ``--color-bg`` page background token.
- DARK_SURFACE   = #f6f8fa — the ``--color-surface`` raised-card token, the
  darker of the two surfaces the web app ships today (styles.css header:
  "Single light theme for the walking skeleton; theming is a later
  design-system increment").

WHY DARK_SURFACE IS NOT A NEAR-BLACK DARK-THEME SURFACE: it is mathematically
impossible for one color to reach 4.5:1 against both #ffffff and a near-black
surface. Against white, 4.5:1 requires L <= (1.0 + 0.05)/4.5 - 0.05 = 0.1833;
against a surface of luminance Ld, it requires L >= 4.5*(Ld + 0.05) - 0.05,
which exceeds 0.1833 for any Ld > 0.00185 (roughly #060606). The dataviz dark
chart surface (#1a1a19, Ld ~ 0.0103) is far above that bound. So when a true
dark theme ships, it needs a PER-MODE brand variant validated against its own
surface — a documented follow-up, not a silent gap. (Charts never take brand
colors at all: the dataviz palette is validated separately; brand != data
encoding — handoff 0008 pillar C.)
"""

from __future__ import annotations

import re

# The two app surfaces every brand color must be readable on (see module
# docstring for the citation of each hex).
LIGHT_SURFACE = "#ffffff"  # web/src/styles.css :root --color-bg
DARK_SURFACE = "#f6f8fa"  # web/src/styles.css :root --color-surface

# Surfaces in check order, with the plain-language name used in refusals.
SURFACES = (
    (LIGHT_SURFACE, "page background"),
    (DARK_SURFACE, "raised card surface"),
)

# WCAG 2.1 SC 1.4.3 Contrast (Minimum), Level AA, normal text.
MIN_CONTRAST = 4.5

# The settings keys that carry brand colors (migration 0015) — the settings
# router runs the contrast guardrail on exactly these.
BRAND_COLOR_KEYS = ("brand_color_primary", "brand_color_accent")

# The settings key recording the uploaded logo's content type (migration
# 0015). Maintained by POST /branding/logo, never edited directly.
LOGO_META_KEY = "brand_logo_meta"
LOGO_META_UNSET = "unset"

_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}\Z")


def _linearize(channel_8bit: int) -> float:
    """One sRGB channel (0..255) to its linear value, per the WCAG 2.1
    relative-luminance definition (0.04045 threshold — see module docstring
    for the errata citation)."""
    c = channel_8bit / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """WCAG 2.1 relative luminance of a '#rrggbb' color:
    L = 0.2126*R + 0.7152*G + 0.0722*B (source in module docstring)."""
    if not _HEX_COLOR_RE.fullmatch(hex_color):
        raise ValueError(f"not a '#rrggbb' hex color: {hex_color!r}")
    h = hex_color[1:]
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b)


def contrast_ratio(color_a: str, color_b: str) -> float:
    """WCAG 2.1 contrast ratio (L1 + 0.05) / (L2 + 0.05), lighter over
    darker; ranges 1.0 (same color) to 21.0 (white on black)."""
    la = relative_luminance(color_a)
    lb = relative_luminance(color_b)
    lighter, darker = (la, lb) if la >= lb else (lb, la)
    return (lighter + 0.05) / (darker + 0.05)


# --- Themed chrome, branding v2 (handoff 0017, design point 7) --------------
#
# Chrome colors sit on the agency's OWN header, not on the app's light
# surfaces, so the guardrail here is PAIRWISE: the same WCAG 2.1 AA math
# (contrast_ratio above, 4.5:1 minimum) applied to the pairs that actually
# render together. Validated against the values that WOULD result from a
# change, so no sequence of single-key updates can reach an unreadable
# header. 'unset' (the seeded default) deactivates the theme — the shell
# stays neutral Headway — and is always accepted.

#: The three chrome settings keys (migration 0027).
CHROME_HEADER_BG_KEY = "brand_chrome_header_bg"
CHROME_HEADER_FG_KEY = "brand_chrome_header_fg"
CHROME_ACCENT_KEY = "brand_chrome_accent"
CHROME_KEYS = (CHROME_HEADER_BG_KEY, CHROME_HEADER_FG_KEY, CHROME_ACCENT_KEY)

#: Sentinel meaning "not themed" (the seeded default; also a valid PUT value
#: to turn the theme off).
CHROME_UNSET = "unset"

#: The chrome pairs that render together: (foreground key, background key,
#: plain-language pair name for refusals).
CHROME_PAIRS = (
    (
        CHROME_HEADER_FG_KEY,
        CHROME_HEADER_BG_KEY,
        "header text on the themed header background",
    ),
    (
        CHROME_ACCENT_KEY,
        CHROME_HEADER_BG_KEY,
        "active-item accent on the themed header background",
    ),
)


def chrome_value_problem(value: str) -> str | None:
    """Format check for one chrome key's value: '#rrggbb' or 'unset'."""
    if value == CHROME_UNSET:
        return None
    if not _HEX_COLOR_RE.fullmatch(value):
        return (
            f"'{value}' is not a value Headway can use for a chrome theme "
            f"color. Please send a six-digit hex color starting with '#' "
            f"(for example '#1a5fb4'), or 'unset' to return this part of "
            f"the chrome to the neutral Headway look."
        )
    return None


def chrome_pair_problem(values: dict[str, str]) -> str | None:
    """The plain-language reason the PROSPECTIVE chrome value set cannot
    stand, or None. ``values`` maps every CHROME_KEYS key to the value it
    would hold after the change. Pairs where either side is 'unset' are
    skipped — the theme only applies when complete, so an incomplete theme
    cannot render an unreadable pair."""
    for fg_key, bg_key, pair_name in CHROME_PAIRS:
        fg = values[fg_key]
        bg = values[bg_key]
        if fg == CHROME_UNSET or bg == CHROME_UNSET:
            continue
        ratio = contrast_ratio(fg, bg)
        if ratio < MIN_CONTRAST:
            return (
                f"That combination doesn't have enough contrast to be "
                f"readable: the {pair_name} ('{fg}' on '{bg}') measures "
                f"{ratio:.2f}:1, and readable text needs at least "
                f"{MIN_CONTRAST}:1 (WCAG 2.1 AA). Please pick a lighter or "
                f"darker color for one side of the pair."
            )
    return None


def brand_color_problem(value: str) -> str | None:
    """The plain-language reason ``value`` cannot be a brand color, or None
    when it passes. Checks hex format first, then the AA contrast guardrail
    against both app surfaces; a refusal names the failing surface and the
    measured ratio (handoff 0008: "you can brand it; you cannot brand it
    inaccessible")."""
    if not _HEX_COLOR_RE.fullmatch(value):
        return (
            f"'{value}' is not a color Headway can use. Please send a "
            f"six-digit hex color starting with '#', for example '#1a5fb4'."
        )
    for surface_hex, surface_name in SURFACES:
        ratio = contrast_ratio(value, surface_hex)
        if ratio < MIN_CONTRAST:
            return (
                f"That color doesn't have enough contrast to be readable: "
                f"'{value}' measures {ratio:.2f}:1 against the app's "
                f"{surface_name} ({surface_hex}), and readable text needs at "
                f"least {MIN_CONTRAST}:1 (WCAG 2.1 AA). Please choose a "
                f"darker or more saturated color."
            )
    return None
