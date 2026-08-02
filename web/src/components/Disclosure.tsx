/**
 * Progressive disclosure (handoff 0044, output 5).
 *
 * THE RULE THIS COMPONENT EXISTS TO ENFORCE
 * -----------------------------------------
 * Headway's plain-language paragraphs are not decoration — they are the
 * honesty this project is built on, written for a reader with zero SQL and
 * one week of Linux. Handoff 0044 moved them out of the way of the figures
 * WITHOUT deleting a word: an EXPLANATION folds into a closed-by-default
 * disclosure and is carried across verbatim; an ADMISSION never folds.
 *
 * So this component is only ever wrapped around explanation. A refusal, a
 * held or excluded count, a cap, a staleness warning, a scope receipt, or a
 * "these are not NTD reported figures" boundary stays outside it, on screen,
 * always — pinned by src/test/disclosure.test.tsx.
 *
 * Mechanics are the house pattern already used by the vehicle list: a real
 * <button> carrying aria-expanded + aria-controls over a panel that is
 * genuinely `hidden` when closed (so it is out of the tab order and out of
 * the accessibility tree, rather than merely invisible).
 */

import { useId, useState, type ReactNode } from "react";
import { copy } from "../copy";

export interface DisclosureProps {
  /** The visible control label. Defaults to "What this shows". */
  label?: string;
  /** The explanation. Carried VERBATIM from wherever it used to sit. */
  children: ReactNode;
  /** Extra class on the wrapper (layout only). */
  className?: string;
}

export function Disclosure({ label, children, className }: DisclosureProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const text = label ?? copy.disclosure.what;
  return (
    <div className={className ? `disclosure ${className}` : "disclosure"}>
      <button
        type="button"
        className="disclosure-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        {/* The caret is decoration; aria-expanded carries the state. */}
        <span aria-hidden="true" className="disclosure-caret">
          {open ? "▾" : "▸"}
        </span>
        {text}
      </button>
      <div className="disclosure-panel" id={panelId} hidden={!open}>
        {children}
      </div>
    </div>
  );
}

export default Disclosure;
