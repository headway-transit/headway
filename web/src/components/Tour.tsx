/**
 * The guided-tour overlay (handoff 0021, design point 3) — hand-rolled, no
 * tour library: five steps teaching THE THESIS (every number can prove
 * itself) by walking /today → a KPI receipt → the verbatim FTA quote →
 * one step of lineage → done.
 *
 * BINDING rules, implemented here:
 * - NEVER BLOCKS: a non-modal dialog (APG) with no backdrop and no focus
 *   trap — the page stays fully usable around it. Focus is MOVED to the
 *   panel heading on every step so keyboard and screen-reader users are
 *   taken along, and Tab order flows naturally through the panel's
 *   controls.
 * - SKIPPABLE AT EVERY STEP: an explicit "Skip the tour" button on every
 *   step, and Escape (from anywhere) leaves the tour.
 * - HONEST TARGETS: a step whose on-screen target does not exist (a fresh
 *   Headway with no figures yet) states that plainly and moves on — the
 *   tour never fabricates a number to point at.
 * - MOTION: the overlay itself does not animate; scrolling a target into
 *   view uses smooth behavior ONLY when the user has not asked for
 *   reduced motion (reduced = instant).
 *
 * Coordination with /today: steps 1–2 need the first KPI receipt OPEN.
 * TodayView subscribes to the tour store and opens it (stamping
 * data-tour="kpi-receipt"); this overlay only ever points at real DOM.
 */

import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { copy } from "../copy";
import {
  TOUR_STEP_COUNT,
  endTour,
  nextTourStep,
  prevTourStep,
  useTour,
} from "../tour";

interface StepSpec {
  title: string;
  body: string;
  /** Shown INSTEAD of pointing when the target is not on screen. */
  noTarget?: string;
  /** CSS selector of the element this step points at (none for "done"). */
  targetSelector?: string;
}

const STEPS: StepSpec[] = [
  {
    title: copy.tour.steps.today.title,
    body: copy.tour.steps.today.body,
    targetSelector: '[data-tour="today-intro"]',
  },
  {
    title: copy.tour.steps.receipt.title,
    body: copy.tour.steps.receipt.body,
    noTarget: copy.tour.steps.receipt.noTarget,
    targetSelector: '[data-tour="kpi-receipt"]',
  },
  {
    title: copy.tour.steps.quote.title,
    body: copy.tour.steps.quote.body,
    noTarget: copy.tour.steps.quote.noTarget,
    targetSelector: '[data-tour="kpi-receipt"] .fta-quote',
  },
  {
    title: copy.tour.steps.lineage.title,
    body: copy.tour.steps.lineage.body,
    noTarget: copy.tour.steps.lineage.noTarget,
    targetSelector: ".lineage-graph-wrap, .lineage-tree",
  },
  {
    title: copy.tour.steps.done.title,
    body: copy.tour.steps.done.body,
  },
];

/** How long to keep looking for a step's target while its view loads —
 *  live lineage fetches can take a few seconds, so the search holds on
 *  (~3s) before honestly declaring the target absent. */
const TARGET_POLL_MS = 100;
const TARGET_POLL_TRIES = 30;

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function TourOverlay() {
  const tour = useTour();
  const location = useLocation();
  const navigate = useNavigate();
  const headingRef = useRef<HTMLHeadingElement>(null);
  /** looking → found | missing. The honest "nothing to point at" line
   *  renders only AFTER the search truly gave up — never as a flash. */
  const [targetState, setTargetState] = useState<
    "looking" | "found" | "missing"
  >("looking");

  const step = STEPS[tour.step];

  // Route discipline (SPA navigation only — the house rule): steps 0–2
  // live on /today; step 3 walks through the receipt's own lineage door.
  // Steering happens ONCE per step ENTRY — the tour never blocks, so a
  // user who navigates away mid-step is never yanked back (the step's
  // honest no-target line covers a screen without the target).
  const steeredStep = useRef<number | null>(null);
  useEffect(() => {
    if (!tour.active) {
      steeredStep.current = null;
      return;
    }
    if (steeredStep.current === tour.step) return;
    steeredStep.current = tour.step;
    if (tour.step <= 2 && location.pathname !== "/today") {
      navigate("/today");
      return;
    }
    if (tour.step === 3 && !location.pathname.endsWith("/lineage")) {
      // The receipt's walk link IS the door the tour takes — the same one
      // the user will use tomorrow. No link (no figure yet) = no walk; the
      // step states that honestly via its noTarget line.
      const walk = document.querySelector<HTMLAnchorElement>(
        '[data-tour="kpi-receipt"] .receipt-walk a',
      );
      const href = walk?.getAttribute("href");
      if (href) navigate(href);
    }
  }, [tour.active, tour.step, location.pathname, navigate]);

  // Find + highlight the step's target. Views load data asynchronously,
  // so poll briefly rather than giving up on first render.
  useEffect(() => {
    if (!tour.active) return;
    setTargetState("looking");
    const selector = step?.targetSelector;
    if (!selector) return;

    let tries = 0;
    let marked: Element | null = null;
    const tryFind = (): boolean => {
      const el = document.querySelector(selector);
      if (!el) return false;
      marked = el;
      el.classList.add("tour-target");
      // jsdom has no scrollIntoView; in browsers, reduced motion means an
      // INSTANT jump (behavior "auto"), never a slow smooth scroll.
      el.scrollIntoView?.({
        block: "center",
        behavior: prefersReducedMotion() ? "auto" : "smooth",
      });
      setTargetState("found");
      return true;
    };
    if (tryFind()) {
      return () => marked?.classList.remove("tour-target");
    }
    const timer = window.setInterval(() => {
      tries += 1;
      if (tryFind()) {
        window.clearInterval(timer);
      } else if (tries >= TARGET_POLL_TRIES) {
        window.clearInterval(timer);
        setTargetState("missing");
      }
    }, TARGET_POLL_MS);
    return () => {
      window.clearInterval(timer);
      marked?.classList.remove("tour-target");
    };
  }, [tour.active, tour.step, step, location.pathname]);

  // Take keyboard/screen-reader users along: focus the step heading.
  useEffect(() => {
    if (!tour.active) return;
    headingRef.current?.focus();
  }, [tour.active, tour.step]);

  // Escape leaves the tour from ANYWHERE — the page is never captive.
  useEffect(() => {
    if (!tour.active) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") endTour();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [tour.active]);

  if (!tour.active || !step) return null;

  const isLast = tour.step === TOUR_STEP_COUNT - 1;
  const showNoTarget = targetState === "missing" && step.noTarget;

  return (
    /* Non-modal dialog (no aria-modal, no trap): the tour never blocks. */
    <div className="tour-panel card" role="dialog" aria-label={copy.tour.label}>
      <p className="tour-step-count">
        {copy.tour.stepCount(
          String(tour.step + 1),
          String(TOUR_STEP_COUNT),
        )}
      </p>
      <h2 tabIndex={-1} ref={headingRef}>
        {step.title}
      </h2>
      <p>{step.body}</p>
      {showNoTarget && <p className="tour-no-target">{step.noTarget}</p>}
      <p className="tour-escape-hint">{copy.tour.escapeHint}</p>
      <div className="tour-actions">
        {tour.step > 0 && (
          <button type="button" onClick={prevTourStep}>
            {copy.tour.back}
          </button>
        )}
        {isLast ? (
          <button type="button" className="primary" onClick={endTour}>
            {copy.tour.finish}
          </button>
        ) : (
          <>
            <button type="button" className="primary" onClick={nextTourStep}>
              {copy.tour.next}
            </button>
            <button type="button" className="link-like" onClick={endTour}>
              {copy.tour.skip}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
