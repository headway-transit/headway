/**
 * Navigation mode: the classic top strip, or the command rail.
 *
 * Deliberately built as the exact twin of src/theme.ts — same storage shape,
 * same `data-` attribute on <html>, same pre-paint stamp in index.html. A
 * second preference that behaved differently from the first would be a second
 * thing to learn for no reason.
 *
 * WHY IT IS A PREFERENCE AND NOT A RELEASE. The rail is a large change to how
 * people move around, and the operator it matters most to is away for two and
 * a half weeks. He should come back to the navigation he learned, and choose
 * the new one — not arrive to find it already happened. Per-user rather than
 * per-installation, so one person can evaluate it while everyone else carries
 * on.
 *
 * WHAT MUST NOT DIVERGE. Both modes render the SAME routes, the SAME
 * components and the SAME authorisation — only the chrome differs. The moment
 * a room exists in one mode and not the other there are two products, so
 * admin-reachability.test.tsx asserts the full inventory in BOTH modes from
 * one source of truth.
 *
 * THIS IS TEMPORARY BY DESIGN. Dual navigation doubles the surface every
 * nav test has to cover, which is acceptable for a fortnight and not
 * acceptable indefinitely. One of the two gets deleted after the evaluation.
 */

import { useSyncExternalStore } from "react";

export type NavMode = "strip" | "rail";

export const NAV_MODE_STORAGE_KEY = "headway-nav";

/** The classic top strip stays the default: nobody opts in by accident. */
const DEFAULT_MODE: NavMode = "strip";

function storedMode(): NavMode | null {
  try {
    const value = window.localStorage.getItem(NAV_MODE_STORAGE_KEY);
    return value === "strip" || value === "rail" ? value : null;
  } catch {
    return null; // storage blocked: the default is a perfectly good answer
  }
}

export function effectiveNavMode(): NavMode {
  return storedMode() ?? DEFAULT_MODE;
}

let current: NavMode = DEFAULT_MODE;
let initialized = false;
const listeners = new Set<() => void>();

function emit() {
  for (const fn of listeners) fn();
}

function apply(mode: NavMode): void {
  document.documentElement.setAttribute("data-nav", mode);
}

function init(): void {
  if (initialized) return;
  initialized = true;
  current = effectiveNavMode();
  apply(current);
}

export function setNavMode(mode: NavMode): void {
  init();
  current = mode;
  try {
    window.localStorage.setItem(NAV_MODE_STORAGE_KEY, mode);
  } catch {
    // Storage blocked: the choice still applies for this session. Refusing
    // to switch because we cannot remember the switch would be worse.
  }
  apply(mode);
  emit();
}

function subscribe(listener: () => void): () => void {
  init();
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): NavMode {
  init();
  return current;
}

/** Server snapshot: the default, so SSR/hydration never disagrees. */
function getServerSnapshot(): NavMode {
  return DEFAULT_MODE;
}

export function useNavMode(): NavMode {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
