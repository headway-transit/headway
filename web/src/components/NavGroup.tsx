/**
 * One named group in the command bar's navigation row (handoff 0044,
 * output 1).
 *
 * The shell used to spend two full wrapping rows on seventeen links. The
 * handoff's open question was where the long tail should go — a command
 * palette, or grouped menus. Grouped menus won: a palette is more modern
 * but it hides the map of the product behind a keystroke, and this
 * audience is one week into Linux.
 *
 * A group is a disclosure, not a custom menu widget: a real <button> with
 * aria-expanded + aria-controls over a list of ORDINARY LINKS. That keeps
 * the keyboard contract identical to the rest of the nav (Tab moves, Enter
 * follows, Escape closes and returns focus), and it keeps every destination
 * a link — never a role="menuitem" that behaves like one.
 */

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

export interface NavGroupProps {
  /** The visible group name ("Reports", "Records"). */
  label: string;
  /** True when the page currently open lives inside this group. */
  containsCurrent: boolean;
  /** Screen-reader-only clarification of what the group holds. */
  hint: string;
  /** Said when the group holds the page you are on (never color alone). */
  currentHint: string;
  children: ReactNode;
}

export function NavGroup({
  label,
  containsCurrent,
  hint,
  currentHint,
  children,
}: NavGroupProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Escape closes and gives focus back to the trigger (APG disclosure
  // behaviour); a pointer press outside closes without stealing focus.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    const onPointer = (e: Event) => {
      const target = e.target as Node | null;
      if (target && wrapRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  return (
    <div className="nav-group" ref={wrapRef}>
      <button
        type="button"
        ref={buttonRef}
        className="nav-group-toggle"
        data-current={containsCurrent ? "true" : undefined}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        {label}
        <span className="visually-hidden">
          {containsCurrent ? ` — ${currentHint}` : ` — ${hint}`}
        </span>
        <span aria-hidden="true" className="nav-group-caret">
          ▾
        </span>
      </button>
      {/* Genuinely hidden when closed: out of the tab order, out of the
          accessibility tree. A CSS-only hide would leave every link in the
          keyboard path with nothing on screen to explain where focus went. */}
      <ul className="nav-group-panel" id={panelId} hidden={!open}>
        {children}
      </ul>
    </div>
  );
}

export default NavGroup;
