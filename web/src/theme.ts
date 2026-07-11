/**
 * Theme store (handoff 0008, pillar A): light and dark are BOTH deliberately
 * selected token sets — dark is not an automatic inversion. The effective
 * theme is:
 *
 *   1. the user's explicit choice, persisted in localStorage ("headway-theme"),
 *   2. otherwise the operating-system preference (prefers-color-scheme),
 *   3. otherwise light.
 *
 * The theme is applied as `data-theme` on <html>; src/styles.css defines the
 * dark token values under `:root[data-theme="dark"]`. Every dark token pair
 * is AA-verified by scripts/check-contrast.mjs, and the dark chart palette is
 * validated against the dark card surface by the dataviz palette validator
 * (see the chart components). index.html stamps the attribute inline before
 * first paint so there is no light flash.
 */

import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "headway-theme";

function storedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null; // storage blocked: fall back to the system preference
  }
}

/** The OS preference. Guarded: jsdom has no matchMedia. */
function systemTheme(): Theme {
  if (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  ) {
    return "dark";
  }
  return "light";
}

export function effectiveTheme(): Theme {
  return storedTheme() ?? systemTheme();
}

let current: Theme = "light";
let initialized = false;
const listeners = new Set<() => void>();

function emit() {
  for (const fn of listeners) fn();
}

function apply(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
}

/**
 * Resolve and apply the effective theme, and follow OS preference changes
 * while the user has made no explicit choice. Called by the app shell.
 */
export function initTheme(): void {
  current = effectiveTheme();
  apply(current);
  if (initialized) return;
  initialized = true;
  if (typeof window.matchMedia === "function") {
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", (event) => {
        if (storedTheme() !== null) return; // explicit choice wins
        current = event.matches ? "dark" : "light";
        apply(current);
        emit();
      });
  }
}

export function getTheme(): Theme {
  return current;
}

/** Explicit user choice: applied now and persisted for future visits. */
export function setTheme(theme: Theme): void {
  current = theme;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // storage blocked: the choice still applies for this visit
  }
  apply(theme);
  emit();
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** React hook: re-renders when the theme changes. */
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, getTheme, getTheme);
}
