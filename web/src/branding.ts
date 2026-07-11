/**
 * Agency branding store (handoff 0008, pillar C): the app shell fetches
 * GET /branding once on load and brands the CHROME — header display name,
 * logo, and accent colors — via CSS custom-property overrides layered over
 * the base tokens.
 *
 * THE GUARDRAIL CHAIN: the two brand colors are accepted by the server only
 * if they measure >= 4.5:1 (WCAG 2.1 AA) against both LIGHT app surfaces
 * (services/api headway_api/branding.py), so any color this store holds is
 * already readable there. Because that guarantee covers the light surfaces
 * only, styles.css applies the brand-color text/accent overrides in the
 * LIGHT theme only; dark mode keeps the base dark accent tokens (a per-mode
 * brand variant is the documented follow-up in branding.py).
 *
 * CHARTS NEVER TAKE BRAND COLORS. The chart palette is validated separately
 * by the dataviz palette validator (CVD separation, lightness band, chroma
 * floor, contrast vs the chart surface) — properties an arbitrary brand hex
 * has never been checked for. Brand != data encoding: a brand color that is
 * fine for a header could make two chart series indistinguishable to a
 * color-blind reader or vanish against the surface. Chart components read
 * only the --series-* / --chart-* tokens, never --brand-*.
 *
 * Branding is cosmetic chrome: if GET /branding fails, the shell keeps its
 * defaults ("Headway", base accent) rather than blocking anything.
 */

import { useSyncExternalStore } from "react";
import { getBranding } from "./api/client";
import type { Branding } from "./api/types";

let current: Branding | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const fn of listeners) fn();
}

export function getCurrentBranding(): Branding | null {
  return current;
}

/** Update the store (used by the shell on load and by /settings/branding after a save). */
export function setBranding(branding: Branding): void {
  current = branding;
  emit();
}

/** Test/unmount hygiene. */
export function clearBranding(): void {
  current = null;
  emit();
}

/**
 * Fetch GET /branding and store the result. Errors leave the defaults in
 * place — branding is chrome, never worth blocking the app for.
 */
export async function loadBranding(): Promise<void> {
  try {
    setBranding(await getBranding());
  } catch {
    // Defaults stay: app name "Headway", base accent tokens, no logo.
  }
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** React hook: re-renders when branding changes. */
export function useBranding(): Branding | null {
  return useSyncExternalStore(subscribe, getCurrentBranding, getCurrentBranding);
}
