/**
 * Guided-tour store (handoff 0021, design point 3): module state in the
 * house store discipline (src/toasts.ts / auth/session.ts). The tour is a
 * five-step, hand-rolled, focus-managed walkthrough of THE THESIS — every
 * number can prove itself:
 *
 *   0  land on /today            (the briefing)
 *   1  open a KPI figure's receipt
 *   2  dwell on the verbatim FTA quote
 *   3  walk lineage one step
 *   4  done — "now you know how to check"
 *
 * BINDING (the handoff's letter): skippable at EVERY step, keyboard
 * accessible, never blocking. The overlay component (components/Tour.tsx)
 * owns rendering and focus; this store owns state and the localStorage
 * first-run flag. TodayView listens to the step to open the receipt the
 * tour is pointing at — the tour never fakes a click.
 */

import { useSyncExternalStore } from "react";

export const TOUR_STEP_COUNT = 5;

/** localStorage flag: set once the user finishes OR dismisses the tour. */
const TOUR_SEEN_KEY = "headway-tour-seen";

export interface TourState {
  active: boolean;
  /** 0-based step index (0..TOUR_STEP_COUNT-1). */
  step: number;
}

let state: TourState = { active: false, step: 0 };
const listeners = new Set<() => void>();

function emit() {
  for (const fn of listeners) fn();
}

function set(next: TourState): void {
  state = next;
  emit();
}

export function getTour(): TourState {
  return state;
}

/**
 * Whether the first-run auto-offer should fire (never seen, never
 * dismissed). Storage failures (blocked storage) suppress the auto-offer
 * rather than re-offering forever.
 */
export function tourSeen(): boolean {
  try {
    return window.localStorage.getItem(TOUR_SEEN_KEY) === "1";
  } catch {
    return true;
  }
}

function markTourSeen(): void {
  try {
    window.localStorage.setItem(TOUR_SEEN_KEY, "1");
  } catch {
    /* storage blocked: the flag simply does not persist */
  }
}

/** Start (or restart) from step 0. Restartable at any time from the nav. */
export function startTour(): void {
  set({ active: true, step: 0 });
}

/**
 * Leave the tour — finishing and skipping both mark it seen (a dismissal
 * is an answer, not a snooze; "Take the tour" in the nav restarts it).
 */
export function endTour(): void {
  markTourSeen();
  set({ active: false, step: 0 });
}

/** Test hygiene ONLY (setup.ts): drop tour state without touching the
 *  localStorage flag — module state must not leak between tests. */
export function resetTour(): void {
  state = { active: false, step: 0 };
  emit();
}

export function nextTourStep(): void {
  if (!state.active) return;
  if (state.step >= TOUR_STEP_COUNT - 1) {
    endTour();
    return;
  }
  set({ active: true, step: state.step + 1 });
}

export function prevTourStep(): void {
  if (!state.active || state.step === 0) return;
  set({ active: true, step: state.step - 1 });
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** React hook: re-renders when the tour state changes. */
export function useTour(): TourState {
  return useSyncExternalStore(subscribe, getTour, getTour);
}
